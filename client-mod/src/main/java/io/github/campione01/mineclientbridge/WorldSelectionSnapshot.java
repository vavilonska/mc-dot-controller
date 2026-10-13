package io.github.campione01.mineclientbridge;

import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonNull;
import com.google.gson.JsonObject;
import java.nio.charset.StandardCharsets;
import java.io.ByteArrayOutputStream;
import java.io.OutputStreamWriter;
import java.io.IOException;
import java.util.List;
import java.util.Set;

/** Pure bounded serialization of one already-captured menu. No game or IO APIs. */
final class WorldSelectionSnapshot {
    static final int MAX_ENTRIES = 32, MAX_TEXT = 256, MAX_BYTES = 16384, MAX_REFUSAL_BYTES = 1024;
    static final String SCREEN = "net.minecraft.client.gui.screens.worldselection.SelectWorldScreen";
    static final String LIST = "net.minecraft.client.gui.screens.worldselection.WorldSelectionList";
    static final String SUMMARY = "net.minecraft.world.level.storage.LevelSummary";
    static final Set<String> MALFORMED = Set.of("native_context_changed", "ui_reference_changed",
            "list_not_unique", "search_not_unique", "ordinary_play_not_unique", "selection_inconsistent",
            "entry_limit", "text_invalid", "geometry_invalid", "output_limit", "generation_overflow",
            "getter_unavailable");

    record Identity(long processId, String runId, String actionSession) { }
    record Rect(int left, int top, int right, int bottom) {
        boolean intersects(Rect other) {
            return Math.max(left, other.left) < Math.min(right, other.right)
                    && Math.max(top, other.top) < Math.min(bottom, other.bottom);
        }
        boolean inside(Rect other) {
            return left >= other.left && top >= other.top && right <= other.right && bottom <= other.bottom;
        }
    }
    record Search(String value, boolean focused, boolean visible, boolean active, String key, Rect bounds) { }
    record ListView(String className, boolean visible, boolean active, Rect viewport, double scrollAmount) { }
    record Play(String key, boolean visible, boolean active, Rect bounds) { }
    record Row(int index, String name, String levelId, String summaryClass, boolean ordinarySummary,
               boolean selected, boolean canJoin, boolean locked, boolean requiresConversion,
               boolean compatible, boolean shouldBackup, boolean experimental, Rect bounds,
               boolean fullyVisible) { }
    record Menu(String screenClass, int width, int height, int entriesTotal, int worldRowsTotal,
                int nonWorldEntriesTotal, int visibleRowsTotal, Search search, ListView list,
                Integer selectedIndex, Play play, List<Row> rows) { }

    static final class Refused extends RuntimeException {
        final String reason;
        Refused(String reason) { super(reason); this.reason = reason; }
    }

    static JsonObject ready(Identity identity, long generation, Menu menu) {
        requireIdentity(identity, generation);
        try {
            validate(menu);
            JsonObject root = common(identity, generation, "ready", true, null);
            root.add("data", data(menu));
            if (size(root) > MAX_BYTES) return refusal(identity, generation, "output_limit");
            return root;
        } catch (Refused refused) {
            return refusal(identity, generation, refused.reason);
        } catch (RuntimeException unavailable) {
            return refusal(identity, generation, "getter_unavailable");
        }
    }

    static JsonObject refusal(Identity identity, long generation, String reason) {
        requireIdentity(identity, generation);
        String status;
        if (reason.equals("wrong_screen")) status = "not_world_selection";
        else if (reason.equals("loading_or_unknown_entry")) status = "loading_or_unknown";
        else if (MALFORMED.contains(reason)) status = "malformed";
        else throw new IllegalArgumentException("unknown_menu_refusal_reason");
        JsonObject result = common(identity, generation, status, false, reason);
        result.add("data", JsonNull.INSTANCE);
        if (size(result) > MAX_REFUSAL_BYTES) throw new IllegalStateException("menu_refusal_exceeds_transport_bound");
        return result;
    }

    static void need(boolean value, String reason) { if (!value) throw new Refused(reason); }

    private static void requireIdentity(Identity identity, long generation) {
        if (identity == null || identity.processId <= 0 || identity.processId > 9007199254740991L
                || !safe(identity.runId, false) || !safe(identity.actionSession, false) || generation <= 0)
            throw new IllegalStateException("menu_identity_not_serializable");
    }

    static boolean safe(String value, boolean emptyAllowed) {
        if (value == null || value.length() > MAX_TEXT || (!emptyAllowed && value.isEmpty())) return false;
        for (int i = 0; i < value.length();) {
            char first = value.charAt(i);
            if (Character.isLowSurrogate(first)) return false;
            if (Character.isHighSurrogate(first)
                    && (i + 1 >= value.length() || !Character.isLowSurrogate(value.charAt(i + 1)))) return false;
            int cp = value.codePointAt(i), type = Character.getType(cp);
            if (type == Character.CONTROL || type == Character.FORMAT || cp == 0x2028 || cp == 0x2029
                    || (cp >= 0xFDD0 && cp <= 0xFDEF) || (cp & 0xFFFF) == 0xFFFE || (cp & 0xFFFF) == 0xFFFF)
                return false;
            i += Character.charCount(cp);
        }
        return true;
    }

    private static void rect(Rect rect) {
        need(rect != null && rect.left >= -32768 && rect.top >= -32768
                && rect.right <= 32768 && rect.bottom <= 32768
                && rect.left < rect.right && rect.top < rect.bottom, "geometry_invalid");
    }

    private static void validate(Menu menu) {
        need(menu != null, "getter_unavailable");
        need(SCREEN.equals(menu.screenClass), "wrong_screen");
        need(menu.width >= 1 && menu.width <= 16384 && menu.height >= 1 && menu.height <= 16384, "geometry_invalid");
        need(menu.entriesTotal >= 0 && menu.entriesTotal <= MAX_ENTRIES, "entry_limit");
        need(menu.nonWorldEntriesTotal == 0, "loading_or_unknown_entry");
        need(menu.worldRowsTotal == menu.entriesTotal && menu.rows != null
                && menu.visibleRowsTotal == menu.rows.size() && menu.rows.size() <= menu.entriesTotal,
                "selection_inconsistent");
        Search search = menu.search; ListView list = menu.list; Play play = menu.play;
        need(search != null, "search_not_unique");
        need(list != null && LIST.equals(list.className), "list_not_unique");
        need(play != null && "selectWorld.select".equals(play.key), "ordinary_play_not_unique");
        need("selectWorld.search".equals(search.key), "search_not_unique");
        need(safe(search.value, true), "text_invalid");
        rect(search.bounds); rect(list.viewport); rect(play.bounds);
        need(Double.isFinite(list.scrollAmount) && list.scrollAmount >= 0 && list.scrollAmount <= Integer.MAX_VALUE,
                "geometry_invalid");
        need(menu.selectedIndex == null || (menu.selectedIndex >= 0 && menu.selectedIndex < menu.entriesTotal),
                "selection_inconsistent");
        int previous = -1;
        for (Row row : menu.rows) {
            need(row != null && row.index > previous && row.index < menu.entriesTotal, "selection_inconsistent");
            previous = row.index;
            need(safe(row.name, false) && safe(row.levelId, false) && safe(row.summaryClass, false), "text_invalid");
            need(row.ordinarySummary == SUMMARY.equals(row.summaryClass), "selection_inconsistent");
            need(row.selected == (menu.selectedIndex != null && row.index == menu.selectedIndex), "selection_inconsistent");
            rect(row.bounds);
            need(row.bounds.intersects(list.viewport) && row.fullyVisible == row.bounds.inside(list.viewport), "geometry_invalid");
        }
    }

    private static JsonObject common(Identity identity, long generation, String status, boolean complete, String reason) {
        JsonObject root = new JsonObject();
        root.addProperty("schema_version", 1); root.addProperty("status", status); root.addProperty("complete", complete);
        if (reason == null) root.add("reason", JsonNull.INSTANCE); else root.addProperty("reason", reason);
        JsonObject id = new JsonObject();
        id.addProperty("process_id", identity.processId); id.addProperty("run_id", identity.runId);
        id.addProperty("action_session", identity.actionSession); root.add("identity", id);
        root.addProperty("observed_instance_generation", Long.toString(generation));
        return root;
    }

    private static JsonObject rectJson(Rect value) {
        JsonObject result = new JsonObject(); result.addProperty("left", value.left); result.addProperty("top", value.top);
        result.addProperty("right", value.right); result.addProperty("bottom", value.bottom); return result;
    }

    private static JsonObject data(Menu menu) {
        JsonObject result = new JsonObject();
        result.addProperty("screen_class", menu.screenClass); result.addProperty("gui_width", menu.width);
        result.addProperty("gui_height", menu.height); result.addProperty("entries_total", menu.entriesTotal);
        result.addProperty("world_rows_total", menu.worldRowsTotal); result.addProperty("non_world_entries_total", 0);
        result.addProperty("visible_rows_total", menu.visibleRowsTotal); result.addProperty("rows_returned", menu.rows.size());
        result.addProperty("rows_truncated", false);
        Search search = menu.search; JsonObject searchJson = new JsonObject();
        searchJson.addProperty("value", search.value); searchJson.addProperty("focused", search.focused);
        searchJson.addProperty("visible", search.visible); searchJson.addProperty("active", search.active);
        searchJson.addProperty("message_key", search.key); searchJson.add("bounds", rectJson(search.bounds));
        searchJson.addProperty("text_truncated", false); result.add("search", searchJson);
        ListView list = menu.list; JsonObject listJson = new JsonObject();
        listJson.addProperty("class", list.className); listJson.addProperty("visible", list.visible);
        listJson.addProperty("active", list.active); listJson.add("viewport", rectJson(list.viewport));
        listJson.addProperty("scroll_amount", list.scrollAmount); result.add("list", listJson);
        if (menu.selectedIndex == null) result.add("selected_list_index", JsonNull.INSTANCE);
        else result.addProperty("selected_list_index", menu.selectedIndex);
        Play play = menu.play; JsonObject playJson = new JsonObject();
        playJson.addProperty("message_key", play.key); playJson.addProperty("visible", play.visible);
        playJson.addProperty("active", play.active); playJson.add("bounds", rectJson(play.bounds)); result.add("play", playJson);
        JsonArray rows = new JsonArray();
        for (Row row : menu.rows) {
            JsonObject item = new JsonObject();
            item.addProperty("list_index", row.index); item.addProperty("level_name", row.name);
            item.addProperty("level_id", row.levelId); item.addProperty("summary_class", row.summaryClass);
            item.addProperty("ordinary_summary", row.ordinarySummary); item.addProperty("selected", row.selected);
            item.addProperty("can_join", row.canJoin); item.addProperty("locked", row.locked);
            item.addProperty("requires_conversion", row.requiresConversion); item.addProperty("compatible", row.compatible);
            item.addProperty("should_backup", row.shouldBackup); item.addProperty("experimental", row.experimental);
            item.add("bounds", rectJson(row.bounds)); item.addProperty("fully_visible", row.fullyVisible);
            item.addProperty("text_truncated", false); rows.add(item);
        }
        result.add("rows", rows); return result;
    }

    private static final class Limit extends RuntimeException { }
    private static final class CappedBytes extends ByteArrayOutputStream {
        @Override public synchronized void write(int value) {
            if (count == MAX_BYTES) throw new Limit();
            super.write(value);
        }
        @Override public synchronized void write(byte[] data, int offset, int length) {
            if (length > MAX_BYTES - count) throw new Limit();
            super.write(data, offset, length);
        }
    }
    static int size(JsonObject value) {
        CappedBytes bytes = new CappedBytes();
        try {
            OutputStreamWriter writer = new OutputStreamWriter(bytes, StandardCharsets.UTF_8);
            new GsonBuilder().disableHtmlEscaping().serializeNulls().create().toJson(value, writer);
            writer.flush();
            return bytes.size();
        } catch (Limit limit) {
            return MAX_BYTES + 1;
        } catch (IOException error) {
            throw new IllegalStateException("menu_serialization_transport_error", error);
        }
    }
    private WorldSelectionSnapshot() { }
}

package io.github.campione01.mineclientbridge;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;

/** Small wire contract. Planning and crafting combinations belong to the caller. */
record ClientActionRequest(String id, String action, long timeoutMs, List<Point> waypoints,
        Cell target, Cell support, String face, int hotbarSlot, boolean jump, boolean sneak,
        int containerId, int slot, int button, String clickType, JsonObject original) {
    record Point(double x, double y, double z, boolean jump) { }
    record Cell(int x, int y, int z) { }
    static final Set<String> ACTIONS = Set.of("follow_path", "break_block", "place_block", "click_slot");
    static final Set<String> FACES = Set.of("up", "down", "north", "south", "east", "west");
    static final Set<String> CLICKS = Set.of("pickup", "quick_move", "swap", "throw", "pickup_all", "quick_craft");

    static ClientActionRequest parse(JsonObject body) {
        String id = string(body, "action_id");
        require(!id.isBlank() && id.length() <= 128, "invalid_action_id");
        String action = string(body, "action");
        require(ACTIONS.contains(action), "unsupported_action");
        long timeout = integer(body, "timeout_ms", 15000);
        require(timeout >= 50 && timeout <= 600000, "invalid_timeout_ms");
        int hotbar = integer(body, "hotbar_slot", -1);
        require(hotbar >= -1 && hotbar <= 8, "invalid_hotbar_slot");
        List<Point> points = new ArrayList<>();
        Cell target = null, support = null;
        String face = null, click = null;
        int container = -1, slot = -1, button = 0;
        if (action.equals("follow_path")) {
            require(body.has("waypoints") && body.get("waypoints").isJsonArray(), "invalid_waypoints");
            for (JsonElement item : body.getAsJsonArray("waypoints")) {
                require(item.isJsonObject(), "invalid_waypoint");
                JsonObject point = item.getAsJsonObject();
                points.add(new Point(number(point, "x"), number(point, "y"), number(point, "z"), bool(point, "jump", false)));
            }
            require(!points.isEmpty() && points.size() <= 512, "invalid_waypoints");
        } else if (action.equals("break_block")) {
            target = cell(body, "target");
        } else if (action.equals("place_block")) {
            support = cell(body, "support");
            face = string(body, "face");
            require(FACES.contains(face), "invalid_face");
        } else {
            container = integer(body, "container_id", -1);
            require(container >= 0, "invalid_container_id");
            require(body.has("slot") && body.has("button"), "missing_slot_or_button");
            slot = integer(body, "slot", -1);
            button = integer(body, "button", -1);
            click = string(body, "click_type");
            require(CLICKS.contains(click), "invalid_click_type");
            // These are vanilla ClickType button encodings, not an inventory policy.
            require(switch (click) {
                case "pickup", "quick_move", "throw", "pickup_all" -> button == 0 || button == 1;
                case "swap" -> (button >= 0 && button <= 8) || button == 40;
                case "quick_craft" -> button >= 0 && button <= 10 && (button & 3) <= 2;
                default -> false;
            }, "invalid_button");
            require(slot >= 0 || slot == -999, "invalid_slot");
        }
        return new ClientActionRequest(id, action, timeout, List.copyOf(points), target, support, face, hotbar,
                bool(body, "jump", false), bool(body, "sneak", false), container, slot, button, click, body.deepCopy());
    }

    static String string(JsonObject body, String key) {
        JsonElement v = body.get(key);
        require(v != null && v.isJsonPrimitive() && v.getAsJsonPrimitive().isString(), "invalid_" + key);
        return v.getAsString();
    }
    private static boolean bool(JsonObject body, String key, boolean fallback) {
        if (!body.has(key)) return fallback;
        JsonElement v = body.get(key);
        require(v.isJsonPrimitive() && v.getAsJsonPrimitive().isBoolean(), "invalid_" + key);
        return v.getAsBoolean();
    }
    private static double number(JsonObject body, String key) {
        JsonElement v = body.get(key);
        require(v != null && v.isJsonPrimitive() && v.getAsJsonPrimitive().isNumber(), "invalid_" + key);
        double n = v.getAsDouble();
        require(Double.isFinite(n), "invalid_" + key);
        return n;
    }
    private static int integer(JsonObject body, String key, int fallback) {
        if (!body.has(key)) return fallback;
        double n = number(body, key);
        require(n == Math.rint(n) && n >= Integer.MIN_VALUE && n <= Integer.MAX_VALUE, "invalid_" + key);
        return (int) n;
    }
    private static Cell cell(JsonObject body, String key) {
        require(body.has(key) && body.get(key).isJsonObject(), "invalid_" + key);
        JsonObject c = body.getAsJsonObject(key);
        require(c.has("x") && c.has("y") && c.has("z"), "invalid_" + key);
        return new Cell(integer(c, "x", 0), integer(c, "y", 0), integer(c, "z", 0));
    }
    static void require(boolean condition, String message) {
        if (!condition) throw new Rejected(400, message);
    }
    static final class Rejected extends RuntimeException {
        final int httpStatus;
        Rejected(int httpStatus, String reason) { super(reason); this.httpStatus = httpStatus; }
    }
}

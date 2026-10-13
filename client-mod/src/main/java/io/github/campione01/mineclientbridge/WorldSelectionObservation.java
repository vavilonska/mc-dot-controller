package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.util.ArrayList;
import java.util.List;
import java.util.function.Supplier;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.components.AbstractWidget;
import net.minecraft.client.gui.components.Button;
import net.minecraft.client.gui.components.EditBox;
import net.minecraft.client.gui.components.events.GuiEventListener;
import net.minecraft.client.gui.screens.Screen;
import net.minecraft.client.gui.screens.worldselection.SelectWorldScreen;
import net.minecraft.client.gui.screens.worldselection.WorldSelectionList;
import net.minecraft.network.chat.contents.TranslatableContents;
import net.minecraft.world.level.storage.LevelSummary;

/** Read-only, same-client-turn observation. No input, world or filesystem access. */
final class WorldSelectionObservation {
    private static final ObservedMenuGeneration GENERATION = new ObservedMenuGeneration();

    static JsonObject capture(Minecraft mc, Screen expectedScreen,
                              Supplier<WorldSelectionSnapshot.Identity> identities) {
        if (!mc.isSameThread()) throw new IllegalStateException("menu_capture_not_client_thread");
        WorldSelectionSnapshot.Identity identity = identities.get();
        long generation = GENERATION.current();
        try {
            Screen screen = mc.screen;
            WorldSelectionSnapshot.need(screen == expectedScreen, "ui_reference_changed");
            if (screen == null || screen.getClass() != SelectWorldScreen.class) {
                generation = GENERATION.observe(screen, null);
                WorldSelectionSnapshot.need(mc.screen == screen && identity.equals(identities.get()), "native_context_changed");
                return WorldSelectionSnapshot.refusal(identity, generation, "wrong_screen");
            }
            Controls controls = controls(screen);
            generation = GENERATION.observe(screen, controls.list);
            WorldSelectionSnapshot.need(controls.list.getScreen() == screen, "ui_reference_changed");
            Capture before = read(screen, controls);
            // No yield. Repeat current values and object identities to detect inconsistent getters/list changes.
            Controls current = controls(screen);
            WorldSelectionSnapshot.need(controls.sameReferences(current) && mc.screen == screen,
                    "ui_reference_changed");
            Capture after = read(screen, current);
            WorldSelectionSnapshot.need(before.sameEntries(after) && before.menu.equals(after.menu),
                    "ui_reference_changed");
            WorldSelectionSnapshot.need(mc.screen == screen && identity.equals(identities.get()),
                    "native_context_changed");
            return WorldSelectionSnapshot.ready(identity, generation, before.menu);
        } catch (WorldSelectionSnapshot.Refused refused) {
            return WorldSelectionSnapshot.refusal(identity, GENERATION.current(), refused.reason);
        } catch (RuntimeException unavailable) {
            return WorldSelectionSnapshot.refusal(identity, GENERATION.current(), "getter_unavailable");
        }
    }

    private record Controls(WorldSelectionList list, EditBox search, Button play) {
        boolean sameReferences(Controls other) {
            return list == other.list && search == other.search && play == other.play;
        }
    }
    private record Capture(List<WorldSelectionList.Entry> entries, WorldSelectionList.Entry selected,
                           WorldSelectionSnapshot.Menu menu) {
        boolean sameEntries(Capture other) {
            if (selected != other.selected || entries.size() != other.entries.size()) return false;
            for (int i = 0; i < entries.size(); i++) if (entries.get(i) != other.entries.get(i)) return false;
            return true;
        }
    }

    private static String key(AbstractWidget widget) {
        return widget.getMessage().getContents() instanceof TranslatableContents translated
                ? translated.getKey() : "";
    }
    private static Controls controls(Screen screen) {
        List<? extends GuiEventListener> children = screen.children();
        WorldSelectionSnapshot.need(children.size() <= 64, "getter_unavailable");
        WorldSelectionList list = null; EditBox search = null; Button play = null;
        for (GuiEventListener child : children) {
            if (child.getClass() == WorldSelectionList.class) {
                WorldSelectionSnapshot.need(list == null, "list_not_unique"); list = (WorldSelectionList) child;
            }
            if (child.getClass() == EditBox.class && "selectWorld.search".equals(key((EditBox) child))) {
                WorldSelectionSnapshot.need(search == null, "search_not_unique"); search = (EditBox) child;
            }
            if (child.getClass() == Button.class && "selectWorld.select".equals(key((Button) child))) {
                WorldSelectionSnapshot.need(play == null, "ordinary_play_not_unique"); play = (Button) child;
            }
        }
        WorldSelectionSnapshot.need(list != null, "list_not_unique");
        WorldSelectionSnapshot.need(search != null, "search_not_unique");
        WorldSelectionSnapshot.need(play != null, "ordinary_play_not_unique");
        return new Controls(list, search, play);
    }
    private static WorldSelectionSnapshot.Rect bounds(AbstractWidget widget) {
        return new WorldSelectionSnapshot.Rect(widget.getX(), widget.getY(), widget.getRight(), widget.getBottom());
    }
    private static Capture read(Screen screen, Controls controls) {
        WorldSelectionList list = controls.list; EditBox search = controls.search; Button play = controls.play;
        WorldSelectionSnapshot.need(list.getScreen() == screen, "ui_reference_changed");
        WorldSelectionSnapshot.need(list.children().size() <= WorldSelectionSnapshot.MAX_ENTRIES, "entry_limit");
        List<WorldSelectionList.Entry> entries = List.copyOf(list.children());
        WorldSelectionSnapshot.need(entries.size() <= WorldSelectionSnapshot.MAX_ENTRIES, "entry_limit");
        WorldSelectionList.Entry selected = list.getSelected();
        WorldSelectionSnapshot.need(selected == list.getSelectedOpt().orElse(null), "selection_inconsistent");
        Integer selectedIndex = null;
        for (int i = 0; i < entries.size(); i++) {
            WorldSelectionSnapshot.need(entries.get(i) instanceof WorldSelectionList.WorldListEntry,
                    "loading_or_unknown_entry");
            if (entries.get(i) == selected) {
                WorldSelectionSnapshot.need(selectedIndex == null, "selection_inconsistent"); selectedIndex = i;
            }
        }
        WorldSelectionSnapshot.need(selected == null || selectedIndex != null, "selection_inconsistent");
        WorldSelectionSnapshot.Rect viewport = bounds(list);
        List<WorldSelectionSnapshot.Row> rows = new ArrayList<>();
        for (int i = 0; i < entries.size(); i++) {
            WorldSelectionList.WorldListEntry entry = (WorldSelectionList.WorldListEntry) entries.get(i);
            WorldSelectionSnapshot.Rect rectangle = new WorldSelectionSnapshot.Rect(list.getRowLeft(),
                    list.getRowTop(i), list.getRowRight(), list.getRowBottom(i));
            if (!rectangle.intersects(viewport)) continue;
            LevelSummary summary = entry.summary;
            WorldSelectionSnapshot.need(summary != null, "getter_unavailable");
            rows.add(new WorldSelectionSnapshot.Row(i, entry.getLevelName(), summary.getLevelId(),
                    summary.getClass().getName(), summary.getClass() == LevelSummary.class, entry == selected,
                    entry.canJoin(), summary.isLocked(), summary.requiresManualConversion(), summary.isCompatible(),
                    summary.shouldBackup(), summary.isExperimental(), rectangle, rectangle.inside(viewport)));
        }
        WorldSelectionSnapshot.Menu menu = new WorldSelectionSnapshot.Menu(screen.getClass().getName(),
                screen.width, screen.height, entries.size(), entries.size(), 0, rows.size(),
                new WorldSelectionSnapshot.Search(search.getValue(), search.isFocused(), search.visible,
                        search.active, key(search), bounds(search)),
                new WorldSelectionSnapshot.ListView(list.getClass().getName(), list.visible, list.active,
                        viewport, list.getScrollAmount()), selectedIndex,
                new WorldSelectionSnapshot.Play(key(play), play.visible, play.active, bounds(play)), List.copyOf(rows));
        return new Capture(entries, selected, menu);
    }
    private WorldSelectionObservation() { }
}

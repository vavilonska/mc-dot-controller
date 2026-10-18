package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.util.Set;
import java.util.UUID;
import java.lang.ref.WeakReference;
import net.minecraft.client.Minecraft;
import net.minecraft.world.inventory.AbstractContainerMenu;
import net.minecraft.world.item.ItemStack;

/** Additive exact-state fence for explicit recovery using ordinary vanilla PICKUP clicks. */
final class InventoryRecoveryGuard {
    static final String FEATURE = "inventory-recovery/1";
    private static WeakReference<Object> observedMenu = new WeakReference<>(null);
    private static WeakReference<Object> observedScreen = new WeakReference<>(null);
    private static String menuIdentity, screenIdentity = "none";
    private static final Set<String> MENUS = Set.of("InventoryMenu", "ChestMenu", "HopperMenu", "DispenserMenu", "ShulkerBoxMenu");
    static JsonObject context(AbstractContainerMenu menu) {
        Object screen = Minecraft.getInstance().screen;
        // Reference identity, never a mod-provided equals/hashCode; no retained old worlds/screens.
        if (observedMenu.get() != menu) {
            observedMenu = new WeakReference<>(menu); menuIdentity = UUID.randomUUID().toString();
        }
        if (observedScreen.get() != screen || screen == null && !screenIdentity.equals("none")) {
            observedScreen = new WeakReference<>(screen); screenIdentity = screen == null ? "none" : UUID.randomUUID().toString();
        }
        var out = new JsonObject();
        out.addProperty("schema_version", 1);
        out.addProperty("menu_instance", menuIdentity);
        out.addProperty("screen_instance", screenIdentity);
        out.addProperty("screen_open", screen != null);
        return out;
    }
    static void validate(ClientActionRequest request) {
        JsonObject body = request.original();
        if (!body.has("inventory_recovery")) return;
        need(body.has("capability_guard") && request.action().equals("click_slot")
            && request.clickType().equals("pickup") && request.button() == 0 && request.slot() >= 0,
            "inventory_recovery_guarded_pickup_required");
        JsonObject spec = object(body, "inventory_recovery");
        need(spec.keySet().equals(Set.of("schema_version", "phase", "context", "selected_slot", "inventory", "slots"))
            && ClientActionRequest.integer(spec, "schema_version", -1) == 1,
            "inventory_recovery_invalid_schema");
        need(Set.of("pickup_hand", "store_cursor").contains(ClientActionRequest.string(spec, "phase")),
            "inventory_recovery_invalid_phase");
        int selected = ClientActionRequest.integer(spec, "selected_slot", -1);
        need(selected >= 0 && selected <= 8, "inventory_recovery_invalid_selection");
        JsonObject context = object(spec, "context");
        need(context.keySet().equals(Set.of("schema_version", "menu_instance", "screen_instance", "screen_open"))
            && ClientActionRequest.integer(context, "schema_version", -1) == 1,
            "inventory_recovery_invalid_context");
        String menu = ClientActionRequest.string(context, "menu_instance"), screen = ClientActionRequest.string(context, "screen_instance");
        need(uuid(menu) && (uuid(screen) || screen.equals("none"))
            && ClientActionRequest.bool(context, "screen_open", false) == !screen.equals("none"),
            "inventory_recovery_invalid_context");
        need(context.has("screen_open"), "inventory_recovery_invalid_context");
        need(spec.has("inventory") && spec.get("inventory").isJsonArray()
            && spec.getAsJsonArray("inventory").size() == 41, "inventory_recovery_inventory_coverage_required");
        for (int i = 0; i < 41; i++) {
            var element = spec.getAsJsonArray("inventory").get(i);
            need(element.isJsonObject(), "inventory_recovery_invalid_inventory");
            var row = element.getAsJsonObject();
            need(row.keySet().equals(Set.of("slot", "item_fingerprint"))
                && ClientActionRequest.integer(row, "slot", -1) == i, "inventory_recovery_invalid_inventory");
            fingerprint(row);
        }
        need(spec.has("slots") && spec.get("slots").isJsonArray()
            && spec.getAsJsonArray("slots").size() >= 41 && spec.getAsJsonArray("slots").size() <= 90,
            "inventory_recovery_menu_coverage_required");
        int index = 0;
        for (var element : spec.getAsJsonArray("slots")) {
            need(element.isJsonObject(), "inventory_recovery_invalid_slot");
            var row = element.getAsJsonObject();
            boolean player = ClientActionRequest.bool(row, "player_inventory", false);
            need(row.keySet().equals(player
                ? Set.of("menu_index", "slot_index", "container_slot", "player_inventory", "active", "inventory_index", "item_fingerprint")
                : Set.of("menu_index", "slot_index", "container_slot", "player_inventory", "active", "item_fingerprint")),
                "inventory_recovery_invalid_slot");
            need(ClientActionRequest.integer(row, "menu_index", -1) == index
                && ClientActionRequest.integer(row, "slot_index", -1) == index++
                && ClientActionRequest.integer(row, "container_slot", -1) >= 0,
                "inventory_recovery_invalid_slot");
            ClientActionRequest.bool(row, "active", false);
            if (player) need(ClientActionRequest.integer(row, "inventory_index", -1)
                == ClientActionRequest.integer(row, "container_slot", -2), "inventory_recovery_invalid_mapping");
            fingerprint(row);
        }
    }
    static String check(Minecraft mc, ClientActionRequest request) {
        if (!request.original().has("inventory_recovery")) return null;
        if (!InventoryRecoveryDispatch.ready()) return "inventory_recovery_native_fence_unavailable";
        var spec = request.original().getAsJsonObject("inventory_recovery");
        var menu = mc.player.containerMenu;
        String simple = menu.getClass().getSimpleName();
        if (!MENUS.contains(simple) || !menu.getClass().getName().equals("net.minecraft.world.inventory." + simple))
            return "inventory_recovery_menu_unsupported";
        if (!sameFacts(mc, spec)) return "inventory_recovery_bound_state_changed";
        if (request.slot() >= menu.slots.size()) return "inventory_recovery_slot_unavailable";
        var slot = menu.slots.get(request.slot());
        if (slot.container != mc.player.getInventory() || !slot.isActive()) return "inventory_recovery_storage_required";
        int index = slot.getContainerSlot();
        if (ClientActionRequest.string(spec, "phase").equals("pickup_hand")) {
            if (!simple.equals("InventoryMenu") || mc.screen != null || !menu.getCarried().isEmpty()
                || (index != mc.player.getInventory().selected && index != 40)
                || slot.getItem().isEmpty() || !slot.mayPickup(mc.player)) return "inventory_recovery_hand_pickup_disallowed";
        } else {
            ItemStack carried = menu.getCarried(), target = slot.getItem();
            if (index < 0 || index > 35 || carried.isEmpty() || !slot.mayPlace(carried)
                || (!target.isEmpty() && !ItemStack.isSameItemSameComponents(target, carried))
                || target.getCount() >= Math.min(64, slot.getMaxStackSize(carried)))
                return "inventory_recovery_destination_disallowed";
        }
        // Slot permission callbacks are not assumed pure; no effect if they changed any binding.
        return sameFacts(mc, spec) ? null : "inventory_recovery_bound_state_changed";
    }
    private static boolean sameFacts(Minecraft mc, JsonObject spec) {
        if (mc.player == null || mc.level == null) return false;
        var inventory = mc.player.getInventory(); var menu = mc.player.containerMenu;
        if (inventory.getContainerSize() != 41 || !context(menu).equals(spec.get("context"))
            || inventory.selected != spec.get("selected_slot").getAsInt()
            || menu.slots.size() != spec.getAsJsonArray("slots").size()) return false;
        for (int i = 0; i < 41; i++) if (!CapabilityItemBinding.matches(
            spec.getAsJsonArray("inventory").get(i).getAsJsonObject(), inventory.getItem(i))) return false;
        for (int i = 0; i < menu.slots.size(); i++) {
            var slot = menu.slots.get(i); var expected = spec.getAsJsonArray("slots").get(i).getAsJsonObject();
            boolean player = slot.container == inventory;
            if (slot.index != i || slot.getContainerSlot() != expected.get("container_slot").getAsInt()
                || player != expected.get("player_inventory").getAsBoolean()
                || slot.isActive() != expected.get("active").getAsBoolean()
                || !CapabilityItemBinding.matches(expected, slot.getItem())) return false;
        }
        return mc.player != null && mc.player.getInventory() == inventory && mc.player.containerMenu == menu
            && context(menu).equals(spec.get("context"));
    }
    private static boolean uuid(String value) { return value.matches("[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"); }
    private static void fingerprint(JsonObject row) {
        String value = ClientActionRequest.string(row, "item_fingerprint");
        need(!value.isBlank() && value.length() <= 128, "inventory_recovery_invalid_fingerprint");
    }
    private static JsonObject object(JsonObject body, String key) {
        need(body.has(key) && body.get(key).isJsonObject(), "inventory_recovery_invalid_" + key);
        return body.getAsJsonObject(key);
    }
    private static void need(boolean condition, String reason) { ClientActionRequest.require(condition, reason); }
    private InventoryRecoveryGuard() { }
}

package io.github.campione01.mineclientbridge;

import static org.junit.jupiter.api.Assertions.*;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.lang.reflect.Constructor;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.parallel.Execution;
import org.junit.jupiter.api.parallel.ExecutionMode;

/** Real Minecraft object gates. Default skip is an unmet platform gate, not a pass. */
@EnabledIfEnvironmentVariable(named = "MDC_REAL_MOD_LOADER_TESTS", matches = "true")
@Execution(ExecutionMode.SAME_THREAD)
class BoundedContainerSnapshotTest {
    private static final Set<String> EMPTY_FIELDS =
            Set.of("empty", "id", "count", "damage", "max_damage");
    private static final Set<String> CARGO_FIELDS =
            Set.of("slot", "id", "count", "damage", "identity_complete");
    private static Class<?> items;
    private static Class<?> stackType;
    private static Class<?> componentType;
    private static Class<?> dataComponents;
    private static Constructor<?> stackConstructor;
    private static Method itemSnapshot;
    private static Method append;
    private static Method beginSnapshot;

    @BeforeAll
    static void initializeRealMinecraftTypes() throws Exception {
        // An actual NeoForge loader must already exist. Never install a fake
        // LoadingModList, substitute registry objects, or swallow bootstrap failure.
        invoke(Class.forName("net.minecraft.SharedConstants")
                .getMethod("tryDetectVersion"), null);
        invoke(Class.forName("net.minecraft.server.Bootstrap")
                .getMethod("bootStrap"), null);
        items = Class.forName("net.minecraft.world.item.Items");
        stackType = Class.forName("net.minecraft.world.item.ItemStack");
        componentType = Class.forName("net.minecraft.core.component.DataComponentType");
        dataComponents = Class.forName("net.minecraft.core.component.DataComponents");
        stackConstructor = stackType.getConstructor(
                Class.forName("net.minecraft.world.level.ItemLike"), int.class);
        Class<?> bridge = Class.forName("io.github.campione01.mineclientbridge.BridgeServer");
        itemSnapshot = bridge.getDeclaredMethod("itemSnapshot", stackType);
        itemSnapshot.setAccessible(true);
        Class<?> helper = Class.forName(
                "io.github.campione01.mineclientbridge.BoundedContainerSnapshot");
        append = helper.getDeclaredMethod("append", stackType, JsonObject.class);
        append.setAccessible(true);
        beginSnapshot = helper.getDeclaredMethod("beginSnapshot");
        beginSnapshot.setAccessible(true);
    }

    @BeforeEach
    void resetSnapshotBudget() throws Exception {
        invoke(beginSnapshot, null);
    }

    @Test
    void nullAndEmptyKeepExactlyTheLegacyFiveFields() throws Exception {
        assertEmpty(snapshot(null));
        assertEmpty(snapshot(stackType.getField("EMPTY").get(null)));
    }

    @Test
    void stonePreservesBasicValuesAndReportsCompleteIdentity() throws Exception {
        JsonObject item = snapshot(stack("STONE", 19));
        assertEquals(Set.of("empty", "id", "count", "damage", "max_damage",
                "unrepresented_component_changes", "identity_complete"), item.keySet());
        assertFalse(item.get("empty").getAsBoolean());
        assertEquals("minecraft:stone", item.get("id").getAsString());
        assertEquals(19, item.get("count").getAsInt());
        assertEquals(0, item.get("damage").getAsInt());
        assertEquals(0, item.get("max_damage").getAsInt());
        assertEquals(0, item.get("unrepresented_component_changes").getAsInt());
        assertTrue(item.get("identity_complete").getAsBoolean());
    }

    @Test
    void customNamesAt128And129And1024HaveAnExplicit128CharacterBound() throws Exception {
        for (int length : new int[]{128, 129, 1024}) {
            Object named = stack("STONE", 1);
            setComponent(named, "CUSTOM_NAME", literal("n".repeat(length)));
            JsonObject item = snapshot(named);
            assertEquals("n".repeat(128), item.get("custom_name").getAsString());
            assertEquals(length > 128, item.get("custom_name_truncated").getAsBoolean());
            assertEquals(0, item.get("unrepresented_component_changes").getAsInt());
            assertFalse(item.get("identity_complete").getAsBoolean(),
                    "Plain text does not establish exact component identity: " + length);
        }
    }

    @Test
    void swordDamageValueIsRepresentedButRemovingItsPrototypeComponentIsNot() throws Exception {
        Object sword = stack("IRON_SWORD", 1);
        assertEquals(0, getComponent(sword, "DAMAGE"));
        JsonObject pristine = snapshot(sword);
        assertEquals(0, pristine.get("damage").getAsInt());
        assertEquals(250, pristine.get("max_damage").getAsInt());
        assertTrue(pristine.get("identity_complete").getAsBoolean());

        setComponent(sword, "DAMAGE", 7);
        JsonObject damaged = snapshot(sword);
        assertEquals(7, damaged.get("damage").getAsInt());
        assertEquals(250, damaged.get("max_damage").getAsInt());
        assertEquals(0, damaged.get("unrepresented_component_changes").getAsInt());
        assertTrue(damaged.get("identity_complete").getAsBoolean());

        Object removed = stack("IRON_SWORD", 1);
        invoke(stackType.getMethod("remove", componentType), removed, component("DAMAGE"));
        assertNull(getComponent(removed, "DAMAGE"));
        JsonObject absent = snapshot(removed);
        assertEquals(0, absent.get("damage").getAsInt());
        assertEquals(250, absent.get("max_damage").getAsInt());
        assertEquals(1, absent.get("unrepresented_component_changes").getAsInt());
        assertFalse(absent.get("identity_complete").getAsBoolean(),
                "The same numeric damage as a pristine sword cannot hide component removal");
    }

    @Test
    void nestedAndComponentBearingCargoStayVisibleWithoutRecursiveIdentityClaims() throws Exception {
        Object named = stack("STONE", 2);
        setComponent(named, "CUSTOM_NAME", literal("cargo name must not be serialized"));
        Object nested = box(List.of(stack("DIAMOND", 3)));
        JsonObject item = snapshot(box(List.of(stack("STONE", 4), named, nested)));
        JsonObject container = item.getAsJsonObject("container");
        assertContainerHeader(container, 3, false);
        JsonArray cargo = container.getAsJsonArray("items");
        assertEquals(3, cargo.size());
        assertCargo(cargo.get(0).getAsJsonObject(), 0, "minecraft:stone", 4, true);
        assertCargo(cargo.get(1).getAsJsonObject(), 1, "minecraft:stone", 2, false);
        assertCargo(cargo.get(2).getAsJsonObject(), 2, "minecraft:shulker_box", 1, false);
        assertFalse(item.get("identity_complete").getAsBoolean());
        assertEquals(0, item.get("unrepresented_component_changes").getAsInt());
        assertFalse(item.toString().contains("minecraft:diamond"));
        assertFalse(item.toString().contains("cargo name must not be serialized"));
    }

    @Test
    void bridgeAndHelperShareFourBoxBudgetAndExplicitResetRestoresIt() throws Exception {
        Object box = box(List.of(stack("STONE", 1)));
        for (int index = 0; index < 5; index++) {
            JsonObject item;
            if (index % 2 == 0) {
                item = snapshot(box);
            } else {
                item = new JsonObject();
                invoke(append, null, box, item);
            }
            JsonObject container = item.getAsJsonObject("container");
            assertContainerHeader(container, 1, index == 4);
            assertEquals(index < 4 ? 1 : 0, container.getAsJsonArray("items").size());
            assertEquals(index < 4, item.get("identity_complete").getAsBoolean());
        }
        invoke(beginSnapshot, null);
        JsonObject reset = snapshot(box);
        assertContainerHeader(reset.getAsJsonObject("container"), 1, false);
        assertEquals(1, reset.getAsJsonObject("container").getAsJsonArray("items").size());
        assertTrue(reset.get("identity_complete").getAsBoolean());
    }

    @Test
    void real28SlotContentsReturnOnlySlotsZeroThrough26AndMarkTruncation() throws Exception {
        List<Object> contents = new ArrayList<>();
        for (int slot = 0; slot < 28; slot++) contents.add(stack("STONE", slot + 1));
        JsonObject item = snapshot(box(contents));
        JsonObject container = item.getAsJsonObject("container");
        assertContainerHeader(container, 28, true);
        JsonArray cargo = container.getAsJsonArray("items");
        assertEquals(27, cargo.size());
        for (int slot = 0; slot < 27; slot++) {
            assertCargo(cargo.get(slot).getAsJsonObject(), slot, "minecraft:stone", slot + 1, true);
        }
        assertFalse(item.get("identity_complete").getAsBoolean());
    }

    private static Object stack(String item, int count) throws Exception {
        return stackConstructor.newInstance(items.getField(item).get(null), count);
    }

    private static Object component(String field) throws Exception {
        return dataComponents.getField(field).get(null);
    }

    private static Object literal(String text) throws Exception {
        return invoke(Class.forName("net.minecraft.network.chat.Component")
                .getMethod("literal", String.class), null, text);
    }

    private static void setComponent(Object stack, String field, Object value) throws Exception {
        invoke(stackType.getMethod("set", componentType, Object.class), stack, component(field), value);
    }

    private static Object getComponent(Object stack, String field) throws Exception {
        return invoke(stackType.getMethod("get", componentType), stack, component(field));
    }

    private static Object box(List<Object> cargo) throws Exception {
        Object box = stack("SHULKER_BOX", 1);
        Object contents = invoke(Class.forName("net.minecraft.world.item.component.ItemContainerContents")
                .getMethod("fromItems", List.class), null, cargo);
        setComponent(box, "CONTAINER", contents);
        return box;
    }

    private static JsonObject snapshot(Object stack) throws Exception {
        return (JsonObject) invoke(itemSnapshot, null, stack);
    }

    private static void assertEmpty(JsonObject item) {
        assertEquals(EMPTY_FIELDS, item.keySet());
        assertTrue(item.get("empty").getAsBoolean());
        assertEquals("", item.get("id").getAsString());
        for (String field : List.of("count", "damage", "max_damage")) {
            assertEquals(0, item.get(field).getAsInt());
        }
    }

    private static void assertContainerHeader(JsonObject container, int extent, boolean truncated) {
        assertEquals(Set.of("schema_version", "capacity", "nested_containers_supported",
                "slots_truncated", "slot_extent", "items"), container.keySet());
        assertEquals(1, container.get("schema_version").getAsInt());
        assertEquals(27, container.get("capacity").getAsInt());
        assertFalse(container.get("nested_containers_supported").getAsBoolean());
        assertEquals(extent, container.get("slot_extent").getAsInt());
        assertEquals(truncated, container.get("slots_truncated").getAsBoolean());
    }

    private static void assertCargo(JsonObject row, int slot, String id, int count, boolean exact) {
        assertEquals(CARGO_FIELDS, row.keySet());
        assertEquals(slot, row.get("slot").getAsInt());
        assertEquals(id, row.get("id").getAsString());
        assertEquals(count, row.get("count").getAsInt());
        assertEquals(0, row.get("damage").getAsInt());
        assertEquals(exact, row.get("identity_complete").getAsBoolean());
    }

    private static Object invoke(Method method, Object target, Object... arguments) throws Exception {
        try {
            return method.invoke(target, arguments);
        } catch (InvocationTargetException failure) {
            Throwable cause = failure.getCause();
            if (cause instanceof Exception exception) throw exception;
            if (cause instanceof Error error) throw error;
            throw new AssertionError("Real Minecraft invocation failed", cause);
        }
    }
}

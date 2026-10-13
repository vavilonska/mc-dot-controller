package io.github.campione01.mineclientbridge;

import java.lang.reflect.Field;
import java.util.Map;
import java.util.UUID;
import net.minecraft.SharedConstants;
import net.minecraft.network.syncher.SynchedEntityData;
import net.minecraft.server.Bootstrap;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.EntityType;
import net.minecraft.world.entity.animal.Bee;
import net.minecraft.world.entity.animal.Rabbit;
import net.minecraft.world.entity.Mob;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.ai.goal.Goal;
import net.minecraft.world.entity.ai.goal.GoalSelector;
import net.minecraft.world.entity.ai.goal.FloatGoal;
import net.minecraft.world.entity.ai.goal.WrappedGoal;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.parallel.Execution;
import org.junit.jupiter.api.parallel.ExecutionMode;
import static org.junit.jupiter.api.Assertions.*;

/** Genuine FML registries and vanilla Bee/Rabbit accessors and registered goals. No game, server, level, fake loader or AI loop. */
@EnabledIfEnvironmentVariable(named="MDC_REAL_MOD_LOADER_TESTS", matches="true")
@Execution(ExecutionMode.SAME_THREAD)
class NativeLivingObservationLoaderTest {
    @BeforeAll static void bootstrap() { SharedConstants.tryDetectVersion(); Bootstrap.bootStrap(); }
    private static void field(Class<?> type, Object instance, String name, Object value) throws Exception {
        Field field = type.getDeclaredField(name); field.setAccessible(true); field.set(instance, value);
    }
    @SuppressWarnings("unchecked")
    private static <T> void baseData(SynchedEntityData.Builder builder, String name, T value) throws Exception {
        Field f = Entity.class.getDeclaredField(name); f.setAccessible(true);
        builder.define((net.minecraft.network.syncher.EntityDataAccessor<T>) f.get(null), value);
    }
    private static Bee bee(int id) throws Exception {
        Field f = sun.misc.Unsafe.class.getDeclaredField("theUnsafe"); f.setAccessible(true);
        Bee bee = (Bee) ((sun.misc.Unsafe) f.get(null)).allocateInstance(Bee.class);
        field(Entity.class, bee, "type", EntityType.BEE); field(Entity.class, bee, "uuid", UUID.randomUUID());
        field(Entity.class, bee, "id", id);
        SynchedEntityData.Builder builder = new SynchedEntityData.Builder(bee);
        // These eight defaults are initialized directly by Entity's pinned constructor,
        // before its virtual defineSynchedData call. Use the real vanilla accessors.
        baseData(builder, "DATA_SHARED_FLAGS_ID", (byte) 0);
        baseData(builder, "DATA_AIR_SUPPLY_ID", bee.getMaxAirSupply());
        baseData(builder, "DATA_CUSTOM_NAME_VISIBLE", false);
        baseData(builder, "DATA_CUSTOM_NAME", java.util.Optional.<net.minecraft.network.chat.Component>empty());
        baseData(builder, "DATA_SILENT", false); baseData(builder, "DATA_NO_GRAVITY", false);
        baseData(builder, "DATA_POSE", net.minecraft.world.entity.Pose.STANDING);
        baseData(builder, "DATA_TICKS_FROZEN", 0);
        var define = Bee.class.getDeclaredMethod("defineSynchedData", SynchedEntityData.Builder.class);
        define.setAccessible(true); define.invoke(bee, builder);
        field(Entity.class, bee, "entityData", builder.build());
        return bee;
    }
    @Test void genuineBeeDefaultFieldsAreObservedWithoutDistanceInference() throws Exception {
        Bee bee = bee(7); var row = NativeLivingObservation.read(bee, 123, 1_000L);
        assertEquals("minecraft:bee", row.type()); assertEquals(bee.getUUID().toString(), row.uuid());
        assertEquals(7, row.entityId()); assertEquals(123, row.tick()); assertEquals(1_000L, row.nano());
        assertFalse(row.aggressive()); assertNull(row.target()); assertFalse(row.bee().angry());
        assertEquals(0, row.bee().remainingAngerTicks()); assertNull(row.bee().persistentAngerTargetUuid());
    }
    @Test void genuineSyncedAngerAccessorAndAggressiveFlagRemainSeparateFacts() throws Exception {
        Bee bee = bee(7); bee.setRemainingPersistentAngerTime(240); bee.setAggressive(true);
        var row = NativeLivingObservation.read(bee, 1, 1);
        assertTrue(row.aggressive()); assertTrue(row.bee().angry()); assertEquals(240, row.bee().remainingAngerTicks());
        bee.setRemainingPersistentAngerTime(0);
        row = NativeLivingObservation.read(bee, 1, 2);
        assertFalse(row.bee().angry()); assertTrue(row.aggressive(), "Zero anger alone does not establish calm");
    }
    @Test void genuineUnsyncedCurrentAndPersistentTargetsAreNeverInferredFromFlags() throws Exception {
        Bee bee = bee(7), target = bee(8); bee.setTarget(target); bee.setPersistentAngerTarget(target.getUUID());
        var row = NativeLivingObservation.read(bee, 1, 1);
        assertFalse(row.aggressive()); assertFalse(row.bee().angry());
        assertEquals(target.getUUID().toString(), row.target().uuid()); assertEquals(8, row.target().entityId());
        assertEquals("minecraft:bee", row.target().type()); assertEquals(target.getUUID().toString(), row.bee().persistentAngerTargetUuid());
        bee.setTarget(null); bee.setPersistentAngerTarget(null);
        row = NativeLivingObservation.read(bee, 1, 2); assertNull(row.target()); assertNull(row.bee().persistentAngerTargetUuid());
    }
    @Test void nativeTargetIdentitySurvivesTypedJsonAndStaleEvidenceIsUnknown() throws Exception {
        Bee bee = bee(7), target = bee(8); bee.setTarget(target); Object context = new Object();
        var row = NativeLivingObservation.read(bee, 100, 1_000_000_000L);
        var batch = new NativeLivingSnapshot.Batch(context, new Object(), "minecraft:overworld", Map.of(row.uuid(), row), true, 2, "observed");
        var json = NativeLivingSnapshot.json(batch, context, "minecraft:overworld", "world", "player", row.uuid(), row.entityId(), row.type(), 100, 1_000_000_000L);
        assertTrue(json.get("known").getAsBoolean()); assertEquals(target.getUUID().toString(), json.getAsJsonObject("current_target").get("uuid").getAsString());
        json = NativeLivingSnapshot.json(batch, context, "minecraft:overworld", "world", "player", row.uuid(), row.entityId(), row.type(), 100, 1_250_000_001L);
        assertFalse(json.get("known").getAsBoolean()); assertFalse(json.has("current_target"));
    }
    @Test void genuineBeeTargetsSurviveProductionHttpEncoderAndKnownNullRemainsDistinct() throws Exception {
        Bee bee = bee(7), target = bee(8); Object context = new Object();
        for (boolean hasTarget : new boolean[]{false, true}) {
            bee.setTarget(hasTarget ? target : null);
            bee.setPersistentAngerTarget(hasTarget ? target.getUUID() : null);
            var row = NativeLivingObservation.read(bee, 100, 1_000_000_000L);
            var batch = new NativeLivingSnapshot.Batch(context, new Object(), "minecraft:overworld", Map.of(row.uuid(), row), true, 2, "observed");
            var facts = NativeLivingSnapshot.json(batch, context, "minecraft:overworld", "world", "player",
                    row.uuid(), row.entityId(), row.type(), 100, 1_050_000_000L);
            var entity = new com.google.gson.JsonObject(); entity.add("native_living", facts);
            var entities = new com.google.gson.JsonArray(); entities.add(entity);
            var nearby = new com.google.gson.JsonObject(); nearby.add("entities", entities);
            var state = new com.google.gson.JsonObject(); state.add("nearby", nearby);
            var parsed = com.google.gson.JsonParser.parseString(BridgeJson.toJson(state)).getAsJsonObject()
                    .getAsJsonObject("nearby").getAsJsonArray("entities").get(0).getAsJsonObject().getAsJsonObject("native_living");
            assertEquals(facts, parsed);
            assertTrue(parsed.has("current_target"));
            assertTrue(parsed.getAsJsonObject("bee").has("persistent_anger_target_uuid"));
            if (hasTarget) {
                assertEquals(target.getUUID().toString(), parsed.getAsJsonObject("current_target").get("uuid").getAsString());
                assertEquals(target.getUUID().toString(), parsed.getAsJsonObject("bee").get("persistent_anger_target_uuid").getAsString());
            } else {
                assertTrue(parsed.get("current_target").isJsonNull());
                assertTrue(parsed.getAsJsonObject("bee").get("persistent_anger_target_uuid").isJsonNull());
            }
        }
    }


    private static sun.misc.Unsafe unsafe() throws Exception {
        Field f = sun.misc.Unsafe.class.getDeclaredField("theUnsafe"); f.setAccessible(true);
        return (sun.misc.Unsafe) f.get(null);
    }
    private static GoalSelector selector() {
        return new GoalSelector(() -> net.minecraft.util.profiling.InactiveProfiler.INSTANCE);
    }
    private static Rabbit rabbit(Class<? extends Rabbit> type) throws Exception {
        Rabbit rabbit = (Rabbit) unsafe().allocateInstance(type);
        field(Entity.class, rabbit, "type", EntityType.RABBIT); field(Entity.class, rabbit, "uuid", UUID.randomUUID());
        field(Entity.class, rabbit, "id", 9);
        field(Entity.class, rabbit, "random", net.minecraft.util.RandomSource.create(123));
        SynchedEntityData.Builder builder = new SynchedEntityData.Builder(rabbit);
        baseData(builder, "DATA_SHARED_FLAGS_ID", (byte) 0);
        baseData(builder, "DATA_AIR_SUPPLY_ID", rabbit.getMaxAirSupply());
        baseData(builder, "DATA_CUSTOM_NAME_VISIBLE", false);
        baseData(builder, "DATA_CUSTOM_NAME", java.util.Optional.<net.minecraft.network.chat.Component>empty());
        baseData(builder, "DATA_SILENT", false); baseData(builder, "DATA_NO_GRAVITY", false);
        baseData(builder, "DATA_POSE", net.minecraft.world.entity.Pose.STANDING); baseData(builder, "DATA_TICKS_FROZEN", 0);
        var define = Rabbit.class.getDeclaredMethod("defineSynchedData", SynchedEntityData.Builder.class);
        define.setAccessible(true); define.invoke(rabbit, builder);
        field(Entity.class, rabbit, "entityData", builder.build());
        field(LivingEntity.class, rabbit, "attributes", new net.minecraft.world.entity.ai.attributes.AttributeMap(Rabbit.createAttributes().build()));
        field(Mob.class, rabbit, "goalSelector", selector()); field(Mob.class, rabbit, "targetSelector", selector());
        // Real registration needs only the navigation evaluator's FloatGoal constructor setting.
        // No level, world, path computation, constructor AI loop or game entrypoint exists here.
        var navigation = (net.minecraft.world.entity.ai.navigation.GroundPathNavigation)
                unsafe().allocateInstance(net.minecraft.world.entity.ai.navigation.GroundPathNavigation.class);
        field(net.minecraft.world.entity.ai.navigation.PathNavigation.class, navigation, "nodeEvaluator", new net.minecraft.world.level.pathfinder.WalkNodeEvaluator());
        field(Mob.class, rabbit, "navigation", navigation);
        var register = Rabbit.class.getDeclaredMethod("registerGoals"); register.setAccessible(true); register.invoke(rabbit);
        return rabbit;
    }
    private static Rabbit rabbit() throws Exception { return rabbit(Rabbit.class); }
    private static class OtherRabbit extends Rabbit {
        OtherRabbit() { super(EntityType.RABBIT, null); }
    }
    private static com.google.gson.JsonObject rabbitWire(Rabbit rabbit) throws Exception {
        Object context = new Object(); var row = NativeLivingObservation.read(rabbit, 100, 1_000_000_000L);
        var batch = new NativeLivingSnapshot.Batch(context, new Object(), "minecraft:overworld", Map.of(row.uuid(), row), true, 1, "observed");
        var facts = NativeLivingSnapshot.json(batch, context, "minecraft:overworld", "world", "player",
                row.uuid(), row.entityId(), row.type(), 100, 1_050_000_000L);
        var entity = new com.google.gson.JsonObject(); entity.add("native_living", facts);
        var entities = new com.google.gson.JsonArray(); entities.add(entity);
        var nearby = new com.google.gson.JsonObject(); nearby.add("entities", entities);
        var root = new com.google.gson.JsonObject(); root.add("nearby", nearby);
        var parsed = com.google.gson.JsonParser.parseString(BridgeJson.toJson(root)).getAsJsonObject()
                .getAsJsonObject("nearby").getAsJsonArray("entities").get(0).getAsJsonObject().getAsJsonObject("native_living");
        assertEquals(facts, parsed); assertTrue(parsed.get("current_target").isJsonNull());
        return parsed;
    }
    @Test void genuineRabbitEnumIdsAndNormalRegisteredGoalInventoriesArePinned() throws Exception {
        assertArrayEquals(new int[]{0,1,2,3,4,5,99}, java.util.Arrays.stream(Rabbit.Variant.values()).mapToInt(Rabbit.Variant::id).toArray());
        for (Rabbit.Variant variant : Rabbit.Variant.values()) {
            if (variant == Rabbit.Variant.EVIL) continue;
            Rabbit rabbit = rabbit(); rabbit.setVariant(variant);
            assertEquals(11, rabbit.goalSelector.getAvailableGoals().size()); assertTrue(rabbit.targetSelector.getAvailableGoals().isEmpty());
            var row = NativeLivingObservation.read(rabbit, 123, 1_000L);
            assertEquals(variant.id(), row.rabbit().variantId()); assertFalse(row.rabbit().killerBunny());
            assertTrue(row.rabbit().passiveGoalsVerified()); assertNull(row.bee());
            assertEquals(123, row.tick()); assertEquals(1_000L, row.nano());
            var parsed = rabbitWire(rabbit).getAsJsonObject("rabbit");
            assertEquals(variant.id(), parsed.get("variant_id").getAsInt()); assertTrue(parsed.get("passive_goals_verified").getAsBoolean());
        }
    }
    @Test void genuineEvilToOrdinaryConversionRetainsAttackGoalsAndIsNeverPassive() throws Exception {
        Rabbit rabbit = rabbit(); var before = NativeLivingObservation.read(rabbit, 1, 1);
        rabbit.setVariant(Rabbit.Variant.EVIL);
        assertEquals(12, rabbit.goalSelector.getAvailableGoals().size()); assertEquals(3, rabbit.targetSelector.getAvailableGoals().size());
        var evil = rabbitWire(rabbit).getAsJsonObject("rabbit");
        assertEquals(99, evil.get("variant_id").getAsInt()); assertTrue(evil.get("killer_bunny").getAsBoolean());
        assertFalse(evil.get("passive_goals_verified").getAsBoolean());
        rabbit.setVariant(Rabbit.Variant.BROWN);
        assertEquals(12, rabbit.goalSelector.getAvailableGoals().size()); assertEquals(3, rabbit.targetSelector.getAvailableGoals().size());
        var converted = rabbitWire(rabbit).getAsJsonObject("rabbit");
        assertEquals(0, converted.get("variant_id").getAsInt()); assertFalse(converted.get("killer_bunny").getAsBoolean());
        assertFalse(converted.get("passive_goals_verified").getAsBoolean());
        assertTrue(before.rabbit().passiveGoalsVerified(), "The original immutable tick row cannot change with the live entity");
    }
    @Test void rawUnknownRabbitIdsAreNotNormalizedIntoBenignBrownProof() throws Exception {
        Rabbit rabbit = rabbit();
        for (int id : new int[]{-1,6,98,100,Integer.MAX_VALUE}) {
            rabbit.getEntityData().set(Rabbit.DATA_TYPE_ID, id);
            assertEquals(Rabbit.Variant.BROWN, rabbit.getVariant(), "Pinned getter has a benign-looking unknown-ID fallback");
            assertNull(NativeLivingObservation.read(rabbit, 1, 1).rabbit()); assertFalse(rabbitWire(rabbit).has("rabbit"));
        }
    }
    @Test void exactRabbitClassAndRegistryTypeAreRequiredAndBeeNullsStayUnchanged() throws Exception {
        assertNull(NativeLivingObservation.read(bee(7), 1, 1).rabbit());
        assertNull(NativeLivingObservation.read(rabbit(OtherRabbit.class), 1, 1).rabbit());
        Rabbit rabbit = rabbit(); field(Entity.class, rabbit, "type", EntityType.COW);
        assertNull(NativeLivingObservation.read(rabbit, 1, 1).rabbit());
    }
    @Test void unknownOrSubclassGoalsAndAnyTargetGoalCannotVerifyPassiveInventory() throws Exception {
        Rabbit rabbit = rabbit(); rabbit.goalSelector.addGoal(1, new Goal() { public boolean canUse() { return false; } });
        assertFalse(NativeLivingObservation.read(rabbit, 1, 1).rabbit().passiveGoalsVerified());
        rabbit = rabbit(); rabbit.goalSelector.addGoal(1, new FloatGoal(rabbit) { });
        assertFalse(NativeLivingObservation.read(rabbit, 1, 1).rabbit().passiveGoalsVerified());
        rabbit = rabbit(); rabbit.targetSelector.addGoal(1, new FloatGoal(rabbit));
        assertFalse(NativeLivingObservation.read(rabbit, 1, 1).rabbit().passiveGoalsVerified());
    }
    @Test void unavailableOverLimitAndOverriddenGoalInventoriesStayUnknown() throws Exception {
        Rabbit rabbit = rabbit(); field(Mob.class, rabbit, "goalSelector", null);
        assertNull(NativeLivingObservation.read(rabbit, 1, 1).rabbit());
        rabbit = rabbit(); field(GoalSelector.class, rabbit.goalSelector, "availableGoals", null);
        assertNull(NativeLivingObservation.read(rabbit, 1, 1).rabbit());
        rabbit = rabbit();
        while (rabbit.goalSelector.getAvailableGoals().size() <= NativeRabbitObservation.MAX_GOALS)
            rabbit.goalSelector.addGoal(1, new FloatGoal(rabbit));
        assertNull(NativeLivingObservation.read(rabbit, 1, 1).rabbit());
        rabbit = rabbit(); field(Mob.class, rabbit, "goalSelector", new GoalSelector(() -> net.minecraft.util.profiling.InactiveProfiler.INSTANCE) { });
        assertNull(NativeLivingObservation.read(rabbit, 1, 1).rabbit());
        rabbit = rabbit(); rabbit.goalSelector.getAvailableGoals().add(new WrappedGoal(1, new FloatGoal(rabbit)) { });
        assertNull(NativeLivingObservation.read(rabbit, 1, 1).rabbit());
    }


    private static net.minecraft.world.entity.monster.Shulker shell(int raw,float animation) throws Exception {
        Field f=sun.misc.Unsafe.class.getDeclaredField("theUnsafe");f.setAccessible(true);
        var shulker=(net.minecraft.world.entity.monster.Shulker)((sun.misc.Unsafe)f.get(null))
                .allocateInstance(net.minecraft.world.entity.monster.Shulker.class);
        field(Entity.class,shulker,"type",EntityType.SHULKER);field(Entity.class,shulker,"uuid",UUID.randomUUID());
        SynchedEntityData.Builder builder=new SynchedEntityData.Builder(shulker);
        baseData(builder,"DATA_SHARED_FLAGS_ID",(byte)0);baseData(builder,"DATA_AIR_SUPPLY_ID",shulker.getMaxAirSupply());
        baseData(builder,"DATA_CUSTOM_NAME_VISIBLE",false);
        baseData(builder,"DATA_CUSTOM_NAME",java.util.Optional.<net.minecraft.network.chat.Component>empty());
        baseData(builder,"DATA_SILENT",false);baseData(builder,"DATA_NO_GRAVITY",false);
        baseData(builder,"DATA_POSE",net.minecraft.world.entity.Pose.STANDING);baseData(builder,"DATA_TICKS_FROZEN",0);
        var define=net.minecraft.world.entity.monster.Shulker.class.getDeclaredMethod("defineSynchedData",SynchedEntityData.Builder.class);
        define.setAccessible(true);define.invoke(shulker,builder);field(Entity.class,shulker,"entityData",builder.build());
        setShellRaw(shulker,raw);field(net.minecraft.world.entity.monster.Shulker.class,shulker,"currentPeekAmount",animation);
        field(net.minecraft.world.entity.monster.Shulker.class,shulker,"currentPeekAmountO",animation);
        return shulker;
    }
    @SuppressWarnings("unchecked")
    private static void setShellRaw(net.minecraft.world.entity.monster.Shulker shulker,int raw) throws Exception {
        Field field=net.minecraft.world.entity.monster.Shulker.class.getDeclaredField("DATA_PEEK_ID");field.setAccessible(true);
        shulker.getEntityData().set((net.minecraft.network.syncher.EntityDataAccessor<Byte>)field.get(null),(byte)raw);
    }
    @Test void genuineShulkerRawClosureDefeatsStaleAnimationDuringTheSameDraw() throws Exception {
        var shulker=shell(100,1);
        assertTrue(CapabilityTargetAction.shulkerShellOpen(shulker));assertEquals(100,shulker.getRawPeekAmount());
        // Network closure does not immediately finish the visual closing animation.
        setShellRaw(shulker,0);assertEquals(1,shulker.getClientPeekAmount(1.0F));
        assertFalse(CapabilityTargetAction.shulkerShellOpen(shulker));
        var row=new com.google.gson.JsonObject();row.addProperty("shell_open",CapabilityTargetAction.shulkerShellOpen(shulker));
        assertFalse(com.google.gson.JsonParser.parseString(BridgeJson.toJson(row)).getAsJsonObject().get("shell_open").getAsBoolean());
        assertFalse(CapabilityTargetAction.shulkerShellOpen(shell(100,0)));
        assertFalse(CapabilityTargetAction.shulkerShellOpen(shell(0,0)));
    }
    @Test void genuineNativeClassesKeepNewHostileThreatsSeparateFromPassiveSpecies() throws Exception {
        Field f=sun.misc.Unsafe.class.getDeclaredField("theUnsafe");f.setAccessible(true);var unsafe=(sun.misc.Unsafe)f.get(null);
        for(Class<? extends Entity> type:java.util.List.of(net.minecraft.world.entity.monster.Drowned.class,
                net.minecraft.world.entity.monster.Vex.class,net.minecraft.world.entity.monster.warden.Warden.class,
                net.minecraft.world.entity.monster.breeze.Breeze.class))
            assertTrue(CapabilityEncounterRoute.nativeDangerous((Entity)unsafe.allocateInstance(type)),type.getName());
        for(Class<? extends Entity> type:java.util.List.of(net.minecraft.world.entity.animal.Cow.class,
                net.minecraft.world.entity.animal.Chicken.class,net.minecraft.world.entity.animal.Pig.class,
                net.minecraft.world.entity.animal.Sheep.class))
            assertFalse(CapabilityEncounterRoute.nativeDangerous((Entity)unsafe.allocateInstance(type)),type.getName());
    }
    @Test void genuineUnmarkedDamagingVanillaClassesUseEncounterOnlyFallback() throws Exception {
        Field f=sun.misc.Unsafe.class.getDeclaredField("theUnsafe");f.setAccessible(true);var unsafe=(sun.misc.Unsafe)f.get(null);
        var types=java.util.Map.<String,Class<? extends Entity>>of("minecraft:goat",net.minecraft.world.entity.animal.goat.Goat.class,
                "minecraft:rabbit",net.minecraft.world.entity.animal.Rabbit.class,
                "minecraft:pufferfish",net.minecraft.world.entity.animal.Pufferfish.class);
        for(var entry:types.entrySet()) {
            Entity entity=(Entity)unsafe.allocateInstance(entry.getValue());
            assertFalse(CapabilityEncounterRoute.nativeDangerous(entity),entry.getKey());
            assertTrue(CapabilityEncounterPolicy.dangerous(entry.getKey(),CapabilityEncounterRoute.nativeDangerous(entity)),entry.getKey());
            assertFalse(CombatThreats.observableThreat(entry.getKey()),"Legacy noncombat/general observation policy is unchanged");
        }
    }
}

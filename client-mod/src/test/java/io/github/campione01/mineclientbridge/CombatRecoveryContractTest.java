package io.github.campione01.mineclientbridge;

import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/** Wiring regressions, not a substitute for client/server interruption acceptance. */
class CombatRecoveryContractTest {
    private static String source(String name) throws Exception {
        return Files.readString(Path.of(System.getProperty("mineclientBridge.projectDir"),
                "src/main/java/io/github/campione01/mineclientbridge", name + ".java"));
    }
    private static void before(String source, String earlier, String later) {
        assertTrue(source.indexOf(earlier) >= 0, earlier);
        assertTrue(source.indexOf(later) > source.indexOf(earlier), earlier + " must precede " + later);
    }

    @Test void manualAreaWeaponAndStickyTargetLossDeathStillPreemptRecovery() throws Exception {
        String combat = source("BoundedCombat");
        for (String gate : new String[]{"return Step.end(\"cancelled\", \"manual_view_changed\")",
                "return Step.end(\"failed\", \"target_missing_not_a_kill\")",
                "return Step.end(\"succeeded\", \"target_dead_observed\")",
                "return Step.end(\"failed\", \"combat_area_limit\")",
                "return Step.end(\"failed\", \"selected_weapon_changed\")"})
            before(combat, gate, "CombatRecovery.Result recovered");
        assertTrue(combat.contains("!entity.getUUID().toString().equals(request.targetUuid())"));
        assertTrue(combat.contains("!BuiltInRegistries.ENTITY_TYPE.getKey(entity.getType()).toString().equals(request.targetType())"));
        before(combat, "if (!motion.finite())", "mc.player.setYRot(expectedYaw)");
    }

    @Test void recoveryReturnsZeroWithoutAttacksButKeepsShieldPolicyAndFreshProtectedChecks() throws Exception {
        String combat = source("BoundedCombat");
        before(combat, "mc.gameRenderer.pick(1.0F)", "CombatRecovery.Result recovered");
        before(combat, "return Step.waitFor(recovered.reason())", "if (request.targetType().equals(\"minecraft:creeper\"))");
        before(combat, "return Step.waitFor(recovered.reason())", "sweepRisk(mc,target)");
        before(combat, "sweepRisk(mc,target)", "mc.startAttack()");
        before(combat, "return Step.end(\"failed\",\"protected_sweep_overlap\")", "mc.startAttack()");
        assertTrue(combat.contains("shield(mc, request.shield() && !creeper)"));
        assertTrue(combat.contains("static Step waitFor(String phase) { return new Step(0, null, phase); }"));
        assertTrue(combat.contains("static Step end(String status, String reason) { return new Step(0, status, reason); }"));
        assertTrue(combat.contains("instanceof AxeItem"));
        assertTrue(combat.contains("selecting_axe_for_protected_bystander"));
        before(combat, "recovered.state() == CombatRecovery.State.RECOVERED", "pursuit.rebaseAfterRecovery(System.nanoTime());");
        assertFalse(source("CombatRecovery").contains("System.nanoTime"));
    }

    @Test void freshDirectionalAndStationaryCorridorsKeepEveryOriginalTerrainGuard() throws Exception {
        String combat = source("BoundedCombat"), terrain = source("TerrainReader");
        // Landing proves only its occupied footprint; the same tick's movement path then
        // gets a fresh direct/detour check. This no longer forbids safe lateral detours.
        assertTrue(combat.contains("direction -> corridorClear(mc, target, 0)"));
        assertTrue(combat.contains("liveRouteEdge(mc,current,step,false)"));
        assertTrue(combat.contains("if (!corridorClear(mc, target, direction))"));
        assertTrue(combat.contains("TerrainReader.flatStepResult(mc,"));
        assertTrue(combat.contains("direction == 0 ? 0 : dx/length*.65*direction"));
        assertTrue(combat.contains("direction == 0 ? 0 : dz/length*.65*direction"));
        assertTrue(terrain.contains("if (!mc.isSameThread())"));
        assertTrue(terrain.contains("return source::readFlatCell;"));
        String typed = terrain.substring(terrain.indexOf("FlatStepCorridor.Cell readFlatCell("),
                terrain.indexOf("@Override public JsonObject readLoaded("));
        before(typed, "availability(x, y, z)", "readBlock(x, y, z)");
        assertTrue(typed.contains("availability != TerrainScan.Availability.LOADED"));
        assertFalse(typed.contains("JsonObject"));
        for (String shared : new String[]{"readProperties(block.state(), null)", "readFluid(block)", "readCollision(block)"})
            assertTrue(typed.contains(shared), shared);
        assertTrue(typed.contains("collision.known(), collision.empty(), collision.topFull()"));
        assertTrue(typed.contains("bounded(fluid.id(), 160), fluid.hazards() != 0"));
        assertTrue(terrain.contains("new CollisionFacts(false, false, false, null, reason)"));
        for (String field : new String[]{"collision_empty", "full_top_support", "fluid", "hazards"})
            assertTrue(terrain.contains("\"" + field + "\""), field);
        String helper = source("FlatStepCorridor");
        for (String guard : new String[]{"!pose.onGround()", "!Double.isFinite(dx)", "!Double.isFinite(dz)",
                "Math.hypot(dx, dz) > MAX_STEP", "Math.abs(pose.y() - Math.rint(pose.y())) > .05",
                "Availability.UNLOADED", "Availability.OUT_OF_WORLD", "!cell.collisionKnown()",
                "!\"minecraft:empty\".equals(cell.fluid())", "cell.hazardous()",
                "!cell.fullTopSupport()", "!cell.collisionEmpty()", "offset = -1; offset <= 1"})
            assertTrue(helper.contains(guard), guard);
    }

    @Test void outerDeadlineGuiDeathWorldCancelTakeoverAndReleaseRemainIndependent() throws Exception {
        String actions = source("ClientActions");
        String context = actions.substring(actions.indexOf("private static boolean context("), actions.indexOf("private static void preTick("));
        for (String gate : new String[]{"mc.player != active.player", "mc.level != active.level", "mc.gameMode == null",
                "!mc.player.isAlive()", "System.nanoTime() >= active.deadline", "mc.screen != null"})
            assertTrue(context.contains(gate), gate);
        String pre = actions.substring(actions.indexOf("private static void preTick("), actions.indexOf("private static void input("));
        before(pre, "if (!context(mc,\"pre_tick\")) return;", "a.combat.tick(mc, a.entry.ticks)");
        before(pre, "a.forward = 0", "a.combat.tick(mc, a.entry.ticks)");
        before(pre, "a.jump = false", "a.combat.tick(mc, a.entry.ticks)");
        assertTrue(actions.contains("final long deadline;"));
        assertEquals(1, actions.split("deadline =", -1).length - 1);
        assertTrue(actions.contains("if (active != null && active.entry == entry) cancel(\"cancel_requested\")"));
        assertTrue(actions.contains("cancel(\"direct_takeover\")"));
        assertTrue(actions.contains("if (active != null) finish(\"cancelled\", reason)"));
        assertTrue(actions.contains("a.combat.release(Minecraft.getInstance())"));
        assertTrue(actions.contains("input.forwardImpulse = a.forward"));
        assertTrue(actions.contains("input.up = a.forward > 0"));
        assertTrue(actions.contains("input.down = a.forward < 0"));
        assertTrue(actions.contains("input.left = input.right = false"));
        assertFalse(source("CombatRecovery").contains("deadline"));
    }
}

package io.github.campione01.mineclientbridge;

import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/** Explicitly source-string wiring checks; not executable client integration. */
class CombatPursuitContractTest {
    private static String source(String name) throws Exception {
        return Files.readString(Path.of(System.getProperty("mineclientBridge.projectDir"),
                "src/main/java/io/github/campione01/mineclientbridge", name + ".java"));
    }
    @Test void recoveryAndStickyTargetChecksPrecedePursuitAndNeverAttackWhileWaiting() throws Exception {
        String s=source("BoundedCombat");
        assertTrue(s.indexOf("target_missing_not_a_kill") < s.indexOf("pursuit.sample("));
        assertTrue(s.indexOf("return Step.waitFor(recovered.reason())") < s.indexOf("pursuit.sample("));
        assertTrue(s.indexOf("return Step.waitFor(approach.reason())") < s.indexOf("mc.startAttack()"));
        assertTrue(s.indexOf("sweepRisk(mc,target)") < s.indexOf("mc.startAttack()"));
        assertTrue(s.contains("pursuit.rebaseAfterRecovery(System.nanoTime())"));
    }
    @Test void rangedCadenceKeepsMeleeShieldAndRequiresStationaryOrMovingTerrain() throws Exception {
        String s=source("BoundedCombat");
        for(String type:new String[]{"minecraft:skeleton","minecraft:stray","minecraft:bogged"})
            assertTrue(s.contains("request.targetType().equals(\""+type+"\")"));
        assertTrue(s.contains("ranged && shieldAvailable"));
        assertTrue(s.contains("shield(mc, ranged ? approach.defend() : request.shield())"));
        assertTrue(s.contains("if (!corridorClear(mc, target, 0))"));
        assertTrue(s.contains("if (ranged && mc.player.isUsingItem()) return Step.waitFor"));
        assertTrue(s.contains("if (!corridorClear(mc, target, direction))"));
        assertEquals(1,s.split("pursuit.reached\\(\\)",-1).length-1);
        int outOfReach=s.indexOf("if (!picked) {");
        int reached=s.indexOf("pursuit.reached();");
        int sweep=s.indexOf("if (mc.player.getMainHandItem().getItem() instanceof SwordItem && sweepRisk");
        assertTrue(reached > outOfReach && reached < sweep);
        assertTrue(s.substring(outOfReach,reached).contains("return move(mc,target,1,\"approaching\");\n        }"));
        assertTrue(s.contains("return Step.waitFor(approach.reason())"));
        assertTrue(s.contains("static Step waitFor(String phase) { return new Step(0, null, phase); }"));
    }
    @Test void preciseDirectionalRejectionAndObservedPhaseMotionAreExposed() throws Exception {
        String s=source("BoundedCombat");
        for(String key:new String[]{"rejected_cell","corridor","corridor_direction","corridor_reason",
                "decision_pose","requested_forward","blocking_after_decision","using_item_after_decision",
                "motion_since_previous_decision","phase_motion_observed","total_non_closing_ms"})
            assertTrue(s.contains("\""+key+"\""),key);
        assertTrue(s.contains("delta.addProperty(\"attributed_to_previous_phase\", lastDecisionPhase)"));
        assertTrue(s.contains("lastDecisionTarget.x-lastDecisionPlayer.x"));
    }
    @Test void pursuitDoesNotOwnDeadlineInputsVelocityOrOldHistoricalMinimum() throws Exception {
        String s=source("CombatPursuit"), combat=source("BoundedCombat");
        for(String forbidden:new String[]{"System.nanoTime", "Minecraft", "setDeltaMovement", "setPos", "keyUse", "startAttack("})
            assertFalse(s.contains(forbidden),forbidden);
        assertFalse(combat.contains("closest"));
        assertFalse(combat.contains("lastProgressNanos"));
        assertFalse(s.contains("totalNonClosing = 0"));
        assertTrue(s.contains("totalNonClosing += Math.max(0, now-windowStart)"));
        String actions=source("ClientActions");
        assertTrue(actions.contains("final long deadline;"));
        assertEquals(1,actions.split("deadline =",-1).length-1);
    }
}

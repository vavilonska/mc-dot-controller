package io.github.campione01.mineclientbridge;

import java.util.List;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/** Small dynamic replays against the production owner and window helper.
 * These coordinates are synthetic observations, not Minecraft AI/physics or live acceptance. */
class BoundedEncounterActivePursuitTest {
    @Test void twoSameSidePursuersRevalidateAcrossSegmentsAndKeepOriginalDistanceBudget() {
        var f = new BoundedEncounterTest.Fixture();
        var originalOwner = f.owner;
        // A stationary reassessment after each segment is intentional. Threats keep moving.
        double[] positions = {0, -.2, -.4, -.6, -.8, -1, -1.2, -1.4,
                -1.4, -1.6, -1.8, -2, -2.2, -2.4, -2.6, -2.8,
                -2.8, -3, -3.2, -3.2};
        int movementTicks = 0, reassessments = 0, liveRevalidations = 0;
        BoundedEncounter.Decision result = null;
        for (int tick = 0; tick < positions.length; tick++) {
            int previousWindows = f.windows;
            result = f.tick(tick, positions[tick], BoundedEncounterTest.pair(4 - .06 * tick));
            assertSame(originalOwner, f.owner);
            assertNotEquals("succeeded", result.terminal());
            assertTrue(f.e().get("risk_remaining").getAsBoolean());
            assertTrue(f.e().get("offense_disabled").getAsBoolean());
            if (result.forward() > 0) {
                movementTicks++;
                assertTrue(f.windows > previousWindows, "Every new permit checks current windows");
                if (!result.planning()) liveRevalidations++;
            }
            if (result.reason().contains("encounter_reassess_")) {
                reassessments++;
                assertEquals(0, result.forward());
                assertEquals(previousWindows, f.windows, "Reassessment never plans in the same tick");
            }
            if (result.terminal() != null) break;
        }
        assertNotNull(result);
        assertEquals("failed", result.terminal());
        assertEquals("retreat_segment_budget_risk_remaining", result.reason());
        assertEquals(0, result.forward());
        assertEquals(3, f.e().get("segments_planned").getAsInt());
        assertEquals(3, reassessments);
        assertTrue(movementTicks > 3);
        assertTrue(liveRevalidations > 0);
        assertEquals(3.2, f.e().get("total_distance_observed").getAsDouble(), 1e-9);
        assertEquals(19, f.e().get("elapsed_ticks").getAsInt());
        assertEquals(950_000_000L, f.e().get("elapsed_nanos").getAsLong());
        assertTrue(f.e().get("outcome_scope").isJsonNull());
        assertTrue(f.e().get("requires_handoff").getAsBoolean());
        assertFalse(f.e().get("safety_assured").getAsBoolean());
    }

    @Test void fartherPursuerClosingRevokesEvenWhenNearestClearanceImproves() {
        var f = new BoundedEncounterTest.Fixture();
        f.tick(0, 0, List.of(BoundedEncounterTest.zombie(4, 0, 3),
                BoundedEncounterTest.zombie(5, 1, 5)));
        int previousWindows = f.windows;
        // Nearest clearance gains .1, but the farther zombie gains .3 on the player.
        var result = f.tick(1, -.2, List.of(BoundedEncounterTest.zombie(4, 0, 2.9),
                BoundedEncounterTest.zombie(5, 1, 4.5)), -.1);
        assertNull(result.terminal());
        assertEquals(0, result.forward());
        assertEquals("encounter_reassess_retreat_observed_clearance_decreased_risk_remaining", result.reason());
        assertEquals(previousWindows, f.windows);
        assertEquals(1, f.e().get("route_revocations").getAsInt());
        assertEquals(.2, f.e().get("total_distance_observed").getAsDouble(), 1e-9);
        assertFalse(f.e().get("movement_authorized").getAsBoolean());
    }

    @Test void repeatedClosingAndReplanningCannotRenewOriginalThreeSecondBudget() {
        var f = new BoundedEncounterTest.Fixture();
        var originalOwner = f.owner;
        BoundedEncounter.Decision result = null;
        for (int tick = 0; tick <= 30; tick++) {
            // Keep each sample fresh but hit the wall budget before the 60-tick cap.
            f.customNow = 1_000_000_000L + tick * 100_000_000L;
            result = f.tick(tick, 0, BoundedEncounterTest.pair(4 - .01 * tick));
            assertSame(originalOwner, f.owner);
            assertNotEquals("succeeded", result.terminal());
            if (tick < 30) assertNull(result.terminal());
        }
        assertNotNull(result);
        assertEquals("failed", result.terminal());
        assertEquals("retreat_budget_risk_remaining", result.reason());
        assertEquals(0, result.forward());
        assertEquals(15, f.e().get("segments_planned").getAsInt());
        assertEquals(15, f.e().get("route_revocations").getAsInt());
        assertEquals(0, f.e().get("total_distance_observed").getAsDouble());
        assertEquals(30, f.e().get("elapsed_ticks").getAsInt());
        assertEquals(3_000_000_000L, f.e().get("elapsed_nanos").getAsLong());
    }
}

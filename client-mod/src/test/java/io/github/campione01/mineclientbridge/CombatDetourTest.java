package io.github.campione01.mineclientbridge;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/** Executable geometry/policy fixtures, not live Minecraft physics or combat acceptance. */
class CombatDetourTest {
    private static final CombatDetour.Point START = new CombatDetour.Point(.5, .5);
    private static final CombatDetour.Point TARGET = new CombatDetour.Point(.5, 6.5);
    private static final FlatStepCorridor.Cell AIR = cell(true, false, "minecraft:air", "minecraft:empty", false);
    private static final FlatStepCorridor.Cell FLOOR = cell(false, true, "minecraft:stone", "minecraft:empty", false);
    private static final FlatStepCorridor.Cell LOG = cell(false, true, "minecraft:oak_log", "minecraft:empty", false);
    private record Block(int x, int y, int z) { }

    private static FlatStepCorridor.Cell cell(boolean empty, boolean support, String id, String fluid, boolean hazard) {
        return new FlatStepCorridor.Cell(FlatStepCorridor.Availability.LOADED, id, true, empty, support, fluid, hazard);
    }
    private static final class Fixture implements FlatStepCorridor.CellSource {
        final Map<Block, FlatStepCorridor.Cell> overrides = new HashMap<>();
        void put(int x, int y, int z, FlatStepCorridor.Cell cell) { overrides.put(new Block(x,y,z), cell); }
        @Override public FlatStepCorridor.Cell read(int x, int y, int z) {
            return overrides.getOrDefault(new Block(x,y,z), y == 63 ? FLOOR : AIR);
        }
    }
    private static CombatDetour planner() { return new CombatDetour(() -> 0); }

    private static boolean intersectsBox(CombatDetour.Point from, CombatDetour.Point to,
                                         double minX, double minZ, double maxX, double maxZ) {
        double low=0, high=1;
        double[] origins={from.x(),from.z()}, deltas={to.x()-from.x(),to.z()-from.z()};
        double[] mins={minX,minZ}, maxs={maxX,maxZ};
        for(int axis=0;axis<2;axis++) {
            if(deltas[axis]==0) { if(origins[axis]<mins[axis] || origins[axis]>maxs[axis]) return false; }
            else {
                double a=(mins[axis]-origins[axis])/deltas[axis], b=(maxs[axis]-origins[axis])/deltas[axis];
                low=Math.max(low,Math.min(a,b)); high=Math.min(high,Math.max(a,b));
                if(low>high) return false;
            }
        }
        return true;
    }

    /** Test adapter uses the production pure square-sweep admission for every segment. */
    private static CombatDetour.EdgeCheck edges(FlatStepCorridor.CellSource source) {
        return (from, to) -> {
            int segments = Math.max(1, (int)Math.ceil(from.distance(to)/.65));
            for (int i=0; i<segments; i++) {
                double x0 = from.x()+(to.x()-from.x())*i/segments;
                double z0 = from.z()+(to.z()-from.z())*i/segments;
                double x1 = from.x()+(to.x()-from.x())*(i+1)/segments;
                double z1 = from.z()+(to.z()-from.z())*(i+1)/segments;
                var result = FlatStepCorridor.check(new FlatStepCorridor.Pose(x0,64,z0,true,0), x1-x0,z1-z0,source);
                if (!result.clear()) return new CombatDetour.EdgeResult(false,0,result.reason());
            }
            return new CombatDetour.EdgeResult(true,0,"clear");
        };
    }

    private static void assertSafePlan(CombatDetour.Result result, CombatDetour.Point start,
                                       CombatDetour.Point target, CombatDetour.EdgeCheck edges) {
        assertNotNull(result.plan(), result.toString());
        assertEquals("detour_found", result.reason());
        var route = result.plan();
        assertTrue(route.waypoints().size() <= CombatDetour.MAX_INTERMEDIATE_WAYPOINTS+1);
        CombatDetour.Point from = start;
        double length = 0;
        for (var to : route.waypoints()) {
            assertTrue(start.distance(to) <= CombatDetour.MAX_RADIUS+1e-8);
            assertTrue(from.distance(to) <= CombatDetour.MAX_EDGE+1e-8);
            assertTrue(edges.check(from,to).clear(), from+" -> "+to);
            length += from.distance(to);
            from = to;
        }
        assertEquals(route.length(),length,1e-8);
        assertTrue(from.distance(target) < start.distance(target)-.39);
        assertTrue(result.candidateChecks() <= CombatDetour.MAX_ROUTE_CANDIDATES);
        assertTrue(result.edgeChecks() <= CombatDetour.MAX_EDGE_CHECKS);
    }

    @Test void treeRequiresSafeLateralExitBeforeTowardTargetProgress() {
        Fixture world = new Fixture(); world.put(0,64,1,LOG); world.put(0,65,1,LOG);
        var check = edges(world);
        assertFalse(check.check(START,new CombatDetour.Point(.5,3.25)).clear());
        var result = planner().plan(START,TARGET,check);
        assertSafePlan(result,START,TARGET,check);
        assertTrue(result.plan().waypoints().size() >= 2);
    }

    @Test void oneBlockPitDetoursUsingFullContinuousSupport() {
        Fixture world = new Fixture(); world.put(0,63,1,AIR);
        var check = edges(world);
        var result = planner().plan(START,TARGET,check);
        assertSafePlan(result,START,TARGET,check);
        assertTrue(result.plan().length() > CombatDetour.MAX_GOAL_DISTANCE);
    }

    @Test void retainedNonAtomicTreeGeometryFindsTheNarrowBlockCenterPassage() {
        // A later target pose and earlier player pose are a geometry fixture, not an
        // atomic live frame or a claim to replay the exact live client encounter.
        var start = new CombatDetour.Point(17.9743191721,28.2788554407);
        var target = new CombatDetour.Point(18.63265,31.02466);
        Fixture world = new Fixture(); world.put(17,64,29,LOG); world.put(17,65,29,LOG);
        var ground = edges(world);
        CombatDetour.EdgeCheck check = (from,to) -> {
            // Unit test standing-target AABB plus the full .31 player half-width.
            // The actual adapter owns exact live entity dimensions and threat margins.
            if(intersectsBox(from,to,target.x()-.61,target.z()-.61,target.x()+.61,target.z()+.61))
                return new CombatDetour.EdgeResult(false,0,"target_body_collision");
            return ground.check(from,to);
        };
        assertFalse(check.check(start,target).clear());
        var center1 = new CombatDetour.Point(18.5,28.5);
        var center2 = new CombatDetour.Point(18.5,29.5);
        assertTrue(check.check(start,center1).clear());
        assertTrue(check.check(center1,center2).clear());
        var result=planner().plan(start,target,check);
        assertSafePlan(result,start,target,check);
        assertTrue(result.plan().waypoints().getLast().distance(target)>=CombatDetour.MIN_TARGET_SEPARATION-1e-8);
    }

    @Test void anIntermediateMayMoveFartherFromTheTarget() {
        Fixture world = new Fixture(); world.put(0,63,1,AIR);
        var ground = edges(world);
        // Force a lateral first leg. End-to-end progress is required; local distance
        // monotonicity would incorrectly reject every admitted first waypoint.
        CombatDetour.EdgeCheck check = (from,to) -> {
            if (from.equals(START) && Math.abs(to.z()-START.z()) > 1e-8)
                return new CombatDetour.EdgeResult(false,0,"lateral_first_fixture");
            return ground.check(from,to);
        };
        var result = planner().plan(START,TARGET,check);
        assertSafePlan(result,START,TARGET,check);
        assertTrue(result.plan().waypoints().getFirst().distance(TARGET) > START.distance(TARGET));
    }

    @Test void unsupportedBarrierHasNoRouteAndNeverReturnsSafePrefix() {
        Fixture world = new Fixture();
        for(int x=-5;x<=5;x++) world.put(x,63,1,AIR);
        var result = planner().plan(START,TARGET,edges(world));
        assertNull(result.plan());
        assertTrue(List.of("detour_no_safe_route","detour_candidate_budget","detour_edge_budget").contains(result.reason()));
    }

    @Test void alternativeLocalGoalCanAvoidAnUnsafeOriginalBearingGoal() {
        Fixture world = new Fixture(); world.put(0,63,3,AIR);
        var check=edges(world);
        var result = planner().plan(START,TARGET,check);
        assertSafePlan(result,START,TARGET,check);
        assertNotEquals(new CombatDetour.Point(.5,3.25),result.plan().waypoints().getLast());
    }

    @Test void noCompletedProgressGoalCannotReturnSafeNonprogressPrefix() {
        CombatDetour.EdgeCheck check=(from,to) -> new CombatDetour.EdgeResult(
                START.distance(TARGET)-to.distance(TARGET)<.4-1e-8,0,"no_completed_goal");
        assertNull(planner().plan(START,TARGET,check).plan());
    }

    @Test void waterLavaHazardAndIncompleteSupportNeverBecomeDetours() {
        List<FlatStepCorridor.Cell> bad = new ArrayList<>();
        bad.add(cell(false,true,"minecraft:stone","minecraft:water",false));
        bad.add(cell(false,true,"minecraft:stone","minecraft:lava",false));
        bad.add(cell(false,true,"minecraft:magma_block","minecraft:empty",true));
        for (var availability : List.of(FlatStepCorridor.Availability.UNLOADED,
                FlatStepCorridor.Availability.UNKNOWN, FlatStepCorridor.Availability.OUT_OF_WORLD))
            bad.add(new FlatStepCorridor.Cell(availability,"minecraft:stone",true,false,true,"minecraft:empty",false));
        bad.add(new FlatStepCorridor.Cell(FlatStepCorridor.Availability.LOADED,"minecraft:stone",false,false,true,"minecraft:empty",false));
        bad.add(AIR);
        for (var invalid : bad) {
            Fixture world = new Fixture();
            for(int x=-5;x<=5;x++) world.put(x,63,1,invalid);
            assertNull(planner().plan(START,TARGET,edges(world)).plan(),invalid.toString());
        }
    }

    @Test void diagonalCornerCollisionIsAvoidedRatherThanClipped() {
        var target = new CombatDetour.Point(4.5,4.5);
        Fixture world = new Fixture(); world.put(1,64,0,LOG);
        var check = edges(world);
        assertFalse(check.check(START,new CombatDetour.Point(.96,.96)).clear());
        assertSafePlan(planner().plan(START,target,check),START,target,check);
    }

    @Test void reflectedTreeAndPitFixturesRemainSafe() {
        for(int sx : new int[]{-1,1}) for(int sz : new int[]{-1,1}) {
            var start = new CombatDetour.Point(sx*.5,sz*.5);
            var target = new CombatDetour.Point(sx*.5,sz*6.5);
            Fixture world = new Fixture();
            world.put(sx==1 ? 0 : -1,63,sz==1 ? 1 : -2,AIR);
            var check = edges(world);
            assertSafePlan(planner().plan(start,target,check),start,target,check);
        }
    }

    @Test void strongerMinimumClearanceWinsAmongAdmittedRoutes() {
        Fixture world = new Fixture(); world.put(0,63,1,AIR);
        var ground = edges(world);
        CombatDetour.EdgeCheck check = (from,to) -> {
            var result = ground.check(from,to);
            return new CombatDetour.EdgeResult(result.clear(),
                    Math.min(from.x(),to.x()) < .5-1e-8 ? .1 : 3,result.reason());
        };
        var result = planner().plan(START,TARGET,check);
        assertSafePlan(result,START,TARGET,check);
        assertEquals(3,result.plan().clearance());
        assertTrue(result.plan().waypoints().getFirst().x() > .5);
    }

    @Test void completeThreatRejectionCannotBeOverruledByTerrainSafety() {
        AtomicInteger calls = new AtomicInteger();
        var result = planner().plan(START,TARGET,(a,b) -> {
            calls.incrementAndGet(); return new CombatDetour.EdgeResult(false,0,"threat_neighborhood_incomplete");
        });
        assertNull(result.plan());
        assertTrue(calls.get()>0);
    }

    @Test void attemptsAreLifetimeBoundedAcrossClearAndRecovery() {
        var planner = planner(); var clear = edges(new Fixture());
        for(int i=1;i<=CombatDetour.MAX_ATTEMPTS;i++) {
            assertNotNull(planner.plan(START,TARGET,clear).plan());
            assertEquals(i,planner.attempts());
            planner.clear(); planner.rebaseAfterRecovery(); planner.clear();
            assertNull(planner.activePlan()); assertEquals(i,planner.attempts());
        }
        var refused = planner.plan(START,TARGET,(a,b) -> fail("budget-exhausted callback"));
        assertEquals("detour_attempt_budget",refused.reason());
        assertNull(refused.plan()); assertEquals(3,planner.attempts());
    }

    @Test void rejectedAndInvalidPlansAlsoConsumeTheSameBudget() {
        var planner = planner();
        assertNull(planner.plan(START,TARGET,(a,b) -> null).plan());
        assertNull(planner.plan(null,TARGET,edges(new Fixture())).plan());
        assertNull(planner.plan(START,START,edges(new Fixture())).plan());
        assertEquals("detour_attempt_budget",planner.plan(START,TARGET,edges(new Fixture())).reason());
    }

    @Test void fixedCandidateAndDirectedEdgeLimitsHoldAndEdgesAreMemoized() {
        Map<String,Integer> calls = new HashMap<>();
        var result = planner().plan(START,TARGET,(from,to) -> {
            String key=from+" -> "+to; calls.merge(key,1,Integer::sum);
            assertTrue(from.distance(to) <= 2+1e-8);
            assertTrue(START.distance(from) <= 3+1e-8 && START.distance(to) <= 3+1e-8);
            return new CombatDetour.EdgeResult(true,0,"clear");
        });
        assertNotNull(result.plan());
        assertTrue(result.edgeChecks() <= CombatDetour.MAX_EDGE_CHECKS);
        assertTrue(result.candidateChecks() <= CombatDetour.MAX_ROUTE_CANDIDATES);
        assertEquals(calls.size(),result.edgeChecks());
        assertTrue(calls.values().stream().allMatch(n -> n==1));
    }

    @Test void timeCapCheckedAfterSlowCallbackBeforePlanAdmission() {
        AtomicLong now = new AtomicLong();
        AtomicInteger calls = new AtomicInteger();
        var planner = new CombatDetour(now::get);
        var result = planner.plan(START,TARGET,(a,b) -> {
            calls.incrementAndGet(); now.addAndGet(CombatDetour.MAX_PLAN_NANOS);
            return new CombatDetour.EdgeResult(true,3,"clear");
        });
        assertNull(result.plan()); assertEquals("detour_time_budget",result.reason());
        assertEquals(1,calls.get()); assertNull(planner.activePlan());
    }

    @Test void alreadyExpiredPlanNeverReadsWorld() {
        AtomicLong now = new AtomicLong();
        var planner = new CombatDetour(() -> now.getAndAdd(CombatDetour.MAX_PLAN_NANOS));
        var result = planner.plan(START,TARGET,(a,b) -> fail("expired callback"));
        assertEquals("detour_time_budget",result.reason()); assertNull(result.plan());
    }

    @Test void expiryBetweenCallbacksRetainsAnEarlierFullyCheckedRoute() {
        AtomicInteger checks=new AtomicInteger(), readsAfterTwo=new AtomicInteger();
        var planner=new CombatDetour(() -> checks.get()>=2 && readsAfterTwo.incrementAndGet()>=2
                ? CombatDetour.MAX_PLAN_NANOS : 0);
        var result=planner.plan(START,TARGET,(a,b) -> {
            checks.incrementAndGet(); return new CombatDetour.EdgeResult(true,0,"clear");
        });
        assertNotNull(result.plan());
        assertEquals(2,result.edgeChecks());
    }

    @Test void reversedMonotonicClockFailsClosedEvenAfterSafeEdges() {
        AtomicLong now = new AtomicLong(100);
        var planner = new CombatDetour(now::get);
        var result = planner.plan(START,TARGET,(a,b) -> {
            now.set(99); return new CombatDetour.EdgeResult(true,1,"clear");
        });
        assertNull(result.plan()); assertEquals("invalid_detour_clock",result.reason());
    }

    @Test void nullExceptionalAndNonfiniteEdgeEvidenceFailClosed() {
        for (CombatDetour.EdgeCheck check : List.<CombatDetour.EdgeCheck>of(
                (a,b) -> null, (a,b) -> {throw new IllegalStateException("fixture");},
                (a,b) -> new CombatDetour.EdgeResult(true,Double.NaN,"clear"),
                (a,b) -> new CombatDetour.EdgeResult(true,Double.POSITIVE_INFINITY,"clear"),
                (a,b) -> new CombatDetour.EdgeResult(true,-1,"clear")))
            assertNull(planner().plan(START,TARGET,check).plan());
    }

    @Test void invalidCoordinatesNeverReachTheWorldCallback() {
        for(double value : new double[]{Double.NaN,Double.POSITIVE_INFINITY,30_000_001}) {
            var result = planner().plan(new CombatDetour.Point(value,0),TARGET,(a,b) -> fail("invalid coordinate"));
            assertEquals("invalid_detour_request",result.reason()); assertNull(result.plan());
        }
    }

    @Test void producedPlanIsImmutableAndDoesNotOutliveClear() {
        var planner = planner(); var result=planner.plan(START,TARGET,edges(new Fixture()));
        assertSame(result.plan(),planner.activePlan());
        assertThrows(UnsupportedOperationException.class,() -> result.plan().waypoints().clear());
        planner.clear(); assertNull(planner.activePlan()); assertEquals(1,planner.attempts());
    }
}

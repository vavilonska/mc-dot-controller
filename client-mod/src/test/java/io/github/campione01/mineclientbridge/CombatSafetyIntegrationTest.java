package io.github.campione01.mineclientbridge;

import java.util.List;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/** Executable helper composition, not a simulated or actual Minecraft client integration. */
class CombatSafetyIntegrationTest {
    static final FlatStepCorridor.Cell SOLID=new FlatStepCorridor.Cell(FlatStepCorridor.Availability.LOADED,
            "minecraft:stone",true,false,true,"minecraft:empty",false);
    static final FlatStepCorridor.Cell AIR=new FlatStepCorridor.Cell(FlatStepCorridor.Availability.LOADED,
            "minecraft:air",true,true,false,"minecraft:empty",false);
    static CombatThreats.Observed mob(int id,String type,double x,double z) {
        return new CombatThreats.Observed(id,"uuid-"+id,type,x,64,z,.3,true,true);
    }
    static CombatThreats.Snapshot snapshot(List<CombatThreats.Observed> mobs,int tick) {
        return new CombatThreats.Snapshot(mobs,tick*50_000_000L,tick,false,true);
    }
    static CombatDetour.EdgeCheck composed(CombatThreats.Snapshot s,FlatStepCorridor.CellSource source,
                                           List<CombatSpatial.Box> boxes) {
        return (a,b)-> {
            var threats=CombatThreats.route(s,s.capturedNanos(),s.capturedTick(),a.x(),a.z(),b.x(),b.z(),1,"uuid-1");
            if(!threats.safe()) return new CombatDetour.EdgeResult(false,0,threats.reason());
            var body=CombatSpatial.check(a.x(),64,a.z(),b.x()-a.x(),b.z()-a.z(),boxes);
            if(!body.clear()) return new CombatDetour.EdgeResult(false,0,body.reason());
            int n=Math.max(1,(int)Math.ceil(a.distance(b)/.65));
            for(int i=0;i<n;i++) {
                var pose=new FlatStepCorridor.Pose(a.x()+(b.x()-a.x())*i/n,64,a.z()+(b.z()-a.z())*i/n,true,0);
                var terrain=CombatRouteEnvelope.check(pose,(b.x()-a.x())/n,(b.z()-a.z())/n,source,boxes);
                if(!terrain.clear()) return new CombatDetour.EdgeResult(false,0,terrain.reason());
            }
            return new CombatDetour.EdgeResult(true,Math.min(100,threats.minimumClearance()),"clear");
        };
    }
    @Test void treeDetourRequiresBothContinuousTerrainAndDynamicTargetClearance() {
        var start=new CombatDetour.Point(.9743191721,.2788554407);
        var target=new CombatDetour.Point(1.63265,3.02466);
        var s=snapshot(List.of(mob(1,"minecraft:skeleton",target.x(),target.z())),0);
        FlatStepCorridor.CellSource cells=(x,y,z)->y==63 || x==0 && z==1 ? SOLID:AIR;
        var bodies=List.of(new CombatSpatial.Box(1,1.33265,64,2.72466,1.93265,65.8,3.32466));
        var edge=composed(s,cells,bodies);
        assertFalse(edge.check(start,new CombatDetour.Point(1.25764,.86386)).clear());
        var plan=new CombatDetour(()->0).plan(start,target,edge);
        assertNotNull(plan.plan(),plan.reason());
        var previous=start;
        for(var waypoint:plan.plan().waypoints()) {
            assertTrue(edge.check(previous,waypoint).clear());previous=waypoint;
        }
    }
    @Test void newCreeperPreemptsOtherwiseClearDetourAndSweep() {
        var s=snapshot(List.of(mob(1,"minecraft:zombie",0,3),mob(2,"minecraft:creeper",1,3)),1);
        var health=new CombatThreats.HealthGuard().sample(1,50_000_000,20);
        assertTrue(CombatThreats.evaluate(s,50_000_000,1,0,64,0,1,"uuid-1",health).stop());
        assertTrue(CombatThreats.sweep(s,50_000_000,1,1,"uuid-1").stop());
        var plan=new CombatDetour(()->0).plan(new CombatDetour.Point(0,0),new CombatDetour.Point(0,3),
                composed(s,(x,y,z)->y==63?SOLID:AIR,List.of()));
        assertNull(plan.plan());
    }
    @Test void dynamicEntityArrivalInvalidatesPreviouslyAdmittedEdge() {
        var s=snapshot(List.of(mob(1,"minecraft:zombie",0,5)),1);
        var source=(FlatStepCorridor.CellSource)(x,y,z)->y==63?SOLID:AIR;
        var a=new CombatDetour.Point(0,0);var b=new CombatDetour.Point(0,.65);
        assertTrue(composed(s,source,List.of()).check(a,b).clear());
        assertFalse(composed(s,source,List.of(new CombatSpatial.Box(2,-.3,64,.4,.3,65.8,1))).check(a,b).clear());
    }
    @Test void recoveryCannotRefundPlannerOrPursuitBudget() {
        var planner=new CombatDetour(()->0);var pursuit=new CombatPursuit();
        for(int i=0;i<3;i++) {
            planner.plan(new CombatDetour.Point(0,0),new CombatDetour.Point(0,5),(a,b)->new CombatDetour.EdgeResult(true,1,"clear"));
            pursuit.sample(i*40,i*2_000_000_000L,new CombatPursuit.Sample(0,0,0,5),false);
            pursuit.rebaseAfterRecovery((i+1)*2_000_000_000L);planner.rebaseAfterRecovery();
        }
        assertEquals(3,planner.attempts());
        assertNull(planner.plan(new CombatDetour.Point(0,0),new CombatDetour.Point(0,5),(a,b)->new CombatDetour.EdgeResult(true,1,"clear")).plan());
        assertTrue(pursuit.sample(120,6_000_000_000L,new CombatPursuit.Sample(0,0,0,5),false).failed());
    }
    @Test void laterEndermanPreemptsAlreadyLatchedHealthRetreat() {
        var health=new CombatThreats.HealthGuard();
        assertTrue(health.sample(0,0,14).interrupted());
        var s=snapshot(List.of(mob(1,"minecraft:zombie",0,3),mob(2,"minecraft:enderman",0,15)),1);
        var gate=CombatThreats.evaluate(s,50_000_000L,1,0,64,0,1,"uuid-1",health.sample(1,50_000_000L,14));
        assertEquals("low_health",gate.reason());
        var route=CombatThreats.escapeRoute(s,50_000_000L,1,0,0,0,-1.5);
        assertFalse(route.safe());assertEquals("enderman_gaze_unplanned",route.reason());
    }
    @Test void escapeGeometryImprovementNeverMeansSafeOutcome() {
        var s=snapshot(List.of(mob(1,"minecraft:creeper",0,3)),0);
        var edge=CombatThreats.escapeRoute(s,0,0,0,0,0,-1.5);
        assertTrue(edge.safe());
        var gate=CombatThreats.evaluate(s,0,0,0,64,0,1,"uuid-1",new CombatThreats.HealthGuard().sample(0,0,20));
        assertTrue(gate.stop());assertTrue(gate.riskRemaining());
    }
}

package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicLong;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/** Production state machine, synthetic observations only. No game, new input path, or runtime enablement. */
class ThreeZombieEncounterTest {
    static final String THIRD="00000000-0000-4000-8000-000000000006";
    static JsonObject request() {
        var b=BoundedEncounterTest.request();b.addProperty("encounter_mode",EncounterRequest.THREE_MODE);
        var third=new JsonObject();third.addProperty("entity_id",6);third.addProperty("uuid",THIRD);third.addProperty("type","minecraft:zombie");
        b.getAsJsonArray("encounter_scope").add(third);return b;
    }
    static List<CombatThreats.Observed> triple(double z) {
        var result=new ArrayList<>(BoundedEncounterTest.pair(z));
        result.add(new CombatThreats.Observed(6,THIRD,"minecraft:zombie",-1,64,z,.3,true,true));return result;
    }
    static class Fixture {
        AtomicLong clock=new AtomicLong(1_000_000_000L);JsonObject root=new JsonObject();
        CombatThreats.HealthGuard health=new CombatThreats.HealthGuard();
        BoundedEncounter owner;int windows,projectiles=0;long age;boolean known=true,truncated,blocked;double hp=20;
        Fixture() { owner=new BoundedEncounter(EncounterRequest.parseOptional(request()),root,0,64,0,30_000_000_000L,clock::get,health); }
        BoundedEncounter.Decision tick(int tick,double z,List<CombatThreats.Observed> mobs) {
            long now=1_000_000_000L+tick*50_000_000L;clock.set(now);
            var s=new CombatThreats.Snapshot(mobs,now-age,tick,truncated,known,projectiles);
            var pose=new CombatRecovery.Motion(0,64,z,0,0,0,true);
            return owner.tick(tick,s,pose,health.sample(tick,now,hp),(a,b)->{
                windows++;
                if(blocked)return new CombatDetour.EdgeResult(false,0,"fixture_wall");
                FlatStepCorridor.CellSource cells=(x,y,zz)->y==63?CombatSafetyIntegrationTest.SOLID:CombatSafetyIntegrationTest.AIR;
                return CombatRetreatWindow.check(s,clock.get(),tick,new FlatStepCorridor.Pose(a.x(),64,a.z(),true,0),b,0,64,0,cells,List.of()).edge();
            },()->null,(data,d)->CombatRetreatEvidence.append(data,d,null,null,null));
        }
        JsonObject e() {return root.getAsJsonObject("encounter");}
    }
    @Test void distinctModeRequiresExactlyThreeOrdinaryZombies() {
        assertEquals(3,BoundedCombatRequest.parse(request()).encounter().scope().size());
        var old=BoundedEncounterTest.request();old.getAsJsonArray("encounter_scope").add(request().getAsJsonArray("encounter_scope").get(2));
        assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(old));
        var few=BoundedEncounterTest.request();few.addProperty("encounter_mode",EncounterRequest.THREE_MODE);
        assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(few));
        for(String type:List.of("minecraft:skeleton","minecraft:husk","minecraft:spider","minecraft:creeper")) {
            var b=request();b.getAsJsonArray("encounter_scope").get(2).getAsJsonObject().addProperty("type",type);
            assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(b));
        }
    }
    @Test void thirdIdentityCannotReuseEitherIdOrUuidOrOmitTarget() {
        for(String field:List.of("entity_id","uuid"))for(int other:new int[]{0,1}) {
            var b=request();var scope=b.getAsJsonArray("encounter_scope");scope.get(2).getAsJsonObject().add(field,scope.get(other).getAsJsonObject().get(field));
            assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(b));
        }
        var b=request();b.addProperty("target_uuid","00000000-0000-4000-8000-000000000099");
        assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(b));
    }
    @Test void newGateIsIndependentDefaultClosedAndCannotBroadenOldGate() {
        String old=System.getProperty(EncounterRequest.ENABLE_PROPERTY),next=System.getProperty(EncounterRequest.THREE_ENABLE_PROPERTY);
        try {
            System.clearProperty(EncounterRequest.ENABLE_PROPERTY);System.clearProperty(EncounterRequest.THREE_ENABLE_PROPERTY);
            assertFalse(EncounterRequest.runtimeEnabled(EncounterRequest.THREE_MODE));assertFalse(EncounterRequest.runtimeEnabled());
            System.setProperty(EncounterRequest.ENABLE_PROPERTY,"true");assertTrue(EncounterRequest.runtimeEnabled());assertFalse(EncounterRequest.runtimeEnabled(EncounterRequest.THREE_MODE));
            System.clearProperty(EncounterRequest.ENABLE_PROPERTY);System.setProperty(EncounterRequest.THREE_ENABLE_PROPERTY,"true");
            assertFalse(EncounterRequest.runtimeEnabled());assertTrue(EncounterRequest.runtimeEnabled(EncounterRequest.THREE_MODE));assertFalse(EncounterRequest.runtimeEnabled("anything"));
        } finally {
            if(old==null)System.clearProperty(EncounterRequest.ENABLE_PROPERTY);else System.setProperty(EncounterRequest.ENABLE_PROPERTY,old);
            if(next==null)System.clearProperty(EncounterRequest.THREE_ENABLE_PROPERTY);else System.setProperty(EncounterRequest.THREE_ENABLE_PROPERTY,next);
        }
    }
    @Test void noApproachShieldOrHiddenInputExpansion() {
        for(String field:List.of("approach","shield","jump","sneak","sprint","hotbar_slot")) {
            var b=request();b.addProperty(field,true);assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(b));
        }
    }
    @Test void observedProjectilesAndUnknownCountsRefuseBeforePlanning() {
        for(int count:new int[]{-1,-2,1,128,129}) {
            var f=new Fixture();f.projectiles=count;var d=f.tick(0,0,triple(3));
            assertEquals("failed",d.terminal());assertEquals(0,d.forward());assertEquals(0,f.windows);
            assertEquals(count>=1&&count<=128?"encounter_projectile_observed_risk_remaining":"encounter_projectile_observation_unknown_risk_remaining",d.reason());
        }
        assertEquals(-1,new CombatThreats.Snapshot(triple(3),1,0,false,true).projectileCount());
    }
    @Test void incompleteUnknownOrStaleSnapshotCannotProveZeroProjectiles() {
        for(int kind=0;kind<3;kind++) {
            var f=new Fixture();if(kind==0)f.truncated=true;if(kind==1)f.known=false;if(kind==2)f.age=150_000_001L;
            var d=f.tick(0,0,triple(3));assertEquals("failed",d.terminal());assertEquals(0,d.forward());assertEquals(0,f.windows);
            assertTrue(d.reason().startsWith("threat_snapshot_"));
        }
    }
    @Test void threeLivingClearanceSamplesRequireKnownZeroProjectiles() {
        var f=new Fixture();assertNull(f.tick(0,0,triple(10)).terminal());assertNull(f.tick(1,0,triple(10)).terminal());
        var d=f.tick(2,0,triple(10));assertEquals("succeeded",d.terminal());assertEquals(0,f.windows);
        assertEquals("three_scoped_living_zombies_beyond_8_for_3_samples",f.e().get("outcome_scope").getAsString());
        assertEquals(3,f.e().getAsJsonArray("scoped_living_threats").size());assertTrue(f.e().get("risk_remaining").getAsBoolean());
        assertFalse(f.e().get("safety_assured").getAsBoolean());assertTrue(f.e().get("offense_disabled").getAsBoolean());
        assertEquals(0,f.e().getAsJsonObject("projectile_observation").get("count").getAsInt());
    }
    @Test void thirdMissingOrDeadCannotEstablishInitialScopeOrCompletion() {
        var f=new Fixture();assertEquals("encounter_initial_scope_unobserved_risk_remaining",f.tick(0,0,BoundedEncounterTest.pair(10)).reason());
        var g=new Fixture();g.tick(0,0,triple(10));var remaining=new ArrayList<>(triple(10));
        var third=remaining.get(2);remaining.set(2,new CombatThreats.Observed(third.entityId(),third.uuid(),third.type(),third.x(),third.y(),third.z(),third.radius(),true,false));
        var d=g.tick(1,0,remaining);assertEquals(0,d.forward());assertNotEquals("succeeded",d.terminal());
        assertEquals(0,g.e().get("clearance_observations").getAsInt());assertTrue(g.e().get("outcome_scope").isJsonNull());
    }
    @Test void fourthZombieAndUnsupportedLivingThreatRemainOutOfScope() {
        for(String type:List.of("minecraft:zombie","minecraft:skeleton","minecraft:creeper","minecraft:enderman")) {
            var f=new Fixture();var mobs=new ArrayList<>(triple(3));mobs.add(new CombatThreats.Observed(7,"other",type,2,64,3,.3,true,true));
            var d=f.tick(0,0,mobs);assertEquals("failed",d.terminal());assertEquals(0,d.forward());assertEquals(0,f.windows);
        }
    }
    @Test void sameDirectionThreeThreatRetreatUsesOriginalWindowAndNoAttackPath() {
        var f=new Fixture();var d=f.tick(0,0,triple(3));assertNull(d.terminal());assertTrue(d.forward()>0);assertTrue(f.windows>0);
        assertEquals(4,f.e().get("max_total_distance").getAsDouble());assertEquals(60,f.e().get("max_total_ticks").getAsInt());
        assertEquals(3_000_000_000L,f.e().get("max_total_nanos").getAsLong());assertTrue(f.e().get("offense_disabled").getAsBoolean());
    }
    @Test void projectileAppearingAfterMovementRevokesAllMovementImmediatelyAtNextTick() {
        var f=new Fixture();assertTrue(f.tick(0,0,triple(3)).forward()>0);f.projectiles=1;var d=f.tick(1,-.1,triple(3));
        assertEquals("encounter_projectile_observed_risk_remaining",d.reason());assertEquals(0,d.forward());assertNull(d.goal());
        assertFalse(f.e().get("movement_authorized").getAsBoolean());assertFalse(f.e().has("goal"));
    }
    @Test void originalDistanceClockAndHealthBoundsAreNotRefundedForThirdTarget() {
        var f=new Fixture();f.tick(0,0,triple(3));assertEquals("retreat_budget_risk_remaining",f.tick(1,-4,triple(3)).reason());
        var g=new Fixture();g.tick(0,0,triple(3));assertEquals("retreat_budget_risk_remaining",g.tick(60,0,triple(3)).reason());
        var h=new Fixture();h.tick(0,0,triple(3));assertEquals("encounter_callback_observation_gap_risk_remaining",h.owner.callbackInterruption(1_150_000_001L));
        var k=new Fixture();k.hp=14;k.tick(0,0,triple(10));k.hp=20;assertNotEquals("succeeded",k.tick(1,0,triple(10)).terminal());
        assertTrue(k.e().get("health_interruption_latched").getAsBoolean());
    }
    @Test void blockedRetreatIsFailureNotSafetyOrFinishedAction() {
        var f=new Fixture();f.blocked=true;var d=f.tick(0,0,triple(3));assertEquals("failed",d.terminal());assertEquals(0,d.forward());
        assertTrue(f.e().get("outcome_scope").isJsonNull());assertTrue(f.e().get("requires_handoff").getAsBoolean());
    }
    static EncounterPauseTest.Fake pauseFixture() {
        var f=new EncounterPauseTest.Fake();var e=f.expected.getAsJsonObject("result").getAsJsonObject("combat").getAsJsonObject("encounter");
        e.addProperty("encounter_mode",EncounterRequest.THREE_MODE);e.add("encounter_scope",request().get("encounter_scope"));return f;
    }
    @Test void threeScopeTerminalPauseRetainsSameContextChecks() {
        var f=pauseFixture();assertTrue(f.run().get("input_release_confirmed").getAsBoolean());assertEquals(1,f.opens);assertEquals(1,f.cancels);
        for(int kind=0;kind<4;kind++) {
            var g=pauseFixture();if(kind==0)g.world=EncounterPauseTest.SESSION;if(kind==1)g.player=EncounterPauseTest.WORLD;if(kind==2)g.session=EncounterPauseTest.WORLD;
            if(kind==3)g.expected.getAsJsonObject("result").getAsJsonObject("combat").getAsJsonObject("encounter").getAsJsonArray("encounter_scope").remove(2);
            assertThrows(ClientActionRequest.Rejected.class,g::run);assertEquals(0,g.opens);assertEquals(0,g.cancels);
        }
    }
    @Test void newModeUnknownTerminalPauseIsNeverRetried() {
        var f=pauseFixture();f.expected.addProperty("status","failed");var hook=new JsonObject();hook.addProperty("attempted",true);hook.addProperty("outcome","unconfirmed");
        f.expected.getAsJsonObject("result").add(EncounterTerminalPause.EVIDENCE,hook);
        assertThrows(ClientActionRequest.Rejected.class,f::run);assertEquals(0,f.opens);
    }
}

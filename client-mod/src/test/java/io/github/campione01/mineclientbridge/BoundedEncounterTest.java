package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.util.List;
import java.util.concurrent.atomic.AtomicLong;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/** Runs the exact native owner state machine and real production retreat-window composition.
 * Synthetic observations, not a Minecraft physics simulator or live game acceptance. */
class BoundedEncounterTest {
    static final String ONE="00000000-0000-4000-8000-000000000004", TWO="00000000-0000-4000-8000-000000000005";
    static JsonObject request() {
        var b=BoundedCombatTest.body();b.addProperty("approach",false);b.addProperty("shield",false);
        b.addProperty("encounter_mode",EncounterRequest.MODE);
        var scope=new com.google.gson.JsonArray();
        for(int id:new int[]{4,5}) { var e=new JsonObject();e.addProperty("entity_id",id);e.addProperty("uuid",id==4?ONE:TWO);e.addProperty("type","minecraft:zombie");scope.add(e); }
        b.add("encounter_scope",scope);return b;
    }
    static CombatThreats.Observed zombie(int id,double x,double z) {
        return new CombatThreats.Observed(id,id==4?ONE:TWO,"minecraft:zombie",x,64,z,.3,true,true);
    }
    static List<CombatThreats.Observed> pair(double z) { return List.of(zombie(4,0,z),zombie(5,1,z)); }
    static class Fixture {
        AtomicLong clock=new AtomicLong(1_000_000_000L);
        JsonObject root=new JsonObject();CombatThreats.HealthGuard health=new CombatThreats.HealthGuard();
        BoundedEncounter owner;int windows;boolean blocked;long callbackCost;double hp=20;long age;
        boolean known=true,truncated;long customNow=-1;
        Fixture() { this(30_000_000_000L); }
        Fixture(long deadline) { owner=new BoundedEncounter(EncounterRequest.parseOptional(request()),root,0,64,0,deadline,clock::get,health); }
        BoundedEncounter.Decision tick(int tick,double z,List<CombatThreats.Observed> mobs) { return tick(tick,z,mobs,0); }
        BoundedEncounter.Decision tick(int tick,double z,List<CombatThreats.Observed> mobs,double vz) {
            long now=customNow>=0?customNow:1_000_000_000L+tick*50_000_000L;clock.set(now);
            var s=new CombatThreats.Snapshot(mobs,now-age,tick,truncated,known);
            var pose=new CombatRecovery.Motion(0,64,z,0,0,vz,true);
            var h=health.sample(tick,now,hp);
            CombatDetour.EdgeCheck windows=(a,b)-> {
                this.windows++;clock.addAndGet(callbackCost);
                if(blocked) return new CombatDetour.EdgeResult(false,0,"fixture_wall");
                FlatStepCorridor.CellSource cells=(x,y,zz)->y==63?CombatSafetyIntegrationTest.SOLID:CombatSafetyIntegrationTest.AIR;
                var result=CombatRetreatWindow.check(s,clock.get(),tick,
                        new FlatStepCorridor.Pose(a.x(),64,a.z(),true,0),b,0,64,0,cells,List.of());
                return result.edge();
            };
            return owner.tick(tick,s,pose,h,windows,()->null,(data,d)->CombatRetreatEvidence.append(data,d,null,null,null));
        }
        JsonObject e() { return root.getAsJsonObject("encounter"); }
    }
    @Test void explicitRequestPreservesOldApiAndDefaultGate() {
        assertNull(BoundedCombatRequest.parse(BoundedCombatTest.body()).encounter());
        assertEquals(2,BoundedCombatRequest.parse(request()).encounter().scope().size());
        String previous=System.getProperty(EncounterRequest.ENABLE_PROPERTY);
        try { System.clearProperty(EncounterRequest.ENABLE_PROPERTY);assertFalse(EncounterRequest.runtimeEnabled());
            System.setProperty(EncounterRequest.ENABLE_PROPERTY,"true");assertTrue(EncounterRequest.runtimeEnabled());
        } finally { if(previous==null) System.clearProperty(EncounterRequest.ENABLE_PROPERTY);else System.setProperty(EncounterRequest.ENABLE_PROPERTY,previous); }
    }
    @Test void malformedScopeAndHiddenMovementFieldsReject() {
        for(String key:List.of("jump","sneak","sprint","hotbar_slot","surprise")) {
            var b=request();b.addProperty(key,false);assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(b));
        }
        var b=request();b.getAsJsonArray("encounter_scope").get(1).getAsJsonObject().addProperty("uuid",ONE);
        final var duplicate=b;assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(duplicate));
        b=request();b.remove("encounter_mode");final var missing=b;assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(missing));
    }
    @Test void newModeCannotHideOnDifferentActionOrUnpairedNavigation() {
        var b=request();b.addProperty("action","click_slot");
        assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(b));
        var paired=request();paired.addProperty("expected_navigation_epoch",1);
        assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(paired));
        var unknown=request();unknown.getAsJsonArray("encounter_scope").get(0).getAsJsonObject().addProperty("extra",1);
        assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(unknown));
    }
    @Test void callbackAgeStartsAtActualSnapshotCaptureNotLaterDecision() {
        var f=new Fixture();f.age=4_000_000;f.tick(0,0,pair(3));
        assertNull(f.owner.callbackInterruption(1_146_000_000L));
        assertEquals("encounter_callback_observation_gap_risk_remaining",f.owner.callbackInterruption(1_146_000_001L));
    }
    @Test void callbackGapEvidenceDistinguishesCallbackDelayFromSnapshotAge() {
        var f=new Fixture();f.age=4_000_000;f.tick(0,0,pair(3));
        assertFalse(f.e().has("callback_interruption"));
        assertNull(f.owner.callbackInterruption(1_146_000_000L,"movement_input"));
        assertFalse(f.e().has("callback_interruption"));
        assertEquals("encounter_callback_observation_gap_risk_remaining",
                f.owner.callbackInterruption(1_146_000_001L,"post_tick"));
        var e=f.e().getAsJsonObject("callback_interruption");
        assertEquals("post_tick",e.get("phase").getAsString());
        assertEquals(1_146_000_001L,e.get("now_nanos").getAsLong());
        assertEquals(1_000_000_000L,e.get("last_tick_nanos").getAsLong());
        assertEquals(996_000_000L,e.get("snapshot_captured_nanos").getAsLong());
        assertEquals(150_000_001L,e.get("observation_age_nanos").getAsLong());
        assertEquals(150_000_000L,e.get("max_observation_age_nanos").getAsLong());
        assertEquals(1L,e.get("callback_interval_nanos").getAsLong());
        assertEquals("movement_input",e.get("previous_callback_phase").getAsString());
        assertEquals(0,e.get("evaluated_tick").getAsInt());
    }
    @Test void firstCallbackGapRetainsMissingPriorCallbackAndMissingTick() {
        var f=new Fixture();
        assertEquals("encounter_callback_observation_gap_risk_remaining",
                f.owner.callbackInterruption(1_150_000_001L,"pre_tick"));
        var e=f.e().getAsJsonObject("callback_interruption");
        assertTrue(e.get("previous_callback_nanos").isJsonNull());
        assertTrue(e.get("callback_interval_nanos").isJsonNull());
        assertTrue(e.get("last_tick_nanos").isJsonNull());
        assertTrue(e.get("snapshot_captured_nanos").isJsonNull());
        assertEquals(-1,e.get("evaluated_tick").getAsInt());
        assertEquals(150_000_001L,e.get("observation_age_nanos").getAsLong());
    }
    @Test void callbackEvidencePreservesClockAndDeadlinePriority() {
        var f=new Fixture(1_150_000_000L);
        assertEquals("encounter_clock_invalid_risk_remaining",f.owner.callbackInterruption(999_999_999L,"pre_tick"));
        assertEquals("deadline_exceeded",f.owner.callbackInterruption(1_150_000_001L,"pre_tick"));
        assertEquals("deadline_exceeded",f.e().getAsJsonObject("callback_interruption").get("reason").getAsString());
    }
    @Test void currentTerminalEvidenceZerosMovementAndRemovesHistoricalGoal() {
        var f=new Fixture();f.tick(0,0,pair(3));assertTrue(f.e().has("goal"));
        f.owner.terminal("cancelled","cancel_requested");
        assertFalse(f.e().has("goal"));assertFalse(f.e().get("movement_authorized").getAsBoolean());
        assertEquals("cancel_requested",f.e().get("state").getAsString());
        assertEquals(0,f.root.get("requested_forward").getAsInt());
        assertEquals("cancel_requested",f.root.get("decision_phase").getAsString());
    }
    @Test void newPlanRunsActualProductionWindowsWithoutOffense() {
        var f=new Fixture();var d=f.tick(0,0,pair(3));
        assertNull(d.terminal());assertTrue(d.forward()>0);assertTrue(f.windows>0);assertEquals(1,f.e().get("segments_planned").getAsInt());
        assertTrue(f.e().get("offense_disabled").getAsBoolean());assertTrue(f.e().get("risk_remaining").getAsBoolean());
    }
    @Test void segmentArrivalRetainsOwnerAndBudgetThenPlansNextSegment() {
        var f=new Fixture();f.tick(0,0,pair(3));
        var arrival=f.tick(1,-1.3,pair(3));assertNull(arrival.terminal());assertEquals(0,arrival.forward());
        assertTrue(arrival.reason().contains("segment_completed"));
        var next=f.tick(2,-1.3,pair(3));assertTrue(next.forward()>0);assertEquals(2,f.e().get("segments_planned").getAsInt());
        assertEquals(1.3,f.e().get("total_distance_observed").getAsDouble(),1e-9);
        assertEquals(2,f.e().get("elapsed_ticks").getAsInt());
    }
    @Test void chasingSnapshotRevokesThenFreshSnapshotCanPlanNewRoute() {
        var f=new Fixture();f.tick(0,0,pair(3));int checked=f.windows;
        var revoke=f.tick(1,0,pair(2.8));assertEquals(0,revoke.forward());assertNull(revoke.terminal());assertEquals(checked,f.windows);
        var fresh=f.tick(2,0,pair(2.6));assertTrue(fresh.forward()>0);assertTrue(f.windows>checked);
        assertEquals(1,f.e().get("route_revocations").getAsInt());
    }
    @Test void pursuitWithNetClearanceGainRevalidatesFreshActualWindows() {
        var f=new Fixture();f.tick(0,0,pair(3));int before=f.windows;
        var d=f.tick(1,-.2,pair(2.9),-.1);assertTrue(d.forward()>0);assertTrue(f.windows>before);
        assertTrue(f.e().getAsJsonObject("live_validation").get("all_remaining_windows_revalidated").getAsBoolean());
    }
    @Test void missingPrimaryTargetRevokesButStillProtectsAgainstOtherScopedZombie() {
        var f=new Fixture();f.tick(0,0,pair(3));
        var one=List.of(zombie(5,1,3));var d=f.tick(1,0,one);
        assertEquals(0,d.forward());assertNull(d.terminal());assertTrue(d.reason().contains("identity_changed"));
        d=f.tick(2,0,one);assertTrue(d.forward()>0);assertFalse(f.e().get("scope_fully_observed").getAsBoolean());
        assertFalse(f.e().get("missing_scope_is_kill").getAsBoolean());assertTrue(f.e().get("risk_remaining").getAsBoolean());
    }
    @Test void reusedIdDifferentUuidDoesNotAcquireReplacement() {
        var f=new Fixture();f.tick(0,0,pair(3));
        var intruder=new CombatThreats.Observed(4,"replacement","minecraft:zombie",0,64,3,.3,true,true);
        var d=f.tick(1,0,List.of(intruder,zombie(5,1,3)));assertEquals("failed",d.terminal());assertEquals(0,d.forward());
        assertEquals("encounter_threat_outside_scope_risk_remaining",d.reason());
    }
    @Test void newlyObservedThirdZombieTerminatesExactScope() {
        var f=new Fixture();f.tick(0,0,pair(3));
        var d=f.tick(1,0,List.of(zombie(4,0,3),zombie(5,1,3),new CombatThreats.Observed(6,"third","minecraft:zombie",2,64,3,.3,true,true)));
        assertEquals("encounter_threat_outside_scope_risk_remaining",d.reason());assertEquals(0,d.forward());
    }
    @Test void knownDeadOrAbsentScopeNeverCountsAsKillOrClearance() {
        for(boolean dead:List.of(true,false)) {
            var f=new Fixture();var e=zombie(4,0,10);
            var mobs=dead?List.of(new CombatThreats.Observed(e.entityId(),e.uuid(),e.type(),0,64,10,.3,true,false)):List.<CombatThreats.Observed>of();
            var d=f.tick(0,0,mobs);assertEquals("failed",d.terminal());assertEquals("encounter_initial_scope_unobserved_risk_remaining",d.reason());
        }
    }
    @Test void creeperAndUnsupportedPreemptEvenLatchedLowHealth() {
        for(String type:List.of("minecraft:creeper","minecraft:enderman","minecraft:spider","minecraft:skeleton")) {
            var f=new Fixture();f.hp=14;f.tick(0,0,pair(3));
            var d=f.tick(1,0,List.of(zombie(4,0,3),new CombatThreats.Observed(8,"new",type,1,64,3,.3,true,true)));
            assertEquals("failed",d.terminal());assertEquals(0,d.forward());assertFalse(d.reason().contains("health"));
        }
    }
    @Test void unknownTruncatedStaleAndDuplicateObservationsRefuse() {
        for(int problem=0;problem<4;problem++) {
            var f=new Fixture();f.tick(0,0,pair(3));var mobs=pair(3);
            if(problem==0) f.known=false;if(problem==1)f.truncated=true;if(problem==2)f.age=150_000_001;
            if(problem==3)mobs=List.of(zombie(4,0,3),zombie(4,1,3));
            var d=f.tick(1,0,mobs);assertEquals("failed",d.terminal());assertEquals(0,d.forward());assertTrue(d.reason().startsWith("threat_snapshot_"));
        }
    }
    @Test void insufficientRemainderCannotRefundDistanceForNewSegment() {
        var f=new Fixture();f.tick(0,0,pair(3));f.tick(1,-1.3,pair(3));f.tick(2,-1.3,pair(3));
        f.tick(3,-2.6,pair(3));f.tick(4,-2.6,pair(3));
        var d=f.tick(5,-3.5,pair(3));assertEquals("failed",d.terminal());assertEquals("retreat_distance_budget_risk_remaining",d.reason());
        assertEquals(3.5,f.e().get("total_distance_observed").getAsDouble(),1e-9);assertEquals(0,d.forward());
    }
    @Test void rechecksConsumeOriginalWallAndTickBudget() {
        var f=new Fixture();BoundedEncounter.Decision d=null;
        for(int i=0;i<=60;i++) { d=f.tick(i,0,pair(3-(i%2)*.1));if(d.terminal()!=null)break; }
        assertEquals("failed",d.terminal());assertTrue(d.reason().contains("budget"));
        assertTrue(f.e().get("elapsed_ticks").getAsInt()<=60);
    }
    @Test void originalShortDeadlineCannotBeExtendedBySegment() {
        var f=new Fixture(1_100_000_000L);f.tick(0,0,pair(3));f.tick(1,-1.3,pair(3));
        assertEquals("deadline_exceeded",f.tick(2,-1.3,pair(3)).reason());
    }
    @Test void healthLatchSurvivesSegmentAndHealing() {
        var f=new Fixture();f.tick(0,0,pair(3));f.hp=16;f.tick(1,-1.3,pair(3));f.hp=20;
        var d=f.tick(2,-1.3,pair(3));assertNull(d.terminal());
        assertTrue(f.e().get("health_interruption_latched").getAsBoolean());assertEquals("rapid_health_loss",f.e().get("health_reason").getAsString());
        for(int i=3;i<6;i++) { d=f.tick(i,-1.3,pair(10));assertNotEquals("succeeded",d.terminal()); }
    }
    @Test void longTickHealthGapStopsWithoutRebuildingGuard() {
        var f=new Fixture();f.tick(0,0,pair(3));f.customNow=1_151_000_000L;
        var d=f.tick(1,0,pair(3));assertEquals("health_observation_gap_risk_remaining",d.reason());assertEquals(0,d.forward());
        f.customNow=1_200_000_000L;assertEquals(d.reason(),f.tick(2,0,pair(10)).reason());
    }
    @Test void latchedHealthCannotHideCurrentGapOrInvalidSample() {
        for(boolean gap:List.of(true,false)) {
            var f=new Fixture();f.hp=14;f.tick(0,0,pair(3));
            if(gap) f.customNow=1_200_000_000L;else f.hp=Double.NaN;
            var d=f.tick(1,-.2,pair(3));assertEquals("failed",d.terminal());assertEquals(0,d.forward());
            assertEquals(gap?"health_observation_gap_risk_remaining":"health_data_unknown_risk_remaining",d.reason());
        }
    }
    @Test void eachClientCallbackCanRefuseStalePermitWithoutWaitingForPreTick() {
        var f=new Fixture();f.tick(0,0,pair(3));
        assertNull(f.owner.callbackInterruption(1_150_000_000L));
        assertEquals("encounter_callback_observation_gap_risk_remaining",f.owner.callbackInterruption(1_150_000_001L));
        assertEquals("retreat_budget_risk_remaining",f.owner.callbackInterruption(4_000_000_000L));
    }
    @Test void initialScopeRequiresBothLivingIdentities() {
        var f=new Fixture();var d=f.tick(0,0,List.of(zombie(4,0,3)));
        assertEquals("encounter_initial_scope_unobserved_risk_remaining",d.reason());assertEquals(0,f.windows);
    }
    @Test void noRouteKeepsExactRejectionsAndNoInput() {
        var f=new Fixture();f.blocked=true;var d=f.tick(0,0,pair(3));assertEquals("no_safe_retreat_risk_remaining",d.reason());
        assertEquals(16,f.e().getAsJsonObject("plan").getAsJsonObject("rejections").get("fixture_wall").getAsInt());assertEquals(0,d.forward());
    }
    @Test void checkingDeadlineIsNeverResetForCandidateOrDiagnostics() {
        var f=new Fixture();f.callbackCost=8_000_001;
        var d=f.tick(0,0,pair(3));assertEquals("retreat_planning_budget_risk_remaining",d.reason());assertEquals(0,d.forward());
        assertEquals(1,f.windows);assertTrue(f.e().getAsJsonObject("plan").get("budget_exhausted").getAsBoolean());
    }
    @Test void successRequiresThreeActualSettledFullScopeSnapshots() {
        var f=new Fixture();assertNull(f.tick(0,0,pair(9)).terminal());assertNull(f.tick(1,0,pair(9)).terminal());
        var d=f.tick(2,0,pair(9));assertEquals("succeeded",d.terminal());assertEquals("encounter_clearance_observed",d.reason());
        assertEquals(0,f.windows);assertEquals(3,f.e().get("clearance_observations").getAsInt());
        assertTrue(f.e().get("risk_remaining").getAsBoolean());assertTrue(f.e().get("requires_handoff").getAsBoolean());
        assertFalse(f.e().get("safety_assured").getAsBoolean());
    }
    @Test void clearanceDecreaseResetsConsecutiveProofAndMissingCannotSucceed() {
        var f=new Fixture();f.tick(0,0,pair(10));var d=f.tick(1,0,pair(9));assertNull(d.terminal());assertEquals(0,f.e().get("clearance_observations").getAsInt());
        d=f.tick(2,0,List.of(zombie(5,1,10)));assertNotEquals("succeeded",d.terminal());
    }
    @Test void pauseFocusCancelAndCleanupFailureHaveExplicitTerminalReleaseContract() {
        assertEquals("encounter_paused_risk_remaining",BoundedEncounter.lifecycle(true,true,false));
        assertEquals("encounter_window_unfocused_risk_remaining",BoundedEncounter.lifecycle(false,false,false));
        assertNull(BoundedEncounter.lifecycle(false,true,false));
        for(String why:List.of("encounter_paused_risk_remaining","encounter_window_unfocused_risk_remaining","cancel_requested","world_transition","position_discontinuity_rebind_required","input_release_unconfirmed")) {
            var f=new Fixture();f.tick(0,0,pair(3));f.owner.terminal("cancelled",why);
            var d=f.tick(1,-.2,pair(3));assertEquals(0,d.forward());assertEquals(why,d.reason());
            var registry=new ActionRegistry();registry.begin(ClientActionRequest.parse(request()));registry.finishAfterCleanup("cancelled",why,!why.equals("input_release_unconfirmed"));
            assertNull(registry.active());assertEquals(!why.equals("input_release_unconfirmed"),registry.status(null).getAsJsonObject("result").get("input_release_confirmed").getAsBoolean());
        }
    }
}

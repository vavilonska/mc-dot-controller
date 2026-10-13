package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class CombatRetreatEvidenceTest {
    @Test void serializedBudgetRetainsOriginalWindowAndCellWithScopeLabels() {
        var threats=new CombatThreats.Snapshot(List.of(new CombatThreats.Observed(1,"one","minecraft:zombie",0,64,5,.3,true,true)),0,0,false,true);
        var clock=new AtomicLong();var cell=new FlatStepCorridor.CellRef(14,64,20,"feet","minecraft:grass_block");
        var plan=CombatRetreatPolicy.plan(threats,new CombatDetour.Point(0,0),(a,b)-> {
            clock.set(8_000_000);return new CombatDetour.EdgeResult(false,0,"feet_collision");
        },clock::get,()->cell);
        var cache=new CombatCellCache((x,y,z)->null);cache.read(1,2,3);cache.read(1,2,3);
        var reads=new TerrainReader.ReadMetrics();reads.stateReads=3;reads.metadataPreflightNanos=7;
        JsonObject json=new JsonObject();CombatRetreatEvidence.append(json,plan.diagnostics(),null,cache,reads);
        assertTrue(plan.diagnostics().checkBudget("post_diagnostics"));CombatRetreatEvidence.stamp(json,plan.diagnostics());
        assertEquals("post_window",json.get("budget_check_stage").getAsString());
        assertEquals("post_diagnostics",json.get("elapsed_through_stage").getAsString());
        var original=json.getAsJsonObject("last_window_result_before_budget");
        assertFalse(original.get("clear").getAsBoolean());assertEquals("feet_collision",original.get("reason").getAsString());
        assertEquals("minecraft:grass_block",original.getAsJsonObject("rejected_cell").get("id").getAsString());
        assertTrue(original.get("returned").getAsBoolean());assertTrue(original.get("result_present").getAsBoolean());
        assertEquals(1,json.getAsJsonArray("candidates").size());assertEquals(1,json.getAsJsonArray("windows").size());
        assertEquals("captured_tick_cumulative",json.getAsJsonObject("cell_cache").get("scope").getAsString());
        assertEquals(2,json.getAsJsonObject("cell_cache").get("requests").getAsInt());
        assertEquals(1,json.getAsJsonObject("cell_cache").get("hits").getAsInt());
        assertEquals("captured_tick_cumulative",json.getAsJsonObject("terrain_reads").get("scope").getAsString());
        assertEquals(3,json.getAsJsonObject("terrain_reads").get("state_reads").getAsInt());
        assertEquals(7,json.getAsJsonObject("terrain_reads").get("metadata_preflight_ns").getAsInt());
        assertUnavailable(json.getAsJsonObject("window_wrapper_timing"),"metrics_missing");
    }
    private static final CombatDetour.EdgeResult CLEAR=new CombatDetour.EdgeResult(true,1,"clear");
    private static CombatRetreatWindow.Metrics inner(long... samples) {
        AtomicInteger index=new AtomicInteger();
        var metrics=new CombatRetreatWindow.Metrics(()->samples[Math.min(index.getAndIncrement(),samples.length-1)]);
        for(int i=0;i<samples.length/2;i++)
            CombatRetreatWindow.check(null,0,0,null,null,0,0,0,null,List.of(),metrics);
        return metrics;
    }
    private static CombatRetreatDiagnostics observed(long elapsed,CombatDetour.EdgeResult result,boolean returned) {
        AtomicLong clock=new AtomicLong();var diagnostics=new CombatRetreatDiagnostics(clock::get);
        assertTrue(diagnostics.beginWindow(1));clock.set(elapsed);diagnostics.endWindow(result,null,returned);
        return diagnostics;
    }
    private static JsonObject timing(CombatRetreatDiagnostics diagnostics,CombatRetreatWindow.Metrics metrics) {
        JsonObject json=new JsonObject();CombatRetreatEvidence.append(json,diagnostics,metrics,null,null);
        return json.getAsJsonObject("window_wrapper_timing");
    }
    private static void assertUnavailable(JsonObject timing,String reason) {
        assertFalse(timing.get("available").getAsBoolean());assertEquals(reason,timing.get("unavailable_reason").getAsString());
        for(String field:List.of("setup_elapsed_ns","inner_call_elapsed_ns","wrapper_elapsed_ns",
                "inner_call_boundary_elapsed_ns","remaining_outer_callback_elapsed_ns"))
            assertFalse(timing.has(field),field+" must remain unavailable, not zero");
    }
    @Test void wrapperAttributionHasExactExclusiveBucketsAndNestedScopeForANormalDenial() {
        var diagnostics=observed(120,new CombatDetour.EdgeResult(false,0,"feet_collision"),true);
        var metrics=inner(20,80);metrics.recordWrapper(10,20,100,true);
        var timing=timing(diagnostics,metrics);
        assertTrue(timing.get("available").getAsBoolean());assertFalse(timing.has("unavailable_reason"));
        assertEquals(1,timing.get("schema_version").getAsInt());
        assertEquals("this_plan_or_validation",timing.get("scope").getAsString());
        assertEquals("nested_wrapper_contains_setup_and_inner_call",timing.get("raw_interval_scope").getAsString());
        assertEquals("exclusive_setup_inner_boundary_remaining_outer",timing.get("attribution_scope").getAsString());
        assertEquals("original_planning_budget",timing.get("observer_cost_scope").getAsString());
        for(String count:List.of("sampled_wrapper_calls","completed_wrapper_calls","observed_window_calls","completed_window_calls","inner_window_calls"))
            assertEquals(1,timing.get(count).getAsLong());
        assertEquals(10,timing.get("setup_elapsed_ns").getAsLong());assertEquals(80,timing.get("inner_call_elapsed_ns").getAsLong());
        assertEquals(90,timing.get("wrapper_elapsed_ns").getAsLong());assertEquals(20,timing.get("inner_call_boundary_elapsed_ns").getAsLong());
        assertEquals(30,timing.get("remaining_outer_callback_elapsed_ns").getAsLong());
        assertEquals(diagnostics.totalWindowElapsedNanos()-metrics.nanos(CombatRetreatWindow.Stage.WINDOW_TOTAL),
                timing.get("setup_elapsed_ns").getAsLong()+timing.get("inner_call_boundary_elapsed_ns").getAsLong()
                        +timing.get("remaining_outer_callback_elapsed_ns").getAsLong());
    }
    @Test void twoWindowsAggregateOnlyWhenAllThreeCountsMatch() {
        AtomicLong clock=new AtomicLong();var diagnostics=new CombatRetreatDiagnostics(clock::get);
        assertTrue(diagnostics.beginWindow(1));clock.set(120);diagnostics.endWindow(CLEAR,null,true);
        assertTrue(diagnostics.beginWindow(2));clock.set(300);diagnostics.endWindow(CLEAR,null,true);
        var metrics=inner(20,80,200,300);metrics.recordWrapper(10,20,100,true);metrics.recordWrapper(130,150,280,true);
        var timing=timing(diagnostics,metrics);
        assertTrue(timing.get("available").getAsBoolean());assertEquals(2,timing.get("completed_wrapper_calls").getAsLong());
        assertEquals(2,timing.get("completed_window_calls").getAsLong());assertEquals(2,timing.get("inner_window_calls").getAsLong());
        assertEquals(30,timing.get("setup_elapsed_ns").getAsLong());assertEquals(210,timing.get("inner_call_elapsed_ns").getAsLong());
        assertEquals(240,timing.get("wrapper_elapsed_ns").getAsLong());assertEquals(50,timing.get("inner_call_boundary_elapsed_ns").getAsLong());
        assertEquals(60,timing.get("remaining_outer_callback_elapsed_ns").getAsLong());
        assertEquals(140,diagnostics.totalWindowElapsedNanos()-metrics.nanos(CombatRetreatWindow.Stage.WINDOW_TOTAL));
    }
    @Test void absentZeroAndMismatchedSamplesRemainUnavailable() {
        var diagnostics=observed(120,CLEAR,true);
        var missing=timing(diagnostics,null);assertUnavailable(missing,"metrics_missing");
        assertFalse(missing.has("sampled_wrapper_calls"));assertFalse(missing.has("inner_window_calls"));
        assertUnavailable(timing(new CombatRetreatDiagnostics(()->0),new CombatRetreatWindow.Metrics(()->0)),"no_samples");
        var metrics=inner(20,80);assertUnavailable(timing(diagnostics,metrics),"count_mismatch");
        metrics.recordWrapper(10,20,100,true);metrics.recordWrapper(130,150,180,true);
        assertUnavailable(timing(diagnostics,metrics),"count_mismatch");
        var extraInner=inner(20,80,100,120);extraInner.recordWrapper(10,20,100,true);
        assertUnavailable(timing(diagnostics,extraInner),"count_mismatch");
    }
    @Test void equalWindowCountsCannotHideNullExceptionsOrIncompleteWrappers() {
        var metrics=inner(20,80);metrics.recordWrapper(10,20,100,true);
        assertUnavailable(timing(observed(120,null,true),metrics),"incomplete_callback");
        var exception=new CombatDetour.EdgeResult(false,0,"retreat_window_exception");
        assertUnavailable(timing(observed(120,exception,false),metrics),"incomplete_callback");
        assertUnavailable(timing(observed(120,exception,true),metrics),"inner_window_exception");
        var incomplete=inner(20,80);incomplete.recordWrapper(10,20,100,false);
        assertUnavailable(timing(observed(120,CLEAR,true),incomplete),"incomplete_wrapper");
        assertFalse(metrics.clockInvalid);assertFalse(incomplete.clockInvalid);
    }
    @Test void eitherExistingInvalidClockMakesAttributionUnavailable() {
        var invalidInner=inner(80,20);invalidInner.recordWrapper(10,20,100,true);
        assertTrue(invalidInner.clockInvalid);assertUnavailable(timing(observed(120,CLEAR,true),invalidInner),"clock_invalid");
        AtomicLong clock=new AtomicLong();var invalidOuter=new CombatRetreatDiagnostics(clock::get);
        assertTrue(invalidOuter.beginWindow(1));clock.set(-1);invalidOuter.endWindow(CLEAR,null,true);
        var metrics=inner(20,80);metrics.recordWrapper(10,20,100,true);
        assertTrue(invalidOuter.clockInvalid());assertUnavailable(timing(invalidOuter,metrics),"clock_invalid");
        assertFalse(metrics.clockInvalid);
    }
    @Test void negativeResidualsStayUnavailableWithoutClampingOrChangingTheExistingClocks() {
        var longInner=inner(0,81);longInner.recordWrapper(10,20,100,true);
        var diagnostics=observed(120,CLEAR,true);
        assertUnavailable(timing(diagnostics,longInner),"negative_inner_boundary");
        var metrics=inner(20,80);metrics.recordWrapper(10,20,100,true);
        var shortOuter=observed(89,CLEAR,true);
        assertUnavailable(timing(shortOuter,metrics),"negative_remaining_outer");
        assertFalse(longInner.clockInvalid);assertFalse(metrics.clockInvalid);
        assertFalse(diagnostics.clockInvalid());assertFalse(shortOuter.clockInvalid());
    }
    @Test void wrapperOverflowIsUnavailableEvenWhenAllCountsMatch() {
        AtomicLong clock=new AtomicLong();var diagnostics=new CombatRetreatDiagnostics(clock::get);
        assertTrue(diagnostics.beginWindow(1));clock.set(1);diagnostics.endWindow(CLEAR,null,true);
        assertTrue(diagnostics.beginWindow(2));clock.set(2);diagnostics.endWindow(CLEAR,null,true);
        var metrics=inner(0,0,0,0);
        metrics.recordWrapper(0,Long.MAX_VALUE-1,Long.MAX_VALUE,true);metrics.recordWrapper(0,0,1,true);
        var timing=timing(diagnostics,metrics);assertUnavailable(timing,"wrapper_timing_invalid");
        assertEquals(2,timing.get("completed_wrapper_calls").getAsLong());assertEquals(2,timing.get("completed_window_calls").getAsLong());
        assertEquals(2,timing.get("inner_window_calls").getAsLong());assertFalse(metrics.clockInvalid);assertFalse(diagnostics.clockInvalid());
    }
    @Test void optionalTimingFieldsAgreeAcrossBothRealHttpEncodingEnvelopes() throws Exception {
        var diagnostics=observed(120,CLEAR,true);var metrics=inner(20,80);metrics.recordWrapper(10,20,100,true);
        var shortOuter=observed(89,CLEAR,true);
        for(JsonObject timing:List.of(timing(diagnostics,metrics),timing(diagnostics,null),timing(shortOuter,metrics))) {
            JsonObject plan=new JsonObject();plan.add("window_wrapper_timing",timing);
            JsonObject encounter=new JsonObject();encounter.add("plan",plan);
            JsonObject combat=new JsonObject();combat.add("encounter",encounter);
            JsonObject result=new JsonObject();result.add("combat",combat);
            JsonObject status=new JsonObject();status.add("result",result);
            JsonObject action=new JsonObject();action.add("client_action",status.deepCopy());
            var encodedStatus=JsonParser.parseString(BridgeJson.toJson(status)).getAsJsonObject();
            var encodedAction=JsonParser.parseString(BridgeJson.toJson(action)).getAsJsonObject().getAsJsonObject("client_action");
            var statusTiming=encodedStatus.getAsJsonObject("result").getAsJsonObject("combat").getAsJsonObject("encounter")
                    .getAsJsonObject("plan").getAsJsonObject("window_wrapper_timing");
            var actionTiming=encodedAction.getAsJsonObject("result").getAsJsonObject("combat").getAsJsonObject("encounter")
                    .getAsJsonObject("plan").getAsJsonObject("window_wrapper_timing");
            assertEquals(timing,statusTiming);assertEquals(timing,actionTiming);
            if(!timing.get("available").getAsBoolean()) {
                assertUnavailable(statusTiming,timing.get("unavailable_reason").getAsString());
                assertUnavailable(actionTiming,timing.get("unavailable_reason").getAsString());
            }
        }
    }
    @Test void tickAndMotionDispatchGatesFollowObservationWorkBeforeReturningInput() throws Exception {
        var path=Path.of(System.getProperty("mineclientBridge.projectDir"),"src/main/java/io/github/campione01/mineclientbridge/BoundedCombat.java");
        String source=Files.readString(path);
        String tick=source.substring(source.indexOf("    Step tick("),source.indexOf("    private Step tickCombat("));
        assertTrue(tick.indexOf("pendingRetreatDiagnostics=null")<tick.indexOf("tickCombat(mc, tick)"));
        assertTrue(tick.indexOf("observeDecisionMotion")<tick.indexOf("checkBudget(\"tick_decision_return\")"));
        assertTrue(tick.indexOf("evidence.add(\"decision_pose\", pose)")<tick.indexOf("checkBudget(\"tick_decision_return\")"));
        assertTrue(tick.indexOf("checkBudget(\"tick_decision_return\")")<tick.indexOf("return step;"));
        assertTrue(tick.contains("step=Step.end(\"failed\""));assertTrue(tick.contains("evidence.addProperty(\"requested_forward\",step.forward())"));
        assertTrue(tick.contains("lastDecisionPhase=step.reason()"));
        String retreat=source.substring(source.indexOf("    private Step safetyRetreat("),source.indexOf("    private void observeDecisionMotion("));
        assertEquals(2,retreat.split("CombatRetreatEvidence.append\\(",-1).length-1);
        assertEquals(2,retreat.split("checkBudget\\(\"post_diagnostics\"\\)",-1).length-1);
        assertTrue(retreat.indexOf("faceMovement(mc,dx,dz)")<retreat.indexOf("checkBudget(\"motion_decision_return\")"));
        assertTrue(retreat.indexOf("checkBudget(\"motion_decision_return\")")<retreat.indexOf("return new Step(distance"));
        assertTrue(retreat.contains("pendingRetreatDiagnostics=plan.diagnostics()"));
        assertTrue(retreat.contains("pendingRetreatDiagnostics=validation.diagnostics()"));
        String wrapper=source.substring(source.indexOf("    private CombatDetour.EdgeResult retreatWindow("),
                source.indexOf("    private FlatStepCorridor.CellRef retreatRejectedCell(")).replaceAll("\\s+","");
        assertTrue(wrapper.substring(wrapper.indexOf('{')+1).startsWith("longwrapperEntry=System.nanoTime();"));
        for(String required:List.of("beforeInner=System.nanoTime();","result=CombatRetreatWindow.check(",
                "finally{longafterInner=System.nanoTime();","recordWrapper(wrapperEntry,beforeInner,afterInner,result!=null)",
                "lastRouteTerrain=result.terrain();")) assertTrue(wrapper.contains(required),required);
        assertEquals(4,wrapper.split("System\\.nanoTime\\(\\)",-1).length-1); // Three new samples plus the existing threat timestamp.
        assertTrue(wrapper.indexOf("newCombatRetreatWindow.Metrics()")<wrapper.indexOf("beforeInner=System.nanoTime();"));
        assertTrue(wrapper.indexOf("newFlatStepCorridor.Pose(")<wrapper.indexOf("beforeInner=System.nanoTime();"));
        assertTrue(wrapper.indexOf("beforeInner=System.nanoTime();")<wrapper.indexOf("result=CombatRetreatWindow.check("));
        assertTrue(wrapper.indexOf("result=CombatRetreatWindow.check(")<wrapper.indexOf("finally{longafterInner=System.nanoTime();"));
        assertTrue(wrapper.indexOf("finally{longafterInner=System.nanoTime();")<wrapper.indexOf("recordWrapper("));
        assertTrue(wrapper.indexOf("recordWrapper(")<wrapper.indexOf("lastRouteTerrain=result.terrain();"));
        assertFalse(wrapper.contains("catch("));
        assertEquals(3,source.split("retreatWindowMetrics=null;lastRouteTerrain=null;",-1).length-1);
        assertTrue(retreat.indexOf("CombatRetreatEvidence.append(diagnostics,")<retreat.indexOf("checkBudget(\"plan_publication\")"));
        assertTrue(retreat.indexOf("CombatRetreatEvidence.append(checked,")<retreat.indexOf("checkBudget(\"pre_motion\")"));
    }
}

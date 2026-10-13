package io.github.campione01.mineclientbridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.util.List;

/** Serialization at decision boundaries only. Callers check the original deadline afterwards. */
final class CombatRetreatEvidence {
    static void append(JsonObject target,CombatRetreatDiagnostics diagnostics,CombatRetreatWindow.Metrics metrics,
                       CombatCellCache cells,TerrainReader.ReadMetrics reads) {
        target.addProperty("diagnostics_schema_version",1);
        target.addProperty("planning_budget_ns",CombatRetreatPolicy.MAX_CHECK_NANOS);
        target.addProperty("timing_scope","invocation_wall_time_cooperative_boundaries_not_hard_realtime");
        target.addProperty("candidate_scope","window_validation_before_final_publication_gates");
        target.addProperty("pre_first_window_elapsed_ns",diagnostics.preFirstWindowElapsedNanos());
        target.addProperty("last_window_elapsed_ns",diagnostics.lastWindowElapsedNanos());
        target.addProperty("total_window_elapsed_ns",diagnostics.totalWindowElapsedNanos());
        JsonArray candidates=new JsonArray();
        for(var candidate:diagnostics.candidates()) {
            JsonObject item=new JsonObject();item.addProperty("candidate",candidate.candidate());
            item.addProperty("window_checks",candidate.windows());item.addProperty("elapsed_ns",candidate.elapsedNanos());
            item.addProperty("clear",candidate.clear());item.addProperty("reason",candidate.reason());
            item.addProperty("budget_exhausted",candidate.budgetExhausted());candidates.add(item);
        }
        target.add("candidates",candidates);
        JsonArray windows=new JsonArray();
        var observedWindows=diagnostics.windows();
        for(var window:observedWindows) windows.add(window(window));
        target.add("windows",windows);
        if(diagnostics.lastWindow()!=null) target.add("last_window_result_before_budget",window(diagnostics.lastWindow()));
        JsonObject stages=new JsonObject();
        if(metrics!=null) for(var stage:CombatRetreatWindow.Stage.values()) {
            JsonObject item=new JsonObject();item.addProperty("calls",metrics.calls(stage));item.addProperty("elapsed_ns",metrics.nanos(stage));
            stages.add(stage.name().toLowerCase(java.util.Locale.ROOT),item);
        }
        stages.addProperty("scope","this_plan_or_validation");
        stages.addProperty("clock_invalid",metrics!=null && metrics.clockInvalid);
        stages.addProperty("nested_times_overlap",true);target.add("window_stages",stages);
        target.add("window_wrapper_timing",wrapperTiming(diagnostics,metrics,observedWindows));
        if(cells!=null) {
            JsonObject cache=new JsonObject();cache.addProperty("scope","captured_tick_cumulative");
            cache.addProperty("requests",cells.requests);cache.addProperty("hits",cells.hits);cache.addProperty("misses",cells.misses);
            cache.addProperty("capacity_rejections",cells.capacityRejections);cache.addProperty("read_failures",cells.readFailures);
            cache.addProperty("entries",cells.size());cache.addProperty("max_entries",CombatCellCache.MAX_CELLS);target.add("cell_cache",cache);
        }
        if(reads!=null) {
            JsonObject terrain=new JsonObject();terrain.addProperty("scope","captured_tick_cumulative");
            terrain.addProperty("loaded_cell_reads",reads.loadedCellReads);terrain.addProperty("state_reads",reads.stateReads);
            terrain.addProperty("fluid_reads",reads.fluidReads);terrain.addProperty("shape_context_reads",reads.shapeContextReads);
            terrain.addProperty("chunk_requests",reads.chunkRequests);terrain.addProperty("chunk_cache_hits",reads.chunkCacheHits);
            terrain.addProperty("chunk_fetches",reads.chunkFetches);terrain.addProperty("state_read_ns",reads.stateReadNanos);
            terrain.addProperty("fluid_hazard_ns",reads.fluidHazardNanos);terrain.addProperty("collision_ns",reads.collisionNanos);
            terrain.addProperty("metadata_preflight_ns",reads.metadataPreflightNanos);
            terrain.addProperty("nested_times_overlap",true);target.add("terrain_reads",terrain);
        }
    }
    /** Small final stamp is after the boundary sample; it cannot provide a hard realtime guarantee. */
    static void stamp(JsonObject target,CombatRetreatDiagnostics diagnostics) {
        target.addProperty("plan_elapsed_ns",diagnostics.elapsedNanos());
        target.addProperty("elapsed_through_stage",diagnostics.lastBudgetCheckStage());
        target.addProperty("budget_check_stage",diagnostics.budgetCheckStage());
        target.addProperty("clock_invalid",diagnostics.clockInvalid());
    }
    /** Optional attribution only. Its sampling, aggregation and serialization use the original budget. */
    private static JsonObject wrapperTiming(CombatRetreatDiagnostics diagnostics,CombatRetreatWindow.Metrics metrics,
                                            List<CombatRetreatDiagnostics.Window> windows) {
        int completedWindows=0;
        long outerSum=0;
        boolean outerInvalid=false,innerException=false;
        for(var window:windows) {
            if(window.returned() && window.resultPresent()) completedWindows++;
            if("retreat_window_exception".equals(window.reason())) innerException=true;
            long duration=window.elapsedNanos();
            if(duration<0 || Long.MAX_VALUE-outerSum<duration) outerInvalid=true;
            else outerSum+=duration;
        }
        String unavailable=null;
        long innerBoundary=0,remainingOuter=0;
        if(metrics==null) unavailable="metrics_missing";
        else if(windows.isEmpty() && metrics.wrapperCalls==0) unavailable="no_samples";
        else if(diagnostics.clockInvalid() || metrics.clockInvalid) unavailable="clock_invalid";
        else if(completedWindows!=windows.size()) unavailable="incomplete_callback";
        else if(innerException) unavailable="inner_window_exception";
        else if(metrics.wrapperCalls!=metrics.completedWrapperCalls) unavailable="incomplete_wrapper";
        else if(metrics.completedWrapperCalls!=completedWindows
                || metrics.calls(CombatRetreatWindow.Stage.WINDOW_TOTAL)!=completedWindows) unavailable="count_mismatch";
        else if(metrics.wrapperTimingInvalid) unavailable="wrapper_timing_invalid";
        else if(outerInvalid || outerSum!=diagnostics.totalWindowElapsedNanos()) unavailable="outer_timing_invalid";
        else {
            long inner=metrics.nanos(CombatRetreatWindow.Stage.WINDOW_TOTAL);
            if(inner<0 || metrics.wrapperInnerCallNanos<inner) unavailable="negative_inner_boundary";
            else if(diagnostics.totalWindowElapsedNanos()<metrics.wrapperElapsedNanos) unavailable="negative_remaining_outer";
            else {
                innerBoundary=metrics.wrapperInnerCallNanos-inner;
                remainingOuter=diagnostics.totalWindowElapsedNanos()-metrics.wrapperElapsedNanos;
            }
        }
        boolean available=unavailable==null;
        JsonObject timing=new JsonObject();
        timing.addProperty("schema_version",1);
        timing.addProperty("scope","this_plan_or_validation");
        timing.addProperty("raw_interval_scope","nested_wrapper_contains_setup_and_inner_call");
        timing.addProperty("attribution_scope","exclusive_setup_inner_boundary_remaining_outer");
        timing.addProperty("observer_cost_scope","original_planning_budget");
        timing.addProperty("available",available);
        if(unavailable!=null) timing.addProperty("unavailable_reason",unavailable);
        if(metrics!=null) {
            timing.addProperty("sampled_wrapper_calls",metrics.wrapperCalls);
            timing.addProperty("completed_wrapper_calls",metrics.completedWrapperCalls);
            timing.addProperty("inner_window_calls",metrics.calls(CombatRetreatWindow.Stage.WINDOW_TOTAL));
        }
        timing.addProperty("observed_window_calls",windows.size());timing.addProperty("completed_window_calls",completedWindows);
        // Omit unknown durations in the source object: all existing HTTP envelopes then agree.
        if(available) {
            timing.addProperty("setup_elapsed_ns",metrics.wrapperSetupNanos);
            timing.addProperty("inner_call_elapsed_ns",metrics.wrapperInnerCallNanos);
            timing.addProperty("wrapper_elapsed_ns",metrics.wrapperElapsedNanos);
            timing.addProperty("inner_call_boundary_elapsed_ns",innerBoundary);
            timing.addProperty("remaining_outer_callback_elapsed_ns",remainingOuter);
        }
        return timing;
    }
    private static JsonObject window(CombatRetreatDiagnostics.Window window) {
        JsonObject result=new JsonObject();result.addProperty("candidate",window.candidate());result.addProperty("window",window.window());
        result.addProperty("elapsed_ns",window.elapsedNanos());result.addProperty("returned",window.returned());
        result.addProperty("result_present",window.resultPresent());
        result.addProperty("clear",window.clear());result.addProperty("reason",window.reason());
        var rejected=window.rejectedCell();
        if(rejected!=null) {
            JsonObject cell=new JsonObject();cell.addProperty("x",rejected.x());cell.addProperty("y",rejected.y());
            cell.addProperty("z",rejected.z());cell.addProperty("layer",rejected.layer());cell.addProperty("id",rejected.id());
            result.add("rejected_cell",cell);
        }
        return result;
    }
    private CombatRetreatEvidence() { }
}

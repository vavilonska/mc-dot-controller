package io.github.campione01.mineclientbridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;

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
        for(var window:diagnostics.windows()) windows.add(window(window));
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

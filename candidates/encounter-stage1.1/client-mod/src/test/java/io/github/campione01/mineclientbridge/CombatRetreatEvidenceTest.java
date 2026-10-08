package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
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
    }
}

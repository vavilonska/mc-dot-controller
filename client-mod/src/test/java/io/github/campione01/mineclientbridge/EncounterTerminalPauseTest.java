package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/** Actual registry terminal serialization and production hook; no Minecraft scheduler simulation. */
class EncounterTerminalPauseTest {
    static JsonObject reply() {
        var r=new JsonObject();r.addProperty("pause_screen_installed",true);
        r.addProperty("already_pause_screen",false);r.addProperty("client_paused_observed",false);
        r.addProperty("pause_effect_confirmed",false);r.addProperty("server_confirmed",false);return r;
    }
    static ClientActionRequest request(ActionRegistry registry,Boolean optIn) {
        var b=BoundedEncounterTest.request();b.addProperty("expected_action_session",registry.session);
        if(optIn!=null)b.addProperty(EncounterRequest.PAUSE_ON_TERMINAL,optIn);
        return ClientActionRequest.parse(b);
    }
    @Test void explicitOptInPausesSynchronouslyAfterActualCleanupAndTerminalRecord() {
        var registry=new ActionRegistry();var entry=registry.begin(request(registry,true));
        registry.finishAfterCleanup("failed","retreat_budget_risk_remaining",true);
        var calls=new AtomicInteger();
        EncounterTerminalPause.afterTerminal(entry,registry.session,binding->{
            calls.incrementAndGet();assertNull(registry.active());
            var saved=registry.status(entry.request.id());
            assertEquals("failed",saved.get("status").getAsString());
            assertTrue(saved.getAsJsonObject("result").get("input_release_confirmed").getAsBoolean());
            assertEquals(entry.request.id(),binding.actionId());assertEquals(registry.session,binding.session());
            return reply();
        });
        assertEquals(1,calls.get());assertEquals("failed",entry.status);
        assertEquals("retreat_budget_risk_remaining",entry.reason);
        var e=entry.result.getAsJsonObject(EncounterTerminalPause.EVIDENCE);
        assertEquals("screen_installed",e.get("outcome").getAsString());
        assertFalse(e.get("client_paused_observed").getAsBoolean());
        assertFalse(e.get("pause_effect_confirmed").getAsBoolean());
    }
    @Test void absentAndFalseOptInKeepOldNoaiTerminalPathUntouched() {
        for(Boolean opt:new Boolean[]{null,false}) {
            var registry=new ActionRegistry();var entry=registry.begin(request(registry,opt));
            registry.finishAfterCleanup("cancelled","old_reason",true);
            EncounterTerminalPause.afterTerminal(entry,registry.session,b->{throw new AssertionError("No opt-in");});
            assertFalse(entry.result.has(EncounterTerminalPause.EVIDENCE));assertEquals("old_reason",entry.reason);
        }
    }
    @Test void failedOrUnknownHookNeverRewritesOriginalTerminalOrRetries() {
        for(boolean rejected:List.of(false,true)) {
            var registry=new ActionRegistry();var entry=registry.begin(request(registry,true));
            registry.finishAfterCleanup("succeeded","encounter_clearance_observed",true);
            var calls=new AtomicInteger();
            EncounterTerminalPause.afterTerminal(entry,registry.session,b->{calls.incrementAndGet();
                if(rejected)throw new ClientActionRequest.Rejected(409,"action_world_changed");
                throw new IllegalStateException("pause_outcome_unknown");});
            EncounterTerminalPause.afterTerminal(entry,registry.session,b->{calls.incrementAndGet();return reply();});
            assertEquals(1,calls.get());assertEquals("succeeded",entry.status);
            assertEquals("encounter_clearance_observed",entry.reason);
            var e=entry.result.getAsJsonObject(EncounterTerminalPause.EVIDENCE);
            assertEquals(rejected?"rejected":"unconfirmed",e.get("outcome").getAsString());
            assertTrue(e.get("pause_screen_installed").isJsonNull());
            assertTrue(e.get("input_release_confirmed").getAsBoolean());
        }
    }
    @Test void cleanupFailureIsRetainedWhileNativePauseIsStillAttempted() {
        var registry=new ActionRegistry();var entry=registry.begin(request(registry,true));
        registry.finishAfterCleanup("succeeded","encounter_clearance_observed",false);
        EncounterTerminalPause.afterTerminal(entry,registry.session,b->{
            assertEquals("failed",entry.status);assertEquals("input_release_unconfirmed",entry.reason);return reply();});
        assertEquals("failed",entry.status);assertEquals("input_release_unconfirmed",entry.reason);
        assertFalse(entry.result.getAsJsonObject(EncounterTerminalPause.EVIDENCE).get("input_release_confirmed").getAsBoolean());
    }
    @Test void hookFailureCannotFinishAReentrantNewOwner() {
        var registry=new ActionRegistry();var entry=registry.begin(request(registry,true));
        registry.finishAfterCleanup("failed","old_terminal",true);
        EncounterTerminalPause.afterTerminal(entry,registry.session,b->{
            var next=BoundedCombatTest.body();next.addProperty("action_id","new-owner");
            registry.begin(ClientActionRequest.parse(next));throw new IllegalStateException("screen_hook_changed_owner");});
        assertEquals("new-owner",registry.active().request.id());assertTrue(registry.active().running());
        assertEquals("failed",entry.status);assertEquals("old_terminal",entry.reason);
    }
    @Test void hookCannotRunBeforeTerminalCleanupWasRecorded() {
        var registry=new ActionRegistry();var entry=registry.begin(request(registry,true));
        EncounterTerminalPause.afterTerminal(entry,registry.session,b->{throw new AssertionError("Still running");});
        assertTrue(entry.running());assertFalse(entry.result.getAsJsonObject(EncounterTerminalPause.EVIDENCE).get("pause_call_attempted").getAsBoolean());
    }
    @Test void nativeRequestFlagIsBooleanScopedAndEchoedOnlyWhenTrue() {
        for(String value:List.of("true","1","")) {
            var b=BoundedEncounterTest.request();b.addProperty(EncounterRequest.PAUSE_ON_TERMINAL,value);
            assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(b));
        }
        var hidden=BoundedCombatTest.body();hidden.addProperty(EncounterRequest.PAUSE_ON_TERMINAL,false);
        assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(hidden));
        var registry=new ActionRegistry();var parsed=EncounterRequest.parseOptional(request(registry,true).original());
        var root=new JsonObject();new BoundedEncounter(parsed,root,0,64,0,30_000_000_000L,()->1L,new CombatThreats.HealthGuard());
        assertTrue(root.getAsJsonObject("encounter").get(EncounterRequest.PAUSE_ON_TERMINAL).getAsBoolean());
    }
    @Test void productionFinishAndAdmissionWireTheHookAtRequiredBoundaries() throws Exception {
        var project=Path.of(System.getProperty("mineclientBridge.projectDir"));
        var source=Files.readString(project.resolve("src/main/java/io/github/campione01/mineclientbridge/ClientActions.java"));
        assertTrue(source.indexOf("BridgeServer.requireEncounterPauseAdmission()")<source.indexOf("BridgeServer.releaseAllInputs()"));
        int finish=source.indexOf("private static void finish(String status");
        assertTrue(source.indexOf("ACTIONS.finishAfterCleanup(status, reason, released)",finish)
                <source.indexOf("EncounterTerminalPause.afterTerminal",finish));
        assertTrue(source.contains("BridgeServer::pauseEncounterTerminalOnGameThread"));
    }
}

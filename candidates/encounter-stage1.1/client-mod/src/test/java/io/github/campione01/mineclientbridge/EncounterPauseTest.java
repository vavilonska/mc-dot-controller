package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.util.List;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class EncounterPauseTest {
    static final String SESSION="00000000-0000-4000-8000-000000000011";
    static final String WORLD="00000000-0000-4000-8000-000000000012";
    static final String PLAYER="00000000-0000-4000-8000-000000000013";
    static final String ID="registered-encounter";
    static JsonObject body() {
        var b=new JsonObject();b.addProperty("pause_schema_version",1);
        b.addProperty("expected_action_session",SESSION);b.addProperty("expected_world_generation",WORLD);
        b.addProperty("expected_player_uuid",PLAYER);b.addProperty("expected_action_id",ID);return b;
    }
    static JsonObject action(String status) {
        var a=new JsonObject();a.addProperty("action_id",ID);a.addProperty("action_session",SESSION);
        a.addProperty("action","combat_entity");a.addProperty("status",status);a.addProperty("reason","original_reason");
        var result=new JsonObject();result.addProperty("world_generation",WORLD);
        if(!status.equals("running")) result.addProperty("input_release_confirmed",true);
        var combat=new JsonObject();var encounter=new JsonObject();encounter.addProperty("encounter_mode",EncounterRequest.MODE);
        encounter.add("encounter_scope",BoundedEncounterTest.request().get("encounter_scope"));
        combat.add("encounter",encounter);result.add("combat",combat);a.add("result",result);return a;
    }
    static class Fake implements EncounterPause.Adapter {
        boolean local=true,guarded,installed,paused,installWorks=true,throwAfterOpen,rejectAfterOpen,foreignOnOpen,worldOnOpen;
        String session=SESSION,world=WORLD,player=PLAYER,screen;
        JsonObject expected=EncounterPauseTest.action("running"),current=expected;
        int opens,cancels;
        public EncounterPause.Context context(String id) { return new EncounterPause.Context(local,session,world,player,guarded,screen,current,expected); }
        public void openPauseScreen() { opens++;if(throwAfterOpen)throw new IllegalStateException("synthetic_unknown");
            if(installWorks) { installed=true;screen=EncounterPause.PAUSE_SCREEN; }
            if(foreignOnOpen) { current=expected.deepCopy();current.addProperty("action_id","new_foreign_owner"); }
            if(worldOnOpen) world=SESSION;
            if(rejectAfterOpen) throw new ClientActionRequest.Rejected(409,"synthetic_late_rejection"); }
        public boolean pauseScreenInstalled() { return installed; }
        public boolean clientPaused() { return paused; }
        public void cancelEncounter() { cancels++;expected.addProperty("status","cancelled");
            expected.addProperty("reason","encounter_paused_risk_remaining");expected.getAsJsonObject("result").addProperty("input_release_confirmed",true); }
        public JsonObject action(String id) { return expected.deepCopy(); }
        JsonObject run() { return EncounterPause.apply(EncounterPause.parse(body()),this); }
    }
    @Test void matchingRunningEncounterPausesAndReleasesWithoutClaimingPropagation() {
        var f=new Fake();var answer=f.run();assertEquals(1,f.opens);assertEquals(1,f.cancels);
        assertTrue(answer.get("pause_screen_installed").getAsBoolean());
        assertFalse(answer.get("client_paused_observed").getAsBoolean());
        assertFalse(answer.get("pause_effect_confirmed").getAsBoolean());
        assertFalse(answer.get("server_confirmed").getAsBoolean());
        assertTrue(answer.get("input_release_confirmed").getAsBoolean());
        assertEquals("encounter_paused_risk_remaining",answer.getAsJsonObject("client_action").get("reason").getAsString());
    }
    @Test void repeatedApplicationNeverTogglesOrOverwritesTerminal() {
        var f=new Fake();f.run();var terminal=f.expected.deepCopy();f.paused=true;
        var answer=f.run();assertEquals(1,f.opens);assertEquals(1,f.cancels);
        assertTrue(answer.get("already_pause_screen").getAsBoolean());assertTrue(answer.get("client_paused_observed").getAsBoolean());
        assertEquals(terminal,answer.getAsJsonObject("client_action"));
    }
    @Test void knownTerminalIsPreservedAndMissingActionNeverBecomesAdmissionProof() {
        for(String status:List.of("failed","cancelled","succeeded")) {
            var f=new Fake();f.expected=action(status);f.current=f.expected;
            var before=f.expected.deepCopy();var answer=f.run();assertEquals(before,answer.getAsJsonObject("client_action"));assertEquals(0,f.cancels);
        }
        var f=new Fake();f.expected=null;f.current=action("failed");f.current.addProperty("action_id","unrelated_old_terminal");
        var answer=f.run();assertTrue(answer.get("client_action").isJsonNull());
        assertTrue(answer.get("input_release_confirmed").isJsonNull());assertFalse(answer.get("expected_action_present").getAsBoolean());
        assertEquals(1,f.opens);assertEquals(0,f.cancels);
    }
    @Test void allContextRefusalsPrecedeScreenOrInputMutation() {
        for(int i=0;i<8;i++) {
            var f=new Fake();
            switch(i) {case 0->f.local=false;case 1->f.session=WORLD;case 2->f.world=SESSION;case 3->f.player=WORLD;
                case 4->f.guarded=true;case 5->f.screen="some.other.Screen";
                case 6->{f.current=f.expected.deepCopy();f.current.addProperty("action_id","foreign");}
                case 7->f.expected.getAsJsonObject("result").getAsJsonObject("combat").getAsJsonObject("encounter").addProperty("encounter_mode","other");}
            var failure=assertThrows(ClientActionRequest.Rejected.class,f::run);assertEquals(409,failure.httpStatus);
            assertEquals(0,f.opens);assertEquals(0,f.cancels);
        }
    }
    @Test void failedOrThrowingScreenInstallationIsUnknownAndNeverRetriedInternally() {
        for(boolean throwing:List.of(false,true)) {
            var f=new Fake();f.installWorks=false;f.throwAfterOpen=throwing;
            assertThrows(IllegalStateException.class,f::run);assertEquals(1,f.opens);assertEquals(0,f.cancels);
        }
    }
    @Test void strictRequestCannotCarryAnotherCommandOrInvalidBinding() {
        for(String key:List.of("pause_schema_version","expected_action_session","expected_world_generation","expected_player_uuid","expected_action_id")) {
            var b=body();b.remove(key);assertThrows(ClientActionRequest.Rejected.class,()->EncounterPause.parse(b));
        }
        var b=body();b.addProperty("command","anything");assertThrows(ClientActionRequest.Rejected.class,()->EncounterPause.parse(b));
        var bad=body();bad.addProperty("expected_action_id","");assertThrows(ClientActionRequest.Rejected.class,()->EncounterPause.parse(bad));
        var bool=body();bool.addProperty("pause_schema_version",true);assertThrows(ClientActionRequest.Rejected.class,()->EncounterPause.parse(bool));
    }
    @Test void lateRejectedAfterScreenMutationIsUnknownNotDefiniteRejection() {
        var f=new Fake();f.rejectAfterOpen=true;
        var failure=assertThrows(IllegalStateException.class,f::run);
        assertInstanceOf(ClientActionRequest.Rejected.class,failure.getCause());
        assertEquals(1,f.opens);assertEquals(0,f.cancels);assertTrue(f.installed);
    }
    @Test void reentrantScreenHookCannotMakePauseCancelANewForeignOwner() {
        for(boolean changeWorld:List.of(false,true)) {
            var f=new Fake();f.foreignOnOpen=!changeWorld;f.worldOnOpen=changeWorld;
            assertThrows(IllegalStateException.class,f::run);
            assertEquals(1,f.opens);assertEquals(0,f.cancels);
            if(!changeWorld) assertEquals("new_foreign_owner",f.current.get("action_id").getAsString());
        }
    }
    @Test void priorUnknownTerminalHookCannotBeReopenedByHttpPause() {
        var f=new Fake();f.expected=action("failed");f.current=f.expected;
        var hook=new JsonObject();hook.addProperty("attempted",true);hook.addProperty("outcome","unconfirmed");
        f.expected.getAsJsonObject("result").add(EncounterTerminalPause.EVIDENCE,hook);
        var failure=assertThrows(ClientActionRequest.Rejected.class,f::run);
        assertEquals("pause_prior_terminal_attempt_no_retry",failure.getMessage());assertEquals(0,f.opens);
        f.screen=EncounterPause.PAUSE_SCREEN;f.installed=true;
        assertTrue(f.run().get("already_pause_screen").getAsBoolean());assertEquals(0,f.opens);
        assertEquals("unconfirmed",hook.get("outcome").getAsString());
    }
}

package io.github.campione01.mineclientbridge;

import static org.junit.jupiter.api.Assertions.*;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Set;
import org.junit.jupiter.api.Test;

/** Mainline cross-action parser and source-wiring contracts; no game is launched. */
class MainlineCombatSliceTest {
    private String source(String name) throws Exception {
        return Files.readString(Path.of(System.getProperty("mineclientBridge.projectDir"),
                "src/main/java/io/github/campione01/mineclientbridge",name+".java"));
    }
    private String region(String source,String first,String end) {
        int begin=source.indexOf(first),last=source.indexOf(end,begin);
        assertTrue(begin>=0 && last>begin,first);return source.substring(begin,last);
    }
    @Test void exactMainEightPlusCombatRetainsRecoveryZeroLifetime() {
        assertEquals(Set.of("follow_path","break_block","place_block","click_slot","recover_environment",
                "boat_drive","boat_mount","boat_dismount","combat_entity"),ClientActionRequest.LEGACY_ACTIONS);
        var recovery=JsonParser.parseString("{\"action\":\"recover_environment\",\"action_id\":\"recover\",\"waypoints\":[]}").getAsJsonObject();
        assertEquals(0,ClientActionRequest.parse(recovery).timeoutMs());
        recovery.addProperty("timeout_ms",0);assertEquals(0,ClientActionRequest.parse(recovery).timeoutMs());
        var combat=BoundedCombatTest.body();combat.addProperty("timeout_ms",0);
        assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(combat));
    }
    @Test void malformedCombatOrEncounterNeverReplacesLegacyOwner() {
        for(String field:new String[]{"target_uuid","target_type","expected_action_session"}) {
            var registry=new ActionRegistry();
            var owner=registry.begin(ClientActionRequest.parse(JsonParser.parseString(
                    "{\"action\":\"recover_environment\",\"action_id\":\"old\",\"waypoints\":[]}").getAsJsonObject()));
            var combat=BoundedCombatTest.body();combat.addProperty(field,"invalid");
            assertThrows(ClientActionRequest.Rejected.class,()->registry.begin(ClientActionRequest.parse(combat)));
            assertSame(owner,registry.active());assertTrue(owner.running());
        }
    }
    @Test void encounterFieldsAreNotAcceptedByOtherActionsEvenWhenPauseFalse() {
        for(String key:new String[]{"encounter_mode","encounter_scope",EncounterRequest.PAUSE_ON_TERMINAL}) {
            var recovery=JsonParser.parseString("{\"action\":\"recover_environment\",\"action_id\":\"old\",\"waypoints\":[]}").getAsJsonObject();
            recovery.addProperty(key,false);
            assertEquals("encounter_requires_combat_entity",assertThrows(ClientActionRequest.Rejected.class,
                    ()->ClientActionRequest.parse(recovery)).getMessage());
        }
    }
    @Test void combatAdmissionIsBeforeTakeoverWhileOldDeadlineStaysAfterTakeover() throws Exception {
        String s=source("ClientActions"),start=region(s,"    static JsonObject start(","    static JsonObject status(");
        int takeover=start.indexOf("BridgeServer.releaseAllInputs()"),begin=start.indexOf("ACTIONS.begin(request)");
        assertTrue(takeover>=0 && begin>takeover);
        for(String gate:new String[]{"ACTIONS.existing(request)","if (active != null) throw",
                "NavigationPositionGuard.requireBinding(mc, request)","!EncounterRequest.runtimeEnabled(encounterRequest.mode())",
                "BridgeServer.requireEncounterPauseAdmission()","new BoundedCombat("})
            assertTrue(start.indexOf(gate)>=0 && start.indexOf(gate)<takeover,gate);
        assertTrue(start.contains("long combatDeadline = request.action().equals(\"combat_entity\")\n                ? System.nanoTime()+request.timeoutMs()*1_000_000L : 0;"));
        assertFalse(start.contains("long deadline="));
        String constructor=region(s,"        RuntimeAction(","    static synchronized void install()");
        assertTrue(constructor.contains("deadline = combat != null ? combatDeadline : entry.request.timeoutMs() == 0 ? Long.MAX_VALUE\n                    : System.nanoTime() + entry.request.timeoutMs() * 1_000_000L;"));
    }
    @Test void oldBindingErrorsArePreservedAndCombatKeepsItsOwnErrors() throws Exception {
        String s=source("ClientActions");
        assertTrue(s.contains("? \"action_world_changed\" : \"world_generation_changed\""));
        assertTrue(s.contains("? \"action_player_changed\" : \"player_changed\""));
        assertTrue(s.contains("\"action_session_changed\""));
    }
    @Test void onlyManagedOwnersGetNewCleanupAndOnlyCombatGetsTerminalHook() throws Exception {
        String finish=region(source("ClientActions"),"    private static void finish(","    static boolean releaseDiscontinuousAttack(");
        assertTrue(finish.contains("boolean managedCleanup = pathAction || a.boat != null || a.transfer != null || discontinuityCleanup || a.combat != null;"));
        assertTrue(finish.indexOf("if (!managedCleanup) ACTIONS.finish(status, reason)")<finish.indexOf("a.input.forwardImpulse"));
        int managed=finish.indexOf("if (managedCleanup) {"),release=finish.indexOf("a.combat.release(Minecraft.getInstance())");
        int combatTerminal=finish.indexOf("a.combat.terminal(released?status:\"failed\",released?reason:\"input_release_unconfirmed\")");
        int terminal=finish.indexOf("ACTIONS.finishAfterCleanup(status, reason, released)"),hook=finish.indexOf("EncounterTerminalPause.afterTerminal");
        assertTrue(managed>=0 && release>managed && combatTerminal>release && terminal>combatTerminal && hook>terminal);
        assertTrue(finish.contains("if (a.combat != null)\n                EncounterTerminalPause.afterTerminal"));
        assertTrue(finish.contains("releaseDiscontinuousAttack("));
    }
    @Test void allThreeCallbacksKeepEpochGuardBeforeEncounterMotion() throws Exception {
        String s=source("ClientActions"),context=region(s,"    private static boolean context(","    private static void preTick()");
        int epoch=context.indexOf("active.navigationEpoch != NavigationPositionGuard.epoch()");
        int encounter=context.indexOf("active.combat!=null && active.combat.isEncounter()");
        assertTrue(epoch>=0 && encounter>epoch);
        assertTrue(context.contains("BoundedEncounter.lifecycle(mc.isPaused(),mc.isWindowActive(),mc.player.isSpectator())"));
        assertTrue(context.contains("active.combat.encounterCallbackInterruption(System.nanoTime(),phase)"));
        for(String call:new String[]{"context(mc,\"pre_tick\")","context(Minecraft.getInstance(),\"movement_input\")","context(mc,\"post_tick\")"})
            assertTrue(s.contains(call),call);
    }
    @Test void advertisedCombatObservationFieldsAreActuallyEmittedAdditively() throws Exception {
        String s=source("BridgeServer");
        assertEquals(2,s.split("combat_observation_schema_version",-1).length-1);
        for(String field:new String[]{"sprinting","attack_strength","attack_speed","entity_interaction_range",
                "using_item","blocking","use_ticks","shield_cooldown"})
            assertTrue(s.contains("player.addProperty(\""+field+"\""),field);
        for(String field:new String[]{"hurt_time","using_item","use_ticks"})
            assertTrue(s.contains("entityJson.addProperty(\""+field+"\""),field);
        assertTrue(s.contains("entityJson.add(\"mainhand\", itemSnapshot(living.getMainHandItem()))"));
        for(String field:new String[]{"environment_schema_version","in_water","eye_in_water","in_lava","in_powder_snow","frozen_ticks","on_fire","fire_ticks"})
            assertTrue(s.contains("player.addProperty(\""+field+"\""),field);
        assertTrue(s.contains("player.add(\"bounding_box\", playerBox)"));
    }
    @Test void originalTwoZombieModeStaysExactAndThreeModeHasIndependentGate() throws Exception {
        assertEquals("two_zombie_retreat_v1",EncounterRequest.MODE);
        var body=BoundedEncounterTest.request();
        body.getAsJsonArray("encounter_scope").add(body.getAsJsonArray("encounter_scope").get(0).deepCopy());
        assertEquals("encounter_requires_two_zombies",assertThrows(ClientActionRequest.Rejected.class,
                ()->ClientActionRequest.parse(body)).getMessage());
        assertTrue(source("ClientActionRequest").contains("CoordinationStepGuard.validate(request)"));
        assertTrue(source("ClientActions").contains("EncounterRequest.THREE_MODE.equals(encounterRequest.mode())"));
        assertTrue(source("BridgeServer").contains("BoundedContainerSnapshot.append"));
    }
}

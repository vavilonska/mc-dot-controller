package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class MainlinePositionBindingTest {
    JsonObject request() {
        return JsonParser.parseString("{\"action_id\":\"guard-test\",\"action\":\"follow_path\",\"waypoints\":[{\"x\":1.5,\"y\":64,\"z\":0.5}]}").getAsJsonObject();
    }
    JsonObject pair() {
        JsonObject r=request();r.addProperty("expected_navigation_epoch",0);
        r.add("expected_origin",JsonParser.parseString("{\"x\":0.5,\"y\":64,\"z\":0.5}"));return r;
    }
    @Test void partialPairsRejectBeforeAnyNativeObservation() {
        JsonObject origin=pair();origin.remove("expected_navigation_epoch");
        JsonObject epoch=pair();epoch.remove("expected_origin");
        for(JsonObject r:new JsonObject[]{origin,epoch}) {
            var rejected=assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(r));
            assertEquals(400,rejected.httpStatus);assertEquals("navigation_binding_pair_required",rejected.getMessage());
        }
    }
    @Test void malformedExplicitPairsAre400EvenWhenGuardWouldBeUnready() {
        for(String v:new String[]{"true","null","\"0\"","0.5","-1","9007199254740992"}) {
            var r=pair();r.add("expected_navigation_epoch",JsonParser.parseString(v));
            assertEquals(400,assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(r)).httpStatus);
        }
        for(String v:new String[]{"null","{}","{\"x\":true,\"y\":64,\"z\":0}","{\"x\":0,\"y\":64,\"z\":\"0\"}"}) {
            var r=pair();r.add("expected_origin",JsonParser.parseString(v));
            assertEquals(400,assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(r)).httpStatus);
        }
    }
    @Test void exactPairAndLegacyRemainAvailable() {
        ClientActionRequest.parse(request());
        var r=pair();var parsed=ClientActionRequest.parse(r);
        assertEquals(r,parsed.original());
        var g=new PositionDiscontinuityGuard();Object w=new Object(),p=new Object();
        for(int t=1;t<=3;t++)g.sample(w,p,new PositionDiscontinuityGuard.Sample(.5,64,.5,0,0,0,true,true,true,false),t);
        g.requireBinding(parsed.original());
        r.addProperty("expected_navigation_epoch",1);
        assertEquals("navigation_epoch_changed",assertThrows(ClientActionRequest.Rejected.class,()->g.requireBinding(r)).getMessage());
    }
    @Test void onlyGuardedLandAndCombatActionsRequireBinding() {
        for(String action:new String[]{"follow_path","break_block","place_block"}) assertTrue(NavigationPositionGuard.applies(action));
        for(String action:new String[]{"recover_environment","boat_drive","boat_mount","boat_dismount","click_slot","gateway_pearl"}) assertFalse(NavigationPositionGuard.applies(action));
        assertEquals(9,ClientActionRequest.LEGACY_ACTIONS.size());
        assertEquals(18,ClientActionRequest.ACTIONS.size());
        assertTrue(ClientActionRequest.ACTIONS.contains("combat_entity"));
        assertTrue(NavigationPositionGuard.applies("combat_entity"));
    }
    @Test void checksPrecedeTakeoverAndActiveEpochChecksPrecedeMovement() throws Exception {
        String s=Files.readString(Path.of(System.getProperty("mineclientBridge.projectDir"),"src/main/java/io/github/campione01/mineclientbridge/ClientActions.java"));
        int start=s.indexOf("static JsonObject start(");int takeover=s.indexOf("BridgeServer.releaseAllInputs();",start);
        assertTrue(s.indexOf("NavigationPositionGuard.requireBinding(mc, request);",start)<takeover);
        assertTrue(s.indexOf("NavigationPositionGuard.requireBinding(mc, request);",start)>start);
        assertTrue(s.contains("active.navigationEpoch != NavigationPositionGuard.epoch()"));
        assertTrue(s.contains("position_discontinuity_rebind_required"));
        String pre=s.substring(s.indexOf("private static void preTick()"),s.indexOf("private static void input("));
        assertTrue(pre.indexOf("NavigationPositionGuard.tick(mc)")<pre.indexOf("if (!context(mc,\"pre_tick\"))"));
        String server=Files.readString(Path.of(System.getProperty("mineclientBridge.projectDir"),"src/main/java/io/github/campione01/mineclientbridge/BridgeServer.java"));
        assertTrue(server.contains("world.add(\"navigation_guard\", NavigationPositionGuard.snapshot(mc))"));
    }
    @Test void eachDiscontinuityReleaseFailureAttemptsBothAndPreservesRequestedCancellation() {
        for(int failAt=0;failAt<2;failAt++) {
            final int selected=failAt;int[] calls={0,0};
            boolean released=ClientActions.releaseDiscontinuousAttack(
                ()->{calls[0]++;if(selected==0)throw new IllegalStateException("key-up");},
                ()->{calls[1]++;if(selected==1)throw new IllegalStateException("stop-destroy");});
            assertArrayEquals(new int[]{1,1},calls);assertFalse(released);
            var registry=new ActionRegistry();var entry=registry.begin(ClientActionRequest.parse(request()));
            registry.finishAfterCleanup("cancelled","position_discontinuity_rebind_required",released);
            assertEquals("failed",entry.status);assertEquals("input_release_unconfirmed",entry.reason);
            assertEquals("cancelled",entry.result.get("requested_terminal_status").getAsString());
            assertEquals("position_discontinuity_rebind_required",entry.result.get("requested_terminal_reason").getAsString());
            assertFalse(entry.result.get("input_release_confirmed").getAsBoolean());assertNull(registry.active());
        }
    }
    @Test void confirmedDiscontinuityCleanupRemainsCancelled() {
        int[] calls={0,0};boolean released=ClientActions.releaseDiscontinuousAttack(()->calls[0]++,()->calls[1]++);
        assertTrue(released);assertArrayEquals(new int[]{1,1},calls);
        var registry=new ActionRegistry();var entry=registry.begin(ClientActionRequest.parse(request()));
        registry.finishAfterCleanup("cancelled","position_discontinuity_rebind_required",released);
        assertEquals("cancelled",entry.status);assertTrue(entry.result.get("input_release_confirmed").getAsBoolean());
        assertFalse(entry.result.has("requested_terminal_status"));
    }
}

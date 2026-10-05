package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class ClientActionsTest {
    private static ClientActionRequest request(String extra) {
        return ClientActionRequest.parse(JsonParser.parseString("{\"action_id\":\"a\",\"action\":\"follow_path\",\"waypoints\":[{\"x\":1.5,\"y\":64,\"z\":2.5}]" + extra + "}").getAsJsonObject());
    }
    private static JsonObject body(String json) { return JsonParser.parseString(json).getAsJsonObject(); }
    @Test void defaultsAndCoordinates() {
        var r = request("");
        assertEquals(15000, r.timeoutMs()); assertEquals(-1, r.hotbarSlot());
        assertEquals(1.5, r.waypoints().getFirst().x()); assertFalse(r.waypoints().getFirst().jump());
    }
    @Test void validatesWireTypesWithoutWorldPolicies() {
        assertThrows(ClientActionRequest.Rejected.class, () -> request(",\"timeout_ms\":\"15000\""));
        assertThrows(ClientActionRequest.Rejected.class, () -> request(",\"hotbar_slot\":9"));
        assertThrows(ClientActionRequest.Rejected.class, () -> request(",\"jump\":\"true\""));
        assertEquals(200000, request(",\"timeout_ms\":200000").timeoutMs());
        var r = ClientActionRequest.parse(body("{\"action_id\":\"mine\",\"action\":\"break_block\",\"target\":{\"x\":-3,\"y\":64,\"z\":0}}"));
        assertEquals(-3, r.target().x());
    }
    @Test void parsesPlacementAndVanillaClickEncodings() {
        var r = ClientActionRequest.parse(body("{\"action_id\":\"p\",\"action\":\"place_block\",\"support\":{\"x\":0,\"y\":63,\"z\":0},\"face\":\"up\",\"jump\":true,\"hotbar_slot\":2}"));
        assertTrue(r.jump()); assertEquals("up", r.face()); assertEquals(2, r.hotbarSlot());
        for (String kind : new String[]{"pickup", "quick_move", "swap", "throw", "pickup_all", "quick_craft"}) {
            var click = ClientActionRequest.parse(body("{\"action_id\":\"c\",\"action\":\"click_slot\",\"container_id\":0,\"slot\":1,\"button\":0,\"click_type\":\"" + kind + "\"}"));
            assertEquals(kind, click.clickType());
        }
    }
    @Test void registryIsSingleFlightAndDeduplicatesPendingAndFinishedRequests() {
        ActionRegistry registry = new ActionRegistry();
        var r = request(""); var first = registry.begin(r);
        assertSame(first, registry.begin(r));
        var otherBody = r.original().deepCopy(); otherBody.addProperty("action_id", "b");
        assertEquals("action_busy", assertThrows(ClientActionRequest.Rejected.class,
                () -> registry.begin(ClientActionRequest.parse(otherBody))).getMessage());
        registry.finish("succeeded", "path_reached");
        assertSame(first, registry.begin(r)); assertNull(registry.active());
        assertEquals("succeeded", registry.status("a").get("status").getAsString());
        assertNotNull(registry.begin(ClientActionRequest.parse(otherBody)));
        assertEquals("succeeded", registry.status("a").get("status").getAsString());
    }
    @Test void cancelledIdsCannotReplayAndDifferentPayloadCannotReuseId() {
        ActionRegistry registry = new ActionRegistry(); registry.begin(request(""));
        registry.finish("cancelled", "direct_takeover");
        assertEquals("cancelled", registry.begin(request("")).status); assertNull(registry.active());
        assertEquals("action_id_payload_mismatch", assertThrows(ClientActionRequest.Rejected.class,
                () -> registry.begin(request(",\"timeout_ms\":1000"))).getMessage());
        assertThrows(ClientActionRequest.Rejected.class, () -> registry.get("missing"));
    }
    @Test void statusIsCopiedAndNullIdleIdSurvivesWireEncoding() throws Exception {
        ActionRegistry registry = new ActionRegistry();
        assertTrue(BridgeJson.toJson(registry.status(null)).contains("\"action_id\":null"));
        var e = registry.begin(request("")); e.result.addProperty("waypoint_index", 0);
        var s = registry.status(null); s.getAsJsonObject("result").addProperty("waypoint_index", 99);
        assertEquals(0, e.result.get("waypoint_index").getAsInt());
        assertFalse(s.get("server_confirmed").getAsBoolean());
    }
    @Test void facingAndContinuousForwardAreFullScaleOnStraightPath() {
        var goal = new ClientActionRequest.Point(0,64,8,false);
        for (int tick=0; tick<10; tick++) {
            var s=PathSteering.toward(0,64,tick*.2,0,true,false,goal);
            assertEquals(1, s.forward()); assertEquals(0,s.yaw()); assertFalse(s.reached());
        }
    }
    @Test void arbitraryTurnIsExecutedOverTicksRatherThanRejected() {
        var goal = new ClientActionRequest.Point(0,64,-8,false);
        float yaw=0;
        for(int i=0;i<4;i++) yaw=PathSteering.toward(0,64,0,yaw,true,false,goal).yaw();
        assertEquals(180,Math.abs(yaw));
        assertEquals(1,PathSteering.toward(0,64,0,yaw,true,false,goal).forward());
    }
    @Test void oneBlockRiseAndCollisionAskForNormalJump() {
        assertTrue(PathSteering.toward(0,64,0,0,true,false,new ClientActionRequest.Point(0,65,1,false)).jump());
        assertTrue(PathSteering.toward(0,64,0,0,true,true,new ClientActionRequest.Point(0,64,2,false)).jump());
        assertFalse(PathSteering.toward(0,64.7,0,0,false,true,new ClientActionRequest.Point(0,65,1,false)).jump());
        assertTrue(PathSteering.toward(0,64,0,0,true,false,new ClientActionRequest.Point(0,64,2,true)).jump());
    }
    @Test void arrivalUsesFeetCoordinatesAndDoesNotSkipVerticalStep() {
        assertFalse(PathSteering.toward(.5,64,.5,0,true,false,new ClientActionRequest.Point(.5,65,.5,false)).reached());
        assertTrue(PathSteering.toward(.5,65,.5,0,true,false,new ClientActionRequest.Point(.5,65,.5,false)).reached());
    }
    @Test void endpointsKeepOneOwnerAndNativeClientInteractions() throws Exception {
        Path src = Path.of(System.getProperty("mineclientBridge.projectDir"), "src/main/java/io/github/campione01/mineclientbridge");
        String bridge=Files.readString(src.resolve("BridgeServer.java"));
        for(String endpoint:new String[]{"action","action/status","action/cancel"})
            assertTrue(bridge.contains("requireControlAccess(exchange, \"/control/"+endpoint+"\""));
        for(String operation:new String[]{"applyKeyAction","applyRawKeyAction","applyLook","applyMouseAction","applyScreenText","applyCommand"})
            assertTrue(bridge.contains("ClientActions.directTakeover(); return "+operation));
        String actions=Files.readString(src.resolve("ClientActions.java"));
        assertTrue(actions.contains("ClientTickEvent.Pre.class"));
        assertTrue(actions.contains("MovementInputUpdateEvent.class"));
        assertTrue(actions.contains("mc.startAttack()"));
        assertTrue(actions.contains("mc.gameMode.useItemOn("));
        assertTrue(actions.contains("mc.gameMode.handleInventoryMouseClick("));
        assertTrue(actions.contains("mc.gameRenderer.pick(1.0F)"));
        for(String forbidden:new String[]{"hasSingleplayerServer", "getHealth()", "getActiveEffects()", "setPos(", "setDeltaMovement(", "sendPacket", "disconnect("})
            assertFalse(actions.contains(forbidden), forbidden);
    }
}

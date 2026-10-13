package io.github.campione01.mineclientbridge;

import static org.junit.jupiter.api.Assertions.*;
import com.google.gson.*;
import java.nio.file.*;
import org.junit.jupiter.api.Test;

/** Cross-feature source/parser checks; these do not execute Minecraft or prove a safe landing. */
class MainlineBoatSliceTest {
    private String source(String name) throws Exception {
        return Files.readString(Path.of(System.getProperty("mineclientBridge.projectDir"),
                "src/main/java/io/github/campione01/mineclientbridge",name));
    }
    @Test void malformedBoatRequestCannotReplaceExistingPathOwner() {
        var registry=new ActionRegistry();
        var path=JsonParser.parseString("{\"action_id\":\"old-path\",\"action\":\"follow_path\",\"waypoints\":[{\"x\":0,\"y\":64,\"z\":1}]}").getAsJsonObject();
        var active=registry.begin(ClientActionRequest.parse(path));
        var boat=BoatDriveRequestTest.body();boat.addProperty("timeout_ms",0);
        assertThrows(ClientActionRequest.Rejected.class,()->registry.begin(ClientActionRequest.parse(boat)));
        assertSame(active,registry.active());assertEquals("running",active.status);
    }
    @Test void routeRequestKindsCannotBorrowEachOthersCoordinateContract() {
        var boat=BoatDriveRequestTest.body();boat.getAsJsonArray("waypoints").get(0).getAsJsonObject().addProperty("y",64);
        assertEquals("boat_waypoint_requires_only_x_z",assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(boat)).getMessage());
        var path=JsonParser.parseString("{\"action_id\":\"path\",\"action\":\"follow_path\",\"waypoints\":[{\"x\":0,\"z\":1}]}").getAsJsonObject();
        assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(path));
    }
    @Test void boatCannotUsePathSprintOrHotbarSideChannels() {
        for(String field:new String[]{"sprint","hotbar_slot","jump"}) {
            var body=BoatDriveRequestTest.body();
            if(field.equals("hotbar_slot")) body.addProperty(field,1); else body.addProperty(field,true);
            assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(body),field);
        }
    }
    @Test void newBoatRequestsAreValidatedBeforeInputTakeoverOrRegistryBegin() throws Exception {
        String s=source("ClientActions.java");String start=s.substring(s.indexOf("static JsonObject start("),s.indexOf("static JsonObject status("));
        int drive=start.indexOf("new BoundedBoatDrive("),transfer=start.indexOf("new BoundedBoatTransfer(");
        int release=start.indexOf("BridgeServer.releaseAllInputs()"),begin=start.indexOf("ACTIONS.begin(request)");
        assertTrue(drive>=0 && transfer>=0 && drive<release && transfer<release && release<begin);
        assertTrue(start.indexOf("ACTIONS.existing(request)")<drive);
    }
    @Test void originalPlayerEnvironmentAndBoundingBoxObservationsRemainPresent() throws Exception {
        String s=source("BridgeServer.java");
        for(String field:new String[]{"environment_schema_version","in_water","eye_in_water","in_lava",
                "in_powder_snow","frozen_ticks","on_fire","fire_ticks","bounding_box"})
            assertTrue(s.contains("\""+field+"\""),field);
        assertTrue(s.contains("playerBox.add(\"min\""));assertTrue(s.contains("playerBox.add(\"max\""));
        assertTrue(s.contains("player.add(\"vehicle\", BoatObservation.snapshot(mc))"));
    }
    @Test void boatSchemaCoexistsWithExplicitCombatAndPauseExtension() throws Exception {
        assertTrue(ClientActionRequest.ACTIONS.contains("combat_entity"));
        String bridge=source("BridgeServer.java"),actions=source("ClientActions.java");
        assertTrue(bridge.contains("createContext(\"/control/pause\""));
        assertTrue(actions.contains("NavigationPositionGuard"));assertTrue(actions.contains("BoundedEncounter"));
        assertTrue(bridge.contains("boatTransfer.addProperty(\"private_singleplayer_only\", true)"));
        assertTrue(bridge.contains("boatTransfer.addProperty(\"max_sneak_ticks\", 10)"));
    }
    @Test void optionalCancelSessionIsCheckedWithoutRemovingLegacyCancel() throws Exception {
        String bridge=source("BridgeServer.java"),actions=source("ClientActions.java");
        assertTrue(bridge.contains("expectedSession = body.has(\"expected_action_session\")"));
        assertTrue(bridge.contains("ClientActions.cancelId(id, expectedSession)"));
        assertTrue(actions.contains("static JsonObject cancelId(String id)"));
        String bound=actions.substring(actions.indexOf("static JsonObject cancelId(String id, String expectedSession)"),
                actions.indexOf("static JsonObject cancelId(String id)"));
        assertTrue(bound.indexOf("!ACTIONS.session.equals(expectedSession)")<bound.indexOf("return cancelId(id)"));
    }
    @Test void boatReleaseFailureNeverPublishesSuccessOrSettlement() {
        var registry=new ActionRegistry();var entry=registry.begin(ClientActionRequest.parse(BoatDriveRequestTest.body()));
        registry.finishAfterCleanup("succeeded","boat_settled_at_endpoint",false);
        assertEquals("failed",entry.status);assertEquals("input_release_unconfirmed",entry.reason);
        assertEquals("succeeded",entry.result.get("requested_terminal_status").getAsString());
        assertFalse(entry.result.get("input_release_confirmed").getAsBoolean());
        assertFalse(entry.result.has("boat_settled"));
    }
    @Test void mainLegacyActionsRemainOutsideNewBoatCleanup() throws Exception {
        String actions=source("ClientActions.java");
        assertTrue(actions.contains("boolean managedCleanup = pathAction || a.boat != null || a.transfer != null"));
        assertTrue(actions.contains("if (!managedCleanup) ACTIONS.finish(status, reason)"));
        assertTrue(actions.contains("case \"recover_environment\" -> recoverEnvironment(mc, a)"));
        assertTrue(actions.contains("entry.request.timeoutMs() == 0 ? Long.MAX_VALUE"));
        assertTrue(actions.contains("a.placedStableTicks >= 5 && consumed"));
    }
}

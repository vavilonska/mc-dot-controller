package io.github.campione01.mineclientbridge;

import static org.junit.jupiter.api.Assertions.*;
import com.google.gson.JsonObject;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;

class AimViewGuardTest {
    private static final String WORLD = "11111111-1111-4111-8111-111111111111";
    private static final String PLAYER = "22222222-2222-4222-8222-222222222222";
    private static final String SESSION = "33333333-3333-4333-8333-333333333333";
    private static final String TARGET = "44444444-4444-4444-8444-444444444444";

    private JsonObject body() {
        JsonObject value = new JsonObject();
        value.addProperty("schema_version", 1);
        value.addProperty("expected_world_generation", WORLD);
        value.addProperty("expected_player_uuid", PLAYER);
        value.addProperty("expected_action_session", SESSION);
        value.addProperty("expected_game_time", 100);
        value.addProperty("expected_yaw", 180);
        value.addProperty("expected_pitch", 0);
        value.addProperty("target_entity_id", 4);
        value.addProperty("target_uuid", TARGET);
        return value;
    }

    @Test void validObservationAndEquivalentWrappedViewAdmit() {
        AimViewGuard guard = AimViewGuard.parse(body());
        assertNull(guard.rejection(WORLD, PLAYER, SESSION, 102, -180, 0, TARGET, true));
        assertEquals(4, guard.entityId());
    }
    @Test void physicalOrExternalViewChangeRejectsBeforeApply() {
        AimViewGuard guard = AimViewGuard.parse(body());
        assertEquals("manual_view_changed", guard.rejection(WORLD, PLAYER, SESSION, 102, -179.9, 0, TARGET, true));
        assertEquals("manual_view_changed", guard.rejection(WORLD, PLAYER, SESSION, 102, 180, 0.1, TARGET, true));
        assertEquals("manual_view_changed", guard.rejection(WORLD, PLAYER, SESSION, 102, Double.NaN, 0, TARGET, true));
    }
    @Test void targetRemovalDeathAndIdReuseReject() {
        AimViewGuard guard = AimViewGuard.parse(body());
        assertEquals("target_missing", guard.rejection(WORLD, PLAYER, SESSION, 102, 180, 0, null, false));
        assertEquals("target_missing", guard.rejection(WORLD, PLAYER, SESSION, 102, 180, 0, PLAYER, true));
        assertEquals("target_dead", guard.rejection(WORLD, PLAYER, SESSION, 102, 180, 0, TARGET, false));
    }
    @Test void restartAndWorldAndPlayerChangesReject() {
        AimViewGuard guard = AimViewGuard.parse(body());
        assertEquals("bridge_session_changed", guard.rejection(WORLD, PLAYER, WORLD, 102, 180, 0, TARGET, true));
        assertEquals("world_changed", guard.rejection(PLAYER, PLAYER, SESSION, 102, 180, 0, TARGET, true));
        assertEquals("player_changed", guard.rejection(WORLD, WORLD, SESSION, 102, 180, 0, TARGET, true));
    }
    @Test void staleAndFutureSnapshotsReject() {
        AimViewGuard guard = AimViewGuard.parse(body());
        assertEquals("stale_aim_observation", guard.rejection(WORLD, PLAYER, SESSION, 106, 180, 0, TARGET, true));
        assertEquals("stale_aim_observation", guard.rejection(WORLD, PLAYER, SESSION, 99, 180, 0, TARGET, true));
    }
    @Test void schemaMissingExtraAndMalformedFieldsReject() {
        JsonObject value = body();
        value.addProperty("schema_version", 2);
        assertThrows(ClientActionRequest.Rejected.class, () -> AimViewGuard.parse(value));
        value.addProperty("schema_version", 1);
        value.addProperty("unexpected", true);
        assertThrows(ClientActionRequest.Rejected.class, () -> AimViewGuard.parse(value));
        value.remove("unexpected");
        value.remove("target_uuid");
        assertThrows(ClientActionRequest.Rejected.class, () -> AimViewGuard.parse(value));
        value.addProperty("target_uuid", "wrong");
        assertThrows(ClientActionRequest.Rejected.class, () -> AimViewGuard.parse(value));
    }
    @Test void nonfiniteAndFractionalValuesReject() {
        JsonObject value = body();
        value.addProperty("expected_yaw", Double.NaN);
        assertThrows(ClientActionRequest.Rejected.class, () -> AimViewGuard.parse(value));
        value.addProperty("expected_yaw", 180);
        value.addProperty("expected_game_time", 100.5);
        assertThrows(ClientActionRequest.Rejected.class, () -> AimViewGuard.parse(value));
        value.addProperty("expected_game_time", "100");
        assertThrows(ClientActionRequest.Rejected.class, () -> AimViewGuard.parse(value));
        value.addProperty("expected_game_time", 100);
        value.addProperty("target_entity_id", 2147483648L);
        assertThrows(ClientActionRequest.Rejected.class, () -> AimViewGuard.parse(value));
    }
    @Test void guardedAdapterDoesNotTakeOverOrReleaseDirectKeys() throws Exception {
        Path project = Path.of(System.getProperty("mineclientBridge.projectDir"));
        String source = Files.readString(project.resolve("src/main/java/io/github/campione01/mineclientbridge/BridgeServer.java"));
        String adapter = source.substring(source.indexOf("private static EndpointResult applyGuardedAimLook("),
                source.indexOf("private static EndpointResult applyLook("));
        assertFalse(adapter.contains("directTakeover"));
        assertFalse(adapter.contains("releaseAll"));
        assertFalse(adapter.contains("setKey"));
        assertTrue(adapter.contains("ClientActions.ownsInput()"));
        assertTrue(adapter.contains("mc.screen != null"));
        assertTrue(adapter.contains("!mc.player.isAlive()"));
        assertTrue(adapter.indexOf("guard.rejection(") < adapter.indexOf("applyLook(yaw, pitch, false)"));
        assertTrue(source.contains("\"eye_position\", vector(mc.player.getEyePosition())"));
        assertTrue(source.contains("\"bounding_box\", box"));
        assertTrue(source.contains("guard_requires_absolute_look"));
    }
}

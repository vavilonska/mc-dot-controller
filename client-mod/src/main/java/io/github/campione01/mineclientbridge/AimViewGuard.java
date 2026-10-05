package io.github.campione01.mineclientbridge;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import java.util.Set;
import java.util.UUID;

/** Stateless compare-before-write contract for an external view-only entity tracker. */
record AimViewGuard(String world, String player, String session, long tick,
        double yaw, double pitch, int entityId, String entityUuid) {
    static final int SCHEMA = 1;
    static final int MAX_AGE_TICKS = 5;
    static final double VIEW_TOLERANCE = 0.01;
    private static final Set<String> FIELDS = Set.of("schema_version", "expected_world_generation",
            "expected_player_uuid", "expected_action_session", "expected_game_time",
            "expected_yaw", "expected_pitch", "target_entity_id", "target_uuid");

    static AimViewGuard parse(JsonElement value) {
        require(value != null && value.isJsonObject(), "invalid_aim_guard");
        JsonObject body = value.getAsJsonObject();
        require(body.keySet().equals(FIELDS), "invalid_aim_guard_fields");
        require(integer(body, "schema_version") == SCHEMA, "unsupported_aim_guard_schema");
        long tick = integer(body, "expected_game_time");
        long id = integer(body, "target_entity_id");
        require(tick >= 0 && id >= Integer.MIN_VALUE && id <= Integer.MAX_VALUE, "invalid_aim_guard_identity");
        double yaw = number(body, "expected_yaw"), pitch = number(body, "expected_pitch");
        require(Math.abs(yaw) <= 1_000_000 && pitch >= -90 && pitch <= 90, "invalid_aim_guard_angles");
        return new AimViewGuard(uuid(body, "expected_world_generation"), uuid(body, "expected_player_uuid"),
                uuid(body, "expected_action_session"), tick, yaw, pitch, (int) id, uuid(body, "target_uuid"));
    }

    String rejection(String liveWorld, String livePlayer, String liveSession, long liveTick,
            double liveYaw, double livePitch, String liveTarget, boolean targetAlive) {
        if (!session.equals(liveSession)) return "bridge_session_changed";
        if (!world.equals(liveWorld)) return "world_changed";
        if (!player.equals(livePlayer)) return "player_changed";
        if (liveTick < tick || liveTick - tick > MAX_AGE_TICKS) return "stale_aim_observation";
        if (!Double.isFinite(liveYaw) || !Double.isFinite(livePitch)
                || Math.abs(Math.IEEEremainder(liveYaw - yaw, 360)) > VIEW_TOLERANCE
                || Math.abs(livePitch - pitch) > VIEW_TOLERANCE) return "manual_view_changed";
        if (!entityUuid.equals(liveTarget)) return "target_missing";
        if (!targetAlive) return "target_dead";
        return null;
    }

    private static String uuid(JsonObject body, String name) {
        String value = ClientActionRequest.string(body, name);
        try {
            require(UUID.fromString(value).toString().equals(value), "invalid_" + name);
        } catch (IllegalArgumentException error) {
            throw new ClientActionRequest.Rejected(400, "invalid_" + name);
        }
        return value;
    }

    private static double number(JsonObject body, String name) {
        JsonElement value = body.get(name);
        require(value != null && value.isJsonPrimitive() && value.getAsJsonPrimitive().isNumber(), "invalid_" + name);
        double n = value.getAsDouble();
        require(Double.isFinite(n), "invalid_" + name);
        return n;
    }

    private static long integer(JsonObject body, String name) {
        number(body, name);
        try {
            return body.get(name).getAsBigDecimal().longValueExact();
        } catch (ArithmeticException | NumberFormatException error) {
            throw new ClientActionRequest.Rejected(400, "invalid_" + name);
        }
    }

    private static void require(boolean condition, String reason) {
        ClientActionRequest.require(condition, reason);
    }
}

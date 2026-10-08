package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.util.Set;
import java.util.UUID;

/** Two explicit, immutable single-boat transfers. No approach, placement, renewal or retry. */
record BoatTransferRequest(boolean mounting, String world, String player, String session,
        long observedTick, String vehicle, int vehicleId, int timeoutMs) {
    static final int SCHEMA = 1, MAX_AGE_TICKS = 5, MAX_SNEAK_TICKS = 10;
    static final int MIN_TIMEOUT_MS = 1000, MAX_TIMEOUT_MS = 5000;
    private static final Set<String> FIELDS = Set.of("action_id", "action", "boat_transfer_schema_version",
            "timeout_ms", "expected_world_generation", "expected_player_uuid", "expected_action_session",
            "expected_game_time", "vehicle_uuid", "vehicle_entity_id", "vehicle_type");

    static BoatTransferRequest parse(JsonObject body) {
        ClientActionRequest.require(body.keySet().equals(FIELDS), "invalid_boat_transfer_fields");
        String action = ClientActionRequest.string(body, "action");
        ClientActionRequest.require(action.equals("boat_mount") || action.equals("boat_dismount"), "invalid_boat_transfer_action");
        ClientActionRequest.require(ClientActionRequest.integer(body, "boat_transfer_schema_version", -1) == SCHEMA,
                "unsupported_boat_transfer_schema");
        ClientActionRequest.require(ClientActionRequest.string(body, "vehicle_type").equals("minecraft:boat"), "boat_type_unsupported");
        int timeout = ClientActionRequest.integer(body, "timeout_ms", -1);
        ClientActionRequest.require(timeout >= MIN_TIMEOUT_MS && timeout <= MAX_TIMEOUT_MS, "boat_transfer_timeout_1000_to_5000");
        int id = ClientActionRequest.integer(body, "vehicle_entity_id", -1);
        ClientActionRequest.require(id >= 0, "invalid_vehicle_entity_id");
        var value = body.get("expected_game_time");
        ClientActionRequest.require(value != null && value.isJsonPrimitive() && value.getAsJsonPrimitive().isNumber(), "invalid_expected_game_time");
        long tick;
        try { tick = value.getAsBigDecimal().longValueExact(); }
        catch (ArithmeticException | NumberFormatException error) { throw new ClientActionRequest.Rejected(400, "invalid_expected_game_time"); }
        ClientActionRequest.require(tick >= 0 && tick <= 9_007_199_254_740_991L, "invalid_expected_game_time");
        return new BoatTransferRequest(action.equals("boat_mount"), uuid(body, "expected_world_generation"),
                uuid(body, "expected_player_uuid"), uuid(body, "expected_action_session"), tick,
                uuid(body, "vehicle_uuid"), id, timeout);
    }

    String binding(String world, String player, String session, long liveTick, String vehicle, int vehicleId, boolean admission) {
        if (!this.world.equals(world)) return "action_world_changed";
        if (!this.player.equals(player)) return "action_player_changed";
        if (!this.session.equals(session)) return "action_session_changed";
        if (!this.vehicle.equals(vehicle) || this.vehicleId != vehicleId) return "vehicle_changed";
        if (liveTick < observedTick || (admission && liveTick - observedTick > MAX_AGE_TICKS)) return "stale_boat_transfer_observation";
        return null;
    }

    private static String uuid(JsonObject body, String name) {
        String value = ClientActionRequest.string(body, name);
        try { ClientActionRequest.require(UUID.fromString(value).toString().equals(value), "invalid_" + name); }
        catch (IllegalArgumentException error) { throw new ClientActionRequest.Rejected(400, "invalid_" + name); }
        return value;
    }
}

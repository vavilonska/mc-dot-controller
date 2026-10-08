package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.util.Set;
import java.util.UUID;

/** Explicit single-target request. No target acquisition, player targets or replay. */
record BoundedCombatRequest(String world, String player, String session, String targetUuid,
        int targetId, String targetType, boolean approach, boolean shield, EncounterRequest encounter) {
    // Request admission is distinct from attack permission: creeper requests are withdrawal-only.
    static final Set<String> REQUEST_TYPES = Set.of("minecraft:zombie", "minecraft:husk", "minecraft:zombie_villager",
            "minecraft:skeleton", "minecraft:stray", "minecraft:bogged", "minecraft:creeper");
    static BoundedCombatRequest parse(JsonObject body) {
        String type = ClientActionRequest.string(body, "target_type");
        ClientActionRequest.require(REQUEST_TYPES.contains(type), "bounded_combat_target_unsupported");
        int id = ClientActionRequest.integer(body, "target_entity_id", -1);
        ClientActionRequest.require(id >= 0, "invalid_target_entity_id");
        int timeout = ClientActionRequest.integer(body, "timeout_ms", 15000);
        ClientActionRequest.require(timeout >= 50 && timeout <= 30000, "bounded_combat_timeout_50_to_30000");
        return new BoundedCombatRequest(uuid(body,"expected_world_generation"), uuid(body,"expected_player_uuid"),
                uuid(body,"expected_action_session"), uuid(body,"target_uuid"), id, type,
                ClientActionRequest.bool(body,"approach",true), ClientActionRequest.bool(body,"shield",true), EncounterRequest.parseOptional(body));
    }
    private static String uuid(JsonObject body, String field) {
        String value = ClientActionRequest.string(body, field);
        try { ClientActionRequest.require(UUID.fromString(value).toString().equals(value), "invalid_" + field); }
        catch (IllegalArgumentException error) { throw new ClientActionRequest.Rejected(400,"invalid_" + field); }
        return value;
    }
}

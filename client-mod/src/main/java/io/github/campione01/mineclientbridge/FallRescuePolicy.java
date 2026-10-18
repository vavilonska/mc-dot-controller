package io.github.campione01.mineclientbridge;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import java.util.LinkedHashSet;
import java.util.Set;

/** Explicit bounded authorization. No inherited authorization from an ordinary movement action. */
final class FallRescuePolicy {
    static final int SCHEMA = 1, MIN_TTL_MS = 1000, DEFAULT_TTL_MS = 60000, MAX_TTL_MS = 600000;
    static final int MAX_EPISODES = 16, MAX_EPISODE_TICKS = 200, MAX_FORECAST_TICKS = 60;
    static final Set<String> PREEMPTIBLE = Set.of("follow_path", "recover_environment", "combat_entity",
            "use_item", "attack_entity", "shoot_entity", "select_hotbar");
    record Arm(String id, String owner, String session, String world, String player,
               int ttlMs, int episodes, Set<String> permittedActionIds) { }
    record Renew(String id, String owner, int revision, int ttlMs) { }
    record Stop(String id, String owner) { }
    private static final Set<String> ARM_KEYS = Set.of("fall_rescue_schema_version", "arm_id", "owner_id",
            "expected_action_session", "expected_world_generation", "expected_player_uuid", "ttl_ms",
            "max_episodes", "permitted_action_ids");
    static Arm arm(JsonObject j) {
        fields(j, ARM_KEYS); schema(j);
        var ids = new LinkedHashSet<String>();
        require(j.has("permitted_action_ids") && j.get("permitted_action_ids").isJsonArray(), "fall_rescue_permitted_action_ids_required");
        for (JsonElement e : j.getAsJsonArray("permitted_action_ids")) {
            require(e.isJsonPrimitive() && e.getAsJsonPrimitive().isString(), "fall_rescue_invalid_action_id");
            String id=e.getAsString(); require(!id.isBlank() && id.length() <= 128 && ids.add(id), "fall_rescue_invalid_action_id");
        }
        require(ids.size() <= 64, "fall_rescue_too_many_action_ids");
        int episodes = ClientActionRequest.integer(j, "max_episodes", 1);
        require(episodes >= 1 && episodes <= MAX_EPISODES, "fall_rescue_invalid_episode_limit");
        return new Arm(text(j,"arm_id"), text(j,"owner_id"), text(j,"expected_action_session"),
                text(j,"expected_world_generation"), text(j,"expected_player_uuid"), ttl(j), episodes, Set.copyOf(ids));
    }
    static Renew renew(JsonObject j) {
        fields(j,Set.of("fall_rescue_schema_version","arm_id","owner_id","expected_arm_revision","ttl_ms"));schema(j);
        int revision=ClientActionRequest.integer(j,"expected_arm_revision",-1);
        require(revision>=1,"fall_rescue_arm_revision_required");
        return new Renew(text(j,"arm_id"),text(j,"owner_id"),revision,ttl(j));
    }
    static Stop stop(JsonObject j) {
        fields(j,Set.of("fall_rescue_schema_version","arm_id","owner_id"));schema(j);
        return new Stop(text(j,"arm_id"),text(j,"owner_id"));
    }
    static void fields(JsonObject j,Set<String> names) { for(String k:j.keySet())require(names.contains(k),"fall_rescue_unknown_field"); }
    private static void schema(JsonObject j) {require(ClientActionRequest.integer(j,"fall_rescue_schema_version",-1)==SCHEMA,"fall_rescue_schema_required");}
    private static String text(JsonObject j,String key){String s=ClientActionRequest.string(j,key);require(!s.isBlank()&&s.length()<=128,"fall_rescue_invalid_"+key);return s;}
    private static int ttl(JsonObject j){int n=ClientActionRequest.integer(j,"ttl_ms",DEFAULT_TTL_MS);require(n>=MIN_TTL_MS&&n<=MAX_TTL_MS,"fall_rescue_invalid_ttl");return n;}
    static void require(boolean ok,String reason){if(!ok)throw new ClientActionRequest.Rejected(409,reason);}
    static double conservativeDamage(double fallDistance,double furtherDescent){
        if(!Double.isFinite(fallDistance)||!Double.isFinite(furtherDescent)||fallDistance<0||furtherDescent<0)return Double.POSITIVE_INFINITY;
        return Math.max(0,Math.ceil(fallDistance+furtherDescent-3));
    }
    static boolean dangerous(double fallDistance,double furtherDescent,float health){
        return !Float.isFinite(health)||health<=0||conservativeDamage(fallDistance,furtherDescent)>=1;
    }
    private FallRescuePolicy() { }
}

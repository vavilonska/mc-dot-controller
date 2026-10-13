package io.github.campione01.mineclientbridge;

import com.google.gson.JsonNull;
import com.google.gson.JsonObject;
import java.util.Map;

/** Immutable values only. A missing, stale or partially covered source is never evidence of calm. */
final class NativeLivingSnapshot {
    static final long MAX_AGE_NANOS = 250_000_000L;
    static final long MAX_TICK_SKEW = 5;
    record Target(String uuid, int entityId, String type) { }
    record BeeState(boolean angry, int remainingAngerTicks, String persistentAngerTargetUuid) { }
    record RabbitState(int variantId, boolean killerBunny, boolean passiveGoalsVerified) { }
    record Row(String uuid, int entityId, String type, long tick, long nano,
               boolean alive, boolean aggressive, Target target, BeeState bee, RabbitState rabbit) {
        Row(String uuid, int entityId, String type, long tick, long nano,
            boolean alive, boolean aggressive, Target target, BeeState bee) {
            this(uuid, entityId, type, tick, nano, alive, aggressive, target, bee, null);
        }
    }
    record Batch(Object context, Object serverLevel, String dimension, Map<String, Row> rows,
                 boolean complete, int inspected, String reason) {
        Batch { rows = Map.copyOf(rows); }
    }

    /** Atomically prevents an old in-flight read from republishing after unload/session replacement. */
    static final class Store {
        private Object context;
        private Batch batch;
        synchronized Object context() { return context; }
        synchronized Batch snapshot() { return batch; }
        synchronized void replace(Object next) { if (context != next) { context = next; batch = null; } }
        synchronized void clear() { context = null; batch = null; }
        synchronized void discard(Object expected) { if (context == expected) { context = null; batch = null; } }
        synchronized boolean publish(Batch next) {
            if (context == null || next.context() != context) return false;
            batch = next; return true;
        }
    }

    static String rejection(Batch batch, Object context, String dimension, String uuid,
                            int entityId, String type, long tick, long nano) {
        if (batch == null || context == null || batch.context() != context) return "context_unavailable";
        if (!batch.dimension().equals(dimension)) return "dimension_changed";
        if (!batch.complete()) return batch.reason();
        Row row = batch.rows().get(uuid);
        if (row == null) return "entity_not_observed";
        if (!row.uuid().equals(uuid) || row.entityId() != entityId || !row.type().equals(type)) return "entity_identity_changed";
        long age = nano - row.nano();
        if (age < 0 || age > MAX_AGE_NANOS) return "source_expired";
        if (tick < 0 || row.tick() < 0 || Math.abs(tick - row.tick()) > MAX_TICK_SKEW) return "source_tick_mismatch";
        if (row.bee() != null && row.bee().remainingAngerTicks() < 0) return "invalid_anger_time";
        if (row.rabbit() != null) {
            int id = row.rabbit().variantId();
            // Pinned vanilla enum IDs, independently asserted by the genuine-loader test.
            if (!row.type().equals("minecraft:rabbit") || !(id >= 0 && id <= 5 || id == 99)
                    || row.rabbit().killerBunny() != (id == 99)) return "invalid_rabbit_variant";
        }
        return null;
    }

    static boolean knownCalmTargetless(Batch batch,Object context,String dimension,String uuid,int entityId,
                                      String type,long tick,long nano) {
        if(rejection(batch,context,dimension,uuid,entityId,type,tick,nano)!=null)return false;
        Row row=batch.rows().get(uuid);
        return row.alive()&&!row.aggressive()&&row.target()==null;
    }

    static JsonObject json(Batch batch, Object context, String dimension, String worldGeneration,
                           String playerUuid, String uuid, int entityId, String type, long tick, long nano) {
        JsonObject out = new JsonObject();
        out.addProperty("schema_version", 1);
        out.addProperty("entity_uuid", uuid); out.addProperty("entity_id", entityId); out.addProperty("entity_type", type);
        out.addProperty("dimension", dimension); out.addProperty("world_generation", worldGeneration); out.addProperty("player_uuid", playerUuid);
        String reason = rejection(batch, context, dimension, uuid, entityId, type, tick, nano);
        out.addProperty("known", reason == null);
        out.addProperty("source", reason == null ? "integrated_server_tick" : "unavailable");
        out.addProperty("reason", reason == null ? "observed" : reason);
        out.addProperty("current_target_known", reason == null);
        if (batch != null && batch.context() == context) {
            out.addProperty("coverage_complete", batch.complete()); out.addProperty("inspected", batch.inspected());
        } else out.addProperty("coverage_complete", false);
        if (reason != null) return out;
        Row row = batch.rows().get(uuid);
        out.addProperty("sample_tick", tick); out.addProperty("sample_nano", Long.toString(nano));
        out.addProperty("source_tick", row.tick()); out.addProperty("source_nano", Long.toString(row.nano()));
        out.addProperty("sample_age_ms", (nano - row.nano()) / 1_000_000.0);
        out.addProperty("alive", row.alive()); out.addProperty("aggressive", row.aggressive());
        if (row.target() == null) out.add("current_target", JsonNull.INSTANCE);
        else {
            JsonObject target = new JsonObject(); target.addProperty("uuid", row.target().uuid());
            target.addProperty("entity_id", row.target().entityId()); target.addProperty("type", row.target().type());
            out.add("current_target", target);
        }
        if (row.bee() != null) {
            JsonObject bee = new JsonObject(); bee.addProperty("angry", row.bee().angry());
            bee.addProperty("remaining_anger_ticks", row.bee().remainingAngerTicks());
            if (row.bee().persistentAngerTargetUuid() == null) bee.add("persistent_anger_target_uuid", JsonNull.INSTANCE);
            else bee.addProperty("persistent_anger_target_uuid", row.bee().persistentAngerTargetUuid());
            out.add("bee", bee);
        }
        if (row.rabbit() != null) {
            JsonObject rabbit = new JsonObject(); rabbit.addProperty("variant_id", row.rabbit().variantId());
            rabbit.addProperty("killer_bunny", row.rabbit().killerBunny());
            rabbit.addProperty("passive_goals_verified", row.rabbit().passiveGoalsVerified());
            out.add("rabbit", rabbit);
        }
        return out;
    }
}

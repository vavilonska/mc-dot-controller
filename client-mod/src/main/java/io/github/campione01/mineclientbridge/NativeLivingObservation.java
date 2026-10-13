package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.util.HashMap;
import java.util.UUID;
import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.server.IntegratedServer;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceKey;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.Mob;
import net.minecraft.world.entity.animal.Bee;
import net.minecraft.world.level.Level;
import net.neoforged.neoforge.client.event.ClientPlayerNetworkEvent;
import net.neoforged.neoforge.client.event.ClientTickEvent;
import net.neoforged.neoforge.common.NeoForge;
import net.neoforged.neoforge.event.level.LevelEvent;
import net.neoforged.neoforge.event.server.ServerStoppedEvent;
import net.neoforged.neoforge.event.tick.ServerTickEvent;

/** Read-only, private integrated-server observations; never waits or reads server entity fields on the client thread. */
final class NativeLivingObservation {
    static final int MAX_INSPECTED = 4096, MAX_ROWS = 256;
    static final double RADIUS = 128;
    private static final NativeLivingSnapshot.Store STORE = new NativeLivingSnapshot.Store();
    private static boolean installed;
    private record Context(IntegratedServer server, ClientLevel clientLevel, ResourceKey<Level> dimension,
                           UUID playerUuid, String worldGeneration) { }
    private NativeLivingObservation() { }

    static synchronized void install() {
        if (installed) return;
        NeoForge.EVENT_BUS.addListener(ClientTickEvent.Post.class, event -> refresh(Minecraft.getInstance()));
        NeoForge.EVENT_BUS.addListener(ServerTickEvent.Post.class, NativeLivingObservation::serverTick);
        NeoForge.EVENT_BUS.addListener(ClientPlayerNetworkEvent.LoggingOut.class, event -> clear());
        NeoForge.EVENT_BUS.addListener(LevelEvent.Unload.class, event -> clear());
        NeoForge.EVENT_BUS.addListener(ServerStoppedEvent.class, event -> clear());
        installed = true;
    }
    static void clear() { STORE.clear(); }

    /** Called only on the client thread. All server-thread input is immutable or an opaque identity token. */
    private static Context refresh(Minecraft mc) {
        if (!mc.isSameThread()) throw new IllegalStateException("Living observation requires client thread");
        IntegratedServer server = mc.getSingleplayerServer();
        if (mc.level == null || mc.player == null || server == null || !mc.hasSingleplayerServer() || server.isPublished()) {
            clear(); return null;
        }
        Context old = (Context) STORE.context();
        if (old == null || old.server() != server || old.clientLevel() != mc.level
                || !old.playerUuid().equals(mc.player.getUUID()) || old.dimension() != mc.level.dimension()) {
            Context next = new Context(server, mc.level, mc.level.dimension(), mc.player.getUUID(), WorldGeneration.current(mc.level));
            STORE.replace(next); return next;
        }
        return old;
    }

    private static void serverTick(ServerTickEvent.Post event) {
        Context request = (Context) STORE.context();
        if (request == null || event.getServer() != request.server()) return;
        IntegratedServer server = request.server();
        if (!server.isSameThread()) throw new IllegalStateException("Living source requires server thread");
        if (server.isPublished() || server.getPlayerList().getPlayers().size() != 1) { STORE.discard(request); return; }
        var player = server.getPlayerList().getPlayer(request.playerUuid());
        ServerLevel level = server.getLevel(request.dimension());
        if (player == null || level == null || player.serverLevel() != level) { STORE.discard(request); return; }
        var rows = new HashMap<String, NativeLivingSnapshot.Row>();
        int inspected = 0; boolean complete = true; String reason = "observed";
        try {
            for (Entity entity : level.getAllEntities()) {
                if (++inspected > MAX_INSPECTED) { complete = false; reason = "inspection_limit"; break; }
                if (!(entity instanceof Mob mob) || entity.isRemoved() || entity.distanceToSqr(player) > RADIUS * RADIUS) continue;
                if (rows.size() >= MAX_ROWS) { complete = false; reason = "row_limit"; break; }
                NativeLivingSnapshot.Row row = read(mob, level.getGameTime(), System.nanoTime());
                if (rows.put(row.uuid(), row) != null) { complete = false; reason = "duplicate_entity_uuid"; break; }
            }
        } catch (RuntimeException unavailable) {
            complete = false; reason = "native_read_failed";
        }
        NativeLivingSnapshot.Batch batch = new NativeLivingSnapshot.Batch(request, level,
                level.dimension().location().toString(), rows, complete, inspected, reason);
        STORE.publish(batch);
    }

    /** Actual vanilla fields, on their owning server thread. Public engine accessors only. */
    static NativeLivingSnapshot.Row read(Mob mob, long tick, long nano) {
        LivingEntity target = mob.getTarget();
        NativeLivingSnapshot.Target targetState = target == null ? null : new NativeLivingSnapshot.Target(
                target.getUUID().toString(), target.getId(), BuiltInRegistries.ENTITY_TYPE.getKey(target.getType()).toString());
        NativeLivingSnapshot.BeeState beeState = null;
        if (mob.getClass() == Bee.class && mob.getType() == net.minecraft.world.entity.EntityType.BEE) {
            Bee bee = (Bee) mob;
            UUID angerTarget = bee.getPersistentAngerTarget();
            beeState = new NativeLivingSnapshot.BeeState(bee.isAngry(), bee.getRemainingPersistentAngerTime(),
                    angerTarget == null ? null : angerTarget.toString());
        }
        return new NativeLivingSnapshot.Row(mob.getUUID().toString(), mob.getId(),
                BuiltInRegistries.ENTITY_TYPE.getKey(mob.getType()).toString(), tick, nano,
                mob.isAlive() && !mob.isRemoved(), mob.isAggressive(), targetState, beeState, NativeRabbitObservation.read(mob));
    }

    record Frame(Object context, NativeLivingSnapshot.Batch batch) { }
    static Frame capture(Minecraft mc) {
        Context request = refresh(mc);
        return new Frame(request, STORE.snapshot());
    }
    static boolean knownCalmTargetless(Minecraft mc,Entity entity,Frame frame) {
        Object request=frame.context()==STORE.context()?frame.context():null;
        return NativeLivingSnapshot.knownCalmTargetless(frame.batch(),request,mc.level.dimension().location().toString(),
                entity.getUUID().toString(),entity.getId(),BuiltInRegistries.ENTITY_TYPE.getKey(entity.getType()).toString(),
                mc.level.getGameTime(),System.nanoTime());
    }
    static void append(Minecraft mc, Entity entity, JsonObject row, Frame frame) {
        if (!(entity instanceof Mob)) return;
        // One immutable batch for every entity in this client state response.
        Object request = frame.context() == STORE.context() ? frame.context() : null;
        row.add("native_living", NativeLivingSnapshot.json(frame.batch(), request,
                mc.level.dimension().location().toString(), WorldGeneration.current(mc.level), mc.player.getUUID().toString(),
                entity.getUUID().toString(), entity.getId(), BuiltInRegistries.ENTITY_TYPE.getKey(entity.getType()).toString(),
                mc.level.getGameTime(), System.nanoTime()));
    }
}

package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.util.Set;
import net.minecraft.client.KeyMapping;
import net.minecraft.client.Minecraft;
import net.minecraft.client.player.Input;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.world.level.GameType;
import net.minecraft.world.entity.ai.attributes.Attributes;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.chunk.LevelChunk;
import net.minecraft.world.level.chunk.status.ChunkStatus;
import net.minecraft.world.phys.AABB;
import net.neoforged.bus.api.EventPriority;
import net.neoforged.neoforge.client.event.ClientPlayerNetworkEvent;
import net.neoforged.neoforge.client.event.ClientTickEvent;
import net.neoforged.neoforge.client.event.MovementInputUpdateEvent;
import net.neoforged.neoforge.client.event.ScreenEvent;
import net.neoforged.neoforge.common.NeoForge;
import net.neoforged.neoforge.event.entity.living.LivingDeathEvent;
import net.neoforged.neoforge.event.level.LevelEvent;

/** One ordinary input sample, no key presses, movement packets, teleport, or physics bypass. */
final class GuardedGameMovement {
    static final GuardedMovement LEASES = new GuardedMovement(System::nanoTime);
    private static final Set<String> FLOORS = Set.of("minecraft:stone", "minecraft:cobblestone",
            "minecraft:dirt", "minecraft:grass_block", "minecraft:granite", "minecraft:diorite",
            "minecraft:andesite", "minecraft:deepslate", "minecraft:cobbled_deepslate",
            "minecraft:oak_planks", "minecraft:birch_planks", "minecraft:spruce_planks");
    private static boolean installed;
    static boolean enabled() { return Boolean.getBoolean("mineclientBridge.guardedMovement"); }

    static synchronized void install() {
        if (installed) return;
        NeoForge.EVENT_BUS.addListener(EventPriority.LOWEST, false,
                MovementInputUpdateEvent.class, GuardedGameMovement::sample);
        NeoForge.EVENT_BUS.addListener(ClientTickEvent.Post.class, event -> LEASES.finishTick());
        NeoForge.EVENT_BUS.addListener(ClientTickEvent.Pre.class, event -> {
            // Clear any exceptional prior tick residue before another tick can consume input.
            if (LEASES.status().sampled()) LEASES.cancelAndRelease("movement_interrupted_tick");
        });
        NeoForge.EVENT_BUS.addListener(EventPriority.HIGHEST, true, ScreenEvent.Opening.class,
                event -> cancelOnGameThread("screen_transition"));
        NeoForge.EVENT_BUS.addListener(ClientPlayerNetworkEvent.LoggingOut.class,
                event -> cancelOnGameThread("world_transition"));
        NeoForge.EVENT_BUS.addListener(ClientPlayerNetworkEvent.Clone.class,
                event -> cancelOnGameThread("player_changed"));
        NeoForge.EVENT_BUS.addListener(LevelEvent.Unload.class, event -> {
            if (event.getLevel().isClientSide()) cancelOnGameThread("world_transition");
        });
        NeoForge.EVENT_BUS.addListener(LivingDeathEvent.class, event -> {
            if (event.getEntity() == Minecraft.getInstance().player) cancelOnGameThread("player_not_ready");
        });
        installed = true;
    }

    static void cancelOnGameThread(String reason) {
        Minecraft mc = Minecraft.getInstance();
        if (mc.isSameThread()) LEASES.cancelAndRelease(reason);
        else LEASES.cancelOutstanding(reason); // Logical cancellation first; next game callback releases.
    }

    private static void sample(MovementInputUpdateEvent event) {
        Minecraft mc = Minecraft.getInstance();
        if (event.getEntity() != mc.player) return;
        Input input = event.getInput();
        LEASES.sample(() -> snapshot(mc, input), () -> {
            GuardedAction.require(mc.isSameThread() && mc.player != null && mc.player.input == input,
                    "movement_input_changed");
            // These fields are consumed by vanilla later in this same player tick. Do not set
            // KeyMapping state/clickCount or emit a keyboard/mouse event that can outlive the lease.
            input.up = true;
            input.forwardImpulse = GuardedMovement.FORWARD_IMPULSE;
        }, () -> {
            GuardedAction.require(mc.isSameThread(), "minecraft_thread_required");
            // Capture the original input object: a replaced/dead player's fields still get released.
            input.up = false;
            input.forwardImpulse = 0;
        });
    }

    private static GuardedMovement.State snapshot(Minecraft mc, Input input) {
        GuardedAction.require(mc.isSameThread(), "minecraft_thread_required");
        GuardedAction.require(mc.player != null && mc.level != null && mc.gameMode != null, "not_in_world");
        var player = mc.player;
        var level = mc.level;
        String generation = WorldGeneration.current(level);
        double x = player.getX(), y = player.getY(), z = player.getZ(), yaw = player.getYRot();
        boolean safe = localSurvival(mc) && ready(mc) && neutral(mc, input) && corridorClear(mc);
        // Re-read readiness and neutral state after corridor callbacks, and reject any pose change.
        GuardedAction.require(mc.player == player && mc.level == level && mc.gameMode != null
                && player.getX() == x && player.getY() == y && player.getZ() == z && player.getYRot() == yaw,
                "context_changed");
        return new GuardedMovement.State(generation, player.getUUID().toString(), level.getGameTime(),
                x, y, z, yaw, enabled() && BridgeServer.isRunning(),
                localSurvival(mc), ready(mc), neutral(mc, input), safe);
    }

    private static boolean localSurvival(Minecraft mc) {
        return mc.hasSingleplayerServer() && mc.getSingleplayerServer() != null
                && !mc.getSingleplayerServer().isPublished() && mc.level.players().size() == 1
                && mc.gameMode.getPlayerMode() == GameType.SURVIVAL;
    }

    private static boolean ready(Minecraft mc) {
        var player = mc.player;
        return mc.screen == null && !mc.isPaused() && player.isAlive() && !player.isDeadOrDying()
                && !player.isSpectator() && !player.isUsingItem() && !player.isPassenger()
                && !player.isSprinting() && !player.isSwimming() && !player.isFallFlying() && !player.isCrouching()
                && !player.getAbilities().flying && !player.getAbilities().mayfly && !player.noPhysics
                && player.getBbWidth() >= 0.599 && player.getBbWidth() <= 0.601
                && player.getBbHeight() >= 1.799 && player.getBbHeight() <= 1.801
                && Double.isFinite(player.getAttributeValue(Attributes.MOVEMENT_SPEED))
                && player.getAttributeValue(Attributes.MOVEMENT_SPEED) > 0
                && player.getAttributeValue(Attributes.MOVEMENT_SPEED) <= 0.10000001
                && Float.isFinite(player.getSpeed()) && player.getSpeed() > 0 && player.getSpeed() <= 0.10000001
                && !player.isInWater() && !player.isInLava() && !player.onClimbable()
                && !player.isOnFire() && player.onGround() && player.getActiveEffects().isEmpty()
                && player.getHealth() == player.getMaxHealth() && player.hurtTime == 0
                && player.getFoodData().getFoodLevel() >= 6 && player.getAirSupply() == player.getMaxAirSupply()
                && mc.getCameraEntity() == player && !player.isAutoJumpEnabled()
                && !mc.options.autoJump().get() && player.autoJumpTime == 0
                && player.getDeltaMovement().horizontalDistance() <= 0.001
                && Math.abs(player.getDeltaMovement().y) <= 0.1
                && Math.abs(player.getY() - Math.rint(player.getY())) <= 0.001;
    }

    private static boolean neutral(Minecraft mc, Input input) {
        var player = mc.player;
        boolean neutral = input == player.input && input.forwardImpulse == 0 && input.leftImpulse == 0
                && !input.up && !input.down && !input.left && !input.right && !input.jumping && !input.shiftKeyDown
                && !BridgeServer.hasHeldInputs() && ClientInputIsolation.statistics().heldKeys() == 0;
        for (KeyMapping mapping : mc.options.keyMappings) neutral &= !mapping.isDown();
        return neutral;
    }

    private static boolean corridorClear(Minecraft mc) {
        double radians = Math.toRadians(mc.player.getYRot());
        AABB swept = mc.player.getBoundingBox().expandTowards(-Math.sin(radians) * 0.6, 0,
                Math.cos(radians) * 0.6).inflate(0.05, 0, 0.05);
        if (!mc.level.getEntities(mc.player, swept.inflate(0.25)).isEmpty()) return false;
        int feetY = (int) Math.rint(mc.player.getY());
        for (int x = (int) Math.floor(swept.minX); x <= (int) Math.floor(swept.maxX); x++) {
            for (int z = (int) Math.floor(swept.minZ); z <= (int) Math.floor(swept.maxZ); z++) {
                // Explicit non-creating chunk lookup. No world/chunk-load side effects.
                LevelChunk chunk = mc.level.getChunkSource().getChunk(x >> 4, z >> 4, ChunkStatus.FULL, false);
                if (chunk == null) return false;
                BlockPos floorPos = new BlockPos(x, feetY - 1, z);
                BlockState floor = chunk.getBlockState(floorPos);
                if (!FLOORS.contains(BuiltInRegistries.BLOCK.getKey(floor.getBlock()).toString())
                        || !floor.getFluidState().isEmpty() || !floor.isCollisionShapeFullBlock(mc.level, floorPos)) return false;
                for (int y = feetY; y <= feetY + 1; y++) {
                    BlockState space = chunk.getBlockState(new BlockPos(x, y, z));
                    if (!space.isAir() || !space.getFluidState().isEmpty()) return false;
                }
            }
        }
        return true;
    }

    static JsonObject observedStatus(Minecraft mc) {
        JsonObject json = status();
        double yaw = Math.IEEEremainder(mc.player.getYRot(), 360);
        if (yaw >= 180) yaw -= 360;
        String observationId = LEASES.observe(new GuardedMovement.State(WorldGeneration.current(mc.level),
                mc.player.getUUID().toString(), mc.level.getGameTime(), mc.player.getX(), mc.player.getY(),
                mc.player.getZ(), yaw, enabled(), false, false, false, false));
        json.addProperty("observation_id", observationId);
        json.addProperty("observation_yaw", yaw);
        json.addProperty("max_observation_age_ms", GuardedMovement.MAX_OBSERVATION_AGE_MS);
        return json;
    }

    static JsonObject status() {
        GuardedMovement.Status state = LEASES.status();
        JsonObject json = new JsonObject();
        json.addProperty("schema_version", GuardedMovement.SCHEMA);
        json.addProperty("enabled", enabled());
        json.addProperty("session", state.session());
        json.addProperty("owner_request_id", state.ownerRequestId());
        json.addProperty("sampled", state.sampled());
        json.addProperty("released", state.released());
        json.addProperty("admission_open", state.admissionOpen());
        json.addProperty("requests_remaining", state.requestsRemaining());
        json.addProperty("max_duration_ms", GuardedMovement.MAX_DURATION_MS);
        json.addProperty("max_ttl_ms", GuardedMovement.MAX_TTL_MS);
        json.addProperty("max_input_samples", 1);
        json.addProperty("forward_impulse", GuardedMovement.FORWARD_IMPULSE);
        json.addProperty("local_unpublished_survival_only", true);
        json.addProperty("held_keys", false);
        json.addProperty("turn_supported", false);
        return json;
    }

    private GuardedGameMovement() { }
}

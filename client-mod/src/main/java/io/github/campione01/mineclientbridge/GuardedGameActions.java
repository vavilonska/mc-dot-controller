package io.github.campione01.mineclientbridge;

import net.minecraft.client.Minecraft;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.TamableAnimal;
import net.minecraft.world.entity.monster.Enemy;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.GameType;
import net.minecraft.world.phys.EntityHitResult;
import net.minecraft.world.phys.Vec3;
import net.neoforged.neoforge.common.ItemAbilities;

/** Game-thread adapter. No movement, target selection, held keys, or attack queue. */
final class GuardedGameActions {
    record Outcome(String action, String worldGeneration, String playerUuid,
                   String targetUuid, float yaw, float pitch) { }

    static boolean enabled() { return Boolean.getBoolean("mineclientBridge.guardedActions"); }

    static Outcome apply(GuardedAction.Request request, GuardedDispatch.Ticket<?> ticket) {
        Minecraft mc = Minecraft.getInstance();
        GuardedAction.require(mc.isSameThread(), "minecraft_thread_required");
        GuardedAction.require(enabled() && BridgeServer.isRunning(), "guarded_actions_disabled");
        GuardedAction.require(GuardedGameMovement.LEASES.status().ownerRequestId() == null, "movement_busy");
        String generation = WorldGeneration.current(mc.level);
        GuardedAction.require(mc.player != null && mc.level != null && mc.gameMode != null,
                "not_in_world");
        GuardedAction.require(mc.screen == null && !mc.isPaused() && mc.player.isAlive()
                && !mc.player.isSpectator() && !mc.player.isUsingItem()
                && mc.getCameraEntity() == mc.player, "player_not_ready");
        GuardedAction.require(mc.hasSingleplayerServer() && mc.getSingleplayerServer() != null
                && !mc.getSingleplayerServer().isPublished() && mc.level.players().size() == 1
                && mc.gameMode.getPlayerMode() == GameType.SURVIVAL, "local_survival_required");

        // Do not trust the renderer's crosshair cached from an earlier frame.
        mc.gameRenderer.pick(1.0F);
        Entity crosshair = mc.hitResult instanceof EntityHitResult hit ? hit.getEntity() : null;
        Entity target = null;
        if (crosshair != null && request.targetUuid().equals(crosshair.getUUID().toString())) {
            target = crosshair;
        } else if (request.action().equals("look")) {
            // Only resolve the external caller's exact UUID in this small local box.
            for (Entity candidate : mc.level.getEntities(mc.player,
                    mc.player.getBoundingBox().inflate(GuardedAction.MAX_RANGE),
                    entity -> request.targetUuid().equals(entity.getUUID().toString()))) {
                if (target != null) throw new GuardedAction.Rejected("ambiguous_target");
                target = candidate;
            }
        }
        GuardedAction.require(target != null, "target_changed");
        Vec3 eyes = mc.player.getEyePosition();
        double distance = Math.sqrt(target.getBoundingBox().distanceToSqr(eyes));
        if (request.action().equals("attack") && mc.hitResult instanceof EntityHitResult hit) {
            // Both the actual ray hit and the entity bounds must be within reach.
            distance = Math.max(distance, eyes.distanceTo(hit.getLocation()));
        }
        boolean allowed = target instanceof LivingEntity living && living.isAlive()
                && !living.isDeadOrDying() && !target.isRemoved() && target.isPickable()
                && target instanceof Enemy && !(target instanceof Player)
                && !(target instanceof TamableAnimal) && !target.isAlliedTo(mc.player)
                && target.level() == mc.level;
        ItemStack held = mc.player.getMainHandItem();
        boolean weaponAllowed = GuardedAction.weaponAllowed(BuiltInRegistries.ITEM.getKey(held.getItem()).toString(),
                held.isEnchanted(), held.canPerformAction(ItemAbilities.SWORD_SWEEP));
        GuardedAction.State live = new GuardedAction.State(generation,
                mc.player.getUUID().toString(), true, true, weaponAllowed, target.getUUID().toString(),
                BuiltInRegistries.ENTITY_TYPE.getKey(target.getType()).toString(), allowed,
                crosshair == null ? null : crosshair.getUUID().toString(), distance,
                mc.player.entityInteractionRange(), mc.player.hasLineOfSight(target)
                && mc.player.canInteractWithEntity(target, 0.0), mc.player.getYRot(), mc.player.getXRot());
        GuardedAction.validate(request, live);
        // Recheck after world/pick/LOS callbacks and just before the ordinary action.
        GuardedAction.require(mc.player != null && mc.level != null && mc.gameMode != null
                && mc.screen == null && mc.player.isAlive() && !mc.isPaused() && !mc.player.isUsingItem()
                && mc.getCameraEntity() == mc.player && mc.gameMode.getPlayerMode() == GameType.SURVIVAL
                && generation.equals(WorldGeneration.current(mc.level))
                && request.playerUuid().equals(mc.player.getUUID().toString()), "context_changed");
        Entity finalCrosshair = mc.hitResult instanceof EntityHitResult hit ? hit.getEntity() : null;
        GuardedAction.require(finalCrosshair == crosshair && target.isAlive() && !target.isRemoved()
                && target.level() == mc.level, "target_changed");
        ticket.checkLive();
        if (request.action().equals("look")) {
            mc.player.setYRot((float) request.yaw());
            mc.player.setXRot((float) request.pitch());
            mc.player.setYHeadRot((float) request.yaw());
            mc.player.setYBodyRot((float) request.yaw());
        } else {
            // The ordinary client attack path runs now, not at some future key tick.
            // Its boolean return is NOT an entity-damage acknowledgement.
            mc.startAttack();
        }
        return new Outcome(request.action(), generation, request.playerUuid(), request.targetUuid(),
                mc.player.getYRot(), mc.player.getXRot());
    }

    private GuardedGameActions() { }
}

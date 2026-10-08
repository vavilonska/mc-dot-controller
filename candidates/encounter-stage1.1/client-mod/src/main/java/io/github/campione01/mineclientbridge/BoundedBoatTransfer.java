package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.util.Locale;
import net.minecraft.client.Minecraft;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.entity.vehicle.Boat;
import net.minecraft.world.phys.EntityHitResult;
import net.neoforged.neoforge.client.ClientHooks;

/** Ordinary one-shot use or bounded sneak; never edits membership, position or velocity. */
final class BoundedBoatTransfer {
    record Step(String terminal, String reason) { }
    final BoatTransferRequest request;
    final Boat boat;
    final LocalPlayer player;
    final JsonObject evidence;
    final BoatTransferProgress progress;

    BoundedBoatTransfer(Minecraft mc, BoatTransferRequest request, JsonObject evidence) {
        this.request = request; this.evidence = evidence; player = mc.player;
        if (!(mc.level.getEntity(request.vehicleId()) instanceof Boat target)) throw rejected("boat_target_missing");
        boat = target; progress = new BoatTransferProgress(request.mounting());
        String reason = guard(mc, true);
        if (reason != null) throw rejected(reason);
        if (request.mounting()) {
            if (player.isPassenger()) throw rejected("boat_mount_requires_unmounted_player");
            if (!boat.getPassengers().isEmpty()) throw rejected("boat_mount_requires_empty_boat");
            if (!player.getMainHandItem().isEmpty()) throw rejected("boat_mount_requires_empty_main_hand");
            if (player.isShiftKeyDown()) throw rejected("boat_mount_requires_released_sneak");
            if (!targetPicked(mc)) throw rejected("boat_target_not_in_reach_or_visible");
        } else if (player.getVehicle() != boat || boat.getControllingPassenger() != player || !exactPassengers()) {
            throw rejected("boat_dismount_requires_sole_driver");
        }
        evidence.addProperty("boat_transfer_schema_version", BoatTransferRequest.SCHEMA);
        evidence.addProperty("vehicle_uuid", request.vehicle());
        evidence.addProperty("vehicle_entity_id", request.vehicleId());
        evidence.addProperty("dispatch_attempted", false);
        evidence.addProperty("interaction_attempts", 0);
        evidence.addProperty("max_sneak_ticks", BoatTransferRequest.MAX_SNEAK_TICKS);
        evidence.addProperty("sneak_ticks", 0);
        evidence.addProperty("input_released", false);
        evidence.addProperty("landing_safety_confirmed", false);
    }

    Step tick(Minecraft mc) {
        String reason = guard(mc, false);
        if (reason != null) return failed(reason);
        if (!request.mounting() && !progress.dispatched() && player.getVehicle() != boat)
            return failed("boat_dismount_precondition_changed");
        long tick = mc.level.getGameTime();
        boolean same = player.getVehicle() == boat;
        reason = progress.observe(tick, player.isPassenger(), same, boat.getControllingPassenger() == player, exactPassengers(), boat.getPassengers().isEmpty());
        evidence.add("vehicle", BoatObservation.snapshot(mc));
        evidence.addProperty("observed_game_time", tick);
        evidence.addProperty("stable_observation_ticks", progress.stableTicks());
        if (reason != null) return new Step((reason.equals("boat_mount_observed") || reason.equals("boat_dismount_observed")) ? "succeeded" : "failed", reason);
        if (request.mounting() && !progress.dispatched()) {
            if (player.isPassenger() || !boat.getPassengers().isEmpty()) return failed("boat_mount_precondition_changed");
            if (!player.getMainHandItem().isEmpty() || player.isShiftKeyDown()) return failed("boat_mount_input_changed");
            if (!targetPicked(mc)) return failed("boat_target_not_in_reach_or_visible");
            var event = ClientHooks.onClickInput(1, mc.options.keyUse, InteractionHand.MAIN_HAND);
            if (event.isCanceled()) return failed("use_cancelled_by_mod");
            // Hooks may change the world/target. Revalidate immediately before the single use.
            reason = guard(mc, false);
            if (reason != null) return failed(reason);
            if (player.isPassenger() || !boat.getPassengers().isEmpty() || !player.getMainHandItem().isEmpty()
                    || player.isShiftKeyDown() || !targetPicked(mc)) return failed("boat_mount_precondition_changed");
            if (!ClientActions.ownsTransfer(this)) return failed("boat_transfer_ownership_changed");
            progress.dispatch(tick);
            evidence.addProperty("dispatch_attempted", true);
            evidence.addProperty("dispatch_game_time", tick);
            evidence.addProperty("interaction_attempts", 1);
            InteractionResult result = mc.gameMode.interact(player, boat, InteractionHand.MAIN_HAND);
            if (!ClientActions.ownsTransfer(this)) return failed("boat_transfer_ownership_changed");
            evidence.addProperty("interaction_result", result.name().toLowerCase(Locale.ROOT));
            if (result.shouldSwing() && event.shouldSwingHand()) player.swing(InteractionHand.MAIN_HAND);
            if (result == InteractionResult.FAIL) return failed("boat_interaction_rejected");
        }
        return new Step(null, progress.dispatched() ? "awaiting_boat_transfer_observation" : "awaiting_boat_sneak_input");
    }

    String inputRejection(Minecraft mc) { return guard(mc, false); }

    boolean sneakInput(Minecraft mc) {
        boolean sneak = progress.sneak(mc.level.getGameTime(), player.getVehicle() == boat);
        evidence.addProperty("sneak_ticks", progress.sneakTicks());
        evidence.addProperty("dispatch_attempted", progress.dispatched());
        if (progress.dispatched()) evidence.addProperty("dispatch_game_time", progress.dispatchTick());
        return sneak;
    }

    private String guard(Minecraft mc, boolean admission) {
        if (!admission && !ClientActions.ownsTransfer(this)) return "boat_transfer_ownership_changed";
        if (!mc.hasSingleplayerServer() || mc.getSingleplayerServer() == null || mc.getSingleplayerServer().isPublished())
            return "boat_transfer_requires_private_singleplayer";
        if (mc.player != player || mc.level == null || mc.gameMode == null) return "world_transition";
        if (mc.isPaused() || mc.screen != null || !player.isAlive() || player.isSpectator()) return "boat_transfer_context_unavailable";
        if (mc.level.getEntity(request.vehicleId()) != boat || !boat.isAlive() || boat.isRemoved() || boat.getClass() != Boat.class)
            return "boat_target_changed";
        String reason = request.binding(WorldGeneration.current(mc.level), player.getUUID().toString(), ClientActions.session(),
                mc.level.getGameTime(), boat.getUUID().toString(), boat.getId(), admission);
        if (reason != null) return reason;
        var v = boat.getDeltaMovement();
        if (!Double.isFinite(v.x) || !Double.isFinite(v.y) || !Double.isFinite(v.z) || !Float.isFinite(boat.deltaRotation)
                || v.horizontalDistance() > .025 || Math.abs(v.y) > .025 || Math.abs(boat.deltaRotation) > .25)
            return "boat_transfer_requires_stationary_boat";
        if (boat.isAboveBubbleColumn || boat.isUnderWater() || boat.isOnFire() || player.isOnFire() || boat.isPassenger()
                || !player.getPassengers().isEmpty()) return "boat_transfer_unsupported_context";
        for (var passenger : boat.getPassengers()) if (passenger != player) return "boat_passengers_changed";
        var hull = boat.getBoundingBox();
        if (!BoatPassengerEnvelope.valid(new BoatCollision.Box(hull.minX, hull.minY, hull.minZ, hull.maxX, hull.maxY, hull.maxZ))
                || hull.getXsize() > 1.5 || hull.getZsize() > 1.5 || hull.getYsize() > .7
                || !Double.isFinite(boat.getX()) || !Double.isFinite(boat.getY()) || !Double.isFinite(boat.getZ())
                || !Float.isFinite(boat.getYRot())) return "boat_transfer_geometry_unknown";
        // Bounded native hull: at most 4 x 3 x 4 loaded cells, never an unbounded area scan.
        var box = hull.inflate(.25);
        for (BlockPos pos : BlockPos.betweenClosed(BlockPos.containing(box.minX, box.minY, box.minZ),
                BlockPos.containing(box.maxX, box.maxY, box.maxZ))) {
            if (!mc.level.hasChunkAt(pos) || mc.level.isOutsideBuildHeight(pos) || !mc.level.getWorldBorder().isWithinBounds(pos))
                return "boat_transfer_unloaded_or_out_of_bounds";
        }
        return null;
    }
    private boolean exactPassengers() { return boat.getPassengers().size() == 1 && boat.getPassengers().getFirst() == player; }
    private boolean targetPicked(Minecraft mc) {
        mc.gameRenderer.pick(1.0F);
        return mc.hitResult instanceof EntityHitResult hit && hit.getEntity() == boat
                && player.hasLineOfSight(boat) && player.canInteractWithEntity(boat, 0.0)
                && player.getEyePosition().distanceTo(hit.getLocation()) <= player.entityInteractionRange();
    }
    void release() {
        BoatInputRelease.clear(boat::setInput, (left, right, up, down) -> {
            var input = player.input;
            input.forwardImpulse = input.leftImpulse = 0;
            input.left = left; input.right = right; input.up = up; input.down = down;
            input.jumping = input.shiftKeyDown = false;
        });
        evidence.addProperty("input_released", true);
    }
    private static Step failed(String reason) { return new Step("failed", reason); }
    private static ClientActionRequest.Rejected rejected(String reason) { return new ClientActionRequest.Rejected(409, reason); }
}

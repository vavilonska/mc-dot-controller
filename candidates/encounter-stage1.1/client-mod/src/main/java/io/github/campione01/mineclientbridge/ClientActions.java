package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.util.Locale;
import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.player.Input;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.inventory.ClickType;
import net.minecraft.world.item.BlockItem;
import net.minecraft.world.item.context.BlockPlaceContext;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.BlockHitResult;
import net.minecraft.world.phys.HitResult;
import net.minecraft.world.phys.Vec3;
import net.neoforged.bus.api.EventPriority;
import net.neoforged.neoforge.client.ClientHooks;
import net.neoforged.neoforge.client.event.ClientPlayerNetworkEvent;
import net.neoforged.neoforge.client.event.ClientTickEvent;
import net.neoforged.neoforge.client.event.MovementInputUpdateEvent;
import net.neoforged.neoforge.common.NeoForge;
import net.neoforged.neoforge.event.level.LevelEvent;

/** Resident executor for the real 1.21.1 client. Vanilla owns movement, collision, interaction and networking. */
final class ClientActions {
    private static final ActionRegistry ACTIONS = new ActionRegistry();
    private static RuntimeAction active;
    private static boolean installed;

    private static final class RuntimeAction {
        final ActionRegistry.Entry entry;
        final LocalPlayer player;
        final ClientLevel level;
        final long deadline;
        final long navigationEpoch;
        final BoundedCombat combat;
        final BoundedBoatDrive boat;
        final BoundedBoatTransfer transfer;
        boolean left, right;
        Input input;
        float forward;
        boolean jump, sneak, attackHeld, dispatched, jumped;
        boolean waypointJumped, sprintHeld;
        int settledTicks;
        int waypoint, dispatchTick, unchangedTicks;
        double bestDistance = Double.POSITIVE_INFINITY;
        Block initialBlock, placedBlock;
        RuntimeAction(ActionRegistry.Entry entry, Minecraft mc, BoundedCombat combat, BoundedBoatDrive boat, BoundedBoatTransfer transfer, long deadline) {
            this.entry = entry;
            this.combat = combat;
            this.boat = boat;
            this.transfer = transfer;
            player = mc.player;
            level = mc.level;
            navigationEpoch = NavigationPositionGuard.epoch();
            this.deadline = deadline;
        }
    }

    static synchronized void install() {
        if (installed) return;
        NeoForge.EVENT_BUS.addListener(ClientTickEvent.Pre.class, event -> preTick());
        NeoForge.EVENT_BUS.addListener(ClientTickEvent.Post.class, event -> postTick());
        NeoForge.EVENT_BUS.addListener(EventPriority.LOWEST, false, MovementInputUpdateEvent.class, ClientActions::input);
        NeoForge.EVENT_BUS.addListener(ClientPlayerNetworkEvent.LoggingOut.class, event -> cancel("world_transition"));
        NeoForge.EVENT_BUS.addListener(ClientPlayerNetworkEvent.Clone.class, event -> cancel("player_changed"));
        NeoForge.EVENT_BUS.addListener(LevelEvent.Unload.class, event -> {
            if (event.getLevel().isClientSide()) cancel("world_transition");
        });
        installed = true;
    }

    static JsonObject start(ClientActionRequest request) {
        Minecraft mc = Minecraft.getInstance();
        requireThread(mc);
        ActionRegistry.Entry old = ACTIONS.existing(request);
        if (old != null) return ACTIONS.status(request.id());
        if (active != null) throw new ClientActionRequest.Rejected(409, "action_busy");
        if (mc.player == null || mc.level == null || mc.gameMode == null)
            throw new ClientActionRequest.Rejected(409, "not_in_world");
        if (request.original().has("expected_world_generation")
                && !ClientActionRequest.string(request.original(),"expected_world_generation").equals(WorldGeneration.current(mc.level)))
            throw new ClientActionRequest.Rejected(409,"action_world_changed");
        if (request.original().has("expected_action_session")
                && !ClientActionRequest.string(request.original(),"expected_action_session").equals(ACTIONS.session))
            throw new ClientActionRequest.Rejected(409,"action_session_changed");
        NavigationPositionGuard.requireBinding(mc, request);
        if (request.original().has("expected_player_uuid")
                && !ClientActionRequest.string(request.original(),"expected_player_uuid").equals(mc.player.getUUID().toString()))
            throw new ClientActionRequest.Rejected(409,"action_player_changed");
        if (request.action().equals("combat_entity") && EncounterRequest.parseOptional(request.original())!=null
                && !EncounterRequest.runtimeEnabled())
            throw new ClientActionRequest.Rejected(409,"encounter_stage1_disabled");
        if (EncounterRequest.pauseRequested(request.original())) BridgeServer.requireEncounterPauseAdmission();
        long deadline=System.nanoTime()+request.timeoutMs()*1_000_000L;
        JsonObject combatEvidence = new JsonObject();
        BoundedCombat combat = request.action().equals("combat_entity")
                ? new BoundedCombat(mc, BoundedCombatRequest.parse(request.original()), combatEvidence, deadline) : null;
        JsonObject boatEvidence = new JsonObject();
        BoundedBoatDrive boat = request.action().equals("boat_drive")
                ? new BoundedBoatDrive(mc, BoatDriveRequest.parse(request.original()), boatEvidence) : null;
        JsonObject transferEvidence = new JsonObject();
        BoundedBoatTransfer transfer = request.action().equals("boat_mount") || request.action().equals("boat_dismount")
                ? new BoundedBoatTransfer(mc, BoatTransferRequest.parse(request.original()), transferEvidence) : null;
        // Transfer ownership once. A direct request later releases only this action's inputs.
        BridgeServer.releaseAllInputs();
        active = new RuntimeAction(ACTIONS.begin(request), mc, combat, boat, transfer, deadline);
        active.entry.result.addProperty("world_generation", WorldGeneration.current(mc.level));
        if (boat != null) {
            active.entry.result.add("boat", boatEvidence);
            boat.boat.setInput(false,false,false,false);
        }
        if (transfer != null) {
            active.entry.result.add("boat_transfer", transferEvidence);
            transfer.boat.setInput(false, false, false, false);
        }
        if (combat != null) {
            active.entry.result.add("combat", combatEvidence);
            active.entry.result.add("phase_ticks", new JsonObject());
        }
        if (request.hotbarSlot() >= 0) mc.player.getInventory().selected = request.hotbarSlot();
        return ACTIONS.status(request.id());
    }

    static JsonObject status(String id) { requireThread(Minecraft.getInstance()); return ACTIONS.status(id); }
    static String session() { return ACTIONS.session; }
    static boolean ownsInput() { return active != null; }
    static boolean ownsTransfer(BoundedBoatTransfer transfer) {
        requireThread(Minecraft.getInstance());
        return active != null && active.transfer == transfer;
    }
    static JsonObject cancelId(String id, String expectedSession) {
        requireThread(Minecraft.getInstance());
        if (expectedSession != null && !ACTIONS.session.equals(expectedSession))
            throw new ClientActionRequest.Rejected(409,"action_session_changed");
        return cancelId(id);
    }
    static JsonObject cancelId(String id) {
        requireThread(Minecraft.getInstance());
        ActionRegistry.Entry entry = ACTIONS.get(id);
        if (active != null && active.entry == entry) cancel("cancel_requested");
        return ACTIONS.status(id);
    }
    static void directTakeover() {
        requireThread(Minecraft.getInstance());
        cancel("direct_takeover");
        GuardedGameMovement.cancelOnGameThread("direct_takeover");
    }
    static void cancel(String reason) {
        Minecraft mc = Minecraft.getInstance();
        if (!mc.isSameThread()) { mc.execute(() -> cancel(reason)); return; }
        if (active != null) finish("cancelled", reason);
    }

    private static boolean context(Minecraft mc,String phase) {
        if (active == null) return false;
        if (mc.player != active.player || mc.level != active.level || mc.gameMode == null) {
            finish("cancelled", "world_transition"); return false;
        }
        NavigationPositionGuard.observe(mc);
        if (NavigationPositionGuard.applies(active.entry.request.action())
                && active.navigationEpoch != NavigationPositionGuard.epoch()) {
            active.entry.result.add("navigation_guard", NavigationPositionGuard.snapshot(mc));
            finish("cancelled", "position_discontinuity_rebind_required"); return false;
        }
        if (active.combat!=null && active.combat.isEncounter()) {
            String interruption=BoundedEncounter.lifecycle(mc.isPaused(),mc.isWindowActive(),mc.player.isSpectator());
            if(interruption!=null) { finish("cancelled",interruption);return false; }
            interruption=active.combat.encounterCallbackInterruption(System.nanoTime(),phase);
            if(interruption!=null) { finish("failed",interruption);return false; }
        }
        if (!mc.player.isAlive()) { finish("failed", "player_unavailable"); return false; }
        if (System.nanoTime() >= active.deadline) { finish("failed", "deadline_exceeded"); return false; }
        if (!active.entry.request.action().equals("click_slot") && mc.screen != null) {
            finish("cancelled", "screen_opened"); return false;
        }
        return true;
    }

    private static void preTick() {
        Minecraft mc = Minecraft.getInstance();
        NavigationPositionGuard.tick(mc);
        if (!context(mc,"pre_tick")) return;
        try {
            RuntimeAction a = active;
            a.entry.ticks++;
            a.forward = 0;
            a.left = a.right = false;
            a.jump = false;
            a.sneak = a.entry.request.sneak();
            if (mc.isPaused()) return;
            switch (a.entry.request.action()) {
                case "follow_path" -> followPath(mc, a);
                case "boat_mount", "boat_dismount" -> {
                    BoundedBoatTransfer.Step step;
                    try { step = a.transfer.tick(mc); }
                    catch (RuntimeException failure) { if (active == a) failException(failure); return; }
                    // An input/mod hook can synchronously cancel or replace this owner.
                    if (active != a) return;
                    a.entry.result.addProperty("phase", step.reason());
                    if (step.terminal() != null) finish(step.terminal(), step.reason());
                }
                case "boat_drive" -> {
                    BoundedBoatDrive.Step step = a.boat.tick(mc);
                    a.forward = step.up() ? 1 : step.down() ? -1 : 0;
                    a.left = step.left(); a.right = step.right();
                    a.entry.result.addProperty("phase",step.reason());
                    if (step.terminal() != null) finish(step.terminal(),step.reason());
                }
                case "break_block" -> mine(mc, a);
                case "place_block" -> preparePlacement(mc, a);
                case "click_slot" -> { }
                case "combat_entity" -> {
                    BoundedCombat.Step step = a.combat.tick(mc, a.entry.ticks);
                    a.entry.result.addProperty("phase", step.reason());
                    JsonObject phases = a.entry.result.getAsJsonObject("phase_ticks");
                    phases.addProperty(step.reason(), phases.has(step.reason()) ? phases.get(step.reason()).getAsInt()+1 : 1);
                    a.forward = step.forward();
                    if (step.terminal() != null) finish(step.terminal(), step.reason());
                }
            }
        } catch (RuntimeException failure) {
            failException(failure);
        }
    }

    private static void input(MovementInputUpdateEvent event) {
        RuntimeAction a = active;
        if (a == null || event.getEntity() != a.player || !context(Minecraft.getInstance(),"movement_input")) return;
        if (a.transfer != null) {
            try {
                String reason = a.transfer.inputRejection(Minecraft.getInstance());
                if (active != a) return;
                if (reason != null) { finish("failed", reason); return; }
            } catch (RuntimeException failure) { if (active == a) failException(failure); return; }
        }
        Input input = event.getInput();
        a.input = input;
        input.forwardImpulse = a.forward;
        input.leftImpulse = a.left ? 1 : a.right ? -1 : 0;
        input.up = a.forward > 0;
        input.down = a.forward < 0;
        if (a.boat == null) input.left = input.right = false;
        else { input.left = a.left; input.right = a.right; }
        input.jumping = a.jump;
        input.shiftKeyDown = a.transfer != null ? a.transfer.sneakInput(Minecraft.getInstance()) : a.sneak;
    }

    private static void postTick() {
        Minecraft mc = Minecraft.getInstance();
        if (!context(mc,"post_tick") || mc.isPaused()) return;
        try {
            RuntimeAction a = active;
            switch (a.entry.request.action()) {
                case "break_block" -> observeBreak(mc, a);
                case "place_block" -> place(mc, a);
                case "click_slot" -> clickSlot(mc, a);
                default -> { }
            }
        } catch (RuntimeException failure) {
            failException(failure);
        }
    }

    private static void followPath(Minecraft mc, RuntimeAction a) {
        var points = a.entry.request.waypoints();
        while (a.waypoint < points.size()) {
            var goal = points.get(a.waypoint);
            var effectiveGoal = new ClientActionRequest.Point(goal.x(),goal.y(),goal.z(),goal.jump() && !a.waypointJumped);
            PathSteering.Step step = PathSteering.toward(a.player.getX(), a.player.getY(), a.player.getZ(),
                    a.player.getYRot(), a.player.onGround(), a.player.horizontalCollision, effectiveGoal,
                    a.waypoint == points.size()-1);
            if (step.reached()) {
                if (a.waypoint == points.size()-1) {
                    sprint(mc,a,false);
                    a.entry.result.addProperty("phase","settling_at_endpoint");
                    a.entry.result.addProperty("distance_to_waypoint",step.distance());
                    Vec3 velocity=a.player.getDeltaMovement();
                    if (PathSteering.settledAt(a.player.getX(),a.player.getY(),a.player.getZ(),
                            velocity.x,velocity.z,a.player.onGround(),goal)) a.settledTicks++;
                    else a.settledTicks=0;
                    if (a.settledTicks < 2) return;
                }
                a.waypoint++; a.waypointJumped=false; a.settledTicks=0;
                a.bestDistance = Double.POSITIVE_INFINITY; a.unchangedTicks = 0; continue;
            }
            a.settledTicks=0;
            a.entry.result.addProperty("waypoint_index", a.waypoint);
            a.entry.result.addProperty("waypoint_count", points.size());
            a.entry.result.addProperty("distance_to_waypoint", step.distance());
            look(mc, step.yaw(), a.player.getXRot());
            a.forward = step.forward();
            a.jump = step.jump();
            if (a.jump) a.waypointJumped=true;
            sprint(mc,a,ClientActionRequest.bool(a.entry.request.original(),"sprint",false) && a.forward > .8);
            a.entry.result.addProperty("sprinting_observed",a.player.isSprinting());
            if (step.distance() < a.bestDistance - 0.04) {
                a.bestDistance = step.distance(); a.unchangedTicks = 0;
            } else if (++a.unchangedTicks >= 60) {
                finish("failed", "stuck");
            }
            return;
        }
        a.entry.result.addProperty("waypoint_index", points.size());
        a.entry.result.addProperty("waypoint_count", points.size());
        finish("succeeded", "path_reached");
    }

    private static void sprint(Minecraft mc, RuntimeAction a, boolean wanted) {
        // Request the ordinary sprint key; the client retains food/item/collision
        // eligibility. Never force sprint-on or write position/velocity.
        if (wanted) {
            a.sprintHeld=true;
            SprintKeyState.set(mc.options.keySprint::isDown,mc.options.keySprint::setDown,true);
        }
        else if (a.sprintHeld) {
            SprintKeyState.set(mc.options.keySprint::isDown,mc.options.keySprint::setDown,false);
            a.player.setSprinting(false);
            a.sprintHeld=false;
        }
    }

    private static void mine(Minecraft mc, RuntimeAction a) {
        BlockPos pos = pos(a.entry.request.target());
        if (!mc.level.hasChunkAt(pos)) { finish("failed", "chunk_not_loaded"); return; }
        if (mc.level.getBlockState(pos).isAir()) { finish("succeeded", "block_absent"); return; }
        if (a.initialBlock == null) a.initialBlock = mc.level.getBlockState(pos).getBlock();
        else if (mc.level.getBlockState(pos).getBlock() != a.initialBlock) { finish("failed", "target_changed"); return; }
        BlockHitResult hit = aimMiningTarget(mc, pos);
        if (hit == null) { finish("failed", "target_not_in_reach_or_visible"); return; }
        // One continuous ordinary attack hold; the client's keybind loop runs continueAttack.
        // Its block ray, NeoForge hooks, mining progress and server prediction remain vanilla.
        if (!mc.mouseHandler.isMouseGrabbed()) mc.mouseHandler.grabMouse();
        mc.options.keyAttack.setDown(true);
        a.attackHeld = true;
        if (!a.dispatched) {
            a.dispatched = true;
            a.entry.result.addProperty("dispatched", true);
            mc.startAttack();
            // Instantly breakable targets must release before the vanilla loop can pick behind them.
            if (mc.level.getBlockState(pos).isAir()) {
                a.entry.result.addProperty("observed_block", "minecraft:air");
                finish("succeeded", "block_broken_observed");
                return;
            }
        }
        a.entry.result.addProperty("destroy_stage", mc.gameMode.getDestroyStage());
    }

    private static BlockHitResult aimMiningTarget(Minecraft mc, BlockPos pos) {
        Vec3 center = Vec3.atCenterOf(pos);
        aim(mc, center);
        BlockHitResult hit = pick(mc, pos, null);
        if (hit != null) return hit; // Preserve the existing fast path.
        Vec3 eye = mc.player.getEyePosition();
        for (MiningAimPoints.Point point : MiningAimPoints.facingFaces(
                pos.getX(), pos.getY(), pos.getZ(), eye.x, eye.y, eye.z)) {
            aim(mc, new Vec3(point.x(), point.y(), point.z()));
            // Candidate coordinates never authorize mining: real picking must hit the
            // same block within ordinary reach, with intervening blocks/entities intact.
            hit = pick(mc, pos, null);
            if (hit != null) return hit;
        }
        // All candidates were occluded/out of range. Keep the old failed-action view.
        aim(mc, center);
        pick(mc, pos, null);
        return null;
    }

    private static void observeBreak(Minecraft mc, RuntimeAction a) {
        BlockPos pos = pos(a.entry.request.target());
        if (mc.level.getBlockState(pos).isAir()) {
            a.entry.result.addProperty("observed_block", "minecraft:air");
            finish("succeeded", "block_broken_observed");
        }
    }

    private static void preparePlacement(Minecraft mc, RuntimeAction a) {
        if (a.dispatched) return;
        BlockPos support = pos(a.entry.request.support());
        if (!mc.level.hasChunkAt(support)) { finish("failed", "chunk_not_loaded"); return; }
        Direction face = Direction.valueOf(a.entry.request.face().toUpperCase(Locale.ROOT));
        Vec3 aim = Vec3.atCenterOf(support).add(face.getStepX() * 0.5, face.getStepY() * 0.5, face.getStepZ() * 0.5);
        aim(mc, aim);
        // One normal jump; wait for the player's collision box to clear the placement cell.
        if (a.entry.request.jump() && !a.jumped && a.player.onGround()) {
            a.jump = true;
            a.jumped = true;
        }
    }

    private static void place(Minecraft mc, RuntimeAction a) {
        BlockPos support = pos(a.entry.request.support());
        Direction face = Direction.valueOf(a.entry.request.face().toUpperCase(Locale.ROOT));
        BlockPos target = support.relative(face);
        if (a.dispatched) {
            if (mc.level.getBlockState(target).getBlock() == a.placedBlock) {
                a.entry.result.addProperty("observed_block", BuiltInRegistries.BLOCK.getKey(a.placedBlock).toString());
                // For a pillar step, leave the action running until ordinary physics lands us.
                if (!a.entry.request.jump() || a.player.onGround()) finish("succeeded", "block_placed_observed");
            } else if (a.entry.ticks - a.dispatchTick >= 10) {
                finish("failed", "placement_not_observed");
            }
            return;
        }
        if (!(a.player.getMainHandItem().getItem() instanceof BlockItem item)) {
            finish("failed", "held_item_is_not_block"); return;
        }
        if (a.entry.request.jump() && a.player.getBoundingBox().intersects(new AABB(target))) return;
        // Re-aim after physics moved the eye position this tick (essential for underfoot placement).
        aim(mc, Vec3.atCenterOf(support).add(face.getStepX() * 0.5, face.getStepY() * 0.5, face.getStepZ() * 0.5));
        BlockHitResult hit = pick(mc, support, face);
        if (hit == null) { finish("failed", "support_face_not_in_reach_or_visible"); return; }
        BlockPlaceContext placement = new BlockPlaceContext(a.player, InteractionHand.MAIN_HAND, a.player.getMainHandItem(), hit);
        if (!placement.getClickedPos().equals(target) || !placement.canPlace()) {
            finish("failed", "placement_target_not_available"); return;
        }
        var event = ClientHooks.onClickInput(1, mc.options.keyUse, InteractionHand.MAIN_HAND);
        if (event.isCanceled()) { finish("failed", "use_cancelled_by_mod"); return; }
        // Exactly one ordinary client interaction. A missing response is never an excuse to replay it.
        a.dispatched = true;
        a.dispatchTick = a.entry.ticks;
        a.placedBlock = item.getBlock();
        a.entry.result.addProperty("dispatched", true);
        a.entry.result.add("target", cellJson(target));
        int beforeCount = a.player.getMainHandItem().getCount();
        InteractionResult result = mc.gameMode.useItemOn(a.player, InteractionHand.MAIN_HAND, hit);
        a.entry.result.addProperty("interaction_result", result.name().toLowerCase(Locale.ROOT));
        if (result.shouldSwing() && event.shouldSwingHand()) {
            a.player.swing(InteractionHand.MAIN_HAND);
            if (a.player.getMainHandItem().getCount() != beforeCount || mc.gameMode.hasInfiniteItems())
                mc.gameRenderer.itemInHandRenderer.itemUsed(InteractionHand.MAIN_HAND);
        }
        if (result == InteractionResult.FAIL) finish("failed", "placement_rejected");
    }

    private static void clickSlot(Minecraft mc, RuntimeAction a) {
        var request = a.entry.request;
        var menu = a.player.containerMenu;
        if (menu.containerId != request.containerId()) { finish("failed", "container_changed"); return; }
        if (request.slot() != -999 && (request.slot() < 0 || request.slot() >= menu.slots.size())) {
            finish("failed", "slot_out_of_range"); return;
        }
        if (!a.dispatched) {
            a.dispatched = true;
            a.dispatchTick = a.entry.ticks;
            a.entry.result.addProperty("dispatched", true);
            mc.gameMode.handleInventoryMouseClick(menu.containerId, request.slot(), request.button(),
                    ClickType.valueOf(request.clickType().toUpperCase(Locale.ROOT)), a.player);
            a.entry.result.add("menu", BridgeServer.menuSnapshot(menu));
            finish("succeeded", "click_dispatched");
        }
    }

    private static BlockHitResult pick(Minecraft mc, BlockPos expected, Direction face) {
        mc.gameRenderer.pick(1.0F);
        if (!(mc.hitResult instanceof BlockHitResult hit) || hit.getType() != HitResult.Type.BLOCK
                || !hit.getBlockPos().equals(expected) || (face != null && hit.getDirection() != face)) return null;
        if (aEyeDistance(mc, hit) > mc.player.blockInteractionRange()) return null;
        return hit;
    }
    private static double aEyeDistance(Minecraft mc, BlockHitResult hit) {
        return mc.player.getEyePosition().distanceTo(hit.getLocation());
    }
    private static void aim(Minecraft mc, Vec3 target) {
        Vec3 d = target.subtract(mc.player.getEyePosition());
        look(mc, (float) Math.toDegrees(Math.atan2(-d.x, d.z)),
                (float) -Math.toDegrees(Math.atan2(d.y, Math.hypot(d.x, d.z))));
    }
    private static void look(Minecraft mc, float yaw, float pitch) {
        mc.player.setYRot(yaw);
        mc.player.setXRot(Math.max(-90, Math.min(90, pitch)));
        mc.player.setYHeadRot(yaw);
    }
    private static BlockPos pos(ClientActionRequest.Cell p) { return new BlockPos(p.x(), p.y(), p.z()); }
    private static JsonObject cellJson(BlockPos pos) {
        JsonObject j = new JsonObject();
        j.addProperty("x", pos.getX()); j.addProperty("y", pos.getY()); j.addProperty("z", pos.getZ());
        return j;
    }
    private static void finish(String status, String reason) {
        RuntimeAction a = active;
        if (a == null) return;
        active = null;
        a.entry.result.addProperty("x", a.player.getX());
        a.entry.result.addProperty("y", a.player.getY());
        a.entry.result.addProperty("z", a.player.getZ());
        if (a.input != null) {
            a.input.forwardImpulse = a.input.leftImpulse = 0;
            a.input.up = a.input.down = a.input.left = a.input.right = a.input.jumping = a.input.shiftKeyDown = false;
        }
        boolean released = true;
        if (a.transfer != null) released &= cleanup(a.transfer::release);
        if (a.boat != null) released &= cleanup(() -> a.boat.release(Minecraft.getInstance()));
        if (a.combat != null) released &= cleanup(() -> a.combat.release(Minecraft.getInstance()));
        released &= cleanup(() -> sprint(Minecraft.getInstance(),a,false));
        if (a.attackHeld) {
            released &= cleanup(() -> {
                Minecraft mc = Minecraft.getInstance();
                mc.options.keyAttack.setDown(false);
                if (mc.gameMode != null) mc.gameMode.stopDestroyBlock();
            });
        }
        // A cleanup failure must not leave a previously published success.
        if(a.combat!=null) a.combat.terminal(released?status:"failed",released?reason:"input_release_unconfirmed");
        ACTIONS.finishAfterCleanup(status, reason, released);
        EncounterTerminalPause.afterTerminal(a.entry, ACTIONS.session, BridgeServer::pauseEncounterTerminalOnGameThread);
    }
    private static boolean cleanup(Runnable release) {
        try { release.run(); return true; }
        catch (RuntimeException failure) {
            BridgeLog.LOGGER.warn("Client input release unconfirmed: {}", failure.getClass().getSimpleName());
            return false;
        }
    }
    private static void failException(RuntimeException failure) {
        BridgeLog.LOGGER.warn("Client action failed: {}", failure.getClass().getSimpleName());
        finish("failed", "client_action_error");
    }
    private static void requireThread(Minecraft mc) {
        if (!mc.isSameThread()) throw new IllegalStateException("minecraft_thread_required");
    }
    private ClientActions() { }
}

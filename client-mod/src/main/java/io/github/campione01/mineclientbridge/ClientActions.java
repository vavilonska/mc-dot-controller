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
        Input input;
        float forward;
        boolean jump, sneak, attackHeld, dispatched, jumped;
        int waypoint, dispatchTick, unchangedTicks;
        double bestDistance = Double.POSITIVE_INFINITY;
        Block initialBlock, placedBlock;
        RuntimeAction(ActionRegistry.Entry entry, Minecraft mc) {
            this.entry = entry;
            player = mc.player;
            level = mc.level;
            deadline = System.nanoTime() + entry.request.timeoutMs() * 1_000_000L;
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
        // Transfer ownership once. A direct request later releases only this action's inputs.
        BridgeServer.releaseAllInputs();
        active = new RuntimeAction(ACTIONS.begin(request), mc);
        active.entry.result.addProperty("world_generation", WorldGeneration.current(mc.level));
        if (request.hotbarSlot() >= 0) mc.player.getInventory().selected = request.hotbarSlot();
        return ACTIONS.status(request.id());
    }

    static JsonObject status(String id) { requireThread(Minecraft.getInstance()); return ACTIONS.status(id); }
    static String session() { return ACTIONS.session; }
    static boolean ownsInput() { return active != null; }
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

    private static boolean context(Minecraft mc) {
        if (active == null) return false;
        if (mc.player != active.player || mc.level != active.level || mc.gameMode == null) {
            finish("cancelled", "world_transition"); return false;
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
        if (!context(mc)) return;
        try {
            RuntimeAction a = active;
            a.entry.ticks++;
            a.forward = 0;
            a.jump = false;
            a.sneak = a.entry.request.sneak();
            if (mc.isPaused()) return;
            switch (a.entry.request.action()) {
                case "follow_path" -> followPath(mc, a);
                case "break_block" -> mine(mc, a);
                case "place_block" -> preparePlacement(mc, a);
                case "click_slot" -> { }
            }
        } catch (RuntimeException failure) {
            failException(failure);
        }
    }

    private static void input(MovementInputUpdateEvent event) {
        RuntimeAction a = active;
        if (a == null || event.getEntity() != a.player || !context(Minecraft.getInstance())) return;
        Input input = event.getInput();
        a.input = input;
        input.forwardImpulse = a.forward;
        input.leftImpulse = 0;
        input.up = a.forward > 0;
        input.down = input.left = input.right = false;
        input.jumping = a.jump;
        input.shiftKeyDown = a.sneak;
    }

    private static void postTick() {
        Minecraft mc = Minecraft.getInstance();
        if (!context(mc) || mc.isPaused()) return;
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
            PathSteering.Step step = PathSteering.toward(a.player.getX(), a.player.getY(), a.player.getZ(),
                    a.player.getYRot(), a.player.onGround(), a.player.horizontalCollision, points.get(a.waypoint));
            if (step.reached()) { a.waypoint++; a.bestDistance = Double.POSITIVE_INFINITY; a.unchangedTicks = 0; continue; }
            a.entry.result.addProperty("waypoint_index", a.waypoint);
            a.entry.result.addProperty("waypoint_count", points.size());
            a.entry.result.addProperty("distance_to_waypoint", step.distance());
            look(mc, step.yaw(), a.player.getXRot());
            a.forward = step.forward();
            a.jump = step.jump();
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
        ACTIONS.finish(status, reason);
        a.entry.result.addProperty("x", a.player.getX());
        a.entry.result.addProperty("y", a.player.getY());
        a.entry.result.addProperty("z", a.player.getZ());
        if (a.input != null) {
            a.input.forwardImpulse = a.input.leftImpulse = 0;
            a.input.up = a.input.down = a.input.left = a.input.right = a.input.jumping = a.input.shiftKeyDown = false;
        }
        if (a.attackHeld) {
            Minecraft mc = Minecraft.getInstance();
            mc.options.keyAttack.setDown(false);
            if (mc.gameMode != null) mc.gameMode.stopDestroyBlock();
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

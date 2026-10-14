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
    // Call-stack guard only, never an alternative owner; survives hook cancellation until native use unwinds.
    private static RuntimeAction scopedDispatchInFlight;
    private static boolean installed;
    private static long ownershipRevision;

    private static final class RuntimeAction {
        final ActionRegistry.Entry entry;
        final LocalPlayer player;
        final ClientLevel level;
        final long deadline;
        final long navigationEpoch;
        final BoundedCombat combat;
        final BoundedBoatDrive boat;
        final BoundedBoatTransfer transfer;
        final CoordinationStepGuard coordinationStep;
        final CapabilityGuard capabilityGuard;
        final CapabilityTargetAction capabilityTarget;
        ScopedNativePreflight.Capture scopedBlockMenu;
        boolean scopedPacketPending;
        BlockHitResult scopedPacketHit;
        ScopedFlatMovement scopedMovement;
        ScopedMining scopedMining;
        ScopedPlacement scopedPlacement;
        ScopedCombat scopedCombat;
        boolean useHeld;
        boolean left, right;
        Input input;
        float forward;
        boolean jump, sneak, attackHeld, dispatched, jumped;
        int waypoint, dispatchTick, unchangedTicks, dryTicks, placedStableTicks, placementBeforeCount, useBeforeCount;
        boolean recoveryStalled;
        boolean waypointJumped, sprintHeld;
        int settledTicks;
        double bestDistance = Double.POSITIVE_INFINITY;
        Block initialBlock, placedBlock;
        RuntimeAction(ActionRegistry.Entry entry, Minecraft mc, BoundedCombat combat, BoundedBoatDrive boat, BoundedBoatTransfer transfer, long combatDeadline, CoordinationStepGuard coordinationStep, long coordinationDeadline, CapabilityGuard capabilityGuard, CapabilityTargetAction capabilityTarget) {
            this.entry = entry;
            this.combat = combat;
            this.boat = boat;
            this.transfer = transfer;
            this.coordinationStep = coordinationStep;
            this.capabilityGuard=capabilityGuard;this.capabilityTarget=capabilityTarget;
            player = mc.player;
            level = mc.level;
            navigationEpoch = NavigationPositionGuard.epoch();
            // Opt-in coordination includes admission work in its bounded lifetime.
            // All legacy owners retain the original deadline expression and timing.
            if (coordinationStep != null) deadline=coordinationDeadline;
            else {
                deadline = combat != null ? combatDeadline : entry.request.timeoutMs() == 0 ? Long.MAX_VALUE
                    : System.nanoTime() + entry.request.timeoutMs() * 1_000_000L;
            }
        }
    }

    static synchronized void install() {
        if (installed) return;
        NeoForge.EVENT_BUS.addListener(ClientTickEvent.Pre.class, event -> preTick());
        NeoForge.EVENT_BUS.addListener(ClientTickEvent.Post.class, event -> postTick());
        NeoForge.EVENT_BUS.addListener(EventPriority.LOWEST, false, MovementInputUpdateEvent.class, ClientActions::input);
        NeoForge.EVENT_BUS.addListener(ClientPlayerNetworkEvent.LoggingOut.class, event -> {
            IntegratedServerIdentity.clear();cancel("world_transition");
        });
        NeoForge.EVENT_BUS.addListener(ClientPlayerNetworkEvent.Clone.class, event -> cancel("player_changed"));
        NeoForge.EVENT_BUS.addListener(LevelEvent.Unload.class, event -> {
            if (event.getLevel().isClientSide()) { MovementBudget.interrupt("movement_budget_context_changed"); cancel("world_transition"); }
        });
        installed = true;
    }

    static JsonObject start(ClientActionRequest request) { return start(request, null); }

    static JsonObject start(ClientActionRequest request, ScopedNativePreflight.Capture scoped) {
        Minecraft mc = Minecraft.getInstance();
        requireThread(mc);
        ActionRegistry.Entry old = ACTIONS.existing(request);
        if (old != null) return status(request.id());
        if (active != null) throw new ClientActionRequest.Rejected(409, "action_busy");
        if (mc.player == null || mc.level == null || mc.gameMode == null)
            throw new ClientActionRequest.Rejected(409, "not_in_world");
        if (request.original().has("expected_world_generation")
                && !ClientActionRequest.string(request.original(),"expected_world_generation").equals(WorldGeneration.current(mc.level)))
            throw new ClientActionRequest.Rejected(409,request.action().equals("combat_entity")
                    ? "action_world_changed" : "world_generation_changed");
        if (request.original().has("expected_action_session")
                && !ClientActionRequest.string(request.original(),"expected_action_session").equals(ACTIONS.session))
            throw new ClientActionRequest.Rejected(409,"action_session_changed");
        if (request.original().has("expected_player_uuid")
                && !ClientActionRequest.string(request.original(),"expected_player_uuid").equals(mc.player.getUUID().toString()))
            throw new ClientActionRequest.Rejected(409,request.action().equals("combat_entity")
                    ? "action_player_changed" : "player_changed");
        MovementBudget.admission(mc,request);
        long capabilityOwnerRevision=ownershipRevision;
        CapabilityGuard capabilityGuard=CapabilityGuard.start(mc,request);
        CapabilityTargetAction capabilityTarget=SetCapabilityTarget(request.action())?CapabilityTargetAction.start(mc,request.original()):null;
        boolean coordinationRequested = CoordinationStepGuard.requested(request.original());
        long coordinationOwnerRevision = ownershipRevision;
        LocalPlayer coordinationPlayer = mc.player;
        ClientLevel coordinationLevel = mc.level;
        long coordinationDeadline = coordinationRequested
                ? System.nanoTime()+request.timeoutMs()*1_000_000L : 0;
        NavigationPositionGuard.requireBinding(mc, request);
        EncounterRequest encounterRequest=request.action().equals("combat_entity")?EncounterRequest.parseOptional(request.original()):null;
        if (encounterRequest!=null && !EncounterRequest.runtimeEnabled(encounterRequest.mode()))
            throw new ClientActionRequest.Rejected(409,EncounterRequest.THREE_MODE.equals(encounterRequest.mode())
                    ?"encounter_three_zombie_disabled":"encounter_stage1_disabled");
        if (EncounterRequest.pauseRequested(request.original())) BridgeServer.requireEncounterPauseAdmission();
        long combatDeadline = request.action().equals("combat_entity")
                ? System.nanoTime()+request.timeoutMs()*1_000_000L : 0;
        JsonObject combatEvidence = new JsonObject();
        BoundedCombat combat = request.action().equals("combat_entity")
                ? new BoundedCombat(mc, BoundedCombatRequest.parse(request.original()), combatEvidence, combatDeadline) : null;
        JsonObject boatEvidence = new JsonObject();
        BoundedBoatDrive boat = request.action().equals("boat_drive")
                ? new BoundedBoatDrive(mc, BoatDriveRequest.parse(request.original()), boatEvidence) : null;
        JsonObject transferEvidence = new JsonObject();
        BoundedBoatTransfer transfer = request.action().equals("boat_mount") || request.action().equals("boat_dismount")
                ? new BoundedBoatTransfer(mc, BoatTransferRequest.parse(request.original()), transferEvidence) : null;
        if (coordinationRequested) {
            if (active != null || ownershipRevision != coordinationOwnerRevision
                    || mc.player != coordinationPlayer || mc.level != coordinationLevel)
                throw new ClientActionRequest.Rejected(409,"coordination_step_owner_changed");
            if (System.nanoTime() >= coordinationDeadline)
                throw new ClientActionRequest.Rejected(409,"coordination_step_deadline_exceeded");
        }
        CoordinationStepGuard coordinationStep = CoordinationStepGuard.start(mc, request);
        if (coordinationStep != null) {
            if (active != null || ownershipRevision != coordinationOwnerRevision
                    || mc.player != coordinationPlayer || mc.level != coordinationLevel)
                throw new ClientActionRequest.Rejected(409,"coordination_step_owner_changed");
            if (System.nanoTime() >= coordinationDeadline)
                throw new ClientActionRequest.Rejected(409,"coordination_step_deadline_exceeded");
            NavigationPositionGuard.requireBinding(mc, request);
            if (active != null || ownershipRevision != coordinationOwnerRevision
                    || mc.player != coordinationPlayer || mc.level != coordinationLevel
                    || coordinationStep.afterHooks(mc)!=null)
                throw new ClientActionRequest.Rejected(409,"coordination_step_context_changed");
            coordinationStep.requireFresh(mc); // Original sample, after every admission hook.
            if (active != null || ownershipRevision != coordinationOwnerRevision
                    || mc.player != coordinationPlayer || mc.level != coordinationLevel
                    || coordinationStep.afterHooks(mc)!=null)
                throw new ClientActionRequest.Rejected(409,"coordination_step_context_changed");
            if (System.nanoTime() >= coordinationDeadline)
                throw new ClientActionRequest.Rejected(409,"coordination_step_deadline_exceeded");
        }
        if(capabilityGuard!=null) {
            if(active!=null || ownershipRevision!=capabilityOwnerRevision)throw new ClientActionRequest.Rejected(409,"capability_owner_changed");
            if (scoped != null) scoped.recheck(mc);
            capabilityGuard.requireFresh(mc,"before_input_release");
            String denied=capabilityGuard.check(mc,false);
            if(denied!=null)throw new ClientActionRequest.Rejected(409,denied);
        }
        // Transfer ownership once. A direct request later releases only this action's inputs.
        if (coordinationStep == null) BridgeServer.releaseAllInputs();
        else CoordinationStepPolicy.transfer(BridgeServer::releaseAllInputs, () -> {
            NavigationPositionGuard.requireBinding(mc, request); // Original epoch/origin, never the post-hook epoch.
            if (active != null || ownershipRevision != coordinationOwnerRevision
                    || mc.player != coordinationPlayer || mc.level != coordinationLevel
                    || coordinationStep.afterHooks(mc)!=null)
                throw new IllegalStateException("coordination_step_owner_changed_after_transfer");
            coordinationStep.requireFresh(mc);
            if (active != null || ownershipRevision != coordinationOwnerRevision
                    || mc.player != coordinationPlayer || mc.level != coordinationLevel
                    || coordinationStep.afterHooks(mc)!=null)
                throw new IllegalStateException("coordination_step_owner_changed_after_transfer");
            if (System.nanoTime() >= coordinationDeadline)
                throw new IllegalStateException("coordination_step_deadline_exceeded_after_transfer");
        });
        if(capabilityGuard!=null) {
            if(active!=null || ownershipRevision!=capabilityOwnerRevision)throw new ClientActionRequest.Rejected(409,"capability_owner_changed");
            if (scoped != null) scoped.recheck(mc);
            capabilityGuard.requireFresh(mc,"after_input_release");
            String denied=capabilityGuard.check(mc,false);
            if(denied!=null)throw new ClientActionRequest.Rejected(409,denied);
        }
        MovementBudget.admission(mc,request); // Recheck original binding after all admission hooks.
        if((MovementBudget.armed()||MovementBudget.budgetAction(request.action()))
                &&(active!=null||ownershipRevision!=capabilityOwnerRevision||mc.player!=coordinationPlayer||mc.level!=coordinationLevel))
            throw new ClientActionRequest.Rejected(409,"movement_budget_owner_changed");
        if (scoped != null) scoped.recheck(mc);
        ownershipRevision++;
        active = new RuntimeAction(ACTIONS.begin(request), mc, combat, boat, transfer, combatDeadline, coordinationStep, coordinationDeadline, capabilityGuard, capabilityTarget);
        if (scoped != null) {
            active.entry.result.add("scoped_native_preflight", scoped.witness(request.id()));
            active.scopedMovement = scoped.movement;
            if (active.scopedMovement != null) active.scopedMovement.activate(active.entry);
            active.scopedCombat=scoped.combat;
            if(active.scopedCombat!=null){active.scopedCombat.activate(active.entry);active.combat.bindScoped(active.scopedCombat);}
            active.scopedPlacement=scoped.placement;
            if(active.scopedPlacement!=null)active.scopedPlacement.activate(active.entry);
            active.scopedMining=scoped.mining;
            if(active.scopedMining!=null)active.scopedMining.activate(active.entry);
        }
        if (scoped != null && scoped.blockMenu()) {
            active.scopedBlockMenu = scoped; active.entry.result.addProperty("dispatched", false);
        }
        if (coordinationStep != null) active.entry.result.addProperty("coordination_step_schema_version",1);
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
        if(capabilityGuard!=null)capabilityGuard.activate();
        if(request.action().equals("movement_budget_start"))MovementBudget.start(mc,request);
        // block-menu-v1 owns exactly one synchronous interaction inside this admitted callback.
        // No asynchronous post-tick dispatch can extend its capture or replay a missing menu.
        if (scoped != null && scoped.blockMenu()) {
            RuntimeAction admitted = active;
            try { interactBlock(mc, admitted); }
            catch (RuntimeException failure) {
                if (active == admitted) failException(failure);
            }
        }
        return status(request.id());
    }

    static boolean scopedOwns(String actionId, long revision) {
        return active != null && active.entry.request.id().equals(actionId) && ownershipRevision == revision
            && !active.dispatched;
    }
    static void scopedBlockMenuPacketFence(LocalPlayer player, InteractionHand hand, BlockHitResult hit) {
        RuntimeAction a = scopedDispatchInFlight;
        if (a == null) return; // Legacy/manual calls outside a scoped dispatch remain unchanged.
        if (active != a || !a.scopedPacketPending || a.dispatched || player != a.player || hand != InteractionHand.MAIN_HAND
                || hit != a.scopedPacketHit || !ScopedBlockMenuDispatch.ready())
            throw new ClientActionRequest.Rejected(409, "block_menu_packet_owner_mismatch");
        Minecraft mc = Minecraft.getInstance();
        // Forge right-click, item-first, sneak-bypass and block-use hooks have returned.
        // This cannot undo arbitrary hook effects. A late failure is an unknown outcome.
        if (!capabilityDispatchCheck(mc, a)) throw new ClientActionRequest.Rejected(409, "block_menu_packet_guard_changed");
        BlockHitResult finalHit = a.scopedBlockMenu.beforeBlockMenuEffect(mc, a.entry.request.id());
        if (!BlockMenuPreflight.hitMatches(hit, finalHit.getBlockPos(), finalHit.getDirection(), finalHit.getLocation()))
            throw new ClientActionRequest.Rejected(409, "block_menu_packet_hit_changed");
        a.entry.result.add("scoped_native_preflight", a.scopedBlockMenu.witness(a.entry.request.id()));
        a.dispatched = true; a.entry.result.addProperty("dispatched", true);
        a.scopedPacketPending = false;
    }
    private static boolean SetCapabilityTarget(String action) { return action.equals("attack_entity") || action.equals("shoot_entity"); }
    static void markCapabilityDispatched(CapabilityTargetAction target) {
        if(active==null||active.capabilityTarget!=target)throw new IllegalStateException("target_owner_changed");
        active.dispatched=true;
    }
    static boolean ownsScopedMovement(ScopedFlatMovement movement,ActionRegistry.Entry entry) {
        return active!=null && active.scopedMovement==movement && active.entry==entry
                && ACTIONS.active()==entry && entry!=null && entry.running();
    }
    static boolean ownsCapabilityTarget(CapabilityTargetAction target) { return active!=null && active.capabilityTarget==target; }
    static JsonObject status(String id) { requireThread(Minecraft.getInstance()); JsonObject j=ACTIONS.status(id);j.add("movement_budget",MovementBudget.snapshot(Minecraft.getInstance()));return j; }
    /** Recheck a coherent read without creating another movement-budget boundary sample. */
    static JsonObject statusWithoutObservation() { requireThread(Minecraft.getInstance()); JsonObject j=ACTIONS.status(null);j.add("movement_budget",MovementBudget.snapshot());return j; }
    static String session() { return ACTIONS.session; }
    static boolean ownsInput() { return active != null; }
    static long ownershipRevision() { return ownershipRevision; }
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
        return status(id);
    }
    static void directTakeover() {
        requireThread(Minecraft.getInstance());
        ownershipRevision++;
        MovementBudget.interrupt("movement_budget_direct_takeover");
        cancel("direct_takeover");
        GuardedGameMovement.cancelOnGameThread("direct_takeover");
    }
    static void cancel(String reason) {
        Minecraft mc = Minecraft.getInstance();
        if (!mc.isSameThread()) { mc.execute(() -> cancel(reason)); return; }
        if (active != null) finish("cancelled", reason);
    }

    private static boolean context(Minecraft mc,String phase) {
        RuntimeAction a=active;
        try{return contextChecked(mc,phase);}
        catch(RuntimeException failure){
            if(a!=null && a.scopedPlacement!=null){if(active==a)finish("cancelled","placement_context_hook_failed");return false;}
            if(a!=null && a.scopedMining!=null){scopedMiningUnknown(a.scopedMining,"mining_context_hook_failed");return false;}
            throw failure;
        }
    }
    private static boolean contextChecked(Minecraft mc,String phase) {
        if (active == null) return false;
        RuntimeAction enteredOwner = active;
        String budgetProblem=MovementBudget.problem(mc);
        if(active!=enteredOwner)return false;
        if(budgetProblem!=null&&!enteredOwner.entry.request.action().equals("movement_budget_finish")){finish("cancelled",budgetProblem);return false;}
        if(budgetProblem!=null&&MovementBudget.snapshot().get("status").getAsString().equals("invalid")){finish("cancelled",budgetProblem);return false;}
        double enteredX=enteredOwner.coordinationStep==null?0:enteredOwner.player.getX();
        double enteredY=enteredOwner.coordinationStep==null?0:enteredOwner.player.getY();
        double enteredZ=enteredOwner.coordinationStep==null?0:enteredOwner.player.getZ();
        if (mc.player != active.player || mc.level != active.level || mc.gameMode == null) {
            String reason="world_transition";
            if(enteredOwner.capabilityGuard!=null)reason=mc.player!=null && mc.level!=enteredOwner.level
                    && mc.player.getUUID().equals(enteredOwner.player.getUUID())?"capability_world_changed":"capability_context_changed";
            finish("cancelled", reason); return false;
        }
        if(enteredOwner.capabilityGuard!=null) {
            String denied=enteredOwner.capabilityGuard.check(mc,enteredOwner.dispatched);
            if(active!=enteredOwner)return false;
            if(denied!=null && !(enteredOwner.scopedCombat!=null && denied.equals("capability_health_guard"))){finish("cancelled",denied);return false;}
        }
        NavigationPositionGuard.observe(mc);
        if (active != enteredOwner) return false;
        if (enteredOwner.coordinationStep != null && (mc.player != enteredOwner.player || mc.level != enteredOwner.level
                || enteredOwner.player.getX()!=enteredX || enteredOwner.player.getY()!=enteredY || enteredOwner.player.getZ()!=enteredZ)) {
            finish("cancelled","coordination_step_context_changed"); return false;
        }
        if (NavigationPositionGuard.applies(active.entry.request.action())
                && active.navigationEpoch != NavigationPositionGuard.epoch()) {
            RuntimeAction epochOwner = active;
            JsonObject guardSnapshot = NavigationPositionGuard.snapshot(mc);
            if (active != epochOwner) return false;
            epochOwner.entry.result.add("navigation_guard", guardSnapshot);
            finish("cancelled", "position_discontinuity_rebind_required"); return false;
        }
        if (active.combat!=null && active.combat.isEncounter()) {
            String interruption=BoundedEncounter.lifecycle(mc.isPaused(),mc.isWindowActive(),mc.player.isSpectator());
            if(interruption!=null) { finish("cancelled",interruption);return false; }
            interruption=active.combat.encounterCallbackInterruption(System.nanoTime(),phase);
            if(interruption!=null) { finish("failed",interruption);return false; }
        }
        if (active.coordinationStep != null) {
            RuntimeAction checkedOwner = active;
            String denied;
            try { denied=checkedOwner.coordinationStep.check(mc); }
            catch (RuntimeException failure) { denied="coordination_step_check_failed"; }
            if (active != checkedOwner) return false;
            if (mc.player != checkedOwner.player || mc.level != checkedOwner.level) denied="coordination_step_context_changed";
            if (denied==null) {
                NavigationPositionGuard.observe(mc);
                if (active != checkedOwner) return false;
                if (mc.player != checkedOwner.player || mc.level != checkedOwner.level
                        || checkedOwner.navigationEpoch != NavigationPositionGuard.epoch()) denied="coordination_step_context_changed";
                else denied=checkedOwner.coordinationStep.afterHooks(mc);
            }
            if (denied!=null) { finish("cancelled",denied); return false; }
        }
        if (!mc.player.isAlive()) { finish("failed", "player_unavailable"); return false; }
        if (System.nanoTime() >= active.deadline) { finish("failed", "deadline_exceeded"); return false; }
        if (!active.entry.request.action().equals("click_slot") && !active.entry.request.action().equals("close_menu")
                && !(active.entry.request.action().equals("interact_block") && active.dispatched) && mc.screen != null) {
            finish("cancelled", "screen_opened"); return false;
        }
        return true;
    }

    private static void preTick() {
        Minecraft mc = Minecraft.getInstance();
        MovementBudget.preTick(mc);
        NavigationPositionGuard.tick(mc);
        if (!context(mc,"pre_tick")) return;
        RuntimeAction entered=active;
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
                case "recover_environment" -> recoverEnvironment(mc, a);
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
                case "place_block" -> { if(a.capabilityGuard!=null)prepareCapabilityPlacement(mc,a);else preparePlacement(mc,a); }
                case "click_slot", "interact_block", "use_item", "select_hotbar", "close_menu", "gateway_pearl", "movement_budget_start", "movement_budget_finish" -> { }
                case "attack_entity", "shoot_entity" -> {
                    CapabilityTargetAction.Step step;
                    try { step=a.capabilityTarget.tick(mc); }
                    catch (RuntimeException failure) { if (active == a) failException(failure); return; }
                    if(active!=a)return;
                    a.entry.result.add("target_action",step.evidence());
                    if(step.status()!=null)finish(step.status(),step.reason());
                }
                case "combat_entity" -> {
                    BoundedCombat.Step step = a.combat.tick(mc, a.entry.ticks);
                    if(active!=a)return; // A native hook may cancel or replace this exact owner.
                    a.entry.result.addProperty("phase", step.reason());
                    JsonObject phases = a.entry.result.getAsJsonObject("phase_ticks");
                    phases.addProperty(step.reason(), phases.has(step.reason()) ? phases.get(step.reason()).getAsInt()+1 : 1);
                    a.forward = step.forward();
                    if (step.terminal() != null) finish(step.terminal(), step.reason());
                }
            }
        } catch (RuntimeException failure) {
            if(active==entered)failException(failure);
        }
    }

    private static void input(MovementInputUpdateEvent event) {
        RuntimeAction a = active;
        MovementBudget.checkInput(Minecraft.getInstance(),event.getInput(),a!=null&&event.getEntity()==a.player);
        if(active!=a)return;
        if (a == null || event.getEntity() != a.player || !context(Minecraft.getInstance(),"movement_input")) return;
        if (a.transfer != null) {
            try {
                String reason = a.transfer.inputRejection(Minecraft.getInstance());
                if (active != a) return;
                if (reason != null) { finish("failed", reason); return; }
            } catch (RuntimeException failure) { if (active == a) failException(failure); return; }
        }
        Input input = event.getInput();
        if(a.scopedCombat!=null){
            try {ScopedCombat.require(ScopedFlatMovement.neutral(input),"scoped_combat_external_movement_input");
                a.scopedCombat.check(Minecraft.getInstance(),false);a.combat.beforeScopedMovement(Minecraft.getInstance(),a.forward);
                if(active!=a)return; a.scopedCombat.check(Minecraft.getInstance(),false);
                if(input!=a.player.input || event.getInput()!=input || !ScopedFlatMovement.neutral(input))throw new ClientActionRequest.Rejected(409,"scoped_combat_input_identity_changed");
            } catch(RuntimeException failed){if(active==a)finish("cancelled","scoped_combat_movement_revalidation_failed");return;}
        }
        if(a.scopedMovement!=null) {
            try {
                if(input!=a.player.input || !ScopedFlatMovement.neutral(input))
                    throw new ClientActionRequest.Rejected(409,"scoped_movement_external_input");
                a.scopedMovement.beforeEffect(Minecraft.getInstance());
                if(active!=a)return;
                if(input!=a.player.input || !ScopedFlatMovement.neutral(input))
                    throw new ClientActionRequest.Rejected(409,"scoped_movement_input_changed_after_hooks");
                a.dispatched=true; a.scopedMovement.markAttempted();
            } catch(RuntimeException failed) { if(active==a)finish("cancelled",ScopedFlatMovement.rejection(failed));return; }
        }
        if(a.scopedMining!=null) {
            ScopedMining guard=a.scopedMining;
            try {
                if(input!=a.player.input || !ScopedMining.neutral(input))throw new ScopedMining.Refused("mining_input_identity_or_neutrality_changed");
                guard.check(Minecraft.getInstance(),true,!guard.targetAir());
                if(active!=a || event.getInput()!=input || input!=a.player.input || !ScopedMining.neutral(input))
                    throw new ScopedMining.Refused("mining_input_changed_after_hooks");
            } catch(RuntimeException failure){scopedMiningUnknown(guard,"mining_input_context_unconfirmed");return;}
        }
        if(a.scopedPlacement!=null) {
            try {a.scopedPlacement.check(Minecraft.getInstance(),a.dispatched,false);
                if(active!=a||event.getInput()!=input||input!=a.player.input||!ScopedMining.neutral(input))
                    throw new ClientActionRequest.Rejected(409,"placement_input_changed_after_hooks");
            } catch(RuntimeException failure){if(active==a)finish("cancelled","placement_input_context_unconfirmed");return;}
        }
        a.input = input;
        input.forwardImpulse = a.forward;
        input.leftImpulse = a.left ? 1 : a.right ? -1 : 0;
        input.up = a.forward > 0;
        input.down = a.forward < 0;
        if (a.boat == null) input.left = input.right = false;
        else { input.left = a.left; input.right = a.right; }
        input.jumping = a.jump;
        input.shiftKeyDown = a.transfer != null ? a.transfer.sneakInput(Minecraft.getInstance()) : a.sneak;
        MovementBudget.checkInput(Minecraft.getInstance(),input,true);
        String budgetProblem=MovementBudget.problem(Minecraft.getInstance());
        if(active==a&&budgetProblem!=null)finish("cancelled",budgetProblem);
    }

    private static void postTick() {
        Minecraft mc = Minecraft.getInstance();
        MovementBudget.observe(mc,true);
        if (!context(mc,"post_tick") || mc.isPaused()) return;
        RuntimeAction entered=active;
        try {
            RuntimeAction a = entered;
            switch (a.entry.request.action()) {
                case "break_block" -> observeBreak(mc, a);
                case "place_block" -> { if(a.capabilityGuard!=null)placeCapability(mc,a);else place(mc,a); }
                case "click_slot" -> clickSlot(mc, a);
                case "interact_block" -> interactBlock(mc,a);
                case "use_item" -> useItem(mc,a);
                case "gateway_pearl" -> gatewayPearl(mc,a);
                case "select_hotbar" -> finish("succeeded","hotbar_selected_observed");
                case "close_menu" -> closeMenu(mc,a);
                case "movement_budget_start" -> { a.entry.result.add("movement_budget",MovementBudget.snapshot());finish("succeeded","movement_budget_started"); }
                case "movement_budget_finish" -> {
                    if(!capabilityDispatchCheck(mc,a))return;
                    if(!BridgeServer.heldInputsSnapshot(mc).get("neutral").getAsBoolean()){finish("failed","movement_budget_input_not_neutral");return;}
                    finish("succeeded","movement_budget_sealed");
                }
                default -> { }
            }
        } catch (RuntimeException failure) {
            if(entered.scopedPlacement==null || active==entered)failException(failure);
        }
    }

    private static void followPath(Minecraft mc, RuntimeAction a) {
        if(a.scopedMovement!=null) {
            try { a.scopedMovement.beforeEffect(mc); }
            catch(RuntimeException failed) { if(active==a)finish("cancelled",ScopedFlatMovement.rejection(failed));return; }
            if(active!=a)return;
        }
        var points = a.entry.request.waypoints();
        while (a.waypoint < points.size()) {
            String routeProblem=a.scopedMovement==null ? CapabilityPath.check(mc,a.entry.request,a.waypoint) : null;
            if(routeProblem!=null){finish("cancelled",routeProblem);return;}
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
            if(a.scopedMovement!=null) {
                try {
                    a.scopedMovement.beforeEffect(mc);
                    if(active!=a)return;
                    // Recompute pure steering after the last potentially effectful fact hook.
                    PathSteering.Step current=PathSteering.toward(a.player.getX(),a.player.getY(),a.player.getZ(),
                            a.player.getYRot(),a.player.onGround(),false,effectiveGoal,a.waypoint==points.size()-1);
                    step=current;
                    a.dispatched=true; a.scopedMovement.markAttempted();
                    a.player.setYRot(current.yaw()); // Sole view write after the final fact fence.
                } catch(RuntimeException failed) { if(active==a)finish("cancelled",ScopedFlatMovement.rejection(failed));return; }
                if(active!=a)return;
            } else look(mc, step.yaw(), a.entry.request.original().has("capability_route")?60:a.player.getXRot());
            a.forward = a.scopedMovement==null ? step.forward() : Math.min(.5F,step.forward());
            a.jump = a.scopedMovement==null && step.jump();
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

    /** Ordinary tick-owned inputs; external planner supplies only observed egress waypoints.
     * Empty/exhausted routes keep flotation, never interpret a model/message gap as key-up.
     * No world, position, velocity, inventory, or packet writes are introduced. */
    private static void recoverEnvironment(Minecraft mc, RuntimeAction a) {
        boolean water = a.player.isInWater();
        boolean powder = a.player.isInPowderSnow;
        var recovery = EnvironmentSteering.update(water,
                a.player.isEyeInFluid(net.minecraft.tags.FluidTags.WATER), a.player.isInLava(),
                powder, a.player.isOnFire(), a.player.onGround(), a.dryTicks);
        boolean hazardous = recovery.hazardous();
        a.jump = recovery.jump();
        a.entry.result.addProperty("environment_schema_version", 1);
        a.entry.result.addProperty("environment_hazard_observed", hazardous);
        // Frozen ticks can decay on dry land. Recovery never waits for full health/food/air.
        a.dryTicks = recovery.dryTicks();
        if (recovery.recovered()) {
            a.entry.result.addProperty("confirmation", "client_dry_observed");
            finish("succeeded", "environment_dry_observed");
            return;
        }
        var points = a.entry.request.waypoints();
        while (!a.recoveryStalled && a.waypoint < points.size()) {
            var step = PathSteering.toward(a.player.getX(), a.player.getY(), a.player.getZ(),
                    a.player.getYRot(), a.player.onGround(), a.player.horizontalCollision, points.get(a.waypoint));
            if (step.reached()) {
                a.waypoint++; a.bestDistance = Double.POSITIVE_INFINITY; a.unchangedTicks = 0;
                continue;
            }
            look(mc, step.yaw(), a.player.getXRot());
            a.forward = step.forward();
            a.jump = a.jump || step.jump();
            if (step.distance() < a.bestDistance - 0.04) {
                a.bestDistance = step.distance(); a.unchangedTicks = 0;
            } else if (++a.unchangedTicks >= 60) {
                // Keep flotation, stop futile horizontal pressure, ask the external planner.
                a.recoveryStalled = true; a.forward = 0;
            }
            break;
        }
        a.entry.result.addProperty("waypoint_index", a.waypoint);
        a.entry.result.addProperty("waypoint_count", points.size());
        a.entry.result.addProperty("environment_route_stalled", a.recoveryStalled);
        a.entry.result.addProperty("environment_waiting_for_route", a.recoveryStalled || a.waypoint >= points.size());
    }

    static boolean ownsScopedCombat(ScopedCombat guard,ActionRegistry.Entry entry){return active!=null && active.scopedCombat==guard
        && active.entry==entry && ACTIONS.active()==entry && entry!=null && entry.running();}
    static ScopedCombat scopedCombat(BoundedCombat combat){return active!=null && active.combat==combat?active.scopedCombat:null;}
    static boolean ownsCombat(BoundedCombat combat){return active!=null && active.combat==combat;}
    static boolean ownsScopedPlacement(ScopedPlacement g,ActionRegistry.Entry entry){return active!=null && active.scopedPlacement==g && active.entry==entry && ACTIONS.active()==entry && entry!=null && entry.running();}
    static ScopedMining scopedMining(){return active==null?null:active.scopedMining;}
    static boolean ownsScopedMining(ScopedMining g,ActionRegistry.Entry entry){return active!=null && active.scopedMining==g && active.entry==entry && ACTIONS.active()==entry && entry!=null && entry.running();}
    static boolean ownsScopedMining(ScopedMining g){return active!=null && active.scopedMining==g;}
    static void scopedMiningUnknown(ScopedMining g,String reason){
        g.markUnknown();
        if(ownsScopedMining(g)){active.entry.result.addProperty("unknown_outcome",true);finish("failed",reason);}
    }
    static void scopedMiningRemoved(ScopedMining g){
        if(!ownsScopedMining(g))return;
        if(!g.removalAdmissible()){scopedMiningUnknown(g,"mining_target_absent_before_attempt");return;}
        try {g.check(Minecraft.getInstance(),true,false);}
        catch(RuntimeException failure){scopedMiningUnknown(g,"mining_removal_context_unconfirmed");return;}
        active.entry.result.addProperty("observed_block","minecraft:air");finish("succeeded","block_broken_observed");
    }
    private static void mineScoped(Minecraft mc,RuntimeAction a) {
        ScopedMining g=a.scopedMining;
        try {
            if(g.targetAir()){scopedMiningRemoved(g);return;}
            g.check(mc,false,false);
            // Aim and renderer/mod callbacks may act; certainty is latched before the first one.
            g.markAttempted();a.entry.result.addProperty("effect_attempted",true);
            BlockHitResult hit=aimMiningTarget(mc,g.target,g);
            if(hit==null)throw new ScopedMining.Refused("mining_target_not_visible_or_reachable");
            if(active!=a)throw new ScopedMining.Refused("mining_owner_changed_after_aim");
            if(!capabilityDispatchCheck(mc,a))return;
            if(!mc.mouseHandler.isMouseGrabbed())mc.mouseHandler.grabMouse();
            g.check(mc,false,true);
            boolean first=!a.dispatched;a.dispatched=true;a.entry.result.addProperty("dispatched",true);
            a.attackHeld=true;mc.options.keyAttack.setDown(true);
            if(first)ScopedMiningDispatch.attack(g,mc::startAttack);
            if(active!=a)return;
            g.check(mc,true,!g.targetAir());
            if(g.targetAir()){scopedMiningRemoved(g);return;}
            a.entry.result.addProperty("destroy_stage",mc.gameMode.getDestroyStage());
        } catch(RuntimeException failure){scopedMiningUnknown(g,failure instanceof ScopedMining.Refused?failure.getMessage():"mining_check_failed");}
    }
    private static void mine(Minecraft mc, RuntimeAction a) {
        if(a.scopedMining!=null){mineScoped(mc,a);return;}
        BlockPos pos = pos(a.entry.request.target());
        if (!mc.level.hasChunkAt(pos)) { finish("failed", "chunk_not_loaded"); return; }
        if (mc.level.getBlockState(pos).isAir()) { finish("succeeded", "block_absent"); return; }
        if (a.initialBlock == null) a.initialBlock = mc.level.getBlockState(pos).getBlock();
        else if (mc.level.getBlockState(pos).getBlock() != a.initialBlock) { finish("failed", "target_changed"); return; }
        BlockHitResult hit = aimMiningTarget(mc, pos);
        if (hit == null) { finish("failed", "target_not_in_reach_or_visible"); return; }
        // One continuous ordinary attack hold; the client's keybind loop runs continueAttack.
        // Its block ray, NeoForge hooks, mining progress and server prediction remain vanilla.
        if(!capabilityDispatchCheck(mc,a))return;
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

    private static BlockHitResult aimMiningTarget(Minecraft mc, BlockPos pos) {return aimMiningTarget(mc,pos,null);}
    private static BlockHitResult aimMiningTarget(Minecraft mc, BlockPos pos,ScopedMining guard) {
        Vec3 center = Vec3.atCenterOf(pos);
        aimMiningPoint(mc, center,guard);
        BlockHitResult hit = pick(mc, pos, null);
        if (hit != null) return hit; // Preserve the existing fast path.
        Vec3 eye = mc.player.getEyePosition();
        for (MiningAimPoints.Point point : MiningAimPoints.facingFaces(
                pos.getX(), pos.getY(), pos.getZ(), eye.x, eye.y, eye.z)) {
            aimMiningPoint(mc, new Vec3(point.x(), point.y(), point.z()),guard);
            // Candidate coordinates never authorize mining: real picking must hit the
            // same block within ordinary reach, with intervening blocks/entities intact.
            hit = pick(mc, pos, null);
            if (hit != null) return hit;
        }
        // All candidates were occluded/out of range. Keep the old failed-action view.
        aimMiningPoint(mc, center,guard);
        pick(mc, pos, null);
        return null;
    }

    private static void aimMiningPoint(Minecraft mc,Vec3 point,ScopedMining guard) {
        if(guard==null){aim(mc,point);return;}
        Vec3 d=point.subtract(mc.player.getEyePosition());
        float yaw=(float)Math.toDegrees(Math.atan2(-d.x,d.z));
        float pitch=(float)-Math.toDegrees(Math.atan2(d.y,Math.hypot(d.x,d.z)));
        guard.check(mc,false,false);mc.player.setYRot(yaw);
        guard.check(mc,false,false);mc.player.setXRot(Math.max(-90,Math.min(90,pitch)));
        guard.check(mc,false,false);mc.player.setYHeadRot(yaw);
        guard.check(mc,false,false);
    }
    private static void observeBreak(Minecraft mc, RuntimeAction a) {
        if(a.scopedMining!=null){
            try {a.scopedMining.check(mc,true,!a.scopedMining.targetAir());
                if(a.scopedMining.targetAir())scopedMiningRemoved(a.scopedMining);
            } catch(RuntimeException failure){scopedMiningUnknown(a.scopedMining,"mining_post_tick_unconfirmed");}
            return;
        }
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
            if (mc.level.getBlockState(target).getBlock() == a.placedBlock
                    && (a.capabilityGuard==null || CapabilityGuard.blockMatches(mc.level.getBlockState(target),
                        ClientActionRequest.string(a.entry.request.original(),"expected_block_id"),
                        a.entry.request.original().has("expected_block_properties")?a.entry.request.original().getAsJsonObject("expected_block_properties"):null))) {
                a.entry.result.addProperty("observed_block", BuiltInRegistries.BLOCK.getKey(a.placedBlock).toString());
                a.placedStableTicks++;
                boolean consumed = mc.gameMode.hasInfiniteItems()
                        || a.player.getMainHandItem().getCount() == a.placementBeforeCount - 1;
                a.entry.result.addProperty("client_stable_ticks", a.placedStableTicks);
                a.entry.result.addProperty("material_consumption_observed", consumed);
                // Client prediction can roll back; never call a first-frame block a settled result.
                // This is still client evidence, not a server acknowledgement.
                if (a.placedStableTicks >= 5 && consumed
                        && (!a.entry.request.jump() || a.player.onGround())) {
                    a.entry.result.addProperty("confirmation", "client_observed_stable");
                    finish("succeeded", "block_placed_observed");
                }
            } else {
                a.placedStableTicks = 0;
                if (a.entry.ticks - a.dispatchTick >= 10) finish("failed", "placement_not_observed");
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
        if(a.capabilityGuard!=null){hit=pick(mc,support,face);if(hit==null){finish("failed","support_face_not_in_reach_or_visible");return;}}
        if(!capabilityDispatchCheck(mc,a))return;
        // Exactly one ordinary client interaction. A missing response is never an excuse to replay it.
        a.dispatched = true;
        a.dispatchTick = a.entry.ticks;
        a.placedBlock = item.getBlock();
        a.entry.result.addProperty("dispatched", true);
        a.entry.result.add("target", cellJson(target));
        int beforeCount = a.player.getMainHandItem().getCount();
        a.placementBeforeCount = beforeCount;
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
            if(!capabilityDispatchCheck(mc,a))return;
            a.dispatched = true;
            a.dispatchTick = a.entry.ticks;
            a.entry.result.addProperty("dispatched", true);
            MovementBudget.beforeClick(mc,request);
            mc.gameMode.handleInventoryMouseClick(menu.containerId, request.slot(), request.button(),
                    ClickType.valueOf(request.clickType().toUpperCase(Locale.ROOT)), a.player);
            a.entry.result.add("menu", BridgeServer.menuSnapshot(menu));
            finish("succeeded", "click_dispatched");
        }
    }

    private static void prepareCapabilityPlacement(Minecraft mc, RuntimeAction a) {
        if (a.dispatched) return;
        BlockPos support = pos(a.entry.request.support());
        if (!mc.level.hasChunkAt(support)) { finish("failed", "chunk_not_loaded"); return; }
        Direction face = Direction.valueOf(a.entry.request.face().toUpperCase(Locale.ROOT));
        if(ClientActionRequest.bool(a.entry.request.original(),"capability_bridge",false)) {
            a.sneak=true;
            Vec3 edge=Vec3.atCenterOf(support).add(face.getStepX()*.65,.5,face.getStepZ()*.65);
            double dx=edge.x-a.player.getX(),dz=edge.z-a.player.getZ();
            if(Math.hypot(dx,dz)>.035) {
                look(mc,(float)Math.toDegrees(Math.atan2(-dx,dz)),60);a.forward=.3F;return;
            }
        }
        Vec3 aim = CapabilityPlacement.hit(a.entry.request);
        aim(mc, aim);
        // One normal jump; wait for the player's collision box to clear the placement cell.
        if (a.entry.request.jump() && !a.jumped && a.player.onGround()) {
            a.jump = true;
            a.jumped = true;
        }
    }

    private static void placeCapability(Minecraft mc, RuntimeAction a) {
        if(a.scopedPlacement!=null)a.scopedPlacement.check(mc,a.dispatched,false);
        BlockPos support = pos(a.entry.request.support());
        Direction face = Direction.valueOf(a.entry.request.face().toUpperCase(Locale.ROOT));
        BlockPos target = support.relative(face);
        if (a.dispatched) {
            if (mc.level.getBlockState(target).getBlock() == a.placedBlock
                    && (a.capabilityGuard==null || CapabilityGuard.blockMatches(mc.level.getBlockState(target),
                        ClientActionRequest.string(a.entry.request.original(),"expected_block_id"),
                        a.entry.request.original().has("expected_block_properties")?a.entry.request.original().getAsJsonObject("expected_block_properties"):null))) {
                a.entry.result.addProperty("observed_block", BuiltInRegistries.BLOCK.getKey(a.placedBlock).toString());
                if(!CapabilityPlacement.after(mc,a.entry.request)){a.placedStableTicks=0;return;}
                a.placedStableTicks++;
                boolean consumed = mc.gameMode.hasInfiniteItems()
                        || a.player.getMainHandItem().getCount() == a.placementBeforeCount - 1;
                a.entry.result.addProperty("client_stable_ticks", a.placedStableTicks);
                a.entry.result.addProperty("material_consumption_observed", consumed);
                // Client prediction can roll back; never call a first-frame block a settled result.
                // This is still client evidence, not a server acknowledgement.
                if (a.placedStableTicks >= 5 && consumed
                        && (!a.entry.request.jump() || a.player.onGround())) {
                    a.entry.result.addProperty("confirmation", "client_observed_stable");
                    finish("succeeded", "block_placed_observed");
                }
            } else {
                a.placedStableTicks = 0;
                if (a.entry.ticks - a.dispatchTick >= 10) finish("failed", "placement_not_observed");
            }
            return;
        }
        if(ClientActionRequest.bool(a.entry.request.original(),"capability_bridge",false)) {
            Vec3 edge=Vec3.atCenterOf(support).add(face.getStepX()*.65,.5,face.getStepZ()*.65);
            if(Math.hypot(edge.x-a.player.getX(),edge.z-a.player.getZ())>.04)return;
        }
        if (!(a.player.getMainHandItem().getItem() instanceof BlockItem item)) {
            finish("failed", "held_item_is_not_block"); return;
        }
        if (a.entry.request.jump() && a.player.getBoundingBox().intersects(new AABB(target))) return;
        // Re-aim after physics moved the eye position this tick (essential for underfoot placement).
        aim(mc, CapabilityPlacement.hit(a.entry.request));
        BlockHitResult hit = pick(mc, support, face);
        if (hit == null) { finish("failed", "support_face_not_in_reach_or_visible"); return; }
        BlockPlaceContext placement = new BlockPlaceContext(a.player, InteractionHand.MAIN_HAND, a.player.getMainHandItem(), hit);
        if (!placement.getClickedPos().equals(target) || !placement.canPlace()) {
            finish("failed", "placement_target_not_available"); return;
        }
        String placementProblem=CapabilityPlacement.predicted(mc,a.entry.request,placement,item);
        if(placementProblem!=null){finish("failed",placementProblem);return;}
        var event = ClientHooks.onClickInput(1, mc.options.keyUse, InteractionHand.MAIN_HAND);
        if (event.isCanceled()) { finish("failed", "use_cancelled_by_mod"); return; }
        if(a.capabilityGuard!=null){hit=pick(mc,support,face);if(hit==null){finish("failed","support_face_not_in_reach_or_visible");return;}}
        if(!capabilityDispatchCheck(mc,a))return;
        if(a.capabilityGuard!=null) {
            BlockPlaceContext finalPlacement=new BlockPlaceContext(a.player,InteractionHand.MAIN_HAND,a.player.getMainHandItem(),hit);
            if(!finalPlacement.getClickedPos().equals(target)||!finalPlacement.canPlace()){finish("failed","placement_target_not_available");return;}
            placementProblem=CapabilityPlacement.predicted(mc,a.entry.request,finalPlacement,item);
            if(active!=a)return;
            if(placementProblem!=null){finish("failed",placementProblem);return;}
            if(!capabilityDispatchCheck(mc,a))return;
        }
        if(a.scopedPlacement!=null)a.scopedPlacement.beforeUse(mc,hit);
        // Exactly one ordinary client interaction. A missing response is never an excuse to replay it.
        a.dispatched = true;
        a.dispatchTick = a.entry.ticks;
        a.placedBlock = a.capabilityGuard==null?item.getBlock():BuiltInRegistries.BLOCK.get(net.minecraft.resources.ResourceLocation.parse(ClientActionRequest.string(a.entry.request.original(),"expected_block_id")));
        a.entry.result.addProperty("dispatched", true);
        a.entry.result.add("target", cellJson(target));
        int beforeCount = a.player.getMainHandItem().getCount();
        a.placementBeforeCount = beforeCount;
        final BlockHitResult placementHit=hit;
        InteractionResult result = a.scopedPlacement==null ? mc.gameMode.useItemOn(a.player, InteractionHand.MAIN_HAND, hit)
            : ScopedPlacementDispatch.use(a.scopedPlacement,()->mc.gameMode.useItemOn(a.player,InteractionHand.MAIN_HAND,placementHit));
        a.entry.result.addProperty("interaction_result", result.name().toLowerCase(Locale.ROOT));
        if (a.scopedPlacement==null && result.shouldSwing() && event.shouldSwingHand()) {
            a.player.swing(InteractionHand.MAIN_HAND);
            if (a.player.getMainHandItem().getCount() != beforeCount || mc.gameMode.hasInfiniteItems())
                mc.gameRenderer.itemInHandRenderer.itemUsed(InteractionHand.MAIN_HAND);
        }
        if (result == InteractionResult.FAIL) finish("failed", "placement_rejected");
    }

    private static boolean capabilityDispatchCheck(Minecraft mc,RuntimeAction a) {
        if(active!=a)return false;
        String budgetProblem=MovementBudget.problem(mc);
        if(active!=a)return false;
        if(budgetProblem!=null && !(a.entry.request.action().equals("movement_budget_finish")&&MovementBudget.snapshot().get("status").getAsString().equals("stopping"))){finish("cancelled",budgetProblem);return false;}
        if(a.capabilityGuard==null)return true;
        String denied=a.capabilityGuard.check(mc,a.dispatched);
        if(denied!=null){finish("cancelled",denied);return false;}
        return active==a;
    }
    private static void interactBlock(Minecraft mc,RuntimeAction a) {
        if(a.dispatched){finish("succeeded","interaction_dispatched");return;}
        BlockPos target=pos(a.entry.request.target());
        Direction face=Direction.valueOf(a.entry.request.face().toUpperCase(Locale.ROOT));
        aim(mc,Vec3.atCenterOf(target).add(face.getStepX()*.5,face.getStepY()*.5,face.getStepZ()*.5));
        BlockHitResult hit=pick(mc,target,face);
        if(hit==null){finish("failed","target_face_not_in_reach_or_visible");return;}
        if (a.scopedBlockMenu != null) a.entry.result.addProperty("local_click_hooks_started", true);
        var event=ClientHooks.onClickInput(1,mc.options.keyUse,InteractionHand.MAIN_HAND);
        if(event.isCanceled()){finish("failed","use_cancelled_by_mod");return;}
        hit=pick(mc,target,face);
        if(hit==null){finish("failed","target_face_not_in_reach_or_visible");return;}
        if(!capabilityDispatchCheck(mc,a))return;
        if (a.scopedBlockMenu != null) {
            // Admission before native use is mandatory; the packet fence is a second check.
            // Any refusal after entry may have local or slot-sync effects and remains unknown.
            if (!ScopedBlockMenuDispatch.ready()) throw new ClientActionRequest.Rejected(409, "block_menu_post_hook_fence_unavailable");
            hit = a.scopedBlockMenu.beforeLocalBlockUse(mc, a.entry.request.id());
            a.scopedPacketPending = true; a.scopedPacketHit = hit;
            a.entry.result.addProperty("local_use_started", true);
        } else { a.dispatched=true;a.entry.result.addProperty("dispatched",true); }
        InteractionResult result;
        if (a.scopedBlockMenu == null) result=mc.gameMode.useItemOn(a.player,InteractionHand.MAIN_HAND,hit);
        else {
            if (scopedDispatchInFlight != null) throw new ClientActionRequest.Rejected(409, "block_menu_nested_use_forbidden");
            scopedDispatchInFlight = a;
            try { result=mc.gameMode.useItemOn(a.player,InteractionHand.MAIN_HAND,hit); }
            finally { scopedDispatchInFlight = null; a.scopedPacketPending = false; }
        }
        if (a.scopedBlockMenu != null && !a.dispatched) {
            if (active == a) finish("failed", "block_menu_packet_not_dispatched");
            return;
        }
        if(active!=a)return;
        a.entry.result.addProperty("interaction_result",result.name().toLowerCase(Locale.ROOT));
        if(result.shouldSwing() && event.shouldSwingHand())a.player.swing(InteractionHand.MAIN_HAND);
        if(active!=a)return;
        finish(result==InteractionResult.FAIL?"failed":"succeeded",result==InteractionResult.FAIL?"interaction_rejected":"interaction_dispatched");
    }
    private static void gatewayPearl(Minecraft mc,RuntimeAction a) {
        if(a.dispatched){finish("failed","gateway_pearl_already_dispatched");return;}
        a.entry.result.addProperty("dispatched",false);
        var b=a.entry.request.original();String problem=CapabilityGateway.check(mc,b);
        if(problem!=null){finish("failed",problem);return;}
        var trajectory=CapabilityGateway.trajectory(mc,b);
        if(trajectory==null){finish("failed","gateway_aperture_not_proven");return;}
        look(mc,trajectory.yaw(),trajectory.pitch());
        var event=ClientHooks.onClickInput(1,mc.options.keyUse,InteractionHand.MAIN_HAND);
        if(event.isCanceled()){finish("failed","use_cancelled_by_mod");return;}
        if(!capabilityDispatchCheck(mc,a))return;
        problem=CapabilityGateway.check(mc,b);if(active!=a)return;if(problem!=null){finish("failed",problem);return;}
        trajectory=CapabilityGateway.trajectory(mc,b);
        if(trajectory==null){finish("failed","gateway_aperture_not_proven");return;}
        if(!capabilityDispatchCheck(mc,a))return;
        look(mc,trajectory.yaw(),trajectory.pitch());
        a.entry.result.add("gateway_target",b.get("target").deepCopy());
        a.entry.result.addProperty("gateway_aperture_envelope_proven",true);
        a.entry.result.addProperty("gateway_entry_tick_bound",trajectory.insideTick());
        a.dispatched=true;a.entry.result.addProperty("dispatched",true);
        var result=mc.gameMode.useItem(a.player,InteractionHand.MAIN_HAND);
        if(active!=a)return;
        a.entry.result.addProperty("interaction_result",result.name().toLowerCase(Locale.ROOT));
        a.entry.result.addProperty("teleport_confirmed",false);
        if(result.shouldSwing()&&event.shouldSwingHand())a.player.swing(InteractionHand.MAIN_HAND);
        if(active!=a)return;
        finish(result==InteractionResult.FAIL?"failed":"succeeded",result==InteractionResult.FAIL?"gateway_pearl_rejected":"gateway_pearl_dispatched_observe_landing");
    }
    private static void useItem(Minecraft mc,RuntimeAction a) {
        int maxTicks=ClientActionRequest.integer(a.entry.request.original(),"use_ticks",40);
        if(!a.dispatched) {
            var animation=a.player.getMainHandItem().getUseAnimation();
            if(animation!=net.minecraft.world.item.UseAnim.EAT && animation!=net.minecraft.world.item.UseAnim.DRINK){finish("failed","consumable_use_only");return;}
            a.useBeforeCount=a.player.getMainHandItem().getCount();
        }
        if(!a.dispatched) {
            var event=ClientHooks.onClickInput(1,mc.options.keyUse,InteractionHand.MAIN_HAND);
            if(event.isCanceled()){finish("failed","use_cancelled_by_mod");return;}
            if(!capabilityDispatchCheck(mc,a))return;
            a.dispatched=true;a.dispatchTick=a.entry.ticks;a.useHeld=true;
            a.entry.result.addProperty("dispatched",true);
            mc.options.keyUse.setDown(true);
            InteractionResult result=mc.gameMode.useItem(a.player,InteractionHand.MAIN_HAND);
            if(active!=a)return;
            a.entry.result.addProperty("interaction_result",result.name().toLowerCase(Locale.ROOT));
            if(result==InteractionResult.FAIL){finish("failed","item_use_rejected");return;}
        }
        if(a.player.getMainHandItem().getCount()!=a.useBeforeCount || a.entry.ticks>a.dispatchTick && !a.player.isUsingItem())finish("succeeded","item_use_finished_observed");
        else if(a.entry.ticks-a.dispatchTick>=maxTicks)finish("failed","item_use_budget_exhausted");
    }
    private static void closeMenu(Minecraft mc,RuntimeAction a) {
        if(!capabilityDispatchCheck(mc,a))return;
        a.dispatched=true;a.entry.result.addProperty("dispatched",true);
        a.player.closeContainer();
        if(active!=a)return;
        finish(mc.screen==null && a.player.containerMenu==a.player.inventoryMenu?"succeeded":"failed","menu_close_observed");
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
        if(a.scopedMining!=null && !status.equals("succeeded") && !reason.equals("cancel_requested")) {
            a.scopedMining.markUnknown();a.entry.result.addProperty("unknown_outcome",true);
        }
        if(a.scopedPlacement!=null && !status.equals("succeeded") && a.scopedPlacement.attempted()) {
            a.scopedPlacement.markUnknown();a.entry.result.addProperty("unknown_outcome",true);a.entry.result.addProperty("requires_handoff",true);
        }
        active = null;
        boolean pathAction = a.entry.request.action().equals("follow_path");
        boolean discontinuityCleanup = reason.equals("position_discontinuity_rebind_required");
        boolean managedCleanup = pathAction || a.boat != null || a.transfer != null || discontinuityCleanup || a.combat != null;
        managedCleanup = managedCleanup || a.capabilityGuard != null;
        // Preserve legacy terminal timing/fields for recovery, mining, placement
        // and inventory actions. New boat/combat owners require confirmed cleanup.
        if (!managedCleanup) ACTIONS.finish(status, reason);
        a.entry.result.addProperty("x", a.player.getX());
        a.entry.result.addProperty("y", a.player.getY());
        a.entry.result.addProperty("z", a.player.getZ());
        if (a.input != null) {
            a.input.forwardImpulse = a.input.leftImpulse = 0;
            a.input.up = a.input.down = a.input.left = a.input.right = a.input.jumping = a.input.shiftKeyDown = false;
        }
        boolean attackReleased = true;
        if (a.attackHeld) {
            Minecraft mc = Minecraft.getInstance();
            if (discontinuityCleanup || a.capabilityGuard!=null) {
                attackReleased = releaseDiscontinuousAttack(() -> mc.options.keyAttack.setDown(false),
                        () -> { if (mc.gameMode != null) {
                            if(a.scopedMining!=null)ScopedMiningDispatch.cleanup(a.scopedMining,mc.gameMode::stopDestroyBlock);
                            else mc.gameMode.stopDestroyBlock();
                        } });
            } else {
                // Existing non-discontinuity ordering/errors remain unchanged.
                mc.options.keyAttack.setDown(false);
                if (mc.gameMode != null) mc.gameMode.stopDestroyBlock();
            }
        }
        if (managedCleanup) {
            boolean released = attackReleased;
            if (a.useHeld) {
                released &= cleanup(() -> Minecraft.getInstance().options.keyUse.setDown(false));
                released &= cleanup(() -> {if(Minecraft.getInstance().gameMode!=null)Minecraft.getInstance().gameMode.releaseUsingItem(a.player);});
            }
            if (a.capabilityTarget != null) released &= cleanup(() -> a.capabilityTarget.release(Minecraft.getInstance()));
            if (a.transfer != null) released &= cleanup(a.transfer::release);
            if (a.boat != null) released &= cleanup(() -> a.boat.release(Minecraft.getInstance()));
            if (a.combat != null) released &= cleanup(() -> a.combat.release(Minecraft.getInstance()));
            released &= cleanup(() -> sprint(Minecraft.getInstance(), a, false));
            if(a.scopedMovement!=null) {
                boolean neutral=ScopedFlatMovement.neutral(a.input) && ScopedFlatMovement.neutral(a.player.input)
                        && !ScopedFlatMovement.keysDown(Minecraft.getInstance()) && !BridgeServer.hasHeldInputs();
                released &= neutral;
                a.entry.result.add("scoped_movement",a.scopedMovement.terminal(neutral));
            }
            // Keep encounter evidence aligned with the terminal cleanup outcome.
            if(a.combat!=null) a.combat.terminal(released?status:"failed",released?reason:"input_release_unconfirmed");
            if(MovementBudget.armed()) {
                MovementBudget.observe(Minecraft.getInstance(),false);
                if(!released)MovementBudget.interrupt("movement_budget_input_release_unconfirmed");
                String budgetFailure=MovementBudget.invalidReason();
                if(budgetFailure!=null){status="failed";reason=budgetFailure;}
            }
            if(a.entry.request.action().equals("movement_budget_finish")&&status.equals("succeeded")&&released) {
                try { MovementBudget.finish(); }
                catch(RuntimeException rejected){MovementBudget.interrupt("movement_budget_seal_failed");status="failed";reason="movement_budget_seal_failed";}
            }
            a.entry.result.add("movement_budget",MovementBudget.snapshot());
            if(a.scopedMining!=null) {
                Minecraft mc=Minecraft.getInstance();
                released &= ScopedMining.neutral(a.input) && ScopedMining.neutral(a.player.input)
                    && !mc.options.keyAttack.isDown() && !ScopedMining.otherKeys(mc) && !BridgeServer.hasHeldInputs();
                a.entry.result.add("mining",a.scopedMining.terminal(released,status.equals("succeeded")
                    && a.entry.result.has("observed_block") && a.entry.result.get("observed_block").getAsString().equals("minecraft:air")));
            }
            if(a.scopedPlacement!=null) {
                Minecraft mc=Minecraft.getInstance();released &= a.scopedPlacement.cleanupState(status.equals("succeeded"))&&ScopedMining.neutral(a.input)&&ScopedMining.neutral(a.player.input)
                    &&!mc.options.keyAttack.isDown()&&!ScopedMining.otherKeys(mc)&&!BridgeServer.hasHeldInputs();
                if(!released&&a.scopedPlacement.attempted()){a.scopedPlacement.markUnknown();a.entry.result.addProperty("unknown_outcome",true);a.entry.result.addProperty("requires_handoff",true);}
                a.entry.result.add("placement",a.scopedPlacement.terminal(released,status.equals("succeeded")&&released));
            }
            ACTIONS.finishAfterCleanup(status, reason, released);
            if (a.combat != null)
                EncounterTerminalPause.afterTerminal(a.entry, ACTIONS.session, BridgeServer::pauseEncounterTerminalOnGameThread);
        }
    }
    static boolean releaseDiscontinuousAttack(Runnable keyUp, Runnable stopDestroy) {
        boolean released = cleanup(keyUp);
        released &= cleanup(stopDestroy); // Non-short-circuit: attempt both even after failure.
        return released;
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

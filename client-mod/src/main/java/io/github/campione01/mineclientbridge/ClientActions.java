package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.util.Locale;
import java.util.Set;
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
    private static final FallRescueCleanupScope FALL_CLEANUP=new FallRescueCleanupScope();
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
        ScopedStepDownMovement scopedStepDown;
        ScopedLocalSegmentMovement scopedLocalSegment;
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
        final PlacementEffectVerification placementVerification = new PlacementEffectVerification();
        net.minecraft.world.level.block.state.BlockState placementBeforeState;
        net.minecraft.world.item.Item placementBeforeItem;
        int placementBeforeSlot;
        final PlacementOwnerFence placementOwner;
        RuntimeAction(ActionRegistry.Entry entry, Minecraft mc, BoundedCombat combat, BoundedBoatDrive boat, BoundedBoatTransfer transfer, long combatDeadline, CoordinationStepGuard coordinationStep, long coordinationDeadline, CapabilityGuard capabilityGuard, CapabilityTargetAction capabilityTarget) {
            this.entry = entry;
            placementOwner = new PlacementOwnerFence(this,mc.player,mc.level,mc.gameMode,
                mc.player.containerMenu,mc.screen,ACTIONS.session,WorldGeneration.current(mc.level));
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
            IntegratedServerIdentity.clear();NativeExternalNavigation.contextLost();NativeFallRescue.stop("world_transition");cancel("world_transition");
        });
        NeoForge.EVENT_BUS.addListener(ClientPlayerNetworkEvent.Clone.class, event -> { NativeExternalNavigation.contextLost();NativeFallRescue.stop("player_changed"); cancel("player_changed"); });
        NeoForge.EVENT_BUS.addListener(LevelEvent.Unload.class, event -> {
            if (event.getLevel().isClientSide()) { NativeExternalNavigation.contextLost();NativeFallRescue.stop("world_transition"); MovementBudget.interrupt("movement_budget_context_changed"); cancel("world_transition"); }
        });
        NeoForge.EVENT_BUS.addListener(EventPriority.HIGHEST, true, net.neoforged.neoforge.client.event.ScreenEvent.Opening.class,
                event -> NativeFallRescue.stop("user_screen_or_pause"));
        installed = true;
    }

    static JsonObject start(ClientActionRequest request) { return start(request, null); }

    static JsonObject start(ClientActionRequest request, ScopedNativePreflight.Capture scoped) {
        Minecraft mc = Minecraft.getInstance();
        requireThread(mc);
        ActionRegistry.Entry old = ACTIONS.existing(request);
        if (old != null) return status(request.id());
        if(request.original().has("defensive_policy") && (scoped==null || scoped.combat==null || scoped.combat.defensive==null))
            throw new ClientActionRequest.Rejected(409,"defensive_scoped_profile_required");
        NativeFallRescue.requireOrdinaryAdmission();
        NativeExternalNavigation.requireOrdinaryAdmission();
        if (active != null) throw new ClientActionRequest.Rejected(409, "action_busy");
        if (mc.player == null || mc.level == null || mc.gameMode == null)
            throw new ClientActionRequest.Rejected(409, "not_in_world");
        NativeAdmission.mark(NativeAdmission.Stage.HOOKS_POSSIBLE);
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
        ExternalControllerGuard.requireIdle(mc);
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
        NativeAdmission.mark(NativeAdmission.Stage.INPUT_TRANSFER);
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
        ExternalControllerGuard.requireIdle(mc);
        // Preserve the original freshness deadline after the final external API reads.
        if(capabilityGuard!=null)capabilityGuard.requireFresh(mc,"external_controller_final");
        if(coordinationStep!=null)coordinationStep.requireFresh(mc);
        if(active!=null || ownershipRevision!=capabilityOwnerRevision
                || mc.player!=coordinationPlayer || mc.level!=coordinationLevel)
            throw new ClientActionRequest.Rejected(409,"external_controller_owner_changed_during_check");
        NativeFallRescue.requireOrdinaryAdmission();
        NativeExternalNavigation.requireOrdinaryAdmission();
        NativeAdmission.mark(NativeAdmission.Stage.REGISTERED);
        ownershipRevision++;
        active = new RuntimeAction(ACTIONS.begin(request), mc, combat, boat, transfer, combatDeadline, coordinationStep, coordinationDeadline, capabilityGuard, capabilityTarget);
        if (scoped != null) {
            active.entry.result.add("scoped_native_preflight", scoped.witness(request.id()));
            active.scopedMovement = scoped.movement;
            if (active.scopedMovement != null) active.scopedMovement.activate(active.entry);
            active.scopedLocalSegment=scoped.localSegment;
            if(active.scopedLocalSegment!=null)active.scopedLocalSegment.activate(active.entry);
            active.scopedStepDown=scoped.stepDown;
            if(active.scopedStepDown!=null)active.scopedStepDown.activate(active.entry);
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
        // A registered, fully witnessed stop-only route never reaches a view, movement or input effect.
        if(active.scopedLocalSegment!=null&&active.scopedLocalSegment.admissionThreat()){
            RuntimeAction admitted=active;
            try{admitted.scopedLocalSegment.beforeEffect(mc);
                if(active==admitted)finish("cancelled","route_spatial_admission_attacker_changed");}
            catch(RuntimeException failure){if(active==admitted)finish("cancelled",ScopedLocalSegmentMovement.rejection(failure));}
            return status(request.id());
        }
        if(request.action().equals("movement_budget_start"))MovementBudget.start(mc,request);
        // block-menu-v1 owns exactly one synchronous interaction inside this admitted callback.
        // No asynchronous post-tick dispatch can extend its capture or replay a missing menu.
        if (scoped != null && scoped.blockMenu()) {
            RuntimeAction admitted = active;
            try { interactBlock(mc, admitted); }
            catch (RuntimeException failure) {
                if (active == admitted) {
                    var capture = admitted.scopedBlockMenu;
                    capture.blockMenuDiagnostics.record(admitted.entry, failure, System.nanoTime() - capture.nano);
                    failException(failure);
                }
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
        a.scopedBlockMenu.blockMenuDiagnostics.mark(BlockMenuDiagnostics.Stage.PACKET_FENCE, BlockMenuDiagnostics.Phase.PACKET_OWNER);
        if (active != a || !a.scopedPacketPending || a.dispatched || player != a.player || hand != InteractionHand.MAIN_HAND
                || hit != a.scopedPacketHit || !ScopedBlockMenuDispatch.ready())
            throw new ClientActionRequest.Rejected(409, "block_menu_packet_owner_mismatch");
        Minecraft mc = Minecraft.getInstance();
        // Forge right-click, item-first, sneak-bypass and block-use hooks have returned.
        // This cannot undo arbitrary hook effects. A late failure is an unknown outcome.
        a.scopedBlockMenu.blockMenuDiagnostics.phase(BlockMenuDiagnostics.Phase.PACKET_GUARD);
        if (!capabilityDispatchCheck(mc, a)) throw new ClientActionRequest.Rejected(409, "block_menu_packet_guard_changed");
        BlockHitResult finalHit = a.scopedBlockMenu.beforeBlockMenuEffect(mc, a.entry.request.id());
        a.scopedBlockMenu.blockMenuDiagnostics.phase(BlockMenuDiagnostics.Phase.PACKET_HIT);
        if (!BlockMenuPreflight.hitMatches(hit, finalHit.getBlockPos(), finalHit.getDirection(), finalHit.getLocation()))
            throw new ClientActionRequest.Rejected(409, "block_menu_packet_hit_changed");
        a.scopedBlockMenu.blockMenuDiagnostics.phase(BlockMenuDiagnostics.Phase.WITNESS);
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
    static boolean ownsScopedStepDown(ScopedStepDownMovement descent,ActionRegistry.Entry entry) {
        return active!=null && active.scopedStepDown==descent && active.entry==entry
                && ACTIONS.active()==entry && entry!=null && entry.running();
    }
    static boolean ownsScopedLocalSegment(ScopedLocalSegmentMovement descent,ActionRegistry.Entry entry) {
        return active!=null && active.scopedLocalSegment==descent && active.entry==entry
                && ACTIONS.active()==entry && entry!=null && entry.running();
    }
    static void localSegmentMotionFailed(ScopedLocalSegmentMovement owner,String reason) {
        owner.motionUnknown(reason);
        if(active!=null&&active.scopedLocalSegment==owner){
            active.entry.result.addProperty("motion_gate_rejected",true);
            active.entry.result.addProperty("effect_outcome","unknown");
            finish("cancelled",reason);
        }
    }
    static boolean ownsCapabilityTarget(CapabilityTargetAction target) { return active!=null && active.capabilityTarget==target; }
    static JsonObject status(String id) { requireThread(Minecraft.getInstance()); JsonObject j=ACTIONS.status(id);j.add("movement_budget",MovementBudget.snapshot(Minecraft.getInstance()));return j; }
    /** Recheck a coherent read without creating another movement-budget boundary sample. */
    static JsonObject statusWithoutObservation() { requireThread(Minecraft.getInstance()); JsonObject j=ACTIONS.status(null);j.add("movement_budget",MovementBudget.snapshot());return j; }
    static String session() { return ACTIONS.session; }
    static long externalOwnerRevision() { return ownershipRevision; } // Pure owner identity fence.
    static boolean ownsInput() { return active != null || NativeFallRescue.blocksInput() || NativeExternalNavigation.blocksInput(); }
    static boolean hasRuntimeAction() { return active != null; }
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
        ExternalControllerGuard.requireIdle(Minecraft.getInstance());
        NativeFallRescue.requireOrdinaryAdmission();
        NativeExternalNavigation.requireOrdinaryAdmission();
        ownershipRevision++;
        MovementBudget.interrupt("movement_budget_direct_takeover");
        cancel("direct_takeover");
        GuardedGameMovement.cancelOnGameThread("direct_takeover");
        NativeFallRescue.requireOrdinaryAdmission();
        NativeExternalNavigation.requireOrdinaryAdmission();
    }
    static void cancel(String reason) {
        Minecraft mc = Minecraft.getInstance();
        if (!mc.isSameThread()) { mc.execute(() -> cancel(reason)); return; }
        if (active != null) finish("cancelled", reason);
    }

    /** An exact declared action may be interrupted, but is never resumed or replaced automatically. */
    static void requireFallRescueAdmission(Set<String> permittedIds) {
        NativeExternalNavigation.requireOrdinaryAdmission();
        RuntimeAction a=active;
        if(a!=null && (!permittedIds.contains(a.entry.request.id())
                || !FallRescuePolicy.PREEMPTIBLE.contains(a.entry.request.action())))
            throw new ClientActionRequest.Rejected(409,"fall_rescue_current_action_not_authorized");
        if(scopedDispatchInFlight!=null)
            throw new ClientActionRequest.Rejected(409,"fall_rescue_native_dispatch_in_flight");
    }
    static boolean terminalCombatCleanup(ScopedCombat guard,ActionRegistry.Entry entry) {
        // An existing handoff scope never falls back to ordinary cleanup after revocation.
        return FALL_CLEANUP.active()||guard!=null&&guard.fallPreempted()
            ?FALL_CLEANUP.permits(guard,entry):!ownsInput();
    }
    static JsonObject preemptForFallRescue(Set<String> permittedIds,java.util.function.BooleanSupplier successorBound) {
        Minecraft mc=Minecraft.getInstance();requireThread(mc);requireFallRescueAdmission(permittedIds);
        requirePreemptionChannelsAbsent();
        if(!successorBound.getAsBoolean())throw new ClientActionRequest.Rejected(409,"fall_rescue_preemption_successor_changed");
        RuntimeAction old=active;JsonObject interrupted=new JsonObject();
        if(old!=null&&(old.player!=mc.player||old.level!=mc.level))
            throw new ClientActionRequest.Rejected(409,"fall_rescue_original_context_changed");
        if(old!=null){
            interrupted.addProperty("action_id",old.entry.request.id());
            interrupted.addProperty("action",old.entry.request.action());
            interrupted.addProperty("effect_outcome","unknown_interrupted");
            interrupted.addProperty("no_auto_resume",true);
            interrupted.addProperty("requires_reconciliation_before_retry",true);
            if(old.scopedCombat!=null)old.scopedCombat.markFallPreempted();
            old.entry.result.addProperty("preempted_by_native_fall_rescue",true);
            old.entry.result.addProperty("no_auto_resume",true);
            // Legacy movement/combat do not consistently maintain dispatched. Absence is not no-effect proof.
            old.entry.result.addProperty("unknown_outcome",true);old.entry.result.addProperty("requires_handoff",true);
        }
        ownershipRevision++;
        MovementBudget.interrupt("native_fall_rescue_preempted");
        // ARBITER is already held across every cleanup callback and the final neutral check.
        if(old!=null){
            long cleanupRevision=ownershipRevision;
            var scope=FALL_CLEANUP.open(old,old.scopedCombat,old.entry,
                ()->active==null&&ACTIONS.active()==old.entry&&ownershipRevision==cleanupRevision
                    &&old.player==mc.player&&old.level==mc.level&&preemptionChannelsAbsent()&&successorBound.getAsBoolean());
            try {finish("cancelled","native_fall_rescue_preempted");}
            catch(RuntimeException failure){
                releaseDiagnostic(old,"fall_preemption_cleanup_callback","fall_rescue_cleanup_scope_changed");
                old.entry.result.addProperty("unknown_outcome",true);
                if(ACTIONS.active()==old.entry)ACTIONS.finishAfterCleanup("cancelled","native_fall_rescue_preempted",false);
                throw failure;
            } finally {FALL_CLEANUP.close(scope);}
            var cleanupInput=old.player.input;
            requirePreemptionSuccessor(mc,old,successorBound);
            if(cleanupInput!=null){
                cleanupInput.forwardImpulse=cleanupInput.leftImpulse=0;
                cleanupInput.up=cleanupInput.down=cleanupInput.left=cleanupInput.right=cleanupInput.jumping=cleanupInput.shiftKeyDown=false;
            }
        }
        // No authority over independent raw or guarded channels: refuse rather than globally release.
        requirePreemptionChannelsAbsent();
        requirePreemptionSuccessor(mc,old,successorBound);
        return interrupted;
    }

    private static boolean preemptionChannelsAbsent() {
        return FallRescueCleanupScope.channelsAbsent(BridgeServer.hasHeldInputs(),
            ClientInputIsolation.statistics().heldKeys(),GuardedGameMovement.LEASES.status().ownerRequestId());
    }
    private static void requirePreemptionChannelsAbsent() {
        if(!preemptionChannelsAbsent())throw new ClientActionRequest.Rejected(409,"fall_rescue_foreign_input_channel_present");
    }
    private static void requirePreemptionSuccessor(Minecraft mc,RuntimeAction old,java.util.function.BooleanSupplier bound) {
        if(active!=null||(old!=null&&(old.player!=mc.player||old.level!=mc.level))
                ||!preemptionChannelsAbsent()||!bound.getAsBoolean())throw new ClientActionRequest.Rejected(409,"fall_rescue_preemption_successor_changed");
    }

    private static boolean context(Minecraft mc,String phase) {
        RuntimeAction a=active;
        try{return contextChecked(mc,phase);}
        catch(RuntimeException failure){
            if(a!=null && a.scopedPlacement!=null){a.scopedPlacement.recordFailure(failure);if(active==a)finish("cancelled","placement_context_hook_failed");return false;}
            if(a!=null && a.scopedMining!=null){scopedMiningUnknown(a.scopedMining,"mining_context_hook_failed");return false;}
            throw failure;
        }
    }
    private static boolean contextChecked(Minecraft mc,String phase) {
        if (active == null) return false;
        RuntimeAction enteredOwner = active;
        if(!externalOwnerCheck(mc,enteredOwner))return false;
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
        NativeExternalNavigation.tick(mc);
        if(NativeExternalNavigation.blocksInput())return;
        NativeFallRescue.preTick(mc);
        if (NativeFallRescue.blocksInput()) return;
        ScopedLocalSegmentDispatch.nextTick();
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
                // A server stop-use update can precede Pre. Release the completed hold
                // before vanilla handleKeybinds can start another main/offhand use.
                // Admission/context guards above still run before this observation.
                case "use_item" -> finishUseItemIfObserved(mc, a);
                case "click_slot", "interact_block", "select_hotbar", "close_menu", "gateway_pearl", "movement_budget_start", "movement_budget_finish" -> { }
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
        if (event.getEntity() == Minecraft.getInstance().player && NativeFallRescue.input(Minecraft.getInstance(),event.getInput())) return;
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
                a.scopedCombat.check(Minecraft.getInstance(),false);
                if(active!=a)return; a.combat.beforeScopedMovement(Minecraft.getInstance(),a.forward);
                if(active!=a)return; // The final permit must not be followed by another mutable guard hook.
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
        if(a.scopedStepDown!=null) {
            try {
                if(input!=a.player.input || event.getInput()!=input || !ScopedFlatMovement.neutral(input))
                    throw new ClientActionRequest.Rejected(409,"step_down_external_input");
                a.scopedStepDown.beforeEffect(Minecraft.getInstance());
                if(active!=a)return;
                if(input!=a.player.input || event.getInput()!=input || !ScopedFlatMovement.neutral(input))
                    throw new ClientActionRequest.Rejected(409,"step_down_input_changed_after_hooks");
                a.dispatched=true;a.scopedStepDown.markAttempted();
            } catch(RuntimeException failed){if(active==a)finish("cancelled",ScopedStepDownMovement.rejection(failed));return;}
        }
        if(a.scopedLocalSegment!=null) {
            try {
                if(input!=a.player.input || event.getInput()!=input || !ScopedFlatMovement.neutral(input))
                    throw new ClientActionRequest.Rejected(409,"local_segment_external_input");
                a.scopedLocalSegment.beforeEffect(Minecraft.getInstance());
                if(active!=a)return;
                if(input!=a.player.input || event.getInput()!=input || !ScopedFlatMovement.neutral(input))
                    throw new ClientActionRequest.Rejected(409,"local_segment_input_changed_after_hooks");
                a.dispatched=true;a.scopedLocalSegment.markAttempted();
            } catch(RuntimeException failed){if(active==a)finish("cancelled",ScopedLocalSegmentMovement.rejection(failed));return;}
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
            } catch(RuntimeException failure){a.scopedPlacement.recordFailure(failure);if(active==a)finish("cancelled","placement_input_context_unconfirmed");return;}
        }
        if(a.scopedLocalSegment!=null){
            try {ScopedLocalSegmentDispatch.arm(a.scopedLocalSegment);a.scopedLocalSegment.recordInput(a.jump,a.forward);}
            catch(RuntimeException failed){if(active==a)finish("cancelled",ScopedLocalSegmentMovement.rejection(failed));return;}
        }
        if(!externalOwnerCheck(Minecraft.getInstance(),a))return;
        if(active!=a || input!=a.player.input || System.nanoTime()>=a.deadline)return;
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
        NativeFallRescue.postTick(mc);
        if (NativeFallRescue.blocksInput()) return;
        MovementBudget.observe(mc,true);
        if (!context(mc,"post_tick") || mc.isPaused()) return;
        RuntimeAction entered=active;
        try {
            RuntimeAction a = entered;
            if(a.scopedLocalSegment!=null){a.scopedLocalSegment.beforeEffect(mc);if(active!=a)return;}
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
            if(entered.entry.request.action().equals("place_block")) {
                placementUnknown(entered,"placement_callback_exception");
                if(entered.scopedPlacement!=null)entered.scopedPlacement.recordFailure(failure);
                if(active==entered)finish("failed","placement_callback_exception");
                return;
            }
            // A reentrant default-stop callback must never annotate or finish a replacement owner.
            if(entered.scopedLocalSegment!=null&&entered.scopedLocalSegment.spatialStopProfile()&&active!=entered)return;
            // Preserve this already validated, owned, pre-next-effect proof in the post-tick callback too.
            // Generic legacy failures and motion-gate unknown outcomes keep their existing paths.
            if(entered.scopedLocalSegment!=null&&entered.scopedLocalSegment.spatialThreatProfile()){
                if(active!=entered)return; // A failed old callback must never release a replacement owner.
                String reason=failure.getMessage();
                boolean known=failure instanceof ClientActionRequest.Rejected
                    &&("capability_threat_observed".equals(reason)&&entered.scopedLocalSegment.hasValidatedThreatStop(entered.entry)
                        ||"route_spatial_pre_effect_attacker_changed".equals(reason)&&entered.scopedLocalSegment.hasPreEffectThreatRace(entered.entry));
                if(known)finish("cancelled",reason);else failException(failure);
                return;
            }
            if(active==entered&&entered.scopedLocalSegment!=null)entered.scopedLocalSegment.recordFailure(failure);
            if(entered.scopedPlacement!=null)entered.scopedPlacement.recordFailure(failure);
            if(entered.scopedPlacement==null || active==entered)failException(failure);
        }
    }

    private static void followPath(Minecraft mc, RuntimeAction a) {
        if(a.scopedLocalSegment!=null){followLocalSegment(mc,a);return;}
        if(a.scopedStepDown!=null){
            try {a.scopedStepDown.beforeEffect(mc);}
            catch(RuntimeException failed){if(active==a)finish("cancelled",ScopedStepDownMovement.rejection(failed));return;}
            if(active!=a)return;
        }
        if(a.scopedMovement!=null) {
            try { a.scopedMovement.beforeEffect(mc); }
            catch(RuntimeException failed) { if(active==a)finish("cancelled",ScopedFlatMovement.rejection(failed));return; }
            if(active!=a)return;
        }
        var points = a.entry.request.waypoints();
        while (a.waypoint < points.size()) {
            String routeProblem=a.scopedMovement==null && a.scopedStepDown==null ? CapabilityPath.check(mc,a.entry.request,a.waypoint) : null;
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
                    if (a.scopedStepDown!=null ? a.scopedStepDown.settled() : PathSteering.settledAt(a.player.getX(),a.player.getY(),a.player.getZ(),
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
            } else if(a.scopedStepDown!=null) {
                try {
                    a.scopedStepDown.beforeEffect(mc);
                    if(active!=a)return;
                    step=PathSteering.toward(a.player.getX(),a.player.getY(),a.player.getZ(),a.player.getYRot(),a.player.onGround(),false,effectiveGoal,true);
                    a.dispatched=true;a.scopedStepDown.markAttempted();
                    a.player.setYRot(step.yaw());
                } catch(RuntimeException failed){if(active==a)finish("cancelled",ScopedStepDownMovement.rejection(failed));return;}
            } else look(mc, step.yaw(), a.entry.request.original().has("capability_route")?60:a.player.getXRot());
            if(a.scopedStepDown!=null && active!=a)return;
            a.forward = a.scopedMovement==null && a.scopedStepDown==null ? step.forward() : Math.min(.5F,step.forward());
            a.jump = a.scopedMovement==null && a.scopedStepDown==null && step.jump();
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

    private static void followLocalSegment(Minecraft mc,RuntimeAction a) {
        try {
            a.scopedLocalSegment.beforeEffect(mc);
            if(active!=a)return;
            var step=a.scopedLocalSegment.step();
            if(step.done()){finish("succeeded","path_reached");return;}
            // Revalidate after any prior facts and recompute from the unchanged raw pose.
            a.scopedLocalSegment.beforeEffect(mc);
            if(active!=a)return;
            step=a.scopedLocalSegment.step();
            a.scopedLocalSegment.markAttempted();a.dispatched=true;
            a.player.setYRot(step.yaw());
            a.forward=step.forward();a.jump=step.jump();a.sneak=false;
            a.entry.result.addProperty("phase","local_segment_active");
            a.entry.result.addProperty("waypoint_index",0);a.entry.result.addProperty("waypoint_count",1);
        } catch(RuntimeException failed){if(active==a){a.scopedLocalSegment.recordFailure(failed);finish("cancelled",ScopedLocalSegmentMovement.rejection(failed));}}
    }

    private static void sprint(Minecraft mc, RuntimeAction a, boolean wanted) {
        // Request the ordinary sprint key; the client retains food/item/collision
        // eligibility. Never force sprint-on or write position/velocity.
        if (wanted) {
            if(FALL_CLEANUP.active())throw new ClientActionRequest.Rejected(409,"fall_rescue_cleanup_nonrelease_effect");
            a.sprintHeld=true;
            SprintKeyState.set(mc.options.keySprint::isDown,mc.options.keySprint::setDown,true);
        }
        else if (a.sprintHeld) {
            SprintKeyState.set(()->{boolean down=mc.options.keySprint.isDown();requireCleanupOwner(a);return down;},
                down->{requireCleanupOwner(a);mc.options.keySprint.setDown(down);},false);
            requireCleanupOwner(a);a.player.setSprinting(false);
            requireCleanupOwner(a);
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
    static ScopedCombat activeDefensiveCombat(){return active!=null && active.scopedCombat!=null && active.scopedCombat.defensive!=null?active.scopedCombat:null;}
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
            verifyPlacementEffect(mc, a, target, false);
            return;
        }
        if (!(a.player.getMainHandItem().getItem() instanceof BlockItem item)) {
            finishPlacement(mc,a,"failed", "held_item_is_not_block"); return;
        }
        if(!placementFence(mc,a))return;
        boolean intersects=a.entry.request.jump() && a.player.getBoundingBox().intersects(new AABB(target));
        if(!placementFence(mc,a)||intersects)return;
        // Re-aim after physics moved the eye position this tick (essential for underfoot placement).
        aim(mc, Vec3.atCenterOf(support).add(face.getStepX() * 0.5, face.getStepY() * 0.5, face.getStepZ() * 0.5));
        if(!placementFence(mc,a))return;
        BlockHitResult hit = pick(mc, support, face);
        if(!placementFence(mc,a))return;
        if (hit == null) { finishPlacement(mc,a,"failed", "support_face_not_in_reach_or_visible"); return; }
        BlockPlaceContext placement = new BlockPlaceContext(a.player, InteractionHand.MAIN_HAND, a.player.getMainHandItem(), hit);
        if (!placement.getClickedPos().equals(target) || !placement.canPlace()) {
            finishPlacement(mc,a,"failed", "placement_target_not_available"); return;
        }
        if(!placementFence(mc,a))return;
        var event = ClientHooks.onClickInput(1, mc.options.keyUse, InteractionHand.MAIN_HAND);
        if(!placementFence(mc,a))return;
        if (event.isCanceled()) { finishPlacement(mc,a,"failed", "use_cancelled_by_mod"); return; }
        if(a.capabilityGuard!=null){hit=pick(mc,support,face);if(hit==null){finishPlacement(mc,a,"failed","support_face_not_in_reach_or_visible");return;}}
        if(!capabilityDispatchCheck(mc,a))return;
        // Exactly one ordinary client interaction. A missing response is never an excuse to replay it.
        a.dispatched = true;
        a.dispatchTick = a.entry.ticks;
        a.placedBlock = item.getBlock();
        a.entry.result.addProperty("dispatched", true);
        a.entry.result.add("target", cellJson(target));
        int beforeCount = a.player.getMainHandItem().getCount();
        a.placementBeforeCount = beforeCount;
        a.placementBeforeItem = a.player.getMainHandItem().getItem();
        a.placementBeforeSlot = a.player.getInventory().selected;
        a.placementBeforeState = mc.level.getBlockState(target);
        a.entry.result.addProperty("placement_before_count", beforeCount);
        a.entry.result.addProperty("placement_before_item", BuiltInRegistries.ITEM.getKey(a.placementBeforeItem).toString());
        a.entry.result.addProperty("placement_before_block", BuiltInRegistries.BLOCK.getKey(a.placementBeforeState.getBlock()).toString());
        a.entry.result.addProperty("placement_verification_max_ticks", PlacementEffectVerification.MAX_TICKS);
        if(!placementFence(mc,a))return;
        InteractionResult result = mc.gameMode.useItemOn(a.player, InteractionHand.MAIN_HAND, hit);
        if(!placementFence(mc,a))return;
        a.entry.result.addProperty("interaction_result", result.name().toLowerCase(Locale.ROOT));
        if (result.shouldSwing() && event.shouldSwingHand()) {
            a.player.swing(InteractionHand.MAIN_HAND);
            if(!placementFence(mc,a))return;
            boolean itemChanged=a.player.getMainHandItem().getCount() != beforeCount || mc.gameMode.hasInfiniteItems();
            if(!placementFence(mc,a))return;
            if(itemChanged)mc.gameRenderer.itemInHandRenderer.itemUsed(InteractionHand.MAIN_HAND);
            if(!placementFence(mc,a))return;
        }
        // Even FAIL can follow packet/hook effects. Preserve it and only observe; never redispatch.
        a.entry.result.addProperty("placement_effect_verification", "pending_read_only");
    }

    private static void verifyPlacementEffect(Minecraft mc, RuntimeAction a, BlockPos target, boolean capability) {
        if(!placementFence(mc,a))return;
        var state = mc.level.getBlockState(target);
        var stack = a.player.getMainHandItem();
        boolean expected = state.getBlock() == a.placedBlock && state != a.placementBeforeState
            && (a.capabilityGuard == null || CapabilityGuard.blockMatches(state,
                ClientActionRequest.string(a.entry.request.original(), "expected_block_id"),
                a.entry.request.original().has("expected_block_properties")
                    ? a.entry.request.original().getAsJsonObject("expected_block_properties") : null));
        boolean consumed = a.player.getInventory().selected == a.placementBeforeSlot
            && (mc.gameMode.hasInfiniteItems()
                || stack.getCount() == a.placementBeforeCount - 1
                    && (stack.isEmpty() && a.placementBeforeCount == 1 || stack.getItem() == a.placementBeforeItem));
        boolean settled = (!a.entry.request.jump() || a.player.onGround())
            && (!capability || expected && CapabilityPlacement.after(mc, a.entry.request));
        int afterCount=stack.getCount();
        String afterBlock=BuiltInRegistries.BLOCK.getKey(state.getBlock()).toString();
        if(!placementFence(mc,a))return;
        int elapsed = a.entry.ticks - a.dispatchTick;
        var decision = a.placementVerification.observe(elapsed, expected, consumed, settled);
        a.entry.result.addProperty("placement_observation_elapsed_ticks", elapsed);
        a.entry.result.addProperty("placement_after_count", afterCount);
        a.entry.result.addProperty("placement_after_block", afterBlock);
        a.entry.result.addProperty("material_consumption_observed", consumed);
        a.entry.result.addProperty("client_stable_ticks", a.placementVerification.stableTicks());
        if(decision == PlacementEffectVerification.Decision.OBSERVED) {
            a.entry.result.addProperty("observed_block", BuiltInRegistries.BLOCK.getKey(a.placedBlock).toString());
            a.entry.result.addProperty("confirmation", "client_observed_stable");
            a.entry.result.addProperty("placement_effect_verification", "observed");
            finishPlacement(mc,a,"succeeded", "block_placed_observed");
        } else if(decision == PlacementEffectVerification.Decision.UNKNOWN) {
            a.entry.result.addProperty("placement_effect_verification", "bounded_observation_inconclusive");
            finishPlacement(mc,a,"failed", "placement_effect_unconfirmed");
        }
    }

    private static void clickSlot(Minecraft mc, RuntimeAction a) {
        var request = a.entry.request;
        var menu = a.player.containerMenu;
        if (active != a) return;
        if (menu.containerId != request.containerId()) { finish("failed", "container_changed"); return; }
        if (request.slot() != -999 && (request.slot() < 0 || request.slot() >= menu.slots.size())) {
            finish("failed", "slot_out_of_range"); return;
        }
        if (!a.dispatched) {
            boolean recovery=request.original().has("inventory_recovery");
            if(!capabilityDispatchCheck(mc,a))return;
            MovementBudget.beforeClick(mc,request);
            if(active!=a)return;
            if(recovery && !capabilityDispatchCheck(mc,a))return;
            a.dispatched = true;
            a.dispatchTick = a.entry.ticks;
            a.entry.result.addProperty("dispatched", true);
            Runnable click=() -> mc.gameMode.handleInventoryMouseClick(menu.containerId, request.slot(), request.button(),
                    ClickType.valueOf(request.clickType().toUpperCase(Locale.ROOT)), a.player);
            try {
                Runnable verify=() -> {};
                if(recovery) {
                    long revision=ownershipRevision;
                    verify=InventoryRecoveryDispatch.run(mc,request,
                        () -> active==a && ACTIONS.active()==a.entry && a.entry.running() && ownershipRevision==revision
                            && !NativeFallRescue.blocksInput(),
                        () -> {ExternalControllerGuard.requireIdle(mc);
                            NativeFallRescue.requireOrdinaryAdmission();
        NativeExternalNavigation.requireOrdinaryAdmission();
                            String denied=a.capabilityGuard.check(mc,true);
                            if(denied!=null)throw new ClientActionRequest.Rejected(409,denied);},
                        () -> {ExternalControllerGuard.requireIdle(mc);
                            a.capabilityGuard.requireFresh(mc,"inventory_recovery_effect");},click);
                } else click.run();
                if(active!=a || mc.player!=a.player || mc.level!=a.level || a.player.containerMenu!=menu) {
                    a.entry.result.addProperty("unknown_outcome",true);
                    if(active==a)finish("failed","inventory_click_context_unconfirmed"); return;
                }
                var snapshot=BridgeServer.menuSnapshot(menu);
                if(active!=a || mc.player!=a.player || mc.level!=a.level || a.player.containerMenu!=menu) {
                    a.entry.result.addProperty("unknown_outcome",true);
                    if(active==a)finish("failed","inventory_click_context_unconfirmed"); return;
                }
                verify.run();
                if(active!=a){a.entry.result.addProperty("unknown_outcome",true);return;}
                a.entry.result.add("menu",snapshot);
                finish("succeeded", "click_dispatched");
            } catch(RuntimeException failure) {
                // Local menu callbacks may already have run. Never finish a replacement owner or replay.
                if(recovery || active!=a)a.entry.result.addProperty("unknown_outcome",true);
                if(active==a)failException(failure);
            }
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
        if(!placementFence(mc,a))return;
        BlockPos support = pos(a.entry.request.support());
        Direction face = Direction.valueOf(a.entry.request.face().toUpperCase(Locale.ROOT));
        BlockPos target = support.relative(face);
        if (a.dispatched) {
            verifyPlacementEffect(mc, a, target, true);
            return;
        }
        if(ClientActionRequest.bool(a.entry.request.original(),"capability_bridge",false)) {
            Vec3 edge=Vec3.atCenterOf(support).add(face.getStepX()*.65,.5,face.getStepZ()*.65);
            if(Math.hypot(edge.x-a.player.getX(),edge.z-a.player.getZ())>.04)return;
        }
        if (!(a.player.getMainHandItem().getItem() instanceof BlockItem item)) {
            finishPlacement(mc,a,"failed", "held_item_is_not_block"); return;
        }
        if(!placementFence(mc,a))return;
        boolean intersects=a.entry.request.jump() && a.player.getBoundingBox().intersects(new AABB(target));
        if(!placementFence(mc,a)||intersects)return;
        // Re-aim after physics moved the eye position this tick (essential for underfoot placement).
        aim(mc, CapabilityPlacement.hit(a.entry.request));
        if(!placementFence(mc,a))return;
        BlockHitResult hit = pick(mc, support, face);
        if(!placementFence(mc,a))return;
        if (hit == null) { finishPlacement(mc,a,"failed", "support_face_not_in_reach_or_visible"); return; }
        BlockPlaceContext placement = new BlockPlaceContext(a.player, InteractionHand.MAIN_HAND, a.player.getMainHandItem(), hit);
        if (!placement.getClickedPos().equals(target) || !placement.canPlace()) {
            finishPlacement(mc,a,"failed", "placement_target_not_available"); return;
        }
        String placementProblem=CapabilityPlacement.predicted(mc,a.entry.request,placement,item);
        if(placementProblem!=null){finishPlacement(mc,a,"failed",placementProblem);return;}
        if(!placementFence(mc,a))return;
        var event = ClientHooks.onClickInput(1, mc.options.keyUse, InteractionHand.MAIN_HAND);
        if(!placementFence(mc,a))return;
        if (event.isCanceled()) { finishPlacement(mc,a,"failed", "use_cancelled_by_mod"); return; }
        if(a.capabilityGuard!=null){hit=pick(mc,support,face);if(hit==null){finishPlacement(mc,a,"failed","support_face_not_in_reach_or_visible");return;}}
        if(!capabilityDispatchCheck(mc,a))return;
        if(a.capabilityGuard!=null) {
            BlockPlaceContext finalPlacement=new BlockPlaceContext(a.player,InteractionHand.MAIN_HAND,a.player.getMainHandItem(),hit);
            if(!finalPlacement.getClickedPos().equals(target)||!finalPlacement.canPlace()){finishPlacement(mc,a,"failed","placement_target_not_available");return;}
            placementProblem=CapabilityPlacement.predicted(mc,a.entry.request,finalPlacement,item);
            if(active!=a)return;
            if(placementProblem!=null){finishPlacement(mc,a,"failed",placementProblem);return;}
            if(!capabilityDispatchCheck(mc,a))return;
        }
        if(a.scopedPlacement!=null)a.scopedPlacement.beforeUse(mc,hit);
        if(!placementFence(mc,a))return;
        // Exactly one ordinary client interaction. A missing response is never an excuse to replay it.
        a.dispatched = true;
        a.dispatchTick = a.entry.ticks;
        a.placedBlock = a.capabilityGuard==null?item.getBlock():BuiltInRegistries.BLOCK.get(net.minecraft.resources.ResourceLocation.parse(ClientActionRequest.string(a.entry.request.original(),"expected_block_id")));
        a.entry.result.addProperty("dispatched", true);
        a.entry.result.add("target", cellJson(target));
        int beforeCount = a.player.getMainHandItem().getCount();
        a.placementBeforeCount = beforeCount;
        a.placementBeforeItem = a.player.getMainHandItem().getItem();
        a.placementBeforeSlot = a.player.getInventory().selected;
        a.placementBeforeState = mc.level.getBlockState(target);
        a.entry.result.addProperty("placement_before_count", beforeCount);
        a.entry.result.addProperty("placement_before_item", BuiltInRegistries.ITEM.getKey(a.placementBeforeItem).toString());
        a.entry.result.addProperty("placement_before_block", BuiltInRegistries.BLOCK.getKey(a.placementBeforeState.getBlock()).toString());
        a.entry.result.addProperty("placement_verification_max_ticks", PlacementEffectVerification.MAX_TICKS);
        if(!placementFence(mc,a))return;
        final BlockHitResult placementHit=hit;
        InteractionResult result = a.scopedPlacement==null ? mc.gameMode.useItemOn(a.player, InteractionHand.MAIN_HAND, hit)
            : ScopedPlacementDispatch.use(a.scopedPlacement,()->mc.gameMode.useItemOn(a.player,InteractionHand.MAIN_HAND,placementHit));
        if(!placementFence(mc,a))return;
        a.entry.result.addProperty("interaction_result", result.name().toLowerCase(Locale.ROOT));
        if (a.scopedPlacement==null && result.shouldSwing() && event.shouldSwingHand()) {
            a.player.swing(InteractionHand.MAIN_HAND);
            if(!placementFence(mc,a))return;
            boolean itemChanged=a.player.getMainHandItem().getCount() != beforeCount || mc.gameMode.hasInfiniteItems();
            if(!placementFence(mc,a))return;
            if(itemChanged)mc.gameRenderer.itemInHandRenderer.itemUsed(InteractionHand.MAIN_HAND);
            if(!placementFence(mc,a))return;
        }
        // Even FAIL can follow packet/hook effects. Preserve it and only observe; never redispatch.
        a.entry.result.addProperty("placement_effect_verification", "pending_read_only");
    }

    private static boolean placementFence(Minecraft mc,RuntimeAction a) {
        boolean same=a.placementOwner.same(active,mc.player,mc.level,mc.gameMode,
            mc.player==null?null:mc.player.containerMenu,mc.screen,ACTIONS.session,WorldGeneration.current(mc.level));
        if(same)return true;
        placementUnknown(a,"placement_callback_context_changed");
        if(active==a)finish("failed","placement_callback_context_changed");
        return false;
    }
    private static void placementUnknown(RuntimeAction a,String reason) {
        a.entry.result.addProperty("unknown_outcome",true);
        a.entry.result.addProperty("requires_handoff",true);
        a.entry.result.addProperty("effects_none_proven",false);
        a.entry.result.addProperty("placement_callback_failure",reason);
    }
    private static void finishPlacement(Minecraft mc,RuntimeAction a,String status,String reason) {
        if(placementFence(mc,a))finish(status,reason);
    }

    private static boolean externalOwnerCheck(Minecraft mc,RuntimeAction a) {
        boolean idle=ExternalControllerGuard.idle(mc);
        if(active!=a)return false;
        if(idle)return true;
        a.entry.result.addProperty("unknown_outcome",true);
        a.entry.result.addProperty("requires_handoff",true);
        a.entry.result.addProperty("no_auto_resume",true);
        finish("failed","external_controller_owner_unconfirmed");
        return false;
    }
    private static boolean capabilityDispatchCheck(Minecraft mc,RuntimeAction a) {
        if(active!=a || !externalOwnerCheck(mc,a))return false;
        String budgetProblem=MovementBudget.problem(mc);
        if(active!=a)return false;
        if(budgetProblem!=null && !(a.entry.request.action().equals("movement_budget_finish")&&MovementBudget.snapshot().get("status").getAsString().equals("stopping"))){finish("cancelled",budgetProblem);return false;}
        if(a.capabilityGuard!=null) {
            String denied=a.capabilityGuard.check(mc,a.dispatched);
            if(active!=a)return false;
            if(denied!=null){finish("cancelled",denied);return false;}
        }
        // Final supported API query follows every callback-backed policy reader.
        if(!externalOwnerCheck(mc,a))return false;
        if(a.capabilityGuard!=null && !a.dispatched)a.capabilityGuard.requireFresh(mc,"external_controller_effect");
        if(active!=a)return false;
        if(System.nanoTime()>=a.deadline){finish("failed","deadline_exceeded");return false;}
        NativeFallRescue.requireOrdinaryAdmission();
        NativeExternalNavigation.requireOrdinaryAdmission();
        return active==a;
    }
    private static void interactBlock(Minecraft mc,RuntimeAction a) {
        if(a.dispatched){finish("succeeded","interaction_dispatched");return;}
        BlockPos target=pos(a.entry.request.target());
        Direction face=Direction.valueOf(a.entry.request.face().toUpperCase(Locale.ROOT));
        blockMenuPhase(a, BlockMenuDiagnostics.Stage.CLICK, BlockMenuDiagnostics.Phase.AIM);
        aim(mc,Vec3.atCenterOf(target).add(face.getStepX()*.5,face.getStepY()*.5,face.getStepZ()*.5));
        blockMenuPhase(a, BlockMenuDiagnostics.Stage.CLICK, BlockMenuDiagnostics.Phase.INITIAL_PICK);
        BlockHitResult hit=pick(mc,target,face);
        if(hit==null){finish("failed","target_face_not_in_reach_or_visible");return;}
        if (a.scopedBlockMenu != null) a.entry.result.addProperty("local_click_hooks_started", true);
        blockMenuPhase(a, BlockMenuDiagnostics.Stage.CLICK, BlockMenuDiagnostics.Phase.CLICK_HOOKS);
        var event=ClientHooks.onClickInput(1,mc.options.keyUse,InteractionHand.MAIN_HAND);
        if(event.isCanceled()){finish("failed","use_cancelled_by_mod");return;}
        blockMenuPhase(a, BlockMenuDiagnostics.Stage.CLICK, BlockMenuDiagnostics.Phase.REPEAT_PICK);
        hit=pick(mc,target,face);
        if(hit==null){finish("failed","target_face_not_in_reach_or_visible");return;}
        blockMenuPhase(a, BlockMenuDiagnostics.Stage.CLICK, BlockMenuDiagnostics.Phase.CAPABILITY_CHECK);
        if(!capabilityDispatchCheck(mc,a))return;
        if (a.scopedBlockMenu != null) {
            // Admission before native use is mandatory; the packet fence is a second check.
            // Any refusal after entry may have local or slot-sync effects and remains unknown.
            blockMenuPhase(a, BlockMenuDiagnostics.Stage.PRE_LOCAL_USE, BlockMenuDiagnostics.Phase.READINESS);
            if (!ScopedBlockMenuDispatch.ready()) throw new ClientActionRequest.Rejected(409, "block_menu_post_hook_fence_unavailable");
            hit = a.scopedBlockMenu.beforeLocalBlockUse(mc, a.entry.request.id());
            a.scopedPacketPending = true; a.scopedPacketHit = hit;
            a.entry.result.addProperty("local_use_started", true);
        } else { a.dispatched=true;a.entry.result.addProperty("dispatched",true); }
        blockMenuPhase(a, BlockMenuDiagnostics.Stage.NATIVE_USE, BlockMenuDiagnostics.Phase.NATIVE_USE);
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
        blockMenuPhase(a, BlockMenuDiagnostics.Stage.NATIVE_USE, BlockMenuDiagnostics.Phase.SWING);
        if(result.shouldSwing() && event.shouldSwingHand())a.player.swing(InteractionHand.MAIN_HAND);
        if(active!=a)return;
        blockMenuPhase(a, BlockMenuDiagnostics.Stage.NATIVE_USE, BlockMenuDiagnostics.Phase.TERMINAL);
        finish(result==InteractionResult.FAIL?"failed":"succeeded",result==InteractionResult.FAIL?"interaction_rejected":"interaction_dispatched");
    }
    private static void blockMenuPhase(RuntimeAction a, BlockMenuDiagnostics.Stage stage, BlockMenuDiagnostics.Phase phase) {
        if (a.scopedBlockMenu != null) a.scopedBlockMenu.blockMenuDiagnostics.mark(stage, phase);
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
        if (finishUseItemIfObserved(mc, a) || !useItemOwnerContext(mc, a)) return;
        if(a.entry.ticks-a.dispatchTick>=maxTicks)finish("failed","item_use_budget_exhausted");
    }
    private static boolean finishUseItemIfObserved(Minecraft mc, RuntimeAction a) {
        if (!a.dispatched || !useItemOwnerContext(mc, a)) return false;
        // Keep the existing Post completion predicate, including its later-tick
        // requirement. Pre only observes completion; it never starts item use.
        boolean finished = a.player.getMainHandItem().getCount()!=a.useBeforeCount
                || a.entry.ticks>a.dispatchTick && !a.player.isUsingItem();
        // Observations may run mod code. Never finish a replacement owner or a
        // stale player/world after such a callback.
        if (!finished || !useItemOwnerContext(mc, a)) return false;
        finish("succeeded", "item_use_finished_observed");
        return true;
    }
    private static boolean useItemOwnerContext(Minecraft mc, RuntimeAction a) {
        return active == a && mc.player == a.player && mc.level == a.level && mc.gameMode != null;
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
        if(a.entry.request.action().equals("place_block") && a.dispatched && !status.equals("succeeded")) {
            a.entry.result.addProperty("unknown_outcome",true);
            a.entry.result.addProperty("requires_handoff",true);
            a.entry.result.addProperty("effects_none_proven",false);
        }
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
        requireCleanupOwner(a);
        a.entry.result.addProperty("x", a.player.getX());
        a.entry.result.addProperty("y", a.player.getY());
        a.entry.result.addProperty("z", a.player.getZ());
        requireCleanupOwner(a);
        if (a.input != null) {
            a.input.forwardImpulse = a.input.leftImpulse = 0;
            a.input.up = a.input.down = a.input.left = a.input.right = a.input.jumping = a.input.shiftKeyDown = false;
        }
        boolean attackReleased = true;
        if (a.attackHeld) {
            Minecraft mc = Minecraft.getInstance();
            if (discontinuityCleanup || a.capabilityGuard!=null) {
                attackReleased = releaseDiscontinuousAttack(() -> {requireCleanupOwner(a);mc.options.keyAttack.setDown(false);},
                        () -> {requireCleanupOwner(a); if (mc.gameMode != null) {
                            if(a.scopedMining!=null)ScopedMiningDispatch.cleanup(a.scopedMining,mc.gameMode::stopDestroyBlock);
                            else mc.gameMode.stopDestroyBlock();
                        } });
            } else {
                // Existing non-discontinuity ordering/errors remain unchanged.
                requireCleanupOwner(a);mc.options.keyAttack.setDown(false);
                requireCleanupOwner(a);if (mc.gameMode != null) mc.gameMode.stopDestroyBlock();
            }
        }
        if (managedCleanup) {
            boolean released = attackReleased;
            if (a.useHeld) {
                released &= cleanupStage(a,"use_key_release",() -> Minecraft.getInstance().options.keyUse.setDown(false));
                released &= cleanupStage(a,"use_item_release",() -> {if(Minecraft.getInstance().gameMode!=null)Minecraft.getInstance().gameMode.releaseUsingItem(a.player);});
            }
            if (a.capabilityTarget != null) released &= cleanupStage(a,"target_release",() -> a.capabilityTarget.release(Minecraft.getInstance()));
            if (a.transfer != null) released &= cleanupStage(a,"transfer_release",a.transfer::release);
            if (a.boat != null) released &= cleanupStage(a,"boat_release",() -> a.boat.release(Minecraft.getInstance()));
            if (a.combat != null) released &= cleanupStage(a,"combat_release",() -> a.combat.release(Minecraft.getInstance()));
            released &= cleanupStage(a,"sprint_release",() -> sprint(Minecraft.getInstance(), a, false));
            requireCleanupOwner(a);
            if(a.scopedMovement!=null) {
                boolean neutral=ScopedFlatMovement.neutral(a.input) && ScopedFlatMovement.neutral(a.player.input)
                        && !ScopedFlatMovement.keysDown(Minecraft.getInstance()) && !BridgeServer.hasHeldInputs();
                released &= neutral;
                a.entry.result.add("scoped_movement",a.scopedMovement.terminal(neutral));
            }
            if(a.scopedStepDown!=null) {
                boolean neutral=ScopedFlatMovement.neutral(a.input) && ScopedFlatMovement.neutral(a.player.input)
                        && !ScopedFlatMovement.keysDown(Minecraft.getInstance()) && !BridgeServer.hasHeldInputs();
                released &= neutral;
                a.entry.result.add("step_down",a.scopedStepDown.terminal(neutral));
                if(status.equals("succeeded") && !a.scopedStepDown.settled()){status="failed";reason="step_down_landing_unconfirmed";}
            }
            if(a.scopedLocalSegment!=null) {
                boolean neutral=ScopedFlatMovement.neutral(a.input) && ScopedFlatMovement.neutral(a.player.input)
                        && !ScopedFlatMovement.keysDown(Minecraft.getInstance()) && !BridgeServer.hasHeldInputs();
                released &= neutral;
                a.entry.result.add("local_segment",a.scopedLocalSegment.terminal(neutral));
                if(status.equals("succeeded") && !a.scopedLocalSegment.settled()){status="failed";reason="local_segment_landing_unconfirmed";}
            }
            // Keep encounter evidence aligned with the terminal cleanup outcome.
            if(a.combat!=null) a.combat.terminal(released?status:"failed",released?reason:"input_release_unconfirmed");
            requireCleanupOwner(a);
            if(MovementBudget.armed()) {
                MovementBudget.observe(Minecraft.getInstance(),false);
                requireCleanupOwner(a);
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
                Minecraft mc=Minecraft.getInstance();
                boolean semanticContext=a.scopedPlacement.cleanupState(status.equals("succeeded"));
                boolean keyNeutral=ScopedMining.neutral(a.input)&&ScopedMining.neutral(a.player.input)
                    &&!mc.options.keyAttack.isDown()&&!ScopedMining.otherKeys(mc)&&!BridgeServer.hasHeldInputs();
                boolean releaseBinding=a.scopedPlacement.releaseBinding(mc);
                released &= keyNeutral&&releaseBinding;
                if((!released||!semanticContext)&&a.scopedPlacement.attempted()){
                    a.scopedPlacement.markUnknown();a.entry.result.addProperty("unknown_outcome",true);a.entry.result.addProperty("requires_handoff",true);
                }
                if(!semanticContext&&status.equals("succeeded")){
                    a.entry.result.addProperty("requested_terminal_status",status);a.entry.result.addProperty("requested_terminal_reason",reason);
                    status="failed";reason="placement_cleanup_context_unconfirmed";
                }
                a.entry.result.add("placement_diagnostics",a.scopedPlacement.diagnostics(keyNeutral,releaseBinding,semanticContext));
                a.entry.result.add("placement",a.scopedPlacement.terminal(keyNeutral,status.equals("succeeded")&&released&&semanticContext));
            }
            if(FALL_CLEANUP.active()) {
                boolean bound=FALL_CLEANUP.bound(a,a.entry);
                released &= bound;
                if(!bound){
                    releaseDiagnostic(a,"fall_preemption_final_fence","fall_rescue_cleanup_scope_changed");
                    if(a.combat!=null)a.combat.terminal("failed","input_release_unconfirmed");
                }
                // A late callback may retire the old registry entry; never finish a replacement.
                if(ACTIONS.active()!=a.entry){a.entry.result.addProperty("unknown_outcome",true);return;}
            }
            ACTIONS.finishAfterCleanup(status, reason, released);
            if (a.combat != null && !reason.equals("native_fall_rescue_preempted"))
                EncounterTerminalPause.afterTerminal(a.entry, ACTIONS.session, BridgeServer::pauseEncounterTerminalOnGameThread);
            else if(a.combat!=null && reason.equals("native_fall_rescue_preempted"))
                a.entry.result.addProperty("automatic_terminal_pause_deferred_to_fall_rescue",true);
        }
    }
    static boolean releaseDiscontinuousAttack(Runnable keyUp, Runnable stopDestroy) {
        boolean released = cleanup(keyUp);
        released &= cleanup(stopDestroy); // Non-short-circuit: attempt both even after failure.
        return released;
    }
    private static void requireCleanupOwner(RuntimeAction a) {
        if(FALL_CLEANUP.active()&&!FALL_CLEANUP.bound(a,a.entry))
            throw new ClientActionRequest.Rejected(409,"fall_rescue_cleanup_scope_changed");
    }
    private static void releaseDiagnostic(RuntimeAction a,String stage,String reason) {
        if(a.entry.result.has("input_release_diagnostics"))return;
        JsonObject value=new JsonObject();value.addProperty("schema_version",1);
        value.addProperty("failed_stage",stage);value.addProperty("reason",reason);
        a.entry.result.add("input_release_diagnostics",value);
    }
    private static boolean cleanupStage(RuntimeAction a,String stage,Runnable release) {
        try {requireCleanupOwner(a);release.run();requireCleanupOwner(a);return true;}
        catch(RuntimeException failure){
            String reason=failure instanceof ClientActionRequest.Rejected&&failure.getMessage()!=null
                &&failure.getMessage().matches("[a-z0-9_]{1,100}")?failure.getMessage():"release_callback_failed";
            releaseDiagnostic(a,stage,reason);return false;
        }
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

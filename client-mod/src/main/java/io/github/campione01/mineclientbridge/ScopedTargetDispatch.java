package io.github.campione01.mineclientbridge;

import java.util.IdentityHashMap;
import net.minecraft.client.Minecraft;
import net.minecraft.network.protocol.Packet;
import net.minecraft.network.protocol.game.ServerboundInteractPacket;
import net.minecraft.network.protocol.game.ServerboundPlayerActionPacket;
import net.minecraft.network.protocol.game.ServerboundSetCarriedItemPacket;
import net.minecraft.network.protocol.game.ServerboundSwingPacket;
import net.minecraft.network.protocol.game.ServerboundUseItemPacket;
import net.minecraft.network.protocol.game.ServerboundUseItemOnPacket;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.player.Player;
import static io.github.campione01.mineclientbridge.TargetActionEffectBudget.Effect;

/** Synchronous exact-effect token. Final local and connection-send hooks are mandatory. */
public final class ScopedTargetDispatch {
    private static boolean attackReady,useReady,releaseReady,releaseLocalReady,stopLocalReady,packetReady,sendReady,startLocalReady,bowLocalReady,meleeLocalReady,meleePostReady,meleeSecondaryReady,meleeInvulnerabilityReady,useReplacementReady;
    private static final ThreadLocal<Call> CALL=new ThreadLocal<>();
    private enum Phase { CALL_ENTRY, BODY_RETURN, ATTACK_ENTRY, ATTACK_LOCAL_ENTRY, USE_ENTRY, USE_LOCAL_ENTRY,
        USE_REPLACEMENT, RELEASE_ENTRY, RELEASE_LOCAL_ENTRY, START_USE_MUTATION, BOW_DRAW,
        MELEE_IMPACT, MELEE_SWEEP, MELEE_SECONDARY, MELEE_INVULNERABILITY, MELEE_POST,
        STOP_ENTRY, STOP_MUTATION, PACKET_HEAD, FINAL_SEND }
    private enum Stage { ENTRY, CHECK_BEGIN, GEOMETRY, POLICY, GEOMETRY_RECHECK, EXTERNAL_RECHECK, RAW_CHECK,
        CHECK_COMPLETE, RESERVED, BODY, ARGUMENTS, LOCAL_CHARGED, PACKET_HEAD_RECORDED,
        PRE_SEND_CHARGED, TRAILING_RAW, FENCE_RETURNED, RETURN_VERIFICATION }
    private static final class Call {
        final ScopedTargetAction guard;
        final Effect kind;
        final boolean cleanup;
        final CombatCallbackFence fence;
        final IdentityHashMap<Packet<?>,Boolean> packets=new IdentityHashMap<>();
        int localCount,headCount,sendCount,selectionHead,selectionSend,cooldowns;
        net.minecraft.world.item.ItemStack stopStack;
        ScopedTargetAction.StackGeometry stopSnapshot;
        InteractionHand stopHand;
        boolean stopStarted;
        Phase phase=Phase.CALL_ENTRY;Stage stage=Stage.ENTRY;
        Call(ScopedTargetAction guard,Effect kind,boolean cleanup){
            this.guard=guard;this.kind=kind;this.cleanup=cleanup;
            java.util.function.BooleanSupplier owner=()->cleanup?ClientActions.terminalTargetCleanup(guard,guard.entry):ClientActions.ownsScopedTarget(guard,guard.entry);
            fence=cleanup?new CombatCallbackFence(owner,System::nanoTime,guard.level::getGameTime):CombatCallbackFence.forAction(owner,System::nanoTime,guard.level::getGameTime,guard.deadline);
        }
    }
    public static void attackInstalled(){attackReady=true;}
    public static void useInstalled(){useReady=true;}
    public static void releaseInstalled(){releaseReady=true;}
    public static void releaseLocalInstalled(){releaseLocalReady=true;}
    public static void stopLocalInstalled(){stopLocalReady=true;}
    public static void packetInstalled(){packetReady=true;}
    public static void sendInstalled(){sendReady=true;}
    public static void startLocalInstalled(){startLocalReady=true;}
    public static void bowLocalInstalled(){bowLocalReady=true;}
    public static void meleeLocalInstalled(){meleeLocalReady=true;}
    public static void meleePostInstalled(){meleePostReady=true;}
    public static void meleeSecondaryInstalled(){meleeSecondaryReady=true;}
    public static void meleeInvulnerabilityInstalled(){meleeInvulnerabilityReady=true;}
    public static void useReplacementInstalled(){useReplacementReady=true;}
    static boolean ready(){return attackReady&&useReady&&releaseReady&&releaseLocalReady&&stopLocalReady&&packetReady&&sendReady
        &&startLocalReady&&bowLocalReady&&meleeLocalReady&&meleePostReady&&meleeSecondaryReady&&meleeInvulnerabilityReady&&useReplacementReady&&AttackPacketReader.ready();}
    static void run(CapabilityTargetAction action,Effect kind,Runnable body){run(action,kind,false,body);}
    static void cleanup(CapabilityTargetAction action,Effect kind,Runnable body){run(action,kind,true,body);}
    private static void run(CapabilityTargetAction action,Effect kind,boolean cleanup,Runnable body){
        ScopedTargetAction guard=action.scoped();
        ScopedTargetAction.require(guard!=null,"target_scope_required");
        ScopedTargetAction.require(CALL.get()==null,"target_recursive_effect_forbidden");
        Call call=new Call(guard,kind,cleanup);CALL.set(call);boolean entered=false;
        try{
            check(call);guard.budget.reserve(kind);call.stage=Stage.RESERVED;entered=true;call.stage=Stage.BODY;body.run();call.phase=Phase.BODY_RETURN;call.stage=Stage.TRAILING_RAW;call.fence.raw();
            if(cleanup)guard.cleanupFence(Minecraft.getInstance());else guard.rawBound(Minecraft.getInstance());
            call.stage=Stage.RETURN_VERIFICATION;
            if(kind==Effect.ABORT){ScopedTargetAction.require(call.localCount==1&&call.sendCount==0,"target_abort_local_unconfirmed");}
            else if(kind==Effect.SWING){ScopedTargetAction.require(call.sendCount==1,"target_swing_packet_unconfirmed");}
            else ScopedTargetAction.require(call.localCount==1&&call.sendCount==1,"target_effect_local_or_packet_unconfirmed");
        }catch(RuntimeException failure){
            if(entered||guard.budget.attempted()||guard.budget.unknown())guard.unknown();
            diagnostic(call,failure);throw failure;
        }
        finally{call.fence.close();CALL.remove();}
    }
    private static void check(Call call){
        call.stage=Stage.CHECK_BEGIN;
        call.fence.check(()->{
            Minecraft mc=Minecraft.getInstance();
            if(call.cleanup){call.guard.cleanupFence(mc);return;}
            if(call.kind==Effect.SWING){call.guard.rawBound(mc);return;}
            call.stage=Stage.GEOMETRY;var geometry=call.guard.geometry();
            call.stage=Stage.POLICY;call.guard.beforeEffect(mc,call.kind);
            call.stage=Stage.GEOMETRY_RECHECK;call.guard.geometryUnchanged(geometry);
            call.stage=Stage.EXTERNAL_RECHECK;call.guard.finalExternalFence(geometry);
            call.stage=Stage.RAW_CHECK;call.guard.rawBound(mc);
        });
        call.stage=Stage.CHECK_COMPLETE;
    }
    /** Fixed local diagnostic vocabulary only. Never log arbitrary exception text, stack, target or packet data. */
    private static String exceptionCode(RuntimeException failure){
        if(failure.getClass()==ClientActionRequest.Rejected.class)return "POLICY_REJECTED";
        if(failure.getClass()!=IllegalStateException.class)return "OTHER_RUNTIME_EXCEPTION";
        String message=failure.getMessage();
        if(message==null)return "OTHER_ILLEGAL_STATE";
        return switch(message){
            case "combat_callback_owner_clock_or_tick_changed" -> "CALLBACK_FENCE";
            case "combat_recursive_effect_check" -> "REENTRANT_FENCE";
            case "target_effect_scope_poisoned" -> "BUDGET_POISONED";
            case "target_single_melee_budget", "target_single_draw_budget", "target_single_release_budget",
                 "target_shield_use_budget", "target_shield_release_budget", "target_abort_budget", "target_swing_budget" -> "RESERVATION_BUDGET";
            case "target_duplicate_local_effect" -> "LOCAL_BUDGET";
            case "target_duplicate_effect_packet" -> "PACKET_BUDGET";
            case "external_controller_game_thread_context_required" -> "EXTERNAL_CONTEXT";
            default -> "OTHER_ILLEGAL_STATE";
        };
    }
    private static void diagnostic(Call call,RuntimeException failure){
        try {
            BridgeLog.LOGGER.warn("Scoped target diagnostic: phase={} stage={} code={} fence={} sampled_elapsed_ns={} pre_send_charges={} local_charges={}",
                call.phase.name(),call.stage.name(),exceptionCode(failure),call.fence.failure().name(),call.fence.sampledElapsed(),
                call.guard.budget.packets(call.kind),call.guard.budget.local(call.kind));
        }catch(RuntimeException loggingFailure){ /* Logging cannot replace the original failure or cleanup path. */ }
    }
    private static Call current(Player player){
        Call call=CALL.get();ScopedTargetAction active=ClientActions.activeScopedTarget();
        if(call==null){ScopedTargetAction.require(active==null||player!=active.player,"target_unscoped_effect_forbidden");return null;}
        ScopedTargetAction.require(player==call.guard.player,"target_effect_player_changed");return call;
    }
    public static void beforeAttack(Player player,Entity target,boolean local){
        beforeAttack(player,target,local,local?Phase.ATTACK_LOCAL_ENTRY:Phase.ATTACK_ENTRY);
    }
    private static void beforeAttack(Player player,Entity target,boolean local,Phase phase){
        Call call=current(player);if(call==null)return;call.phase=phase;call.stage=Stage.ARGUMENTS;
        ScopedTargetAction.require(call.kind==Effect.MELEE&&!call.cleanup&&target==call.guard.action().hitTarget(),"target_attack_identity_or_kind_changed");
        check(call); // Player.attack contains later NeoForge callbacks; charge at its primary impact seam.
    }
    public static boolean beforeUse(Player player,InteractionHand hand,boolean onBlock,boolean local){
        Call call=CALL.get();
        if(call==null)return ClientActions.activeScopedTarget()==null;
        call.phase=local?Phase.USE_LOCAL_ENTRY:Phase.USE_ENTRY;call.stage=Stage.ARGUMENTS;
        ScopedTargetAction.require(player==call.guard.player&&!onBlock&&!call.cleanup
            &&(call.kind==Effect.DRAW&&hand==InteractionHand.MAIN_HAND||call.kind==Effect.SHIELD_USE&&hand==InteractionHand.OFF_HAND),"target_wrong_use_effect");
        ScopedTargetAction.require(!player.isUsingItem(),"target_use_already_active");
        check(call);return true; // Charge only after onArrowNock/onItemUseStart, at the final field write.
    }
    /** Exact vanilla bow/shield use preserves its stack object. A hook-returned
     * replacement is outside this primitive, even if it is an equal copy. */
    public static void beforeUseReplacement(Player player){
        Call call=current(player);if(call==null)return;call.phase=Phase.USE_REPLACEMENT;call.stage=Stage.ARGUMENTS;
        throw new ClientActionRequest.Rejected(409,"target_use_stack_replacement_forbidden");
    }
    public static void beforeRelease(Player player,boolean local){
        Call call=current(player);if(call==null)return;call.phase=local?Phase.RELEASE_LOCAL_ENTRY:Phase.RELEASE_ENTRY;call.stage=Stage.ARGUMENTS;
        ScopedTargetAction.require(call.kind==Effect.BOW_RELEASE||call.kind==Effect.SHIELD_RELEASE||call.kind==Effect.SHIELD_CLEANUP,"target_wrong_release_effect");
        boolean bow=call.kind==Effect.BOW_RELEASE;
        var used=player.getUseItem();var bound=ScopedTargetAction.argumentStack(used);
        var hand=bow?InteractionHand.MAIN_HAND:InteractionHand.OFF_HAND;
        ScopedTargetAction.require(player.isUsingItem()&&player.getUsedItemHand()==hand
            &&used.getItem()==(bow?net.minecraft.world.item.Items.BOW:net.minecraft.world.item.Items.SHIELD),"target_release_item_changed");
        check(call);ScopedTargetAction.unchangedArgument(bound,player.getUseItem());
        ScopedTargetAction.require(player.isUsingItem()&&player.getUsedItemHand()==hand,"target_final_release_state_changed");
        if(local&&!bow)local(call); // Bow has another onArrowLoose event before its final local seam.
    }
    public static void beforeStartUseMutation(LivingEntity entity,InteractionHand hand,net.minecraft.world.item.ItemStack stack,int duration){
        if(!(entity instanceof Player player))return;Call call=current(player);if(call==null)return;call.phase=Phase.START_USE_MUTATION;call.stage=Stage.ARGUMENTS;
        var bound=ScopedTargetAction.argumentStack(stack);
        ScopedTargetAction.require(!call.cleanup&&(call.kind==Effect.DRAW&&hand==InteractionHand.MAIN_HAND
            ||call.kind==Effect.SHIELD_USE&&hand==InteractionHand.OFF_HAND)
            &&stack==player.getItemInHand(hand)&&duration==72000
            &&stack.getItem()==(call.kind==Effect.DRAW?net.minecraft.world.item.Items.BOW:net.minecraft.world.item.Items.SHIELD),"target_start_use_mutation_changed");
        ScopedTargetAction.require(!player.isUsingItem(),"target_use_already_active");check(call);
        ScopedTargetAction.unchangedArgument(bound,player.getItemInHand(hand));
        ScopedTargetAction.require(!player.isUsingItem(),"target_final_use_already_active");local(call);
    }
    public static void beforeBowDraw(net.minecraft.world.item.ItemStack weapon,net.minecraft.world.item.ItemStack ammo,LivingEntity entity){
        if(!(entity instanceof Player player))return;Call call=current(player);if(call==null)return;call.phase=Phase.BOW_DRAW;call.stage=Stage.ARGUMENTS;
        // Capture both arguments before CommonHooks.getProjectile or component equality can run.
        var boundWeapon=ScopedTargetAction.argumentStack(weapon);var boundAmmo=ScopedTargetAction.argumentStack(ammo);
        ScopedTargetAction.require(call.kind==Effect.BOW_RELEASE&&!call.cleanup&&weapon==player.getUseItem()
            &&weapon==player.getItemInHand(InteractionHand.MAIN_HAND)&&ammo.is(net.minecraft.world.item.Items.ARROW)
            &&CapabilityItemBinding.same(ammo,player.getProjectile(weapon)),"target_bow_local_draw_changed");
        ScopedTargetAction.unchangedArgument(boundWeapon,weapon);ScopedTargetAction.unchangedArgument(boundAmmo,ammo);
        check(call);ScopedTargetAction.unchangedArgument(boundWeapon,weapon);ScopedTargetAction.unchangedArgument(boundAmmo,ammo);
        ScopedTargetAction.require(weapon==player.getUseItem()&&weapon==player.getItemInHand(InteractionHand.MAIN_HAND)
            &&weapon.getItem()==net.minecraft.world.item.Items.BOW&&ammo.getItem()==net.minecraft.world.item.Items.ARROW,
            "target_bow_final_arguments_changed");
        call.guard.rawBound(Minecraft.getInstance());local(call);
    }
    public static void beforeMeleeImpact(Player player,Entity target){
        Call call=current(player);if(call==null)return;
        beforeAttack(player,target,false,Phase.MELEE_IMPACT);check(call);local(call);
    }
    public static void beforeMeleeSweep(Player player,boolean sweeping){
        Call call=current(player);if(call==null)return;call.phase=Phase.MELEE_SWEEP;call.stage=Stage.ARGUMENTS;
        ScopedTargetAction.require(call.kind==Effect.MELEE&&!sweeping,"target_sweep_forbidden");check(call);
    }
    public static void beforeMeleeSecondaryMutation(Player player){
        Call call=current(player);if(call==null)return;call.phase=Phase.MELEE_SECONDARY;call.stage=Stage.ARGUMENTS;
        throw new ClientActionRequest.Rejected(409,"target_secondary_knockback_forbidden");
    }
    public static void beforeMeleeInvulnerability(Entity entity,net.minecraft.world.damagesource.DamageSource source){
        Call call=CALL.get();if(call==null||call.kind!=Effect.MELEE)return;
        if(entity!=call.guard.target&&entity!=call.guard.action().hitTarget())return;
        call.phase=Phase.MELEE_INVULNERABILITY;call.stage=Stage.ARGUMENTS;
        ScopedTargetAction.require(source.getClass()==net.minecraft.world.damagesource.DamageSource.class
            &&source.getEntity()==call.guard.player&&source.getDirectEntity()==call.guard.player,"target_melee_damage_source_changed");
        check(call);
        ScopedTargetAction.require(source.getEntity()==call.guard.player&&source.getDirectEntity()==call.guard.player,"target_melee_final_damage_source_changed");
        call.fence.raw();
    }
    public static void beforeMeleePostMutation(Player player){
        Call call=current(player);if(call==null)return;call.phase=Phase.MELEE_POST;call.stage=Stage.ARGUMENTS;
        ScopedTargetAction.require(call.kind==Effect.MELEE&&call.localCount==1,"target_melee_post_without_impact");
        call.fence.check(()->{
            var geometry=call.guard.geometry();call.guard.afterMelee(Minecraft.getInstance());
            call.guard.geometryUnchanged(geometry);call.guard.finalExternalFence(geometry);call.guard.rawBound(Minecraft.getInstance());
        });
    }
    public static void beforeStopUsing(LivingEntity player){beforeStop(player,false);}
    public static void beforeStopMutation(LivingEntity player){beforeStop(player,true);}
    private static void beforeStop(LivingEntity player,boolean local){
        Call call=CALL.get();if(call==null)return; // Natural interruption may safely stop; it cannot fire a bow.
        if(player!=call.guard.player)return; // Target death/other vanilla entities may stop their own item use.
        call.phase=local?Phase.STOP_MUTATION:Phase.STOP_ENTRY;call.stage=Stage.ARGUMENTS;
        if(!local){
            ScopedTargetAction.require(!call.stopStarted,"target_duplicate_stop_begin");
            call.stopStarted=true;call.stopStack=call.guard.player.getUseItem();
            call.stopSnapshot=ScopedTargetAction.argumentStack(call.stopStack);call.stopHand=call.guard.player.getUsedItemHand();
        }else{
            ScopedTargetAction.require(call.stopStarted&&call.stopStack==call.guard.player.getUseItem()
                &&call.stopHand==call.guard.player.getUsedItemHand()
                &&call.stopStack.getItem()==(call.kind==Effect.ABORT||call.kind==Effect.BOW_RELEASE?net.minecraft.world.item.Items.BOW:net.minecraft.world.item.Items.SHIELD),
                "target_stop_use_state_replaced");
        }
        if(local)ScopedTargetAction.unchangedArgument(call.stopSnapshot,call.guard.player.getUseItem());
        if(call.kind==Effect.ABORT){check(call);if(local){ScopedTargetAction.unchangedArgument(call.stopSnapshot,call.guard.player.getUseItem());local(call);}}
        else {ScopedTargetAction.require(call.kind==Effect.BOW_RELEASE||call.kind==Effect.SHIELD_RELEASE||call.kind==Effect.SHIELD_CLEANUP,"target_unexpected_stop_use");
            if(call.cleanup)call.guard.cleanupFence(Minecraft.getInstance());else call.guard.rawBound(Minecraft.getInstance());
            if(local)ScopedTargetAction.unchangedArgument(call.stopSnapshot,call.guard.player.getUseItem());}
    }
    private static void local(Call call){
        ScopedTargetAction.require(++call.localCount==1,"target_duplicate_local_effect");call.guard.budget.chargeLocal(call.kind);call.stage=Stage.LOCAL_CHARGED;
        call.fence.raw();
    }
    private static boolean effectPacket(Packet<?> packet){return packet instanceof ServerboundInteractPacket||packet instanceof ServerboundUseItemPacket
        ||packet instanceof ServerboundUseItemOnPacket||packet instanceof ServerboundSetCarriedItemPacket
        ||packet instanceof ServerboundPlayerActionPacket action&&(action.getClass()!=ServerboundPlayerActionPacket.class
            ||action.getAction()==ServerboundPlayerActionPacket.Action.RELEASE_USE_ITEM);}
    public static void packet(Packet<?> packet){
        Call call=CALL.get();
        if(call==null){ScopedTargetAction.require(ClientActions.activeScopedTarget()==null||!effectPacket(packet),"target_unscoped_packet_forbidden");return;}
        call.phase=Phase.PACKET_HEAD;call.stage=Stage.ARGUMENTS;
        validatePacket(call,packet);check(call);validatePacket(call,packet);
        ScopedTargetAction.require(call.packets.put(packet,Boolean.FALSE)==null,"target_repeated_packet_head");
        if(packet instanceof ServerboundSetCarriedItemPacket)ScopedTargetAction.require(++call.selectionHead==1,"target_duplicate_selection_packet");
        else ScopedTargetAction.require(++call.headCount==1,"target_duplicate_effect_packet_head");
        call.stage=Stage.PACKET_HEAD_RECORDED;call.fence.raw();
    }
    public static void send(Packet<?> packet){
        Call call=CALL.get();
        if(call==null){ScopedTargetAction.require(ClientActions.activeScopedTarget()==null||!effectPacket(packet),"target_unscoped_final_packet_forbidden");return;}
        call.phase=Phase.FINAL_SEND;call.stage=Stage.ARGUMENTS;
        ScopedTargetAction.require(Boolean.FALSE.equals(call.packets.get(packet)),"target_final_packet_missing_or_reused");
        validatePacket(call,packet);check(call);validatePacket(call,packet);
        call.packets.put(packet,Boolean.TRUE);
        if(packet instanceof ServerboundSetCarriedItemPacket)ScopedTargetAction.require(++call.selectionSend==1,"target_duplicate_final_selection");
        else {ScopedTargetAction.require(++call.sendCount==1,"target_duplicate_final_effect");call.guard.budget.chargePacket(call.kind);}
        call.stage=Stage.PRE_SEND_CHARGED;call.fence.raw();call.stage=Stage.FENCE_RETURNED;
    }
    private static void validatePacket(Call call,Packet<?> packet){
        Class<?> type=packet.getClass();
        ScopedTargetAction.require(type==ServerboundSetCarriedItemPacket.class||type==ServerboundSwingPacket.class
            ||type==ServerboundInteractPacket.class||type==ServerboundUseItemPacket.class||type==ServerboundPlayerActionPacket.class,
            "target_packet_reader_unknown");
        if(packet instanceof ServerboundSetCarriedItemPacket slot){
            ScopedTargetAction.require(!call.cleanup&&slot.getSlot()==call.guard.selected,"target_wrong_selection_packet");return;
        }
        if(packet instanceof ServerboundSwingPacket swing){ScopedTargetAction.require(call.kind==Effect.SWING&&swing.getHand()==InteractionHand.MAIN_HAND,"target_wrong_swing_packet");return;}
        if(packet instanceof ServerboundInteractPacket interact){
            ScopedTargetAction.require(call.kind==Effect.MELEE&&interact instanceof io.github.campione01.mineclientbridge.mixin.ScopedCombatInteractAccessor
                &&((io.github.campione01.mineclientbridge.mixin.ScopedCombatInteractAccessor)interact).mineclientBridge$entityId()==call.guard.action().hitTarget().getId(),"target_wrong_attack_packet_identity");
            ScopedTargetAction.require(!interact.isUsingSecondaryAction(),"target_attack_packet_secondary_pose");
            ScopedTargetAction.require(AttackPacketReader.attack(interact),"target_interaction_is_not_exact_vanilla_attack");return;
        }
        if(packet instanceof ServerboundUseItemPacket use){ScopedTargetAction.require(Float.isFinite(use.getYRot())&&Float.isFinite(use.getXRot())
            &&use.getYRot()==call.guard.player.getYRot()&&use.getXRot()==call.guard.player.getXRot(),"target_use_packet_pose_changed");ScopedTargetAction.require(
            call.kind==Effect.DRAW&&use.getHand()==InteractionHand.MAIN_HAND||call.kind==Effect.SHIELD_USE&&use.getHand()==InteractionHand.OFF_HAND,"target_wrong_use_packet");return;}
        if(packet instanceof ServerboundPlayerActionPacket release){ScopedTargetAction.require(
            release.getAction()==ServerboundPlayerActionPacket.Action.RELEASE_USE_ITEM
            &&(call.kind==Effect.BOW_RELEASE||call.kind==Effect.SHIELD_RELEASE||call.kind==Effect.SHIELD_CLEANUP),"target_wrong_release_packet");return;}
        throw new ClientActionRequest.Rejected(409,"target_unexpected_packet");
    }
    /** The private final Action is not invoked: only the pinned vanilla attack singleton is admitted. */
    static final class AttackPacketReader {
        private static final java.lang.reflect.Field ACTION=field("action",false),SINGLETON=field("ATTACK_ACTION",true);
        private static final Object VANILLA=read(SINGLETON,null);
        private static java.lang.reflect.Field field(String name,boolean isStatic){
            try{
                var field=ServerboundInteractPacket.class.getDeclaredField(name);int modifiers=field.getModifiers();
                if(!java.lang.reflect.Modifier.isFinal(modifiers)||java.lang.reflect.Modifier.isStatic(modifiers)!=isStatic
                    ||!field.getType().getName().equals(ServerboundInteractPacket.class.getName()+"$Action")
                    ||field.getType().getClassLoader()!=ServerboundInteractPacket.class.getClassLoader()||!field.trySetAccessible())return null;
                return field;
            }catch(ReflectiveOperationException|SecurityException failure){return null;}
        }
        private static Object read(java.lang.reflect.Field field,Object owner){
            try{return field==null?null:field.get(owner);}catch(IllegalAccessException|IllegalArgumentException failure){return null;}
        }
        static boolean ready(){return ACTION!=null&&SINGLETON!=null&&VANILLA!=null
            &&VANILLA.getClass().getName().equals(ServerboundInteractPacket.class.getName()+"$1")
            &&VANILLA.getClass().getClassLoader()==ServerboundInteractPacket.class.getClassLoader()&&read(SINGLETON,null)==VANILLA;}
        static boolean attack(ServerboundInteractPacket packet){return ready()&&packet.getClass()==ServerboundInteractPacket.class&&read(ACTION,packet)==VANILLA;}
    }
    private ScopedTargetDispatch(){}
}

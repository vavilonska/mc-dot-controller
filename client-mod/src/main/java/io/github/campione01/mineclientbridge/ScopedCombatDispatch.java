package io.github.campione01.mineclientbridge;

import java.util.function.BooleanSupplier;
import java.util.function.Supplier;
import net.minecraft.client.Minecraft;
import net.minecraft.network.protocol.Packet;
import net.minecraft.network.protocol.game.ServerboundInteractPacket;
import net.minecraft.network.protocol.game.ServerboundUseItemPacket;
import net.minecraft.network.protocol.game.ServerboundSetCarriedItemPacket;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.player.Player;

/** Dynamic effect fence only; ownership remains exclusively with ClientActions. */
public final class ScopedCombatDispatch {
    private static final class Call {
        final ScopedCombat guard;final BoundedCombat combat;final boolean attack;
        final CombatCallbackFence fence;
        int effectPackets,swingPackets,selectionPackets;
        Call(ScopedCombat guard,BoundedCombat combat,boolean attack){this.guard=guard;this.combat=combat;this.attack=attack;
            fence=new CombatCallbackFence(()->ClientActions.ownsScopedCombat(guard,guard.entry),System::nanoTime,()->guard.level.getGameTime());}
    }
    private static final ThreadLocal<Call> CALL=new ThreadLocal<>();
    private static final ThreadLocal<Cleanup> CLEANUP=new ThreadLocal<>();
    private record Cleanup(ScopedCombat guard,boolean terminal){}
    private static boolean packetReady,attackReady;
    public static void packetInstalled(){packetReady=true;}
    public static void attackInstalled(){attackReady=true;}
    static boolean ready(){return packetReady && attackReady;}
    static boolean attack(BoundedCombat combat,BooleanSupplier vanilla){return run(combat,true,vanilla::getAsBoolean);}
    static <T> T shield(BoundedCombat combat,Supplier<T> vanilla){return run(combat,false,vanilla);}
    private static <T> T run(BoundedCombat combat,boolean attack,Supplier<T> vanilla){
        ScopedCombat guard=ClientActions.scopedCombat(combat);
        if(guard==null){ScopedCombat.require(ClientActions.ownsCombat(combat),"combat_owner_changed");return vanilla.get();}
        ScopedCombat.require(CALL.get()==null,"scoped_combat_recursive_effect_forbidden");
        Call call=new Call(guard,combat,attack);CALL.set(call);
        boolean entered=false;
        try {check(call);entered=true;T result=vanilla.get();call.fence.raw();return result;}
        catch(RuntimeException failure){if(entered)guard.unknown();throw failure;}
        finally {call.fence.close();CALL.remove();}
    }
    static void cleanup(ScopedCombat guard,boolean terminal,Runnable body){
        if(guard==null){body.run();return;}
        ScopedCombat.require(CLEANUP.get()==null,"scoped_combat_recursive_cleanup");
        CLEANUP.set(new Cleanup(guard,terminal));try{guard.cleanupFence(Minecraft.getInstance(),terminal);body.run();guard.cleanupFence(Minecraft.getInstance(),terminal);}
        finally{CLEANUP.remove();}
    }
    private static void check(Call call){
        call.fence.check(()->{
        Minecraft mc=Minecraft.getInstance();call.guard.check(mc,call.attack);
        double x=mc.player.getX(),y=mc.player.getY(),z=mc.player.getZ();
        float yaw=mc.player.getYRot(),pitch=mc.player.getXRot();Object ray=mc.hitResult;
        double tx=call.guard.target.getX(),ty=call.guard.target.getY(),tz=call.guard.target.getZ();
        if(call.attack)call.combat.beforeScopedAttack(mc);
        else ScopedCombat.require(mc.player.getOffhandItem().is(net.minecraft.world.item.Items.SHIELD),"scoped_combat_shield_changed");
        call.guard.check(mc,call.attack); // All hooks precede exact owner/context recheck.
        ScopedCombat.require(mc.player.getX()==x && mc.player.getY()==y && mc.player.getZ()==z
            && mc.player.getYRot()==yaw && mc.player.getXRot()==pitch && mc.hitResult==ray
            && call.guard.target.getX()==tx && call.guard.target.getY()==ty && call.guard.target.getZ()==tz,
            "scoped_combat_effect_geometry_changed_during_hooks");
        });
    }
    public static void beforeAttack(Player player,Entity target){
        Call call=CALL.get();if(call==null)return;
        ScopedCombat.require(call.attack && player==call.guard.player && target==call.guard.target,"scoped_combat_attack_target_changed");check(call);
    }
    public static void packet(Packet<?> packet){
        Cleanup cleanup=CLEANUP.get();
        if(cleanup!=null){
            ScopedCombat.require(packet instanceof net.minecraft.network.protocol.game.ServerboundPlayerActionPacket release
                && release.getAction()==net.minecraft.network.protocol.game.ServerboundPlayerActionPacket.Action.RELEASE_USE_ITEM,
                "scoped_combat_cleanup_nonrelease_packet");cleanup.guard.cleanupFence(Minecraft.getInstance(),cleanup.terminal);return;
        }
        Call call=CALL.get();if(call==null)return;
        if(call.attack && packet instanceof net.minecraft.network.protocol.game.ServerboundSwingPacket swing){
            ScopedCombat.require(swing.getHand()==net.minecraft.world.InteractionHand.MAIN_HAND,"scoped_combat_wrong_swing_hand");
            ScopedCombat.require(++call.swingPackets==1,"scoped_combat_duplicate_swing");call.fence.raw();return;
        }
        if(packet instanceof ServerboundInteractPacket interact){
            ScopedCombat.require(++call.effectPackets==1,"scoped_combat_duplicate_effect_packet");
            ScopedCombat.require(interact instanceof io.github.campione01.mineclientbridge.mixin.ScopedCombatInteractAccessor
                && ((io.github.campione01.mineclientbridge.mixin.ScopedCombatInteractAccessor)interact).mineclientBridge$entityId()==call.guard.request.targetId(),
                "scoped_combat_packet_target_changed");
            boolean[] attack={false};interact.dispatch(new ServerboundInteractPacket.Handler(){
                public void onAttack(){attack[0]=true;}
                public void onInteraction(net.minecraft.world.InteractionHand hand){}
                public void onInteraction(net.minecraft.world.InteractionHand hand,net.minecraft.world.phys.Vec3 point){}
            });ScopedCombat.require(attack[0],"scoped_combat_packet_is_not_attack");
        }
        if(packet instanceof ServerboundUseItemPacket use){ScopedCombat.require(++call.effectPackets==1 && use.getHand()==net.minecraft.world.InteractionHand.OFF_HAND,"scoped_combat_packet_wrong_hand_or_duplicate");}
        if(packet instanceof ServerboundSetCarriedItemPacket slot)ScopedCombat.require(++call.selectionPackets==1 && slot.getSlot()==call.guard.player.getInventory().selected,"scoped_combat_packet_wrong_slot");
        ScopedCombat.require(packet instanceof ServerboundSetCarriedItemPacket
            || call.attack && packet instanceof ServerboundInteractPacket
            || !call.attack && packet instanceof ServerboundUseItemPacket,"scoped_combat_unexpected_effect_packet");
        check(call);
        if(packet instanceof ServerboundInteractPacket || packet instanceof ServerboundUseItemPacket)call.guard.chargeEffect();
    }
    private ScopedCombatDispatch(){}
}

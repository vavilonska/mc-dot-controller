package io.github.campione01.mineclientbridge;

import java.util.function.BooleanSupplier;
import net.minecraft.client.Minecraft;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.network.protocol.Packet;
import net.minecraft.network.protocol.game.ServerboundPlayerActionPacket;

/** A bounded dynamic callback token only. ClientActions retains the sole owner and all input writes. */
public final class ScopedMiningDispatch {
    private static boolean clientReady, gameModeReady;
    private static final ThreadLocal<ScopedMining> CALL=new ThreadLocal<>();
    private ScopedMiningDispatch() { }
    public static void clientInstalled(){clientReady=true;}
    public static void gameModeInstalled(){gameModeReady=true;}
    static boolean ready(){return clientReady && gameModeReady;}
    public static boolean attack(BooleanSupplier vanilla) {return attack(ClientActions.scopedMining(),vanilla);}
    static boolean attack(ScopedMining guard,BooleanSupplier vanilla) {
        if(guard==null)return vanilla.getAsBoolean();
        ScopedMining.require(CALL.get()==null,"mining_recursive_callback_forbidden");
        CALL.set(guard);
        try {
            if(guard.targetAir()){ClientActions.scopedMiningRemoved(guard);return false;}
            guard.check(Minecraft.getInstance(),false,true);
            guard.markAttempted();
            boolean result=vanilla.getAsBoolean();
            guard.check(Minecraft.getInstance(),true,!guard.targetAir());
            if(guard.targetAir())ClientActions.scopedMiningRemoved(guard);
            return result;
        } catch(ScopedMining.Refused refused) {
            ClientActions.scopedMiningUnknown(guard,refused.getMessage());return false;
        } catch(RuntimeException failure) {
            ClientActions.scopedMiningUnknown(guard,"mining_callback_exception");throw failure;
        } finally {CALL.remove();}
    }
    public static void hold(Runnable vanilla) {attack(()->{vanilla.run();return true;});}
    private static final ThreadLocal<ScopedMining> CLEANUP=new ThreadLocal<>();
    static void cleanup(ScopedMining guard,Runnable vanilla) {
        ScopedMining.require(CLEANUP.get()==null,"mining_recursive_cleanup");
        CLEANUP.set(guard);try{vanilla.run();}finally{CLEANUP.remove();}
    }
    public static void abort(Packet<?> packet) {
        ScopedMining guard=CLEANUP.get();if(guard!=null)guard.abortPacket(Minecraft.getInstance(),packet);
    }
    public static void afterInputHook() {
        ScopedMining guard=CALL.get();if(guard!=null)guard.check(Minecraft.getInstance(),false,true);
    }
    public static void beforeDestroy(BlockPos pos) {
        ScopedMining g=CALL.get();if(g==null)return;
        ScopedMining.require(pos.equals(g.target),"mining_destroy_target_changed");
        g.check(Minecraft.getInstance(),false,true);
    }
    public static void beforeRemoval(net.minecraft.world.level.block.state.BlockState state,net.minecraft.world.level.Level level,
            BlockPos pos,net.minecraft.world.entity.player.Player player,boolean harvest,net.minecraft.world.level.material.FluidState fluid) {
        ScopedMining guard=CALL.get();if(guard!=null)guard.beforeRemoval(state,level,pos,player,harvest,fluid);
    }
    public static void progressAbort(Packet<?> packet) {
        ScopedMining guard=CALL.get();if(guard==null)return;
        guard.progressAbortPacket(Minecraft.getInstance(),packet);
    }
    public static void packet(Packet<?> packet,BlockPos pos,Direction face,int sequence,boolean stop) {
        ScopedMining g=CALL.get();if(g==null)return;
        ScopedMining.require(pos.equals(g.target),"mining_packet_target_changed");
        g.packet(Minecraft.getInstance(),packet,sequence,face,stop?
            ServerboundPlayerActionPacket.Action.STOP_DESTROY_BLOCK:ServerboundPlayerActionPacket.Action.START_DESTROY_BLOCK);
    }
}

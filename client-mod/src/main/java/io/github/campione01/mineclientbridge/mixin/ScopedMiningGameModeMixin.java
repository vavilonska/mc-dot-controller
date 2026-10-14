package io.github.campione01.mineclientbridge.mixin;

import io.github.campione01.mineclientbridge.ScopedMiningDispatch;
import net.minecraft.client.multiplayer.MultiPlayerGameMode;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.network.protocol.Packet;
import net.minecraft.world.level.block.state.BlockState;
import net.neoforged.neoforge.event.entity.player.PlayerInteractEvent;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.Redirect;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

/** Exact transformed survival destroy chronology. Creative mode cannot enter this profile. */
@Mixin(MultiPlayerGameMode.class)
public abstract class ScopedMiningGameModeMixin {
    @Inject(method="<init>",at=@At("RETURN"),require=1)
    private void mineclientBridge$miningGameInstalled(CallbackInfo ci){ScopedMiningDispatch.gameModeInstalled();}
    @Inject(method="startDestroyBlock",at=@At("HEAD"),require=1)
    private void mineclientBridge$beforeStart(BlockPos pos,Direction face,CallbackInfoReturnable<Boolean> cir){ScopedMiningDispatch.beforeDestroy(pos);}
    @Inject(method="continueDestroyBlock",at=@At("HEAD"),require=1)
    private void mineclientBridge$beforeContinue(BlockPos pos,Direction face,CallbackInfoReturnable<Boolean> cir){ScopedMiningDispatch.beforeDestroy(pos);}
    @Redirect(method="destroyBlock",at=@At(value="INVOKE",target="Lnet/minecraft/world/level/block/state/BlockState;onDestroyedByPlayer(Lnet/minecraft/world/level/Level;Lnet/minecraft/core/BlockPos;Lnet/minecraft/world/entity/player/Player;ZLnet/minecraft/world/level/material/FluidState;)Z"),require=1)
    private boolean mineclientBridge$afterDestroyHooks(BlockState state,net.minecraft.world.level.Level level,BlockPos pos,
            net.minecraft.world.entity.player.Player player,boolean harvest,net.minecraft.world.level.material.FluidState fluid){
        ScopedMiningDispatch.beforeRemoval(state,level,pos,player,harvest,fluid);
        return state.onDestroyedByPlayer(level,pos,player,harvest,fluid);
    }
    @Redirect(method="startDestroyBlock",at=@At(value="INVOKE",target="Lnet/minecraft/client/multiplayer/ClientPacketListener;send(Lnet/minecraft/network/protocol/Packet;)V"),require=1)
    private void mineclientBridge$progressAbort(net.minecraft.client.multiplayer.ClientPacketListener connection,Packet<?> packet){
        ScopedMiningDispatch.progressAbort(packet);connection.send(packet);
    }
    @Redirect(method="stopDestroyBlock",at=@At(value="INVOKE",target="Lnet/minecraft/client/multiplayer/ClientPacketListener;send(Lnet/minecraft/network/protocol/Packet;)V"),require=1)
    private void mineclientBridge$abort(net.minecraft.client.multiplayer.ClientPacketListener connection,Packet<?> packet){
        ScopedMiningDispatch.abort(packet);connection.send(packet);
    }
    @Inject(method="lambda$startDestroyBlock$1",at=@At("RETURN"),require=1,remap=false)
    private void mineclientBridge$startPacket(BlockState state,PlayerInteractEvent.LeftClickBlock event,BlockPos pos,
            Direction face,int sequence,CallbackInfoReturnable<Packet<?>> cir){
        ScopedMiningDispatch.packet(cir.getReturnValue(),pos,face,sequence,false);
    }
    @Inject(method="lambda$continueDestroyBlock$3",at=@At("RETURN"),require=1,remap=false)
    private void mineclientBridge$stopPacket(BlockPos pos,Direction face,int sequence,CallbackInfoReturnable<Packet<?>> cir){
        ScopedMiningDispatch.packet(cir.getReturnValue(),pos,face,sequence,true);
    }
}

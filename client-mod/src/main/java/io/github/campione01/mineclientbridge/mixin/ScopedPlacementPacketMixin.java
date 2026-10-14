package io.github.campione01.mineclientbridge.mixin;

import io.github.campione01.mineclientbridge.ScopedPlacementDispatch;
import net.minecraft.client.multiplayer.MultiPlayerGameMode;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.network.protocol.Packet;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.phys.BlockHitResult;
import org.apache.commons.lang3.mutable.MutableObject;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

/** Validate the actual returned packet after all local use hooks, before startPrediction sends it. */
@Mixin(MultiPlayerGameMode.class)
public abstract class ScopedPlacementPacketMixin {
    @Inject(method="<init>",at=@At("RETURN"),require=1)
    private void mineclientBridge$placementPacketInstalled(CallbackInfo ci){ScopedPlacementDispatch.packetInstalled();}
    @Inject(method="useItemOn",at=@At("HEAD"),require=1)
    private void mineclientBridge$placementEnter(LocalPlayer player,InteractionHand hand,BlockHitResult hit,CallbackInfoReturnable<InteractionResult> cir){
        ScopedPlacementDispatch.enterUse(player,hand,hit);
    }
    @Inject(method="lambda$useItemOn$4",at=@At("RETURN"),require=1,remap=false)
    private void mineclientBridge$placementPacket(MutableObject<InteractionResult> result,LocalPlayer player,
            InteractionHand hand,BlockHitResult hit,int sequence,CallbackInfoReturnable<Packet<?>> cir){
        ScopedPlacementDispatch.packet(cir.getReturnValue(),player,hand,hit,sequence);
    }
}

package io.github.campione01.mineclientbridge.mixin;

import io.github.campione01.mineclientbridge.ScopedBlockMenuDispatch;
import net.minecraft.client.multiplayer.MultiPlayerGameMode;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.phys.BlockHitResult;
import org.apache.commons.lang3.mutable.MutableObject;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

/** Exact 1.21.1 seam after performUseItemOn's hooks and before its interaction packet. */
@Mixin(MultiPlayerGameMode.class)
public abstract class ScopedBlockMenuPacketMixin {
    @Inject(method="<init>", at=@At("RETURN"), require=1)
    private void mineclientBridge$blockMenuInstalled(CallbackInfo ci) { ScopedBlockMenuDispatch.installed(); }

    @Inject(method="lambda$useItemOn$4", at=@At(value="NEW",
        target="net/minecraft/network/protocol/game/ServerboundUseItemOnPacket"), require=1, remap=false)
    private void mineclientBridge$blockMenuPacket(MutableObject<InteractionResult> result, LocalPlayer player,
            InteractionHand hand, BlockHitResult hit, int sequence, CallbackInfoReturnable<?> cir) {
        ScopedBlockMenuDispatch.beforePacket(player, hand, hit);
    }
}

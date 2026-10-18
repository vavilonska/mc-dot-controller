package io.github.campione01.mineclientbridge.mixin;

import io.github.campione01.mineclientbridge.NativeFallRescueDispatch;
import net.minecraft.core.BlockPos;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.item.BucketItem;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.Level;
import net.minecraft.world.phys.BlockHitResult;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

/** Loaded exact NeoForge 1.21.1 BucketItem seam. No token means untouched vanilla behavior. */
@Mixin(BucketItem.class)
public abstract class NativeFallRescueBucketMixin {
    @Inject(method="<init>",at=@At("RETURN"),require=1)
    private void mineclientBridge$fallBucketInstalled(CallbackInfo ci){NativeFallRescueDispatch.bucketInstalled();}
    @Inject(method="emptyContents(Lnet/minecraft/world/entity/player/Player;Lnet/minecraft/world/level/Level;Lnet/minecraft/core/BlockPos;Lnet/minecraft/world/phys/BlockHitResult;Lnet/minecraft/world/item/ItemStack;)Z",at=@At("HEAD"),require=1)
    private void mineclientBridge$fallBucketEntry(Player p,Level l,BlockPos pos,BlockHitResult hit,ItemStack stack,CallbackInfoReturnable<Boolean> cir){NativeFallRescueDispatch.bucket(this,p,l,pos,hit,stack,false);}
    @Inject(method="emptyContents(Lnet/minecraft/world/entity/player/Player;Lnet/minecraft/world/level/Level;Lnet/minecraft/core/BlockPos;Lnet/minecraft/world/phys/BlockHitResult;Lnet/minecraft/world/item/ItemStack;)Z",
        at=@At(value="INVOKE",target="Lnet/minecraft/world/level/Level;setBlock(Lnet/minecraft/core/BlockPos;Lnet/minecraft/world/level/block/state/BlockState;I)Z"),require=1)
    private void mineclientBridge$fallBucketEffect(Player p,Level l,BlockPos pos,BlockHitResult hit,ItemStack stack,CallbackInfoReturnable<Boolean> cir){NativeFallRescueDispatch.bucket(this,p,l,pos,hit,stack,true);}
}

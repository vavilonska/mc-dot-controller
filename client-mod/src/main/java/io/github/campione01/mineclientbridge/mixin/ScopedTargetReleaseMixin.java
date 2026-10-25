package io.github.campione01.mineclientbridge.mixin;
import io.github.campione01.mineclientbridge.ScopedTargetDispatch;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.player.Player;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
/** Release local effect follows NeoForge onUseItemStop. The original call scope remains live. */
@Mixin(LivingEntity.class)
public abstract class ScopedTargetReleaseMixin {
    @Inject(method="<init>",at=@At("RETURN"),require=1)
    private void mineclientBridge$targetReleaseInstalled(CallbackInfo ci){ScopedTargetDispatch.releaseLocalInstalled();ScopedTargetDispatch.stopLocalInstalled();ScopedTargetDispatch.startLocalInstalled();}
    @Inject(method="releaseUsingItem",at=@At(value="INVOKE",target="Lnet/minecraft/world/item/ItemStack;releaseUsing(Lnet/minecraft/world/level/Level;Lnet/minecraft/world/entity/LivingEntity;I)V"),require=1)
    private void mineclientBridge$targetLocalRelease(CallbackInfo ci){if((Object)this instanceof Player player)ScopedTargetDispatch.beforeRelease(player,true);}
    @Inject(method="stopUsingItem",at=@At("HEAD"),require=1)
    private void mineclientBridge$targetAbort(CallbackInfo ci){ScopedTargetDispatch.beforeStopUsing((LivingEntity)(Object)this);}
    @Inject(method="stopUsingItem",at=@At(value="FIELD",target="Lnet/minecraft/world/entity/LivingEntity;useItem:Lnet/minecraft/world/item/ItemStack;",opcode=181),require=1)
    private void mineclientBridge$targetAbortMutation(CallbackInfo ci){ScopedTargetDispatch.beforeStopMutation((LivingEntity)(Object)this);}
    @Inject(method="startUsingItem",at=@At(value="FIELD",target="Lnet/minecraft/world/entity/LivingEntity;useItem:Lnet/minecraft/world/item/ItemStack;",opcode=181),locals=org.spongepowered.asm.mixin.injection.callback.LocalCapture.CAPTURE_FAILHARD,require=1)
    private void mineclientBridge$targetStartMutation(net.minecraft.world.InteractionHand hand,CallbackInfo ci,net.minecraft.world.item.ItemStack capturedStack,int duration){
        ScopedTargetDispatch.beforeStartUseMutation((LivingEntity)(Object)this,hand,capturedStack,duration);
    }
}


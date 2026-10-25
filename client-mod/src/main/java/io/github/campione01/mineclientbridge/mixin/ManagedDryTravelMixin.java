package io.github.campione01.mineclientbridge.mixin;
import io.github.campione01.mineclientbridge.ManagedDryTravelFence;
import io.github.campione01.mineclientbridge.NativeManagedNavigation;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.phys.Vec3;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Shadow;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.ModifyArg;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
import org.spongepowered.asm.mixin.injection.callback.LocalCapture;
/** Refuses new ordinary jump/travel intent; never rewrites velocity, position, or movement packets. */
@Mixin(LivingEntity.class)
public abstract class ManagedDryTravelMixin implements ManagedDryTravelFence {
    @Shadow protected boolean jumping;
    @Shadow public float xxa;
    @Shadow public float zza;
    @Inject(method="aiStep",at=@At(value="FIELD",target="Lnet/minecraft/world/entity/LivingEntity;jumping:Z",opcode=180,ordinal=0),require=1)
    private void mdc$dryJump(CallbackInfo ci){
        if((Object)this instanceof LocalPlayer player&&NativeManagedNavigation.neutralizeDryInput(player,new Vec3(xxa,0,zza))){jumping=false;xxa=0;zza=0;}
    }
    @Inject(method="jumpFromGround",at=@At(value="INVOKE",target="Lnet/minecraft/world/entity/LivingEntity;setDeltaMovement(DDD)V",ordinal=0),cancellable=true,locals=LocalCapture.CAPTURE_FAILHARD,require=1)
    private void mdc$dryJumpEffect(CallbackInfo ci,float power,Vec3 originalMotion){
        if((Object)this instanceof LocalPlayer player&&NativeManagedNavigation.refuseDryJump(player,power,originalMotion))ci.cancel();
    }
    @ModifyArg(method="aiStep",at=@At(value="INVOKE",target="Lnet/minecraft/world/entity/LivingEntity;travel(Lnet/minecraft/world/phys/Vec3;)V"),index=0,require=1)
    private Vec3 mdc$dryTravel(Vec3 intent){return (Object)this instanceof LocalPlayer player?NativeManagedNavigation.dryTravelIntent(player,intent):intent;}
}

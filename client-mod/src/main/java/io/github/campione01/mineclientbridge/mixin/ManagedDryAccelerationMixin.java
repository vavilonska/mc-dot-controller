package io.github.campione01.mineclientbridge.mixin;
import io.github.campione01.mineclientbridge.ManagedDryAccelerationFence;
import io.github.campione01.mineclientbridge.NativeManagedNavigation;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.phys.Vec3;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
/** Cancels only the pending vanilla acceleration; no direct velocity or position writes. */
@Mixin(Entity.class)
public abstract class ManagedDryAccelerationMixin implements ManagedDryAccelerationFence {
    @Inject(method="moveRelative",at=@At("HEAD"),cancellable=true,require=1)
    private void mdc$dryAcceleration(float amount,Vec3 intent,CallbackInfo ci){
        if((Object)this instanceof LocalPlayer player&&NativeManagedNavigation.refuseDryAcceleration(player,amount,intent))ci.cancel();
    }
}

package io.github.campione01.mineclientbridge.mixin;
import io.github.campione01.mineclientbridge.ManagedDryInputFence;
import io.github.campione01.mineclientbridge.NativeManagedNavigation;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.world.phys.Vec3;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
/** After input events and push-out, before vanilla copies ordinary movement intent. */
@Mixin(LocalPlayer.class)
public abstract class ManagedDryInputMixin implements ManagedDryInputFence {
    @Inject(method="aiStep",at=@At(value="INVOKE",target="Lnet/minecraft/client/player/AbstractClientPlayer;aiStep()V"),require=1)
    private void mdc$dryInput(CallbackInfo ci){
        LocalPlayer player=(LocalPlayer)(Object)this;var input=player.input;
        if(NativeManagedNavigation.neutralizeDryInput(player,new Vec3(input.leftImpulse,0,input.forwardImpulse))){
            input.leftImpulse=0;input.forwardImpulse=0;input.up=false;input.down=false;input.left=false;input.right=false;input.jumping=false;input.shiftKeyDown=false;
        }
    }
}

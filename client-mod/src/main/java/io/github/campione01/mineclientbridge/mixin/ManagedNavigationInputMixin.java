package io.github.campione01.mineclientbridge.mixin;

import io.github.campione01.mineclientbridge.ManagedNavigationInputFence;
import io.github.campione01.mineclientbridge.ManagedNavigationInputPolicy;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Pseudo;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Coerce;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/** The read-only forced-input getter stays untouched, so proof cannot hide held keys. */
@Pseudo
@Mixin(targets="baritone.fj",remap=false)
public abstract class ManagedNavigationInputMixin implements ManagedNavigationInputFence {
    @Inject(method="setInputForceState(Lbaritone/api/utils/input/Input;Z)V",at=@At("HEAD"),cancellable=true,remap=false,require=1)
    private void mdc$walkingInput(@Coerce Object input,boolean forced,CallbackInfo callback) {
        if(forced&&input instanceof Enum<?> key&&ManagedNavigationInputPolicy.reject(this,key.name()))callback.cancel();
    }
}

package io.github.campione01.mineclientbridge.mixin;

import io.github.campione01.mineclientbridge.ScopedMiningDispatch;
import net.minecraft.client.Minecraft;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Shadow;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.Redirect;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

/** Pin 1.21.1's only ordinary start/continue callers; preserves vanilla bodies and normal results. */
@Mixin(Minecraft.class)
public abstract class ScopedMiningClientMixin {
    @Shadow public abstract boolean startAttack();
    @Shadow private void continueAttack(boolean down){throw new AssertionError("mixin shadow");}
    @Inject(method="<init>",at=@At("RETURN"),require=1)
    private void mineclientBridge$miningClientInstalled(CallbackInfo ci){ScopedMiningDispatch.clientInstalled();io.github.campione01.mineclientbridge.RecoveryInteractionDispatch.clientInstalled();}
    @Inject(method="startAttack",at=@At(value="INVOKE",target="Lnet/neoforged/neoforge/client/ClientHooks;onClickInput(ILnet/minecraft/client/KeyMapping;Lnet/minecraft/world/InteractionHand;)Lnet/neoforged/neoforge/client/event/InputEvent$InteractionKeyMappingTriggered;",shift=At.Shift.AFTER),require=1)
    private void mineclientBridge$afterAttackInput(CallbackInfoReturnable<Boolean> cir){ScopedMiningDispatch.afterInputHook();}
    @Inject(method="continueAttack",at=@At(value="INVOKE",target="Lnet/neoforged/neoforge/client/ClientHooks;onClickInput(ILnet/minecraft/client/KeyMapping;Lnet/minecraft/world/InteractionHand;)Lnet/neoforged/neoforge/client/event/InputEvent$InteractionKeyMappingTriggered;",shift=At.Shift.AFTER),require=1)
    private void mineclientBridge$afterContinueInput(boolean down,CallbackInfo ci){ScopedMiningDispatch.afterInputHook();}
    @Redirect(method="handleKeybinds",at=@At(value="INVOKE",target="Lnet/minecraft/client/Minecraft;startAttack()Z"),require=1)
    private boolean mineclientBridge$start(Minecraft mc){return ScopedMiningDispatch.attack(this::startAttack);}
    @Redirect(method="handleKeybinds",at=@At(value="INVOKE",target="Lnet/minecraft/client/Minecraft;continueAttack(Z)V"),require=1)
    private void mineclientBridge$continue(Minecraft mc,boolean down){if(!io.github.campione01.mineclientbridge.RecoveryInteractionDispatch.suppressVanillaContinue(down))ScopedMiningDispatch.hold(()->continueAttack(down));}
}

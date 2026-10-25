package io.github.campione01.mineclientbridge.mixin;
import io.github.campione01.mineclientbridge.ScopedItemInteractionDispatch;
import net.minecraft.world.item.EnderEyeItem;
import net.minecraft.world.item.context.UseOnContext;
import net.minecraft.world.InteractionResult;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.Redirect;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;
@Mixin(EnderEyeItem.class)
public abstract class ScopedEyeInteractionMixin {
    @Inject(method="<init>",at=@At("RETURN"),require=1)
    private void mdc$itemInstalled(CallbackInfo ci){ScopedItemInteractionDispatch.eyeInstalled();}
    @Inject(method="useOn",at=@At("HEAD"),require=1)
    private void mdc$itemUse(UseOnContext context,CallbackInfoReturnable<InteractionResult> ci){ScopedItemInteractionDispatch.beforeItemUse((EnderEyeItem)(Object)this,context);}
    @Inject(method="useOn",at=@At("RETURN"),require=1)
    private void mdc$itemResult(UseOnContext context,CallbackInfoReturnable<InteractionResult> ci){ScopedItemInteractionDispatch.itemResult((EnderEyeItem)(Object)this,context,ci.getReturnValue());}
}

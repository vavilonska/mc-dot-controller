package io.github.campione01.mineclientbridge.mixin;
import io.github.campione01.mineclientbridge.ScopedItemInteractionDispatch;
import net.minecraft.world.item.FlintAndSteelItem;
import net.minecraft.world.item.context.UseOnContext;
import net.minecraft.world.InteractionResult;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.Redirect;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;
@Mixin(FlintAndSteelItem.class)
public abstract class ScopedFlintInteractionMixin {
    @Inject(method="<init>",at=@At("RETURN"),require=1)
    private void mdc$itemInstalled(CallbackInfo ci){ScopedItemInteractionDispatch.flintInstalled();}
    @Inject(method="useOn",at=@At("HEAD"),require=1)
    private void mdc$itemUse(UseOnContext context,CallbackInfoReturnable<InteractionResult> ci){ScopedItemInteractionDispatch.beforeItemUse((FlintAndSteelItem)(Object)this,context);}
    @Inject(method="useOn",at=@At("RETURN"),require=1)
    private void mdc$itemResult(UseOnContext context,CallbackInfoReturnable<InteractionResult> ci){ScopedItemInteractionDispatch.itemResult((FlintAndSteelItem)(Object)this,context,ci.getReturnValue());}
    @Redirect(method="useOn",at=@At(value="INVOKE",target="Lnet/minecraft/world/level/Level;setBlock(Lnet/minecraft/core/BlockPos;Lnet/minecraft/world/level/block/state/BlockState;I)Z"),require=2)
    private boolean mdc$flintEffect(net.minecraft.world.level.Level level,net.minecraft.core.BlockPos position,
            net.minecraft.world.level.block.state.BlockState state,int flags,UseOnContext context){
        ScopedItemInteractionDispatch.beforeFlintEffect((FlintAndSteelItem)(Object)this,context,level,position,state,flags);
        return level.setBlock(position,state,flags);
    }
}

package io.github.campione01.mineclientbridge.mixin;

import io.github.campione01.mineclientbridge.ScopedPlacementDispatch;
import net.minecraft.world.item.BlockItem;
import net.minecraft.world.item.context.BlockPlaceContext;
import net.minecraft.world.level.block.state.BlockState;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

/** Plain BlockItem placeBlock is exactly the ordinary Level.setBlock call. */
@Mixin(BlockItem.class)
public abstract class ScopedPlacementItemMixin {
    @Inject(method="<init>",at=@At("RETURN"),require=1)
    private void mineclientBridge$placementItemInstalled(CallbackInfo ci){ScopedPlacementDispatch.itemInstalled();}
    @Inject(method="placeBlock",at=@At("HEAD"),require=1)
    private void mineclientBridge$placementEffect(BlockPlaceContext context,BlockState state,CallbackInfoReturnable<Boolean> cir){
        ScopedPlacementDispatch.beforeEffect((BlockItem)(Object)this,context,state);
    }
}

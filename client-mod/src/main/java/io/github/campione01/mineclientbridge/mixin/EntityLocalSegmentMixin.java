package io.github.campione01.mineclientbridge.mixin;

import io.github.campione01.mineclientbridge.ScopedLocalSegmentDispatch;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.MoverType;
import net.minecraft.world.phys.Vec3;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/** Leaves vanilla unarmed motion unchanged. No position or velocity writes. */
@Mixin(Entity.class)
public abstract class EntityLocalSegmentMixin {
    @Inject(method="move(Lnet/minecraft/world/entity/MoverType;Lnet/minecraft/world/phys/Vec3;)V",at=@At("HEAD"),cancellable=true)
    private void mineclientBridge$localSegmentMotion(MoverType type,Vec3 requested,CallbackInfo ci){
        if(!ScopedLocalSegmentDispatch.beforeMove((Entity)(Object)this,type,requested))ci.cancel();
    }
}

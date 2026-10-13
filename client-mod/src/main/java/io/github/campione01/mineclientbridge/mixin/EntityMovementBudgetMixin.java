package io.github.campione01.mineclientbridge.mixin;

import io.github.campione01.mineclientbridge.MovementBudget;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.MoverType;
import net.minecraft.world.phys.Vec3;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/** Observation only. Never cancels a move or rewrites arguments/position/velocity. */
@Mixin(Entity.class)
public abstract class EntityMovementBudgetMixin {
    @Inject(method="turn(DD)V",at=@At("HEAD"))
    private void mineclientBridge$budgetActualTurn(double yaw,double pitch,CallbackInfo ci){MovementBudget.effectivePlayerTurn((Entity)(Object)this,yaw,pitch);}
    @Inject(method="move(Lnet/minecraft/world/entity/MoverType;Lnet/minecraft/world/phys/Vec3;)V",at=@At("HEAD"))
    private void mineclientBridge$budgetBeginMove(MoverType type,Vec3 movement,CallbackInfo ci){MovementBudget.beginMove((Entity)(Object)this,type,movement);}
    @Inject(method="move(Lnet/minecraft/world/entity/MoverType;Lnet/minecraft/world/phys/Vec3;)V",at=@At("RETURN"))
    private void mineclientBridge$budgetEndMove(MoverType type,Vec3 movement,CallbackInfo ci){MovementBudget.endMove((Entity)(Object)this);}
    @Inject(method="setPosRaw(DDD)V",at=@At(value="FIELD",target="Lnet/minecraft/world/entity/Entity;position:Lnet/minecraft/world/phys/Vec3;",opcode=181,shift=At.Shift.AFTER))
    private void mineclientBridge$budgetPosition(double x,double y,double z,CallbackInfo ci){MovementBudget.positionChanged((Entity)(Object)this);}
}

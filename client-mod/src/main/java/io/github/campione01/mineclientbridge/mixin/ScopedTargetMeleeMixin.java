package io.github.campione01.mineclientbridge.mixin;
import io.github.campione01.mineclientbridge.ScopedTargetDispatch;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.entity.Entity;
import net.neoforged.neoforge.event.entity.player.SweepAttackEvent;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.Redirect;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
/** One nonsweeping primary impact, with all later player mutations re-fenced. */
@Mixin(Player.class)
public abstract class ScopedTargetMeleeMixin {
 @Inject(method="<init>",at=@At("RETURN"),require=1)
 private void mineclientBridge$targetMeleeInstalled(CallbackInfo ci){ScopedTargetDispatch.meleeLocalInstalled();ScopedTargetDispatch.meleePostInstalled();ScopedTargetDispatch.meleeSecondaryInstalled();}
 @Inject(method="attack",at=@At(value="INVOKE",target="Lnet/minecraft/world/entity/Entity;hurt(Lnet/minecraft/world/damagesource/DamageSource;F)Z"),require=1)
 private void mineclientBridge$targetMeleeImpact(Entity target,CallbackInfo ci){ScopedTargetDispatch.beforeMeleeImpact((Player)(Object)this,target);}
 @Redirect(method="attack",at=@At(value="INVOKE",target="Lnet/neoforged/neoforge/event/entity/player/SweepAttackEvent;isSweeping()Z"),require=1)
 private boolean mineclientBridge$targetMeleeSweep(SweepAttackEvent event){boolean sweeping=event.isSweeping();ScopedTargetDispatch.beforeMeleeSweep((Player)(Object)this,sweeping);return sweeping;}
 @Inject(method="attack",at=@At(value="INVOKE",target="Lnet/minecraft/world/entity/LivingEntity;knockback(DDD)V"),require=2)
 private void mineclientBridge$targetMeleeKnockback(Entity target,CallbackInfo ci){ScopedTargetDispatch.beforeMeleeSecondaryMutation((Player)(Object)this);}
 @Inject(method="attack",at=@At(value="INVOKE",target="Lnet/minecraft/world/entity/Entity;push(DDD)V"),require=1)
 private void mineclientBridge$targetMeleePush(Entity target,CallbackInfo ci){ScopedTargetDispatch.beforeMeleeSecondaryMutation((Player)(Object)this);}
 @Inject(method="attack",at={@At(value="INVOKE",target="Lnet/minecraft/world/entity/player/Player;setLastHurtMob(Lnet/minecraft/world/entity/Entity;)V"),@At(value="INVOKE",target="Lnet/minecraft/world/entity/player/Player;causeFoodExhaustion(F)V"),@At(value="INVOKE",target="Lnet/minecraft/world/entity/player/Player;resetAttackStrengthTicker()V")},require=3)
 private void mineclientBridge$targetMeleePost(Entity target,CallbackInfo ci){ScopedTargetDispatch.beforeMeleePostMutation((Player)(Object)this);}
}

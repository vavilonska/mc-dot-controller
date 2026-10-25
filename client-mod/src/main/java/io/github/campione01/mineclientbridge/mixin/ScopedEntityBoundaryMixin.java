package io.github.campione01.mineclientbridge.mixin;
import io.github.campione01.mineclientbridge.ScopedTargetDispatch;
import io.github.campione01.mineclientbridge.ScopedPortalEntryDispatch;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.damagesource.DamageSource;
import net.minecraft.world.level.block.Portal;
import net.minecraft.core.BlockPos;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;
/** Exact scoped local boundaries; the portal observer never cancels vanilla contact. */
@Mixin(Entity.class)
public abstract class ScopedEntityBoundaryMixin {
 @Inject(method="<init>",at=@At("RETURN"),require=1)
 private void mineclientBridge$entityBoundariesInstalled(CallbackInfo ci){ScopedTargetDispatch.meleeInvulnerabilityInstalled();ScopedPortalEntryDispatch.installed();}
 @Inject(method="isInvulnerableTo",at=@At("RETURN"),require=1)
 private void mineclientBridge$targetInvulnerability(DamageSource source,CallbackInfoReturnable<Boolean> ci){ScopedTargetDispatch.beforeMeleeInvulnerability((Entity)(Object)this,source);}
 @Inject(method="setAsInsidePortal",at=@At("HEAD"),require=1)
 private void mineclientBridge$portalContact(Portal portal,BlockPos cell,CallbackInfo ci){ScopedPortalEntryDispatch.contact((Entity)(Object)this,portal,cell);}
}

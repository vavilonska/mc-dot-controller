package io.github.campione01.mineclientbridge.mixin;
import io.github.campione01.mineclientbridge.ScopedTargetDispatch;
import net.minecraft.world.item.ProjectileWeaponItem;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.entity.LivingEntity;
import java.util.List;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;
/** Bow draw follows the NeoForge arrow-loose callback; other players remain unaffected. */
@Mixin(ProjectileWeaponItem.class)
public abstract class ScopedTargetProjectileMixin {
 @Inject(method="<init>",at=@At("RETURN"),require=1)
 private void mineclientBridge$targetBowInstalled(CallbackInfo ci){ScopedTargetDispatch.bowLocalInstalled();}
 @Inject(method="draw",at=@At("HEAD"),require=1)
 private static void mineclientBridge$targetBowDraw(ItemStack weapon,ItemStack ammo,LivingEntity entity,CallbackInfoReturnable<List<ItemStack>> ci){ScopedTargetDispatch.beforeBowDraw(weapon,ammo,entity);}
}

package io.github.campione01.mineclientbridge.mixin;
import io.github.campione01.mineclientbridge.InventoryRecoveryDispatch;
import net.minecraft.client.multiplayer.MultiPlayerGameMode;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
@Mixin(MultiPlayerGameMode.class)
public abstract class InventoryRecoveryClickMixin {
    @Inject(method="<init>",at=@At("RETURN"),require=1)
    private void mineclientBridge$recoveryClickInstalled(CallbackInfo ci){InventoryRecoveryDispatch.clickInstalled();}
    @Inject(method="handleInventoryMouseClick",at=@At(value="INVOKE",target="Lnet/minecraft/world/inventory/AbstractContainerMenu;clicked(IILnet/minecraft/world/inventory/ClickType;Lnet/minecraft/world/entity/player/Player;)V"),require=1)
    private void mineclientBridge$recoveryClick(CallbackInfo ci){InventoryRecoveryDispatch.beforeClick();}
}

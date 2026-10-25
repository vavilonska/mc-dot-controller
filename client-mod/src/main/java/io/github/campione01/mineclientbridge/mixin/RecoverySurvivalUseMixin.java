package io.github.campione01.mineclientbridge.mixin;

import io.github.campione01.mineclientbridge.RecoverySurvivalV6;
import net.minecraft.client.Minecraft;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(Minecraft.class)
public abstract class RecoverySurvivalUseMixin {
    @Inject(method="<init>",at=@At("RETURN"))
    private void recovery$survivalInstalled(CallbackInfo ci){RecoverySurvivalV6.installed();}
    @Inject(method="startUseItem",at=@At("HEAD"),cancellable=true)
    private void recovery$noBreadRestart(CallbackInfo ci){if(RecoverySurvivalV6.suppressDefaultUse())ci.cancel();}
}

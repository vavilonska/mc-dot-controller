package io.github.campione01.mineclientbridge.mixin;
import io.github.campione01.mineclientbridge.InventoryRecoveryDispatch;
import net.minecraft.client.multiplayer.ClientCommonPacketListenerImpl;
import net.minecraft.network.protocol.Packet;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
@Mixin(ClientCommonPacketListenerImpl.class)
public abstract class InventoryRecoverySendMixin {
    @Inject(method="<init>",at=@At("RETURN"),require=1)
    private void mineclientBridge$recoverySendInstalled(CallbackInfo ci){InventoryRecoveryDispatch.sendInstalled();}
    @Inject(method="send",at=@At(value="INVOKE",target="Lnet/minecraft/network/Connection;send(Lnet/minecraft/network/protocol/Packet;)V"),require=1)
    private void mineclientBridge$recoverySend(Packet<?> packet,CallbackInfo ci){InventoryRecoveryDispatch.beforeSend(packet);}
}

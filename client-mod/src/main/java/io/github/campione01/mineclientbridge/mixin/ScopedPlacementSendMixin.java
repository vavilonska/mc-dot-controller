package io.github.campione01.mineclientbridge.mixin;
import io.github.campione01.mineclientbridge.ScopedPlacementDispatch;
import net.minecraft.client.multiplayer.ClientCommonPacketListenerImpl;
import net.minecraft.network.protocol.Packet;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
/** After NeoForge NetworkRegistry.checkPacket, immediately before Connection.send. */
@Mixin(ClientCommonPacketListenerImpl.class)
public abstract class ScopedPlacementSendMixin {
    @Inject(method="<init>",at=@At("RETURN"),require=1)
    private void mineclientBridge$placementSendInstalled(CallbackInfo ci){ScopedPlacementDispatch.sendInstalled();io.github.campione01.mineclientbridge.NativeFallRescueDispatch.sendInstalled();}
    @Inject(method="send",at=@At(value="INVOKE",target="Lnet/minecraft/network/Connection;send(Lnet/minecraft/network/protocol/Packet;)V"),require=1)
    private void mineclientBridge$placementSend(Packet<?> packet,CallbackInfo ci){ScopedPlacementDispatch.send(packet);io.github.campione01.mineclientbridge.NativeFallRescueDispatch.send(packet);}
}

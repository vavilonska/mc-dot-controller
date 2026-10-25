package io.github.campione01.mineclientbridge.mixin;
import io.github.campione01.mineclientbridge.ScopedCombatDispatch;
import io.github.campione01.mineclientbridge.ScopedTargetDispatch;
import net.minecraft.client.multiplayer.ClientCommonPacketListenerImpl;
import net.minecraft.network.protocol.Packet;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
/** All synchronous combat dispatch packets pass this last native owner fence. */
@Mixin(ClientCommonPacketListenerImpl.class)
public abstract class ScopedCombatPacketMixin {
    @Inject(method="<init>",at=@At("RETURN"),require=1)
    private void mineclientBridge$combatPacketInstalled(CallbackInfo ci){ScopedCombatDispatch.packetInstalled();ScopedTargetDispatch.packetInstalled();io.github.campione01.mineclientbridge.ScopedItemInteractionDispatch.packetInstalled();}
    @Inject(method="send",at=@At("HEAD"),require=1)
    private void mineclientBridge$combatPacket(Packet<?> packet,CallbackInfo ci){io.github.campione01.mineclientbridge.ScopedItemInteractionDispatch.packet(packet);ScopedTargetDispatch.packet(packet);ScopedCombatDispatch.packet(packet);}
}

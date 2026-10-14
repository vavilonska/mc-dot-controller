package io.github.campione01.mineclientbridge.mixin;
import net.minecraft.network.protocol.game.ServerboundInteractPacket;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.gen.Accessor;
@Mixin(ServerboundInteractPacket.class)
public interface ScopedCombatInteractAccessor {
    @Accessor("entityId") int mineclientBridge$entityId();
}

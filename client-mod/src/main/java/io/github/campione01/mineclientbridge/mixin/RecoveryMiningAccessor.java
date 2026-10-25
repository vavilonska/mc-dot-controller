package io.github.campione01.mineclientbridge.mixin;
import net.minecraft.client.multiplayer.MultiPlayerGameMode;
import net.minecraft.client.multiplayer.ClientPacketListener;
import net.minecraft.core.BlockPos;
import net.minecraft.world.item.ItemStack;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.gen.Accessor;
/** Read-only original mining identity; no access transformer or raw progress mutation. */
@Mixin(MultiPlayerGameMode.class)
public interface RecoveryMiningAccessor {
    @Accessor("destroyBlockPos") BlockPos recovery$target();
    @Accessor("destroyingItem") ItemStack recovery$item();
    @Accessor("destroyProgress") float recovery$progress();
    @Accessor("connection") ClientPacketListener recovery$connection();
}

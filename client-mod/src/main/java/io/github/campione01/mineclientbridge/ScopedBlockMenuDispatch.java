package io.github.campione01.mineclientbridge;

import net.minecraft.client.player.LocalPlayer;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.phys.BlockHitResult;

/** Narrow mixin bridge; never a public action endpoint or independent owner. */
public final class ScopedBlockMenuDispatch {
    private static boolean installed;
    private ScopedBlockMenuDispatch() { }
    public static void installed() { installed = true; }
    static boolean ready() { return installed; }
    public static void beforePacket(LocalPlayer player, InteractionHand hand, BlockHitResult hit) {
        ClientActions.scopedBlockMenuPacketFence(player, hand, hit);
    }
}

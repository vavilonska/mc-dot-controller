package io.github.campione01.mineclientbridge;

import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.RotatedPillarBlock;

/** Menu dependency geometry only: exact vanilla overworld trunks and wood.
 * Every canonical axis state inherits the audited constant full-cube outline
 * and collision from BlockBehaviour. This does not authorize breaking, drops,
 * XP, arbitrary pillars, fluid occupancy, or an additional menu target family.
 */
final class BlockMenuLogGeometry {
    private BlockMenuLogGeometry() { }
    static boolean allows(Block block) {
        if (block == null || block.getClass() != RotatedPillarBlock.class) return false;
        return block == Blocks.OAK_LOG || block == Blocks.OAK_WOOD
            || block == Blocks.STRIPPED_OAK_LOG || block == Blocks.STRIPPED_OAK_WOOD
            || block == Blocks.SPRUCE_LOG || block == Blocks.SPRUCE_WOOD
            || block == Blocks.STRIPPED_SPRUCE_LOG || block == Blocks.STRIPPED_SPRUCE_WOOD
            || block == Blocks.BIRCH_LOG || block == Blocks.BIRCH_WOOD
            || block == Blocks.STRIPPED_BIRCH_LOG || block == Blocks.STRIPPED_BIRCH_WOOD
            || block == Blocks.JUNGLE_LOG || block == Blocks.JUNGLE_WOOD
            || block == Blocks.STRIPPED_JUNGLE_LOG || block == Blocks.STRIPPED_JUNGLE_WOOD
            || block == Blocks.ACACIA_LOG || block == Blocks.ACACIA_WOOD
            || block == Blocks.STRIPPED_ACACIA_LOG || block == Blocks.STRIPPED_ACACIA_WOOD
            || block == Blocks.DARK_OAK_LOG || block == Blocks.DARK_OAK_WOOD
            || block == Blocks.STRIPPED_DARK_OAK_LOG || block == Blocks.STRIPPED_DARK_OAK_WOOD
            || block == Blocks.MANGROVE_LOG || block == Blocks.MANGROVE_WOOD
            || block == Blocks.STRIPPED_MANGROVE_LOG || block == Blocks.STRIPPED_MANGROVE_WOOD
            || block == Blocks.CHERRY_LOG || block == Blocks.CHERRY_WOOD
            || block == Blocks.STRIPPED_CHERRY_LOG || block == Blocks.STRIPPED_CHERRY_WOOD;
    }
}

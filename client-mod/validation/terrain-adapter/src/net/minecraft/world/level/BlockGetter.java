package net.minecraft.world.level;
import net.minecraft.core.BlockPos; import net.minecraft.world.level.block.state.BlockState; import net.minecraft.world.level.material.FluidState; import net.minecraft.world.level.block.entity.BlockEntity;
public interface BlockGetter { BlockState getBlockState(BlockPos pos); FluidState getFluidState(BlockPos pos); BlockEntity getBlockEntity(BlockPos pos); int getHeight(); int getMinBuildHeight(); }

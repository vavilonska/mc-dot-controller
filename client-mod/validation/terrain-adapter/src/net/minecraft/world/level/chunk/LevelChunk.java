package net.minecraft.world.level.chunk;
import finite.Trace; import net.minecraft.core.BlockPos; import net.minecraft.world.level.block.state.BlockState; import java.util.function.Function;
public class LevelChunk { public Function<BlockPos,BlockState> lookup; public LevelChunk(Function<BlockPos,BlockState> lookup){this.lookup=lookup;} public BlockState getBlockState(BlockPos p){Trace.hit("chunk.getBlockState:"+p);return lookup.apply(p);} }

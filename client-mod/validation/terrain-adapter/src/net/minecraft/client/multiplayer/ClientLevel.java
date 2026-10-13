package net.minecraft.client.multiplayer;
import finite.Trace; import java.util.*; import net.minecraft.world.level.chunk.LevelChunk; import net.minecraft.world.level.chunk.status.ChunkStatus; import net.minecraft.world.level.BlockGetter; import net.minecraft.core.BlockPos; import net.minecraft.world.level.block.state.BlockState; import net.minecraft.world.level.material.FluidState; import net.minecraft.world.level.block.entity.BlockEntity;
public class ClientLevel implements BlockGetter {
 public int min=-64,max=320; public long time=100; public final ChunkSource chunks=new ChunkSource();
 public static final class ChunkSource { public LevelChunk chunk; public boolean missing; public final Set<String> missingKeys=new HashSet<>();
  public LevelChunk getChunk(int x,int z,ChunkStatus status,boolean create){Trace.hit("chunks.getChunk:"+x+","+z+","+status+","+create);if(status!=ChunkStatus.FULL||create)throw new AssertionError("Unexpected chunk creation");return missing||missingKeys.contains(x+","+z)?null:chunk;}
 }
 public static final class Dimension { public String location(){return "minecraft:overworld";} }
 public ChunkSource getChunkSource(){Trace.hit("level.getChunkSource");return chunks;}
 public int getMinBuildHeight(){Trace.hit("level.min");return min;} public int getMaxBuildHeight(){Trace.hit("level.max");return max;} public int getHeight(){Trace.hit("level.height");return max-min;}
 public long getGameTime(){return time;} public Dimension dimension(){return new Dimension();}
 public BlockState getBlockState(BlockPos p){throw new AssertionError("Live level access forbidden");} public FluidState getFluidState(BlockPos p){throw new AssertionError("Live level access forbidden");} public BlockEntity getBlockEntity(BlockPos p){throw new AssertionError("Live level access forbidden");}
}

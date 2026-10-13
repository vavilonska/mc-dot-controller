package net.minecraft.world.level.block;
import finite.Trace; import net.minecraft.core.Direction; import net.minecraft.world.phys.shapes.VoxelShape; import net.minecraft.world.level.block.state.BlockState;
public class Block { public String id; public BlockState defaultState; public Block(String id){this.id=id;}
 public static boolean isFaceFull(VoxelShape shape,Direction dir){if(dir!=Direction.UP) throw new AssertionError("Unexpected direction");return shape.fixtureTopFull();}
 public BlockState defaultBlockState(){Trace.hit("Blocks.AIR.defaultBlockState");return defaultState;}
}

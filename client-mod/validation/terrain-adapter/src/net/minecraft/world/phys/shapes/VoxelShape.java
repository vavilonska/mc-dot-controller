package net.minecraft.world.phys.shapes;
import finite.Trace; import net.minecraft.world.phys.AABB;
public class VoxelShape {
 public boolean empty,topFull=true; public AABB box=new AABB(0,0,0,1,1,1);
 public boolean isEmpty(){Trace.hit("shape.isEmpty");return empty;}
 public boolean fixtureTopFull(){Trace.hit("Block.isFaceFull:UP");return topFull;}
 public AABB bounds(){Trace.hit("shape.bounds");return box;}
}

package net.minecraft.world.level.block.state;
import finite.Trace; import java.util.*; import net.minecraft.world.level.block.*; import net.minecraft.world.level.block.state.properties.Property; import net.minecraft.world.level.material.FluidState; import net.minecraft.world.level.BlockGetter; import net.minecraft.core.BlockPos; import net.minecraft.world.phys.shapes.*; import net.minecraft.client.Minecraft;
public class BlockState {
 public interface ShapeHook { void call(BlockGetter getter,BlockPos pos,CollisionContext context); }
 public Block block=new Block("minecraft:stone"); public boolean air,hasLit; public Boolean lit=false;
 public Map<Property<?>,Comparable<?>> values=new LinkedHashMap<>(); public FluidState fluid=new FluidState(); public VoxelShape shape=new VoxelShape(); public ShapeHook hook=(g,p,c)->{};
 public String label="state"; public int valuesCalls;
 public Block getBlock(){Trace.hit(label+".getBlock");return block;}
 public boolean isAir(){Trace.hit(label+".isAir");return air;}
 public Map<Property<?>,Comparable<?>> getValues(){Trace.hit(label+".getValues:"+(++valuesCalls));return values;}
 public FluidState getFluidState(){Trace.hit(label+".getFluidState");return fluid;}
 public boolean hasProperty(Property<?> p){Trace.hit(label+".hasProperty:lit");return hasLit;}
 @SuppressWarnings("unchecked") public <T extends Comparable<T>> T getValue(Property<T> p){Trace.hit(label+".getValue:lit");return (T)lit;}
 public VoxelShape getCollisionShape(BlockGetter getter,BlockPos pos,CollisionContext context){Trace.hit(label+".getCollisionShape:"+pos);
  boolean bounded=getter.getClass().getSimpleName().equals("ShapeView") && !(getter instanceof net.minecraft.client.multiplayer.ClientLevel);
  boolean same=context.player==Minecraft.getInstance().player;
  Trace.hit("shape.context:bounded="+bounded+",same_player="+same);if(!bounded||!same)throw new AssertionError("Unbounded or wrong player shape context");hook.call(getter,pos,context);return shape;
 }
}

package net.minecraft.core.registries;
import finite.Trace; import net.minecraft.world.level.block.Block; import net.minecraft.world.level.material.FluidState.Fluid;
public final class BuiltInRegistries {
 public static final class Key { final String id; Key(String id){this.id=id;} public String toString(){return id;} }
 public static final class Registry<T> { final String label; Registry(String label){this.label=label;}
  public Key getKey(T value){Trace.hit(label+".getKey");String id=value instanceof Block b?b.id:((Fluid)value).id;return id==null?null:new Key(id);}
 }
 public static final Registry<Block> BLOCK=new Registry<>("BLOCK"); public static final Registry<Fluid> FLUID=new Registry<>("FLUID");
}

package net.minecraft.world.level.material;
import finite.Trace;
public class FluidState {
 public static final class Fluid { public String id; public Fluid(String id){this.id=id;} }
 public Fluid type=new Fluid("minecraft:empty"); public boolean source,lava,water; public String label="fluid";
 public Fluid getType(){Trace.hit(label+".getType");return type;}
 public boolean isSource(){Trace.hit(label+".isSource");return source;}
 public boolean is(String tag){Trace.hit(label+".is:"+tag);return tag.equals("lava")?lava:water;}
}

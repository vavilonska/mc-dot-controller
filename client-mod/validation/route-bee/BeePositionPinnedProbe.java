package io.github.campione01.mineclientbridge;
import net.minecraft.core.BlockPos;
import java.lang.reflect.Method;
import java.nio.file.*;
/** Real pinned coordinate classes + production reader helpers only; no game/server/level/AI entrypoint. */
public final class BeePositionPinnedProbe {
 static int checks,unknownCalls;
 static void ok(boolean v,String why){checks++;if(!v)throw new AssertionError(why);}
 static class OtherPos extends BlockPos {OtherPos(){super(1,2,3);}public int getX(){unknownCalls++;throw new AssertionError("unknown getX invoked");}}
 static class OtherMutable extends BlockPos.MutableBlockPos {OtherMutable(){super(1,2,3);}public int getY(){unknownCalls++;throw new AssertionError("unknown getY invoked");}}
 public static void main(String[] args)throws Exception{
  Method trusted=NativeBeeRouteObservation.class.getDeclaredMethod("trustedPosition",BlockPos.class);trusted.setAccessible(true);
  Method copy=NativeBeeRouteObservation.class.getDeclaredMethod("position",BlockPos.class);copy.setAccessible(true);
  for(String name:new String[]{"getX","getY","getZ"}){
   ok(BlockPos.class.getMethod(name).getDeclaringClass()==net.minecraft.core.Vec3i.class,"base getter owner");
   ok(BlockPos.MutableBlockPos.class.getMethod(name).getDeclaringClass()==net.minecraft.core.Vec3i.class,"mutable getter owner");
  }
  var mutable=new BlockPos.MutableBlockPos(17,-4,29);ok((boolean)trusted.invoke(null,mutable),"exact mutable trusted");
  var sampled=(NativeLivingSnapshot.BeePosition)copy.invoke(null,mutable);mutable.set(100,200,300);
  ok(sampled.equals(new NativeLivingSnapshot.BeePosition(17,-4,29)),"actual mutable copied into immutable primitive record");
  ok((boolean)trusted.invoke(null,new BlockPos(1,2,3)),"exact base trusted");ok((boolean)trusted.invoke(null,new Object[]{null}),"null allowed");
  for(BlockPos value:new BlockPos[]{new OtherPos(),new OtherMutable()}){
   boolean allowed=(boolean)trusted.invoke(null,value);ok(!allowed,"unknown subclass refused before coordinate getters");if(allowed)copy.invoke(null,value);
  }
  ok(unknownCalls==0,"unknown getters never invoked");
  var report=new com.google.gson.JsonObject();report.addProperty("status","passed");report.addProperty("checks",checks);report.addProperty("unknown_getter_calls",unknownCalls);
  report.addProperty("scope","Actual pinned BlockPos and MutableBlockPos, production trust/copy helpers and immutable record; no Bee/game/world/AI bootstrap");
  Files.writeString(Path.of(args[0]),report.toString(),StandardOpenOption.CREATE_NEW);System.out.println("PASS pinned coordinate checks="+checks);
 }
}

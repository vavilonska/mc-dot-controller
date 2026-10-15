package io.github.campione01.mineclientbridge;
import java.nio.file.*;
import org.objectweb.asm.*;
import org.objectweb.asm.tree.*;
import com.google.gson.*;
import net.minecraft.core.*;
import net.minecraft.world.phys.*;
import net.minecraft.world.phys.shapes.Shapes;
/** Origin-translated synthetic geometry; no saved world or observed action data. */
public class QuantizedRayChecks {
 static int checks; static void ok(boolean v,String s){if(!v)throw new AssertionError(s);checks++;}
 static java.lang.reflect.Method viewMethod() throws Exception {
  ClassNode cn=new ClassNode();new ClassReader(Files.newInputStream(Path.of(System.getProperty("consolidation.entity.class")))).accept(cn,0);
  MethodNode m=cn.methods.stream().filter(x->x.name.equals("calculateViewVector")&&x.desc.equals("(FF)Lnet/minecraft/world/phys/Vec3;")).findFirst().orElseThrow();
  // Preserve original instruction sequence and local slots 1/2. Slot zero remains
  // unused, as in original final Entity implementation. No client/world creation.
  m.access=Opcodes.ACC_PUBLIC|Opcodes.ACC_STATIC;m.name="view";m.desc="(Ljava/lang/Object;FF)Lnet/minecraft/world/phys/Vec3;";
  ClassWriter w=new ClassWriter(0);w.visit(Opcodes.V21,Opcodes.ACC_PUBLIC,"ExtractedEntityView",null,"java/lang/Object",null);m.accept(w);w.visitEnd();byte[] b=w.toByteArray();
  class Loader extends ClassLoader {Class<?> make(){return defineClass("ExtractedEntityView",b,0,b.length);}}
  return new Loader().make().getMethod("view",Object.class,float.class,float.class);
 }
 public static void main(String[] args) throws Exception {
  var field=net.minecraft.util.Mth.class.getDeclaredField("SIN");field.setAccessible(true);float[] lut=(float[])field.get(null);var bytes=java.nio.ByteBuffer.allocate(lut.length*4);for(float f:lut)bytes.putFloat(f);Files.write(Path.of(args[0]).resolveSibling("engine-sine-table.bin"),bytes.array());
  var method=viewMethod();JsonArray rows=new JsonArray();BlockPos target=new BlockPos(2,0,0);int accepted=0,rejected=0;
  for(Direction face:Direction.values())for(double distance:new double[]{.15,.5,1.5,3.0})for(double u:new double[]{-.9,-.2,0,.37,.9})for(double v:new double[]{-.9,0,.61}){
   Vec3 center=BlockMenuPreflight.faceCenter(target,face);int axis=face.getAxis().ordinal();double[] e={center.x,center.y,center.z};e[axis]+=distance*(face.getStepX()+face.getStepY()+face.getStepZ());e[(axis+1)%3]+=u;e[(axis+2)%3]+=v;
   Vec3 eye=new Vec3(e[0],e[1],e[2]);float[] angles=BlockMenuPreflight.intendedAim(eye,center);Vec3 view=(Vec3)method.invoke(null,null,angles[1],angles[0]);Vec3 expected=BlockMenuPreflight.representableHit(eye,center,target,face,view);
   BlockHitResult hit=Shapes.block().clip(eye,eye.add(view.scale(6)),target);
   JsonObject row=new JsonObject();row.add("eye",BlockMenuPreflight.vector(eye));row.add("center",BlockMenuPreflight.vector(center));row.add("target",BlockMenuPreflight.pos(target));row.addProperty("face",face.getName());row.addProperty("yaw",(double)angles[0]);row.addProperty("pitch",(double)angles[1]);row.addProperty("admitted",expected!=null);
   if(expected==null){rejected++;}else {accepted++;row.add("expected",BlockMenuPreflight.vector(expected));ok(hit!=null&&!hit.isInside(),"actual geometry");ok(BlockMenuPreflight.hitMatches(hit,target,face,expected),"real clip parity");ok(!BlockMenuPreflight.hitMatches(hit,target.relative(face),face,expected),"neighbor rejected");ok(!BlockMenuPreflight.hitMatches(hit,target,face.getOpposite(),expected),"wrong face");ok(!BlockMenuPreflight.hitMatches(new BlockHitResult(expected.add(.01,.01,.01),face,target,false),target,face,expected),"large offset");}
   rows.add(row);
  }
  Vec3 eye=new Vec3(.5,(double)1.62F,.5),center=new Vec3(2,.5,.5);float[] angles=BlockMenuPreflight.intendedAim(eye,center);Vec3 view=(Vec3)method.invoke(null,null,angles[1],angles[0]);var hit=Shapes.block().clip(eye,eye.add(view.scale(4.5)),target);Vec3 expected=BlockMenuPreflight.representableHit(eye,center,target,Direction.WEST,view);
  ok(expected!=null&&Math.abs(hit.getLocation().y-.5001507705544)<1e-12,"translated quantized-ray counterexample");ok(!BlockMenuPreflight.hitMatches(hit,target,Direction.WEST,center),"old predicate reproduces refusal");ok(BlockMenuPreflight.hitMatches(hit,target,Direction.WEST,expected),"new predicate accepts representable ray");
  ok(BlockMenuPreflight.representableHit(eye,center,target,Direction.WEST,view.scale(-1))==null,"reversed ray");
  ok(BlockMenuPreflight.representableHit(new Vec3(2,1,.5),center,target,Direction.WEST,new Vec3(0,-1,0))==null,"parallel ray");
  ok(BlockMenuPreflight.representableHit(eye,center,target,Direction.WEST,new Vec3(1,-eye.y/1.5,0))==null,"edge hit");
  ok(!BlockMenuPreflight.inCertifiedPrism(eye,center,new Vec3(2,.5,1)),"uncertified cell");
  Files.writeString(Path.of(args[0]),new GsonBuilder().setPrettyPrinting().create().toJson(rows));System.out.println("PASS "+checks+" assertions; "+accepted+" accepted, "+rejected+" fail-closed geometry rows; all six orientations; unmodified extracted Entity view bytecode + real engine LUT/Shapes + production helpers");
 }
}

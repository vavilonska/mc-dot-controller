package probe;
import java.io.*;
import java.nio.file.*;
import java.util.*;
import com.google.gson.*;
import org.objectweb.asm.*;
import org.objectweb.asm.tree.*;
import org.objectweb.asm.util.*;
import org.spongepowered.asm.launch.*;
import org.spongepowered.asm.mixin.*;
import org.spongepowered.asm.service.*;
/** Actual registered production config on official targets; no Minecraft startup or object construction. */
public final class ManagedWaterMixinProbe {
 static int checks;static void check(boolean value,String why){checks++;if(!value)throw new AssertionError(why);}
 static byte[] bytes(String name)throws Exception{try(InputStream in=ManagedWaterMixinProbe.class.getClassLoader().getResourceAsStream(name.replace('.','/')+".class")){if(in==null)throw new FileNotFoundException(name);return in.readAllBytes();}}
 static ClassNode node(byte[] bytes){var n=new ClassNode();new ClassReader(bytes).accept(n,0);return n;}
 static MethodNode method(ClassNode n,String name){return n.methods.stream().filter(m->m.name.equals(name)).findFirst().orElseThrow();}
 static List<AbstractInsnNode> ops(MethodNode m){List<AbstractInsnNode> list=new ArrayList<>();for(var i:m.instructions)if(i.getOpcode()>=0)list.add(i);return list;}
 static boolean call(AbstractInsnNode i,String value){return i instanceof MethodInsnNode m&&(m.owner+'.'+m.name+m.desc).contains(value);}
 static int at(MethodNode m,String value){var list=ops(m);for(int i=0;i<list.size();i++)if(call(list.get(i),value))return i;return -1;}
 static void precedes(ClassNode n,String name,String gate,String effect){var m=method(n,name);check(at(m,gate)>=0&&at(m,effect)>at(m,gate),name+" "+gate+" before "+effect);}
 static void handler(ClassNode n,String name,String api){check(n.methods.stream().filter(m->m.name.contains(name)).anyMatch(m->at(m,api)>=0),"handler reaches production "+api);}
 static byte[] negative(String mode,String target,byte[] bytes){
  if(mode.equals("none"))return bytes;var n=node(bytes);boolean changed=false;
  for(var m:n.methods)for(var i:m.instructions.toArray()){
   if(mode.equals("missing-input")&&target.endsWith("LocalPlayer")&&m.name.equals("aiStep")&&call(i,"AbstractClientPlayer.aiStep(")){
    ((MethodInsnNode)i).name="removedRequiredSeam";changed=true;}
   if(mode.equals("missing-jump-read")&&target.endsWith("LivingEntity")&&m.name.equals("aiStep")&&i instanceof FieldInsnNode f&&f.getOpcode()==Opcodes.GETFIELD&&f.name.equals("jumping")){
    f.name="removedRequiredSeam";changed=true;}
   if(mode.equals("missing-jump-effect")&&target.endsWith("LivingEntity")&&m.name.equals("jumpFromGround")&&call(i,"setDeltaMovement(DDD)")){
    ((MethodInsnNode)i).name="removedRequiredSeam";changed=true;}
   if(mode.equals("missing-travel")&&target.endsWith("LivingEntity")&&m.name.equals("aiStep")&&call(i,"LivingEntity.travel(")){
    ((MethodInsnNode)i).name="removedRequiredSeam";changed=true;}
  }
  if(mode.equals("missing-acceleration")&&target.equals("net.minecraft.world.entity.Entity")){method(n,"moveRelative").name="removedRequiredSeam";changed=true;}
  if(!changed)return bytes;var writer=new ClassWriter(0);n.accept(writer);return writer.toByteArray();
 }
 public static void main(String[] args)throws Exception{
  Path out=Path.of(args[0]);Files.createDirectories(out);String mode=args.length>1?args[1]:"none";
  JsonObject config;try(var in=ManagedWaterMixinProbe.class.getClassLoader().getResourceAsStream("mineclient_bridge.mixins.json")){config=JsonParser.parseReader(new InputStreamReader(in)).getAsJsonObject();}
  Set<String> targets=new TreeSet<>();String pkg=config.get("package").getAsString();int registrations=0;
  for(var name:config.getAsJsonArray("client")){
   registrations++;ClassNode mixin=node(bytes(pkg+'.'+name.getAsString()));var annotations=new ArrayList<AnnotationNode>();if(mixin.visibleAnnotations!=null)annotations.addAll(mixin.visibleAnnotations);if(mixin.invisibleAnnotations!=null)annotations.addAll(mixin.invisibleAnnotations);
   var a=annotations.stream().filter(x->x.desc.equals("Lorg/spongepowered/asm/mixin/Mixin;")).findFirst().orElseThrow();
   for(int i=0;i<a.values.size();i+=2)if(a.values.get(i).equals("value"))for(Object type:(List<?>)a.values.get(i+1))targets.add(((Type)type).getClassName());
  }
  check(registrations==20,"exact seventeen baseline plus three water mixins");
  MixinBootstrap.init();var service=(OfflineMixinService)MixinService.getService();service.enterDefaultPhase();var env=MixinEnvironment.getDefaultEnvironment().setSide(MixinEnvironment.Side.CLIENT);
  Mixins.addConfiguration("mineclient_bridge.mixins.json");var transformer=service.createTransformer();Map<String,ClassNode> result=new HashMap<>();
  for(String target:targets){byte[] before=negative(mode,target,bytes(target)),after=transformer.transformClass(env,target,before);check(!Arrays.equals(before,after),"transformed "+target);
   var n=new ClassNode();new ClassReader(after).accept(new CheckClassAdapter(n,true),0);result.put(target,n);Files.write(out.resolve(target.replace('.','_')+".class"),after);}
  check(mode.equals("none"),"missing required seam must cause production injection failure");
  var local=result.get("net.minecraft.client.player.LocalPlayer");var living=result.get("net.minecraft.world.entity.LivingEntity");var entity=result.get("net.minecraft.world.entity.Entity");
  precedes(local,"aiStep","ClientHooks.onMovementInputUpdate","mdc$dryInput");precedes(local,"aiStep","moveTowardsClosestSpace","mdc$dryInput");precedes(local,"aiStep","mdc$dryInput","AbstractClientPlayer.aiStep");
  handler(local,"mdc$dryInput","NativeManagedNavigation.neutralizeDryInput");
  var ai=ops(method(living,"aiStep"));int jumpGate=-1,jumpRead=-1;for(int i=0;i<ai.size();i++){if(call(ai.get(i),"mdc$dryJump"))jumpGate=i;if(ai.get(i)instanceof FieldInsnNode f&&f.getOpcode()==Opcodes.GETFIELD&&f.name.equals("jumping")){jumpRead=i;break;}}
  check(jumpGate>=0&&jumpRead>jumpGate,"final jump intent gate after vanilla input copy before consumption");
  precedes(living,"jumpFromGround","getJumpPower","mdc$dryJumpEffect");precedes(living,"jumpFromGround","mdc$dryJumpEffect","setDeltaMovement(DDD)");
  handler(living,"mdc$dryJumpEffect","NativeManagedNavigation.refuseDryJump");
  precedes(living,"aiStep","mdc$dryTravel","LivingEntity.travel(");handler(living,"mdc$dryTravel","NativeManagedNavigation.dryTravelIntent");
  precedes(entity,"moveRelative","mdc$dryAcceleration","getInputVector");precedes(entity,"moveRelative","mdc$dryAcceleration","setDeltaMovement");handler(entity,"mdc$dryAcceleration","NativeManagedNavigation.refuseDryAcceleration");
  check(local.interfaces.contains("io/github/campione01/mineclientbridge/ManagedDryInputFence"),"actual local marker installed");
  check(living.interfaces.contains("io/github/campione01/mineclientbridge/ManagedDryTravelFence"),"actual jump/travel marker installed");
  check(entity.interfaces.contains("io/github/campione01/mineclientbridge/ManagedDryAccelerationFence"),"actual final acceleration marker installed");
  // Explicit claim boundary: original later ladder callback and ordinary move remain present and uncancelled by this repair.
  var relative=method(living,"handleRelativeFrictionAndCalculateMovement");check(at(relative,"handleOnClimbable")>=0&&at(relative,"LivingEntity.move(")>at(relative,"handleOnClimbable"),"later ladder callback/displacement preserved");
  for(var n:List.of(local,living,entity))for(var m:n.methods)if(m.name.contains("mdc$dry"))for(var op:ops(m))check(!call(op,"setDeltaMovement")&&!call(op,".setPos")&&!call(op,".move("),"water hook never directly rewrites physics");
  check(OfflineMixinService.applied.size()==registrations,"all registered mixins applied");check(OfflineMixinService.attemptedLoads.isEmpty(),"no game class load");Files.write(out.resolve("applied-mixins.txt"),OfflineMixinService.applied);
  System.out.println("ManagedWaterMixinProbe PASS checks="+checks+" mixins="+registrations+" targets="+targets.size());
 }
}

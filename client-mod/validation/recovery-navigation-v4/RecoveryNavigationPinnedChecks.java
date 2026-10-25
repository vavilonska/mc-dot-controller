package io.github.campione01.mineclientbridge;
import java.util.*;
import java.util.jar.*;
import org.objectweb.asm.*;
import org.objectweb.asm.tree.*;
/** Independent pinned shape/read selector audit, no registry bootstrap or Minecraft object instantiation. */
public final class RecoveryNavigationPinnedChecks {
 static int n;static void check(boolean b,String s){if(!b)throw new AssertionError(s);n++;}
 static ClassNode read(JarFile j,String name)throws Exception{return RecoveryRespawnPinnedChecks.read(j,name);}
 static MethodNode method(ClassNode c,String name,String desc){return RecoveryRespawnPinnedChecks.method(c,name,desc);}
 static List<String> calls(MethodNode m){return RecoveryRespawnPinnedChecks.calls(m);}
 static List<Double> numbers(MethodNode m){var values=new ArrayList<Double>();for(var i:m.instructions)if(i instanceof LdcInsnNode l&&l.cst instanceof Double d)values.add(d);return values;}
 public static void main(String[] args)throws Exception{
  try(var j=new JarFile(args[0])){
   var bed=read(j,"net/minecraft/world/level/block/BedBlock");var chest=read(j,"net/minecraft/world/level/block/ChestBlock");String shape="(Lnet/minecraft/world/level/block/state/BlockState;Lnet/minecraft/world/level/BlockGetter;Lnet/minecraft/core/BlockPos;Lnet/minecraft/world/phys/shapes/CollisionContext;)Lnet/minecraft/world/phys/shapes/VoxelShape;";
   check(calls(method(bed,"getShape",shape)).stream().anyMatch(s->s.contains("getConnectedDirection")),"bed direction selected by captured state");check(calls(method(chest,"getShape",shape)).stream().anyMatch(s->s.contains("BlockState.getValue")),"chest type selected by captured state");
   check(numbers(method(bed,"<clinit>","()V")).containsAll(List.of(3.0,9.0,13.0,16.0)),"bed 3/16 base bottom 9/16 top legs");check(numbers(method(chest,"<clinit>","()V")).containsAll(List.of(14.0,15.0,16.0)),"chest 14/16 top 1/16 inset directional doublebounds");
   for(String name:List.of("BedBlock","ChestBlock","AbstractChestBlock","BaseEntityBlock","HorizontalDirectionalBlock","Block","CraftingTableBlock"))check(read(j,"net/minecraft/world/level/block/"+name).methods.stream().noneMatch(m->m.name.equals("getCollisionShape")),"inherited collision implementation "+name);
   var behavior=read(j,"net/minecraft/world/level/block/state/BlockBehaviour");check(calls(method(behavior,"getCollisionShape",shape)).stream().anyMatch(s->s.contains("BlockState.getShape")),"default collision uses actual state shape");
   var state=read(j,"net/minecraft/world/level/block/state/BlockBehaviour$BlockStateBase");String contextual="(Lnet/minecraft/world/level/BlockGetter;Lnet/minecraft/core/BlockPos;Lnet/minecraft/world/phys/shapes/CollisionContext;)Lnet/minecraft/world/phys/shapes/VoxelShape;";check(calls(method(state,"getCollisionShape",contextual)).stream().anyMatch(s->s.endsWith("Block.getCollisionShape"+shape)),"contextual state collision delegates provider with context");
   var sprint=method(read(j,"net/minecraft/world/entity/Entity"),"isSprinting","()Z");check(calls(sprint).equals(List.of("net/minecraft/world/entity/Entity.getSharedFlag(I)Z")),"sprint getter only metadata flag read");check(Arrays.stream(sprint.instructions.toArray()).noneMatch(i->i.getOpcode()==Opcodes.PUTFIELD||i.getOpcode()==Opcodes.PUTSTATIC),"sprint getter no writes");
   var step=method(read(j,"net/minecraft/world/entity/LivingEntity"),"maxUpStep","()F");check(Arrays.stream(step.instructions.toArray()).anyMatch(i->i instanceof FieldInsnNode f&&f.name.equals("STEP_HEIGHT")),"actual step height attribute");check(calls(step).stream().anyMatch(s->s.contains("getControllingPassenger")),"actual step includes vanilla passenger adjustment");
   for(String name:List.of("net/minecraft/world/entity/player/Player","net/minecraft/client/player/AbstractClientPlayer","net/minecraft/client/player/LocalPlayer"))check(read(j,name).methods.stream().noneMatch(m->m.name.equals("maxUpStep")||m.name.equals("isSprinting")),"player inherits actual read "+name);
  }
  try(var in=RecoveryNavigationV4.Geometry.class.getResourceAsStream("RecoveryNavigationV4$Geometry.class")){
   var c=new ClassNode();new ClassReader(in).accept(c,0);for(var m:c.methods)for(var i:m.instructions)if(i instanceof MethodInsnNode call){check(!Set.of("setDeltaMovement","setPos","setSprinting","jumpFromGround","attack","useItem","startDestroyBlock","respawn","execute","schedule").contains(call.name),"geometry no effect calls");check(!call.name.equals("toAabbs"),"no unbounded list conversion");}
   var cell=c.methods.stream().filter(m->m.name.equals("cell")).findFirst().orElseThrow();check(calls(cell).stream().anyMatch(s->s.contains("BlockState.getCollisionShape")&&s.contains("CollisionContext")),"production explicit player context collision selector");
  }
  System.out.println("RecoveryNavigationPinnedChecks PASS assertions="+n+"; pinned native bytecode only, not live collision capture");
 }
}

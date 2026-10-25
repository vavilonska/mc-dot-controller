package io.github.campione01.mineclientbridge;
import java.util.*;
import java.util.jar.*;
import org.objectweb.asm.*;
import org.objectweb.asm.tree.*;
/** Pinned native selector/chronology and compiled implementation seam checks. Not live Mixin readiness. */
public final class RecoveryMaintenancePinnedChecks {
 static int n;static void check(boolean b,String s){if(!b)throw new AssertionError(s);n++;}
 static ClassNode read(JarFile j,String name)throws Exception{return RecoveryInteractionPinnedChecks.read(j,name);}
 static ClassNode own(Class<?> cls)throws Exception{try(var in=cls.getResourceAsStream(cls.getSimpleName()+".class")){var c=new ClassNode();new ClassReader(in).accept(c,0);return c;}}
 static MethodNode method(ClassNode c,String name){return RecoveryInteractionPinnedChecks.method(c,name);}
 static List<MethodInsnNode> calls(MethodNode m,String owner,String name){return RecoveryInteractionPinnedChecks.calls(m,owner,name);}
 static int at(MethodNode m,AbstractInsnNode node){return m.instructions.indexOf(node);}
 public static void main(String[] args)throws Exception{
  String gm="net/minecraft/client/multiplayer/MultiPlayerGameMode",item="net/minecraft/world/item/BlockItem",level="net/minecraft/world/level/Level";
  try(var j=new JarFile(args[0])){
   var game=read(j,gm);var use=method(game,"useItemOn");check(calls(use,gm,"ensureHasSentCarriedItem").size()==1&&calls(use,gm,"startPrediction").size()==1,"vanilla use prerequisites/prediction");
   var lambda=method(game,"lambda$useItemOn$4");int perform=at(lambda,calls(lambda,gm,"performUseItemOn").getFirst()),packet=-1;for(var i:lambda.instructions)if(i instanceof TypeInsnNode t&&t.getOpcode()==Opcodes.NEW&&t.desc.equals("net/minecraft/network/protocol/game/ServerboundUseItemOnPacket"))packet=at(lambda,i);check(perform<packet&&packet>=0,"local callback effects before native packet");
   var place=method(read(j,item),"placeBlock");var sets=calls(place,level,"setBlock");check(sets.size()==1&&sets.getFirst().desc.equals("(Lnet/minecraft/core/BlockPos;Lnet/minecraft/world/level/block/state/BlockState;I)Z"),"exact placeBlock one ordinary setBlock");check(Arrays.stream(place.instructions.toArray()).anyMatch(x->x instanceof IntInsnNode v&&v.operand==11),"native placementflags11");
   for(var i:place.instructions)if(i instanceof MethodInsnNode c)check(Set.of("getLevel","getClickedPos","setBlock").contains(c.name),"placeBlock HEAD directly precedes ordinarywrite no externalcallback");
   var tnt=read(j,"net/minecraft/world/level/block/TntBlock");var destroy=method(tnt,"playerWillDestroy");check(Arrays.stream(destroy.instructions.toArray()).anyMatch(i->i instanceof FieldInsnNode f&&f.name.equals("UNSTABLE")),"native TNT unstable check");check(calls(destroy,"net/minecraft/world/level/block/TntBlock","onCaughtFire").size()==1,"conditional TNT ignition path exists not blanket safe");
   var bed=read(j,"net/minecraft/world/level/block/BedBlock");check(bed.methods.stream().noneMatch(m->m.name.equals("canSurvive")),"bed no downward survival override");check(calls(method(bed,"updateShape"),"net/minecraft/world/level/block/BedBlock","getNeighbourDirection").size()==1,"bed update horizontal peer branch");
   for(String c:List.of("CraftingTableBlock","HorizontalDirectionalBlock","Block"))check(read(j,"net/minecraft/world/level/block/"+c).methods.stream().noneMatch(m->m.name.equals("updateShape")||m.name.equals("canSurvive")),"no gravity/support override "+c);
   var entity=read(j,"net/minecraft/world/entity/Entity");check((method(entity,"getBoundingBox").access&Opcodes.ACC_FINAL)!=0,"AABB query getter final cannot subclass override");
   var get=read(j,level).methods.stream().filter(m->m.name.equals("getEntities")&&m.desc.endsWith("Ljava/util/List;I)V")).findFirst().orElseThrow();check(calls(get,"net/minecraft/world/level/entity/LevelEntityGetter","get").size()==1,"bounded native AABB entity query");
   var loop=method(read(j,level),"lambda$getEntities$2");check(Arrays.stream(loop.instructions.toArray()).anyMatch(i->i instanceof FieldInsnNode f&&f.name.equals("ABORT")),"native max result abort");
  }
  var dispatch=own(RecoveryMaintenancePlacementDispatch.class);
  for(var m:dispatch.methods)for(var i:m.instructions){
   if(i instanceof TypeInsnNode t&&t.getOpcode()==Opcodes.NEW)check(!t.desc.contains("Packet"),"never crafts packet");
   if(i instanceof MethodInsnNode c){check(!Set.of("setBlock","setPos","setDeltaMovement","setKey","useItem","attack","live","owns","stop").contains(c.name),"scope no extra effect/stop revoke "+c.name);}
   if(i instanceof FieldInsnNode f&&f.getOpcode()==Opcodes.PUTFIELD)check(!f.owner.endsWith("/Input"),"no input write");
  }
  check(calls(method(dispatch,"use"),gm,"useItemOn").size()==1,"one vanilla use only");
  var nativeCode=own(NativeRecoveryShortInput.class);var tick=method(nativeCode,"interactionTick");int claim=at(tick,calls(tick,"io/github/campione01/mineclientbridge/RecoveryShortInputLedger","claimCall").getFirst());int effect=at(tick,calls(tick,"io/github/campione01/mineclientbridge/RecoveryMaintenancePlacementDispatch","use").getFirst());check(claim<effect,"durable claim before vanilla effect");
  var metadata=own(RecoveryMaintenanceV5.class);for(var m:metadata.methods)for(var i:m.instructions)if(i instanceof MethodInsnNode c)check(!Set.of("entitiesForRendering","setBlock","setPos","attack","useItemOn","execute","schedule","setDeltaMovement").contains(c.name),"metadata not world action/global scan");
  var primed=method(metadata,"primed");check(Arrays.stream(primed.instructions.toArray()).anyMatch(i->i instanceof IntInsnNode v&&v.operand==33),"33 bounded primed query");for(var i:primed.instructions)if(i instanceof MethodInsnNode c)check(!Set.of("getType","getId","getUUID","isRemoved","getFuse","position").contains(c.name),"unknown entity no virtual metadata reads");
  for(String mixin:List.of("ScopedPlacementItemMixin","ScopedPlacementPacketMixin","ScopedPlacementSendMixin")){
   var cls=Class.forName("io.github.campione01.mineclientbridge.mixin."+mixin,false,RecoveryMaintenancePinnedChecks.class.getClassLoader());var c=own(cls);check(c.methods.stream().anyMatch(m->Arrays.stream(m.instructions.toArray()).anyMatch(i->i instanceof MethodInsnNode x&&x.owner.equals("io/github/campione01/mineclientbridge/RecoveryMaintenancePlacementDispatch")&&x.name.endsWith("Installed"))),"actual installed seam "+mixin);
  }
  System.out.println("RecoveryMaintenancePinnedChecks PASS checks="+n+"; pinned bytecode only, no game/Mixin-loader execution");
 }
}

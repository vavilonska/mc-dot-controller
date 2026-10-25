package io.github.campione01.mineclientbridge;
import java.io.*;import java.nio.file.*;import java.security.MessageDigest;import java.util.*;
import com.google.gson.*;import org.objectweb.asm.*;import org.objectweb.asm.tree.*;
/** Exhaustive target-module exact reader compatibility inventory, using actual official bytecode.
 * Static factory/declaration evidence is not a populated game/player admission proof. */
public final class TargetReaderParityAudit {
 static final String P="io/github/campione01/mineclientbridge/",N="net/minecraft/";
 static final Map<String,ClassNode> nodes=new HashMap<>();static final JsonObject hashes=new JsonObject();static final JsonArray findings=new JsonArray(),declarations=new JsonArray();static int checks;
 static ClassNode node(String name)throws Exception{if(nodes.containsKey(name))return nodes.get(name);try(var in=TargetReaderParityAudit.class.getClassLoader().getResourceAsStream(name+".class")){if(in==null)throw new FileNotFoundException(name);byte[] b=in.readAllBytes();hashes.addProperty(name,HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(b)));var c=new ClassNode();new ClassReader(b).accept(c,0);nodes.put(name,c);return c;}}
 static void test(boolean yes,String why){checks++;if(!yes)findings.add(why);}
 static String declares(String type,String name,String desc)throws Exception{for(String at=type;at!=null;at=node(at).superName)for(var m:node(at).methods)if(m.name.equals(name)&&(desc==null||m.desc.equals(desc)))return at;return null;}
 static void declaration(String type,String name,String desc,String expected)throws Exception{String actual=declares(type,name,desc);var row=new JsonObject();row.addProperty("type",type);row.addProperty("method",name);row.addProperty("descriptor",desc);row.addProperty("expected",expected);row.addProperty("actual",actual);declarations.add(row);test(expected.equals(actual),"declaration mismatch "+type+"."+name+": "+actual+" expected "+expected);}
 static JsonObject factories(Set<String> wanted)throws Exception{
  String[] owners={"client/main/Main","client/Minecraft","client/Options","client/multiplayer/ClientPacketListener","client/multiplayer/MultiPlayerGameMode","client/multiplayer/ClientLevel","client/multiplayer/ClientChunkCache","world/entity/Entity","world/entity/EntityType","world/entity/projectile/ProjectileUtil","world/entity/LivingEntity","world/entity/player/Player","world/entity/player/Inventory","world/entity/EntityDimensions","world/entity/ai/attributes/AttributeSupplier","world/entity/ai/attributes/Attributes","world/inventory/AbstractContainerMenu","world/inventory/InventoryMenu","world/inventory/CraftingMenu","world/level/chunk/ChunkAccess","world/level/chunk/LevelChunkSection","network/syncher/SynchedEntityData$Builder","core/Holder$Reference","core/NonNullList","core/component/DataComponentMap$Builder","core/component/DataComponentMap","world/item/ItemStack","world/item/Items","world/item/Item$Properties","world/level/block/Block","world/level/block/Blocks","world/scores/Scoreboard","world/damagesource/DamageSources","world/entity/boss/enderdragon/EnderDragon","world/entity/boss/enderdragon/phases/EnderDragonPhase","world/entity/boss/enderdragon/phases/EnderDragonPhaseManager","world/phys/Vec3","world/phys/AABB","world/phys/EntityHitResult","world/effect/MobEffectInstance"};
  var sites=new JsonObject();for(String type:wanted)sites.add(type,new JsonArray());
  var all=new LinkedHashSet<String>(wanted);for(String owner:owners)all.add(N+owner);
  all.add("com/google/common/collect/Maps");
  for(String owner:all){var c=node(owner);for(var m:c.methods)for(var i:m.instructions){
   if(i instanceof TypeInsnNode t&&t.getOpcode()==Opcodes.NEW&&wanted.contains(t.desc))sites.getAsJsonArray(t.desc).add(owner+"#"+m.name+m.desc+" NEW");
   if(i instanceof InvokeDynamicInsnNode d)for(Object b:d.bsmArgs)if(b instanceof Handle h&&h.getTag()==Opcodes.H_NEWINVOKESPECIAL&&wanted.contains(h.getOwner()))sites.getAsJsonArray(h.getOwner()).add(owner+"#"+m.name+m.desc+" constructor-handle");
   if(owner.equals(N+"world/entity/boss/enderdragon/phases/EnderDragonPhase")&&i instanceof LdcInsnNode l&&l.cst instanceof Type t&&wanted.contains(t.getInternalName()))sites.getAsJsonArray(t.getInternalName()).add(owner+"#"+m.name+" registered phase-class; manager reflection factory");
  }}
  for(String type:wanted)test(!sites.getAsJsonArray(type).isEmpty(),"no inspected official factory site for "+type);return sites;
 }
 static boolean subtype(String type,String base)throws Exception{for(String at=type;at!=null&&!at.equals("java/lang/Object");at=node(at).superName)if(at.equals(base))return true;return false;}
 static JsonObject blockFactories(Set<String> wanted)throws Exception{
  String blocks=N+"world/level/block/Blocks",block=N+"world/level/block/Block";var names=new TreeSet<String>();
  for(var m:node(P+"ScopedTargetAction$PolicyCells").methods)for(var i:m.instructions)if(i instanceof FieldInsnNode f&&f.owner.equals(blocks))names.add(f.name);
  var mapped=new JsonObject();for(var m:node(blocks).methods)if(m.name.equals("<clinit>")){String pending=null;for(var i:m.instructions){
   if(i instanceof TypeInsnNode t&&t.getOpcode()==Opcodes.NEW&&subtype(t.desc,block))pending=t.desc;
   if(i instanceof MethodInsnNode c&&c.getOpcode()==Opcodes.INVOKESTATIC&&c.owner.equals(blocks)&&!c.name.startsWith("register")){
    Type ret=Type.getReturnType(c.desc);if(ret.getSort()==Type.OBJECT&&subtype(ret.getInternalName(),block)){
     var classes=new TreeSet<String>();for(var helper:node(blocks).methods)if(helper.name.equals(c.name)&&helper.desc.equals(c.desc))for(var instruction:helper.instructions)if(instruction instanceof TypeInsnNode t&&t.getOpcode()==Opcodes.NEW&&subtype(t.desc,block))classes.add(t.desc);
     if(classes.size()==1)pending=classes.first();else if(!ret.getInternalName().equals(block))pending=ret.getInternalName();else pending=null;
    }
   }
   if(i instanceof FieldInsnNode f&&f.getOpcode()==Opcodes.PUTSTATIC&&f.owner.equals(blocks)){if(names.contains(f.name)){test(pending!=null,"concrete allowed-cell factory "+f.name);if(pending!=null)mapped.addProperty(f.name,pending);}pending=null;}
  }}
  test(mapped.size()==names.size(),"every existing allowed policy cell mapped without registry bootstrap");
  String shape="(Lnet/minecraft/world/level/block/state/BlockState;Lnet/minecraft/world/level/BlockGetter;Lnet/minecraft/core/BlockPos;Lnet/minecraft/world/phys/shapes/CollisionContext;)Lnet/minecraft/world/phys/shapes/VoxelShape;";
  for(var e:mapped.entrySet()){String type=e.getValue().getAsString();wanted.add(type);declaration(type,"getShape",shape,type.equals(N+"world/level/block/AirBlock")?type:N+"world/level/block/state/BlockBehaviour");declaration(type,"getCollisionShape",shape,N+"world/level/block/state/BlockBehaviour");}
  return mapped;
 }
 static JsonObject audit()throws Exception{
  var wanted=new TreeSet<String>();for(String cls:List.of("ScopedTargetAction","ScopedTargetAction$PolicyCells","ScopedTargetDispatch","ScopedTargetDispatch$AttackPacketReader","TargetActionKeySnapshot")){
   var c=node(P+cls);for(var m:c.methods)for(var i:m.instructions)if(i instanceof LdcInsnNode l&&l.cst instanceof Type t&&t.getSort()==Type.OBJECT&&t.getInternalName().startsWith(N))wanted.add(t.getInternalName());
  }
  // These literals are method owners/types, not exact concrete instance readers.
  wanted.removeAll(Set.of(N+"world/entity/Entity",N+"world/entity/LivingEntity",N+"world/entity/projectile/Projectile",N+"world/item/Item",N+"world/level/block/state/BlockBehaviour",N+"world/level/BlockGetter",N+"world/phys/shapes/CollisionContext",N+"core/component/DataComponentMap"));
  wanted.add(N+"core/component/DataComponentMap$Builder$SimpleMap");wanted.add("java/util/HashMap");
  // Damage source and ordinary packet constructors are also direct factory sites in their own classes/game mode.
  String entity=N+"world/entity/Entity",living=N+"world/entity/LivingEntity";
  var entityTypes=new TreeSet<String>();for(String type:wanted)if(type.startsWith(N+"world/entity/monster/")||type.equals(N+"world/entity/boss/enderdragon/EnderDragon")||type.equals(N+"world/entity/boss/enderdragon/EndCrystal")||type.equals(N+"world/entity/boss/EnderDragonPart")||type.equals(N+"client/player/LocalPlayer"))entityTypes.add(type);
  for(String type:entityTypes){for(String method:List.of("getId","getUUID","getType","getEntityData","position","level","getDeltaMovement","getBoundingBox","getX","getY","getZ","isRemoved"))declaration(type,method,null,method.equals("getDeltaMovement")&&type.equals(N+"world/entity/monster/Shulker")?type:entity);
   boolean isLiving=false;for(String at=type;at!=null;at=node(at).superName)if(at.equals(living))isLiving=true;
   declaration(type,"isAlive",null,isLiving?living:entity);if(isLiving)declaration(type,"getHealth",null,living);
  }
  for(String item:List.of("world/item/AxeItem","world/item/BowItem"))declaration(N+item,"components",null,N+"world/item/Item");
  var menu=node(N+"world/inventory/InventoryMenu");var slots=new TreeSet<String>();for(var m:menu.methods)for(var i:m.instructions)if(i instanceof TypeInsnNode t&&t.getOpcode()==Opcodes.NEW){for(String at=t.desc;at!=null;at=node(at).superName)if(at.equals(N+"world/inventory/Slot")){slots.add(t.desc);break;}}
  for(String slot:slots){declaration(slot,"getItem",null,N+"world/inventory/Slot");declaration(slot,"getContainerSlot",null,N+"world/inventory/Slot");}
  test(!slots.isEmpty(),"actual inventory-menu slot factories found");
  var attrs=new JsonObject();String last=null;for(var m:node(N+"world/entity/ai/attributes/Attributes").methods)if(m.name.equals("<clinit>"))for(var i:m.instructions){if(i instanceof TypeInsnNode t&&t.getOpcode()==Opcodes.NEW)last=t.desc;if(i instanceof FieldInsnNode f&&f.getOpcode()==Opcodes.PUTSTATIC&&Set.of("ATTACK_KNOCKBACK","ENTITY_INTERACTION_RANGE","ATTACK_SPEED","ATTACK_DAMAGE").contains(f.name))attrs.addProperty(f.name,last);}
  test(attrs.size()==4,"four protected target attributes mapped");for(var e:attrs.entrySet())test(e.getValue().getAsString().equals(N+"world/entity/ai/attributes/RangedAttribute"),"exact target attribute "+e.getKey());
  var shulker=node(N+"world/entity/monster/Shulker");var velocity=shulker.methods.stream().filter(m->m.name.equals("getDeltaMovement")).findFirst().orElseThrow();var op=new ArrayList<AbstractInsnNode>();for(var i:velocity.instructions)if(i.getOpcode()>=0)op.add(i);test(op.size()==2&&op.get(0) instanceof FieldInsnNode f&&f.getOpcode()==Opcodes.GETSTATIC&&f.owner.equals(N+"world/phys/Vec3")&&f.name.equals("ZERO")&&op.get(1).getOpcode()==Opcodes.ARETURN,"exact Shulker pure ZERO velocity bytecode");
  var blockMap=blockFactories(wanted);
  var out=new JsonObject();out.add("official_factories",factories(wanted));out.add("allowed_policy_cell_factories",blockMap);out.add("target_attributes",attrs);out.add("method_declarations",declarations);out.add("findings",findings);out.add("class_sha256",hashes);out.addProperty("checks",checks);return out;
 }
 public static void main(String[] args)throws Exception{var out=audit();out.addProperty("scope","compiled target reader literals plus actual official factories and method owners; no registry/world/player construction");out.addProperty("status",findings.isEmpty()?"passed":"mismatches_or_unresolved_factory_sites");Files.writeString(Path.of(args[0]),new GsonBuilder().setPrettyPrinting().create().toJson(out)+"\n",StandardOpenOption.CREATE_NEW);System.out.println("TargetReaderParityAudit checks="+checks+" findings="+findings.size());if(!findings.isEmpty())throw new AssertionError(findings.toString());}
}

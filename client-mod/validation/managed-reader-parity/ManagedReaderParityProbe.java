package io.github.campione01.mineclientbridge;

import java.io.*;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
import com.google.gson.*;
import org.objectweb.asm.*;
import org.objectweb.asm.tree.*;
import net.minecraft.world.entity.ai.attributes.RangedAttribute;
import net.neoforged.neoforge.common.PercentageAttribute;

/** Actual compiled production/official class proof. No registry bootstrap, synthetic loader, world, or player. */
public final class ManagedReaderParityProbe {
    private static final String ATTR="net/minecraft/world/entity/ai/attributes/Attributes";
    private static final String RANGED="net/minecraft/world/entity/ai/attributes/RangedAttribute";
    private static final String PERCENT="net/neoforged/neoforge/common/PercentageAttribute";
    private static final String WORLD="io/github/campione01/mineclientbridge/ManagedDryWorld";
    private static int checks;
    private static String mode="none";
    private static final JsonObject hashes=new JsonObject();
    private static void check(boolean yes,String why){checks++;if(!yes)throw new AssertionError(why);}
    private static byte[] bytes(String name)throws Exception{
        try(var in=ManagedReaderParityProbe.class.getClassLoader().getResourceAsStream(name+".class")){
            if(in==null)throw new FileNotFoundException(name);byte[] b=in.readAllBytes();
            hashes.addProperty(name,HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(b)));return b;
        }
    }
    private static ClassNode node(String name)throws Exception{var n=new ClassNode();new ClassReader(bytes(name)).accept(n,0);return n;}
    private static MethodNode method(ClassNode n,String name){return n.methods.stream().filter(m->m.name.equals(name)).findFirst().orElseThrow();}
    private static List<AbstractInsnNode> ops(MethodNode m){var out=new ArrayList<AbstractInsnNode>();for(var i:m.instructions)if(i.getOpcode()>=0)out.add(i);return out;}
    private static Class<?> nativeClass(String name)throws Exception{return Class.forName(name.replace('/','.'),false,ManagedReaderParityProbe.class.getClassLoader());}
    private static boolean call(AbstractInsnNode i,String owner,String name){return i instanceof MethodInsnNode m&&m.owner.equals(owner)&&m.name.equals(name);}
    private static String type(AbstractInsnNode i){check(i instanceof LdcInsnNode&&((LdcInsnNode)i).cst instanceof Type,"exact class literal");return ((Type)((LdcInsnNode)i).cst).getInternalName();}
    private static AbstractInsnNode nextOp(AbstractInsnNode i){do{i=i.getNext();}while(i!=null&&i.getOpcode()<0);return i;}
    // Read the actual compiled branch. This is not a manually reimplemented admission rule.
    private static Class<?> selectedClass(MethodNode m,boolean identicalHolder)throws Exception{
        var list=ops(m);int k=-1;
        for(int i=0;i<list.size();i++)if(list.get(i) instanceof FieldInsnNode f&&f.owner.equals(ATTR)&&f.name.equals("MOVEMENT_SPEED")){check(k<0,"only one movement holder read");k=i;}
        check(k>0,"production reads exact official movement holder");
        check(list.get(k-1) instanceof VarInsnNode v&&v.getOpcode()==Opcodes.ALOAD&&v.var==1,"compare actual holder argument");
        check(list.get(k+1) instanceof JumpInsnNode j&&j.getOpcode()==Opcodes.IF_ACMPNE,"identity comparison, never equals/registry name");
        var branch=(JumpInsnNode)list.get(k+1);var same=list.get(k+2);var other=nextOp(branch.label);
        check(type(same).equals(PERCENT),"exact holder maps to exact PercentageAttribute");
        check(type(other).equals(RANGED),"all other protected holders retain exact RangedAttribute");
        check(list.get(k+3) instanceof JumpInsnNode end&&end.getOpcode()==Opcodes.GOTO,"closed two-way selection");
        var end=(JumpInsnNode)list.get(k+3);
        check(nextOp(other)==nextOp(end.label)&&call(nextOp(end.label),WORLD,"exact"),"both branches immediately enter exact class fence");
        return nativeClass(type(identicalHolder?same:other));
    }
    static final class PercentageSubclass extends PercentageAttribute {PercentageSubclass(){super("test",.1,0,1);}}
    static final class RangedSubclass extends RangedAttribute {RangedSubclass(){super("test",.1,0,1);}}
    private static void productionParity()throws Exception{
        var n=node(WORLD);var m=method(n,"attribute");
        // Negative probes mutate only this in-memory test inspection, never production files/classes.
        if(!mode.equals("none"))for(var i:ops(m)){
            if(mode.equals("swapped")&&i instanceof LdcInsnNode l&&l.cst instanceof Type t&&t.getInternalName().equals(PERCENT))l.cst=Type.getObjectType(RANGED);
            if(mode.equals("subclass")&&i instanceof LdcInsnNode l&&l.cst instanceof Type t&&t.getInternalName().equals(PERCENT))l.cst=Type.getType(PercentageSubclass.class);
            if(mode.equals("wrong-holder")&&i instanceof FieldInsnNode f&&f.owner.equals(ATTR)&&f.name.equals("MOVEMENT_SPEED"))f.name="GRAVITY";
        }
        var list=ops(m);
        check(list.stream().filter(i->call(i,WORLD,"exact")).count()==3,"holder, value, instance exact fences retained");
        check(list.stream().filter(i->i instanceof FieldInsnNode f&&f.owner.equals(ATTR)).count()==1,"no second holder allowlist");
        check(list.stream().noneMatch(i->i.getOpcode()==Opcodes.INSTANCEOF),"no subclass acceptance");
        var exact=ops(method(n,"exact"));
        check(exact.stream().anyMatch(i->call(i,"java/lang/Object","getClass")),"actual runtime exact class reader");
        check(exact.stream().anyMatch(i->i.getOpcode()==Opcodes.IF_ACMPNE||i.getOpcode()==Opcodes.IF_ACMPEQ),"class identity fence");
        check(exact.stream().noneMatch(i->call(i,"java/lang/Class","isInstance")||call(i,"java/lang/Class","isAssignableFrom")),"no reflective subclass widening");
        Class<?> movement=selectedClass(m,true),other=selectedClass(m,false);
        check(movement==PercentageAttribute.class&&other==RangedAttribute.class,"actual loaded official classes match production literals");
        check(movement!=RangedAttribute.class&&other!=PercentageAttribute.class,"swapped class negatives");
        check(movement!=PercentageSubclass.class&&other!=RangedSubclass.class,"subclass negatives");
        check(movement!=String.class&&other!=String.class,"unknown class negatives");
        check(list.stream().anyMatch(i->call(i,"net/minecraft/world/entity/ai/attributes/AttributeInstance","getAttribute")),"instance holder check retained");
        check(list.stream().anyMatch(i->call(i,"net/minecraft/world/entity/ai/attributes/AttributeInstance","getBaseValue")),"base-value check retained");
        check(list.stream().anyMatch(i->call(i,"net/minecraft/world/entity/ai/attributes/AttributeInstance","getModifiers")),"modifier refusal retained");
        Set<String> consumed=new TreeSet<>();for(var i:ops(method(n,"body")))if(i instanceof FieldInsnNode f&&f.owner.equals(ATTR))consumed.add(f.name);
        check(consumed.equals(Set.of("MOVEMENT_SPEED","GRAVITY","JUMP_STRENGTH","STEP_HEIGHT")),"exact four protected attribute call sites");
    }
    private static JsonObject officialMappings()throws Exception{
        var mappings=new JsonObject();String lastNew=null;
        for(var i:ops(method(node(ATTR),"<clinit>"))){
            if(i instanceof TypeInsnNode t&&t.getOpcode()==Opcodes.NEW)lastNew=t.desc;
            if(i instanceof FieldInsnNode f&&f.getOpcode()==Opcodes.PUTSTATIC&&f.owner.equals(ATTR)&&Set.of("MOVEMENT_SPEED","GRAVITY","JUMP_STRENGTH","STEP_HEIGHT").contains(f.name))mappings.addProperty(f.name,lastNew);
        }
        check(mappings.size()==4,"all four actual initializer mappings retained");
        for(String f:List.of("MOVEMENT_SPEED","GRAVITY","JUMP_STRENGTH","STEP_HEIGHT"))check(mappings.get(f).getAsString().equals(f.equals("MOVEMENT_SPEED")?PERCENT:RANGED),"official initializer "+f);
        var p=node(PERCENT);check(p.superName.equals(RANGED),"official PercentageAttribute superclass");
        check(p.methods.stream().allMatch(m->m.name.equals("<init>")||m.name.equals("toValueComponent")),"official subclass only constructors and tooltip override");
        check(PercentageAttribute.class.getMethod("getDefaultValue").getDeclaringClass().getName().equals("net.minecraft.world.entity.ai.attributes.Attribute"),"default-value reader inherited from exact Attribute");
        check(PercentageAttribute.class.getMethod("sanitizeValue",double.class).getDeclaringClass()==RangedAttribute.class,"sanitization inherited from exact RangedAttribute");
        node("net/minecraft/world/entity/ai/attributes/Attribute");node(RANGED);
        return mappings;
    }
    private static JsonObject constructionAudit()throws Exception{
        String[] readers={"net/minecraft/client/Minecraft","net/minecraft/client/player/LocalPlayer","net/minecraft/client/multiplayer/ClientLevel","net/minecraft/client/multiplayer/ClientChunkCache","net/minecraft/client/multiplayer/MultiPlayerGameMode","net/minecraft/client/server/IntegratedServer","net/minecraft/client/multiplayer/ClientLevel$ClientLevelData","net/minecraft/world/entity/player/Abilities","net/minecraft/network/syncher/SynchedEntityData","net/minecraft/world/entity/ai/attributes/AttributeMap","net/minecraft/world/entity/ai/attributes/AttributeInstance","net/minecraft/core/Holder$Reference","net/minecraft/world/phys/Vec3","net/minecraft/world/phys/AABB","net/minecraft/world/level/chunk/LevelChunk","net/minecraft/world/level/chunk/LevelChunkSection","net/minecraft/world/level/chunk/PalettedContainer","net/minecraft/world/level/block/state/BlockState"};
        var out=new JsonObject();for(String r:readers){var n=node(r);check(n.name.equals(r),"official exact reader exists "+r);var a=new JsonArray();for(var m:n.methods)if(m.name.equals("<init>"))a.add(m.desc);check(!a.isEmpty(),"native concrete reader constructors "+r);out.add(r,a);}
        // Exact ordinary native factory sites. This binds static compatibility, not populated live instances.
        String[][] factories={
            {"net/minecraft/client/Minecraft","net/minecraft/client/main/Main","main"},
            {"net/minecraft/client/player/LocalPlayer","net/minecraft/client/multiplayer/MultiPlayerGameMode","createPlayer"},
            {"net/minecraft/client/multiplayer/ClientLevel","net/minecraft/client/multiplayer/ClientPacketListener","handleLogin"},
            {"net/minecraft/client/multiplayer/MultiPlayerGameMode","net/minecraft/client/multiplayer/ClientPacketListener","handleLogin"},
            {"net/minecraft/client/multiplayer/ClientLevel$ClientLevelData","net/minecraft/client/multiplayer/ClientPacketListener","handleLogin"},
            {"net/minecraft/client/multiplayer/ClientChunkCache","net/minecraft/client/multiplayer/ClientLevel","<init>"},
            {"net/minecraft/client/server/IntegratedServer","net/minecraft/client/Minecraft","lambda$doWorldLoad$40"},
            {"net/minecraft/world/entity/player/Abilities","net/minecraft/world/entity/player/Player","<init>"},
            {"net/minecraft/network/syncher/SynchedEntityData","net/minecraft/network/syncher/SynchedEntityData$Builder","build"},
            {"net/minecraft/world/entity/ai/attributes/AttributeMap","net/minecraft/world/entity/LivingEntity","<init>"},
            {"net/minecraft/world/entity/ai/attributes/AttributeInstance","net/minecraft/world/entity/ai/attributes/AttributeSupplier","createInstance"},
            {"net/minecraft/core/Holder$Reference","net/minecraft/core/Holder$Reference","createStandAlone"},
            {"net/minecraft/world/phys/Vec3","net/minecraft/world/entity/Entity","setPosRaw"},
            {"net/minecraft/world/phys/AABB","net/minecraft/world/entity/EntityDimensions","makeBoundingBox"},
            {"net/minecraft/world/level/chunk/LevelChunk","net/minecraft/client/multiplayer/ClientChunkCache","replaceWithPacketData"},
            {"net/minecraft/world/level/chunk/LevelChunkSection","net/minecraft/world/level/chunk/ChunkAccess","replaceMissingSections"},
            {"net/minecraft/world/level/chunk/PalettedContainer","net/minecraft/world/level/chunk/LevelChunkSection","<init>"},
            {"net/minecraft/world/level/block/state/BlockState","net/minecraft/world/level/block/Block","<init>"}
        };
        var proofs=new JsonObject();for(String[] row:factories){
            var owner=node(row[1]);var sites=new JsonArray();
            for(var m:owner.methods)if(m.name.equals(row[2]))for(var i:ops(m)){
                if(i instanceof TypeInsnNode t&&t.getOpcode()==Opcodes.NEW&&t.desc.equals(row[0]))sites.add(m.name+m.desc+" NEW "+t.desc);
                if(i instanceof InvokeDynamicInsnNode dynamic)for(Object arg:dynamic.bsmArgs)
                    if(arg instanceof Handle handle&&handle.getTag()==Opcodes.H_NEWINVOKESPECIAL&&handle.getOwner().equals(row[0])&&handle.getName().equals("<init>"))sites.add(m.name+m.desc+" constructor handle "+handle.getOwner());
            }
            check(!sites.isEmpty(),"actual ordinary native factory for "+row[0]);proofs.add(row[0],sites);
        }
        check(proofs.size()==readers.length,"every concrete reader has a pinned ordinary factory");
        var living=node("net/minecraft/world/entity/LivingEntity");
        check(living.methods.stream().filter(m->m.name.equals("<init>")).anyMatch(m->ops(m).stream().anyMatch(i->call(i,"com/google/common/collect/Maps","newHashMap"))),"active effects ordinary HashMap factory");
        var maps=node("com/google/common/collect/Maps");
        check(maps.methods.stream().filter(m->m.name.equals("newHashMap")&&m.desc.equals("()Ljava/util/HashMap;")).anyMatch(m->ops(m).stream().anyMatch(i->i instanceof TypeInsnNode t&&t.getOpcode()==Opcodes.NEW&&t.desc.equals("java/util/HashMap"))),"Guava factory creates exact JDK HashMap");
        out.add("ordinary_native_factory_sites",proofs);
        return out;
    }
    public static void main(String[] args)throws Exception{
        mode=args.length>1?args[1]:"none";productionParity();var mappings=officialMappings();var constructors=constructionAudit();var out=new JsonObject();out.addProperty("status","passed");out.addProperty("checks",checks);
        out.addProperty("scope","actual compiled production and official native classes; registry-free; no player/world admission");out.add("official_attribute_mappings",mappings);out.add("native_reader_constructor_audit",constructors);out.add("class_sha256",hashes);
        Files.writeString(Path.of(args[0]),new GsonBuilder().setPrettyPrinting().create().toJson(out)+"\n",StandardOpenOption.CREATE_NEW);
        System.out.println("ManagedReaderParityProbe PASS checks="+checks+" real compiled/official classes; no registry, player or world");
    }
}

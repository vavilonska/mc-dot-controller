package io.github.campione01.mineclientbridge;
import com.google.gson.*;
import java.io.*;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
import java.util.jar.JarFile;
import org.objectweb.asm.*;
import org.objectweb.asm.tree.*;

/** Offline pinned class+vanilla datapack audit, not a running-world tag/attribute guarantee. */
public final class RecoveryWartPinnedChecks {
    static int checks;
    static void check(boolean ok,String label){if(!ok)throw new AssertionError(label);checks++;}
    static ClassNode read(JarFile jar,String name)throws Exception{ClassNode c=new ClassNode();try(var in=jar.getInputStream(jar.getJarEntry(name+".class"))){new ClassReader(in).accept(c,0);}return c;}
    static MethodNode method(ClassNode c,String name,String desc){return c.methods.stream().filter(m->m.name.equals(name)&&(desc==null||m.desc.equals(desc))).findFirst().orElseThrow();}
    static Set<String> expand(JarFile jar,String id,Set<String> seen)throws Exception{
        check(seen.add(id),"tag_no_cycle");String[] pair=id.split(":",2);JsonObject json;
        try(var reader=new InputStreamReader(jar.getInputStream(jar.getJarEntry("data/"+pair[0]+"/tags/block/"+pair[1]+".json")),java.nio.charset.StandardCharsets.UTF_8)){json=JsonParser.parseReader(reader).getAsJsonObject();}
        Set<String> out=new HashSet<>();for(JsonElement value:json.getAsJsonArray("values")){String s=value.isJsonPrimitive()?value.getAsString():value.getAsJsonObject().get("id").getAsString();if(s.startsWith("#"))out.addAll(expand(jar,s.substring(1),new HashSet<>(seen)));else out.add(s);}return out;
    }
    public static void main(String[] args)throws Exception{
        Path official=Path.of(args[1]);String sha=HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(official)));
        check(sha.equals("499f6897d1837516680f3114072d8106e11c9adcd933fe5cf051b551089b0c99"),"official_resource_pin");
        int pickCount,hoeCount;
        try(var jar=new JarFile(official.toFile())){var pick=expand(jar,"minecraft:mineable/pickaxe",new HashSet<>());var hoe=expand(jar,"minecraft:mineable/hoe",new HashSet<>());pickCount=pick.size();hoeCount=hoe.size();check(!pick.contains("minecraft:nether_wart_block"),"wart_not_in_recursive_pickaxe_tag");check(hoe.contains("minecraft:nether_wart_block"),"wart_in_recursive_hoe_tag");}
        try(var jar=new JarFile(args[0])){
            var init=method(read(jar,"net/minecraft/world/level/block/Blocks"),"<clinit>",null);boolean in=false,exactBlock=false,strengthOne=false,requiresTool=false;AbstractInsnNode previous=null;
            for(var insn:init.instructions){
                if(insn instanceof LdcInsnNode ldc&&"nether_wart_block".equals(ldc.cst))in=true;
                if(in){if(insn instanceof TypeInsnNode t&&t.getOpcode()==Opcodes.NEW)exactBlock=t.desc.equals("net/minecraft/world/level/block/Block");if(insn instanceof MethodInsnNode call&&call.name.equals("strength"))strengthOne=call.desc.startsWith("(F)")&&previous!=null&&previous.getOpcode()==Opcodes.FCONST_1;if(insn instanceof MethodInsnNode call&&call.name.equals("requiresCorrectToolForDrops"))requiresTool=true;if(insn instanceof FieldInsnNode f&&f.getOpcode()==Opcodes.PUTSTATIC&&f.name.equals("NETHER_WART_BLOCK"))break;}
                if(insn.getOpcode()>=0)previous=insn;
            }
            check(exactBlock&&strengthOne&&!requiresTool,"wart_literal_Block_strength1_no_correcttool_builder");
            var ctor=method(read(jar,"net/minecraft/world/level/block/state/BlockBehaviour$Properties"),"<init>","()V");boolean assignsTool=false;for(var insn:ctor.instructions)if(insn instanceof FieldInsnNode f&&f.getOpcode()==Opcodes.PUTFIELD&&f.name.equals("requiresCorrectToolForDrops"))assignsTool=true;check(!assignsTool,"requires_correct_tool_defaults_false");
            var progress=method(read(jar,"net/minecraft/world/level/block/state/BlockBehaviour"),"getDestroyProgress",null);boolean thirty=false,digSpeed=false;for(var insn:progress.instructions){if(insn instanceof IntInsnNode n&&n.operand==30)thirty=true;if(insn instanceof MethodInsnNode m&&m.name.equals("getDigSpeed"))digSpeed=true;}check(thirty&&digSpeed,"pinned_harvest_divisor30_and_player_speed");
            var tool=method(read(jar,"net/minecraft/world/item/Tier"),"createToolProperties",null);boolean defaultSpeed=false;
            for(var insn:tool.instructions)if(insn instanceof MethodInsnNode m&&m.owner.equals("net/minecraft/world/item/component/Tool")&&m.name.equals("<init>")){var before=insn.getPrevious();while(before!=null&&before.getOpcode()<0)before=before.getPrevious();var speed=before==null?null:before.getPrevious();while(speed!=null&&speed.getOpcode()<0)speed=speed.getPrevious();defaultSpeed=before!=null&&before.getOpcode()==Opcodes.ICONST_1&&speed!=null&&speed.getOpcode()==Opcodes.FCONST_1;}check(defaultSpeed,"pinned_tool_default_speed1_damage1");
            var mode=read(jar,"net/minecraft/client/multiplayer/MultiPlayerGameMode");var start=method(mode,"lambda$startDestroyBlock$1",null);boolean zero=false;
            for(var insn:start.instructions)if(insn instanceof FieldInsnNode f&&f.getOpcode()==Opcodes.PUTFIELD&&f.name.equals("destroyProgress")){var prior=insn.getPrevious();while(prior!=null&&prior.getOpcode()<0)prior=prior.getPrevious();zero=prior!=null&&prior.getOpcode()==Opcodes.FCONST_0;}check(zero,"native_start_progress_initializes_zero");
            var more=method(mode,"continueDestroyBlock",null);boolean adds=false;for(var insn:more.instructions)if(insn instanceof MethodInsnNode m&&m.name.equals("getDestroyProgress")){var after=insn.getNext();while(after!=null&&after.getOpcode()<0)after=after.getNext();adds=after!=null&&after.getOpcode()==Opcodes.FADD;}check(adds,"native_continue_float_adds_progress");
            var tiers=method(read(jar,"net/minecraft/world/item/Tiers"),"<clinit>",null);boolean stone=false,uses131=false;for(var insn:tiers.instructions){if(insn instanceof LdcInsnNode l&&"STONE".equals(l.cst))stone=true;if(stone&&insn instanceof IntInsnNode n&&n.operand==131)uses131=true;if(stone&&insn instanceof FieldInsnNode f&&f.name.equals("STONE")&&f.getOpcode()==Opcodes.PUTSTATIC)break;}check(uses131,"stone_default_max_damage131");
        }
        float progress=0,step=1F/1F/30F;int continuing=0;while(progress<1&&continuing<100){progress+=step;continuing++;}check(continuing==30&&continuing+1==31,"float32_30_continue_plus1_start");check(continuing+1<=32,"unchanged_native_call_cap_sufficient_in_stated_baseline");
        try(var in=RecoveryInteraction.class.getResourceAsStream("RecoveryInteraction.class")){ClassNode c=new ClassNode();new ClassReader(in).accept(c,0);var obs=method(c,"observation","(Lcom/google/gson/JsonObject;Lnet/minecraft/client/Minecraft;Z)V");boolean actualMax=false;for(var insn:obs.instructions)if(insn instanceof MethodInsnNode m&&m.owner.equals("net/minecraft/world/item/ItemStack")&&m.name.equals("getMaxDamage"))actualMax=true;check(actualMax,"observation_consumes_actual_stack_max_damage");var binding=method(c,"finalBinding",null);boolean above=false;for(var insn:binding.instructions)if(insn instanceof MethodInsnNode m&&m.name.equals("allowedTarget"))above=true;check(above,"abovefeet_rechecked_after_ray_at_final_binding");}
        JsonObject report=new JsonObject();report.addProperty("evidence","offline pinned bytecode and vanilla resource tags; not a live capture");report.addProperty("resource_sha256",sha);report.addProperty("exact_class","net.minecraft.world.level.block.Block");report.addProperty("block_id","minecraft:nether_wart_block");report.addProperty("hardness",1);report.addProperty("requires_correct_tool",false);report.addProperty("recursive_pickaxe_tag_count",pickCount);report.addProperty("recursive_hoe_tag_count",hoeCount);report.addProperty("baseline_mining_speed",1);report.addProperty("float32_progress_per_continue",step);report.addProperty("continue_calls",continuing);report.addProperty("start_plus_continue_calls",continuing+1);report.addProperty("float32_total_progress",progress);report.addProperty("default_stone_max_damage",131);report.addProperty("given_damage",106);report.addProperty("default_remaining",25);report.addProperty("assumptions","ordinary ground, no effects/attribute/tool-component overrides, normal hooks; 2000ms/no renewal still applies; incomplete known attempt is not auto-replayed");Files.write(Path.of(args[2]),RecoveryShortInputCodec.encode(report));
        System.out.println("RecoveryWartPinnedChecks PASS assertions="+checks+" start+continue="+(continuing+1));
    }
}

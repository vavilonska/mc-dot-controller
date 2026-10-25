package io.github.campione01.mineclientbridge;
import java.io.*;
import java.util.*;
import java.util.jar.*;
import org.objectweb.asm.*;
import org.objectweb.asm.tree.*;

/** Read-only pinned bytecode selector/chronology checks, not a live Mixin application claim. */
public final class RecoveryInteractionPinnedChecks {
    static int checks;
    static void check(boolean b,String label){if(!b)throw new AssertionError(label);checks++;}
    static ClassNode read(JarFile jar,String path)throws Exception{ClassNode n=new ClassNode();try(var in=jar.getInputStream(jar.getJarEntry(path+".class"))){new ClassReader(in).accept(n,0);}return n;}
    static MethodNode method(ClassNode c,String name){var found=c.methods.stream().filter(m->m.name.equals(name)).toList();check(found.size()==1,c.name+"#"+name+" unique");return found.getFirst();}
    static List<MethodInsnNode> calls(MethodNode m,String owner,String name){List<MethodInsnNode> out=new ArrayList<>();for(var i:m.instructions)if(i instanceof MethodInsnNode x&&x.owner.equals(owner)&&x.name.equals(name))out.add(x);return out;}
    static int at(MethodNode m,AbstractInsnNode n){return m.instructions.indexOf(n);}
    public static void main(String[] args)throws Exception{
        String gm="net/minecraft/client/multiplayer/MultiPlayerGameMode",mc="net/minecraft/client/Minecraft",listener="net/minecraft/client/multiplayer/ClientPacketListener";
        try(var jar=new JarFile(args[0])){
            var g=read(jar,gm);var client=read(jar,mc);var common=read(jar,"net/minecraft/client/multiplayer/ClientCommonPacketListenerImpl");
            for(String field:List.of("destroyBlockPos","destroyingItem","destroyProgress","connection"))check(g.fields.stream().filter(f->f.name.equals(field)).count()==1,"accessor_target_"+field);
            var start=method(g,"startDestroyBlock");var cont=method(g,"continueDestroyBlock");var stop=method(g,"stopDestroyBlock");
            check(calls(start,listener,"send").size()==1,"start_retarget_abort_send_selector");check(calls(stop,listener,"send").size()==1,"stop_abort_send_selector");
            var lambdaStart=method(g,"lambda$startDestroyBlock$1");var lambdaStop=method(g,"lambda$continueDestroyBlock$3");
            check(calls(lambdaStop,gm,"destroyBlock").size()==1,"stop_lambda_local_removal");
            int destroy=at(lambdaStop,calls(lambdaStop,gm,"destroyBlock").getFirst());int packet=-1;for(var n:lambdaStop.instructions)if(n instanceof TypeInsnNode t&&t.getOpcode()==Opcodes.NEW&&t.desc.endsWith("ServerboundPlayerActionPacket"))packet=at(lambdaStop,n);check(packet>destroy,"local_removal_precedes_stop_packet_construction");
            check(calls(method(g,"startPrediction"),listener,"send").size()==1,"prediction_send_exact_selector");
            check(calls(method(g,"destroyBlock"),"net/minecraft/world/level/block/state/BlockState","onDestroyedByPlayer").size()==1,"removal_redirect_exact_selector");
            check(calls(method(client,"handleKeybinds"),mc,"continueAttack").size()==1,"scoped_continue_redirect_exact");
            check(calls(method(client,"continueAttack"),gm,"stopDestroyBlock").size()==1,"vanilla_false_abort_exists");
            check(calls(method(common,"send"),"net/minecraft/network/Connection","send").size()==1,"post_network_registry_send_selector");
            for(String setter:List.of("setYRot","setXRot")){
                var m=method(read(jar,"net/minecraft/world/entity/Entity"),setter);int puts=0;for(var n:m.instructions)if(n.getOpcode()==Opcodes.PUTFIELD)puts++;check(puts==1,"angle_setter_one_field_"+setter);
                for(var n:m.instructions)if(n instanceof MethodInsnNode call)check(!call.owner.contains("network")&&!call.name.toLowerCase(Locale.ROOT).contains("attack"),"angle_setter_no_network_interaction");
            }
        }
        // Compiled implementation contains no packet construction, attack/use/placement dispatch or raw progress setter.
        try(var in=RecoveryInteraction.class.getResourceAsStream("RecoveryInteraction.class")){
            ClassNode n=new ClassNode();new ClassReader(in).accept(n,0);
            for(var m:n.methods)for(var insn:m.instructions){
                if(insn instanceof TypeInsnNode t&&t.getOpcode()==Opcodes.NEW)check(!t.desc.contains("Packet"),"no_handcrafted_packet");
                if(insn instanceof MethodInsnNode call)check(!Set.of("attack","startAttack","continueAttack","useItem","useItemOn","setDeltaMovement","setPos","teleportTo").contains(call.name),"no_disallowed_dispatch");
                if(insn instanceof FieldInsnNode field&&field.getOpcode()==Opcodes.PUTFIELD)check(!Set.of("destroyProgress","isDestroying","destroyBlockPos").contains(field.name),"no_raw_mining_progress_write");
            }
        }
        try(var in=NativeRecoveryShortInput.class.getResourceAsStream("NativeRecoveryShortInput.class")){
            ClassNode n=new ClassNode();new ClassReader(in).accept(n,0);var cleanup=method(n,"requestCleanup");
            int lastMonitorExit=-1,execute=-1;
            for(var insn:cleanup.instructions){if(insn.getOpcode()==Opcodes.MONITOREXIT)lastMonitorExit=at(cleanup,insn);if(insn instanceof MethodInsnNode call&&call.name.equals("execute"))execute=at(cleanup,insn);}
            check(lastMonitorExit>=0&&execute>lastMonitorExit,"inline_execute_outside_all_cleanup_monitor_regions");
            var observe=n.methods.stream().filter(m->m.name.equals("observe")&&m.desc.equals("(Ljava/lang/String;)Lcom/google/gson/JsonObject;")).findFirst().orElseThrow();
            var hooks=calls(observe,"io/github/campione01/mineclientbridge/RecoveryInteraction","hooksReady");check(hooks.size()==1,"interaction_observe_hook_readiness_bound");
            var noWorld=calls(observe,"io/github/campione01/mineclientbridge/NativeRecoveryShortInput","describeNoWorld");check(noWorld.size()==1&&at(observe,noWorld.getFirst())<at(observe,hooks.getFirst()),"no_world_branch_before_hook_readiness");
            var release=method(n,"cleanup");int settled=-1,nativeRelease=-1;boolean earlyReturn=false;
            for(var insn:release.instructions){
                if(settled<0&&insn instanceof MethodInsnNode call&&call.name.equals("settled"))settled=at(release,insn);
                if(insn instanceof MethodInsnNode call&&call.owner.endsWith("RecoveryInteraction")&&call.name.equals("release"))nativeRelease=at(release,insn);
            }
            for(var insn:release.instructions)if(insn.getOpcode()==Opcodes.RETURN&&at(release,insn)>settled&&at(release,insn)<nativeRelease)earlyReturn=true;
            check(settled>=0&&nativeRelease>settled&&earlyReturn,"known_zero_terminal_retires_before_any_native_abort");
            var tick=method(n,"interactionTick");for(var insn:tick.instructions)check(insn.getOpcode()!=Opcodes.MONITORENTER,"interaction_driver_no_outer_monitor");
        }
        System.out.println("RecoveryInteractionPinnedChecks PASS assertions="+checks+" (selector audit only; live loader qualification remains required)");
    }
}

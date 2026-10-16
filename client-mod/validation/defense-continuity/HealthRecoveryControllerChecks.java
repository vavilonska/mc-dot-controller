package io.github.campione01.mineclientbridge;

import com.google.gson.*;
import java.nio.file.*;
import java.lang.invoke.MethodHandles;
import java.lang.reflect.*;
import java.util.*;
import org.objectweb.asm.*;
import org.objectweb.asm.commons.*;
import org.objectweb.asm.tree.*;

/** Executes the unchanged compiled recovery helper with explicit environment/effect doubles. */
public final class HealthRecoveryControllerChecks {
    static final String P="io/github/campione01/mineclientbridge/",H=P+"HealthRecoveryControllerChecks";
    static int assertions;
    static void ok(boolean value,String name){assertions++;if(!value)throw new AssertionError(name);}
    public static class Player { public float health=20;public float getHealth(){return health;}public double getX(){return 0;}public double getY(){return 64;}public double getZ(){return 0;} }
    public static class Level {public long tick=77;public long getGameTime(){return tick;}}
    public static class Clock {static Long forced;public static long nanoTime(){return forced==null?System.nanoTime():forced;}}
    public static class Mc {public Player player=new Player();public Level level=new Level();}
    public static class Request {public boolean wanted=true;public boolean shield(){return wanted;}public int targetId(){return 15;}public String targetUuid(){return "target";} }
    public static class Guard {
        public boolean owner=true,context=true;public int checks,fences;public long elapsedNanos;public Runnable afterEffect;
        public void check(Mc mc,boolean alive){checks++;if(!owner||!context)throw new IllegalStateException("owner_or_context");}
        public void callbackFence(Mc mc,long started,long tick){fences++;check(mc,false);if(tick!=77 || elapsedNanos>50000000L)throw new IllegalStateException("callback_fence");}
    }
    public static class Controller {
        public CombatThreats.HealthGuard healthGuard;
        public String safetyReason;
        public CombatThreats.Snapshot threats;
        public Request request=new Request();
        public JsonObject evidence=new JsonObject();
        public int currentTick=3;
        public Guard active;
        public int shieldRequests,effectAttempts;public boolean holding;
        public void shield(Mc mc,boolean wanted){
            shieldRequests++;active.check(mc,false);
            if(wanted&&!holding){effectAttempts++;holding=true;if(active.afterEffect!=null)active.afterEffect.run();}
            if(!wanted)holding=false;
        }
    }
    static ClassNode read(Path p)throws Exception{var n=new ClassNode();new ClassReader(Files.readAllBytes(p)).accept(n,0);return n;}
    static MethodNode method(ClassNode node,String name){return node.methods.stream().filter(m->m.name.equals(name)).findFirst().orElseThrow();}
    static long calls(MethodNode m,String owner,String name){long n=0;for(var i:m.instructions)if(i instanceof MethodInsnNode x&&x.owner.equals(owner)&&x.name.equals(name))n++;return n;}
    static int callAt(MethodNode m,String owner,String name){int n=0;for(var i:m.instructions){if(i instanceof MethodInsnNode x&&x.owner.equals(owner)&&x.name.equals(name))return n;n++;}return -1;}
    static Class<?> replay(ClassNode combat)throws Exception{
        String name=P+"CompiledObservationRecoveryReplay";
        Map<String,String> aliases=new HashMap<>();
        aliases.put(P+"BoundedCombat",name);aliases.put(P+"BoundedCombatRequest",H+"$Request");
        aliases.put(P+"ScopedCombat",H+"$Guard");aliases.put("net/minecraft/client/Minecraft",H+"$Mc");
        aliases.put("net/minecraft/client/player/LocalPlayer",H+"$Player");
        aliases.put("net/minecraft/client/multiplayer/ClientLevel",H+"$Level");
        aliases.put("java/lang/System",H+"$Clock");
        ClassWriter writer=new ClassWriter(ClassWriter.COMPUTE_MAXS);
        writer.visit(Opcodes.V21,Opcodes.ACC_PUBLIC,name,null,H+"$Controller",null);
        var remapper=new Remapper(){@Override public String map(String type){return aliases.getOrDefault(type,type);}};
        for(String selected:List.of("observationRecoveryStep","observeThreatGate","number","sampleHealth")) {
            MethodNode original=method(combat,selected);
            var dest=writer.visitMethod(Opcodes.ACC_PUBLIC|(original.access&Opcodes.ACC_STATIC),original.name,remapper.mapMethodDesc(original.desc),null,null);
            original.accept(new MethodRemapper(dest,remapper));
        }
        var init=writer.visitMethod(Opcodes.ACC_PUBLIC,"<init>","()V",null,null);init.visitCode();init.visitVarInsn(Opcodes.ALOAD,0);
        init.visitMethodInsn(Opcodes.INVOKESPECIAL,H+"$Controller","<init>","()V",false);init.visitInsn(Opcodes.RETURN);init.visitMaxs(1,1);init.visitEnd();writer.visitEnd();
        return MethodHandles.lookup().defineClass(writer.toByteArray());
    }
    static Controller controller(Class<?> type)throws Exception{
        var c=(Controller)type.getConstructor().newInstance();c.active=new Guard();c.healthGuard=new CombatThreats.HealthGuard(18);
        c.healthGuard.enableObservationRecovery();c.healthGuard.sampleSource(1,1,0,20);c.healthGuard.sampleSource(2,2,161079773L,20);
        c.threats=snapshot(3,System.nanoTime(),"minecraft:zombie","target");return c;
    }
    static CombatThreats.Snapshot snapshot(int tick,long now,String kind,String uuid){return new CombatThreats.Snapshot(List.of(new CombatThreats.Observed(15,uuid,kind,2,64,0,.3,true,true)),now,tick,false,true);}
    static BoundedCombat.Step invoke(Class<?> type,Controller c,Guard guard,long started,long tick)throws Exception{
        try{return (BoundedCombat.Step)type.getMethod("observationRecoveryStep",Mc.class,int.class,Guard.class,long.class,long.class).invoke(c,new Mc(),3,guard,started,tick);}
        catch(InvocationTargetException e){if(e.getCause() instanceof RuntimeException r)throw r;throw new AssertionError(e.getCause());}
    }
    static JsonObject observe(Class<?> type,Controller c,CombatThreats.HealthGuard.Result health)throws Exception {
        long now=System.nanoTime();var snapshot=targetSnapshot(c.currentTick,now);
        var gate=CombatThreats.evaluate(snapshot,now,c.currentTick,0,64,0,15,"target",health);
        type.getMethod("observeThreatGate",CombatThreats.Gate.class,CombatThreats.HealthGuard.Result.class).invoke(c,gate,health);
        return c.evidence.getAsJsonObject("threat_gate");
    }
    static CombatThreats.Snapshot targetSnapshot(int tick,long now){return snapshot(tick,now,"minecraft:zombie","target");}
    public static void main(String[] args)throws Exception{
        Path classes=Path.of(args[0]);var combat=read(classes.resolve(P+"BoundedCombat.class"));var helper=method(combat,"observationRecoveryStep");
        // Bytecode relations pin the real shield/freshness entry points; the replay does not substitute a production effect path.
        ok(calls(helper,P+"CombatThreats","defensiveTarget")==1,"actual fresh target gate wired");
        ok(calls(helper,P+"BoundedCombat","shield")==1,"exact existing shield entry");
        ok(calls(helper,P+"ScopedCombat","check")==1 && calls(helper,P+"ScopedCombat","callbackFence")==1,"post-effect owner/context and callback fence");
        for(var i:helper.instructions)if(i instanceof MethodInsnNode x)ok(!Set.of("startAttack","setYRot","setXRot","setYHeadRot","pick","beforeScopedMovement").contains(x.name),"helper contains no offense/aim/move call");
        var tick=method(combat,"tickCombat");
        ok(callAt(tick,P+"BoundedCombat","observationRecoveryStep")<callAt(tick,P+"BoundedCombat","safetyRetreat"),"recovery precedes forced withdrawal");
        ok(callAt(tick,P+"BoundedCombat","observationRecoveryStep")<callAt(tick,"net/minecraft/client/renderer/GameRenderer","pick"),"recovery precedes aim/pick/offense");
        ok(calls(method(combat,"bindScoped"),P+"CombatThreats$HealthGuard","enableObservationRecovery")==1,"scoped-only opt-in");
        ok(calls(method(combat,"shield"),P+"ScopedCombatDispatch","shield")==1,"real shield method still uses fenced dispatch");
        ok(calls(method(combat,"release"),P+"ScopedCombatDispatch","cleanup")==1,"real release still uses original cleanup");
        var dispatch=read(classes.resolve(P+"ScopedCombatDispatch.class"));
        ok(calls(method(dispatch,"run"),P+"ScopedCombatDispatch","check")==1,"dispatch checks before vanilla effect");
        ok(calls(method(dispatch,"packet"),P+"ScopedCombatDispatch","check")==1,"packet fence retained");
        var sourceHelper=method(combat,"sampleHealth");
        ok(calls(sourceHelper,"net/minecraft/client/multiplayer/ClientLevel","getGameTime")==1,"real source clock read");
        ok(calls(sourceHelper,P+"CombatThreats$HealthGuard","sampleSource")==1,"source bound policy call");
        ok(calls(tick,P+"BoundedCombat","sampleHealth")==1 && calls(method(combat,"beforeScopedAttack"),P+"BoundedCombat","sampleHealth")==1
            && calls(method(combat,"beforeScopedMovement"),P+"BoundedCombat","sampleHealth")==1,"decision, final attack and final movement health reads source-bound");
        var scopedClass=read(classes.resolve(P+"ScopedCombat.class"));
        ok(calls(method(scopedClass,"identity"),"net/minecraft/client/Minecraft","isPaused")==1,"original pause precondition retained");
        var type=replay(combat);var frozen=(Controller)type.getConstructor().newInstance();
        frozen.healthGuard=new CombatThreats.HealthGuard(18);frozen.healthGuard.enableObservationRecovery();
        var mc=new Mc();var sample=type.getMethod("sampleHealth",Mc.class,int.class);
        Clock.forced=0L;sample.invoke(frozen,mc,1);mc.level.tick=78;Clock.forced=160000000L;
        sample.invoke(frozen,mc,2);
        for(int i=1;i<=20;i++){Clock.forced=160000000L+i*50000000L;
            var result=(CombatThreats.HealthGuard.Result)sample.invoke(frozen,mc,2+i);
            ok(result.interrupted(),"actual compiled source read never recovers frozen world "+i);}
        ok(frozen.healthGuard.recoveryCompleted()==0 && frozen.healthGuard.diagnostics().latched(),"compiled source freeze irreversible");
        mc.level.tick=79;Clock.forced=1210000000L;
        ok(((CombatThreats.HealthGuard.Result)sample.invoke(frozen,mc,23)).interrupted(),"world unfreeze cannot revive latched action");
        ok(frozen.healthGuard.sourceDiagnostic().sourceTick()==79,"evidence reports actual game clock not action tick");
        Clock.forced=null;
        var c=controller(type);var step=invoke(type,c,c.active,System.nanoTime(),77);
        ok(step!=null && step.forward()==0 && step.terminal()==null && step.reason().equals("health_observation_recovering"),"compiled helper returns zero-forward running wait");
        ok(c.effectAttempts==1 && c.holding && c.active.fences==1,"shield effect then fence");
        ok(!c.evidence.get("observation_recovery_wait_grants_offense").getAsBoolean(),"no fabricated offense permit");
        c.threats=snapshot(3,System.nanoTime(),"minecraft:zombie","target");invoke(type,c,c.active,System.nanoTime(),77);
        ok(c.effectAttempts==1,"already-held shield not dispatched again by environment model");
        c=controller(type);c.request.wanted=false;step=invoke(type,c,c.active,System.nanoTime(),77);
        ok(step!=null && c.effectAttempts==0 && !c.holding,"no shield input without explicit request");
        c=controller(type);ok(invoke(type,c,null,System.nanoTime(),77)==null && c.effectAttempts==0,"legacy no opt-in branch");
        c=controller(type);c.safetyReason="caller_min_health";ok(invoke(type,c,c.active,System.nanoTime(),77)==null && c.effectAttempts==0,"adverse latch wins");
        c=controller(type);c.healthGuard.sampleSource(3,3,211079773L,19);ok(invoke(type,c,c.active,System.nanoTime(),77)==null && c.effectAttempts==0,"new recovery damage wins");
        for(String kind:List.of("minecraft:creeper","minecraft:enderman","minecraft:spider")){
            c=controller(type);c.threats=snapshot(3,System.nanoTime(),kind,"target");ok(invoke(type,c,c.active,System.nanoTime(),77)==null && c.effectAttempts==0 && c.safetyReason!=null,"new danger blocks shield recovery "+kind);
        }
        c=controller(type);c.threats=snapshot(3,System.nanoTime()-150000001L,"minecraft:zombie","target");
        ok(invoke(type,c,c.active,System.nanoTime(),77)==null && c.effectAttempts==0 && c.safetyReason.equals("threat_snapshot_stale"),"stale observation not relaxed");
        c=controller(type);c.threats=snapshot(3,System.nanoTime(),"minecraft:zombie","replacement");
        ok(invoke(type,c,c.active,System.nanoTime(),77)==null && c.effectAttempts==0,"target identity change refuses");
        for(String failure:List.of("owner_before","context_before","owner_during","context_during","effect_exception","deadline_after","world_tick_changed")){
            c=controller(type);final Controller held=c;
            if(failure.equals("owner_before"))c.active.owner=false;
            if(failure.equals("context_before"))c.active.context=false;
            if(failure.equals("owner_during"))c.active.afterEffect=()->held.active.owner=false;
            if(failure.equals("context_during"))c.active.afterEffect=()->held.active.context=false;
            if(failure.equals("effect_exception"))c.active.afterEffect=()->{throw new IllegalStateException("effect_unknown");};
            if(failure.equals("deadline_after"))c.active.elapsedNanos=50000001L;
            boolean failed=false;
            try{invoke(type,c,c.active,System.nanoTime()-(failure.equals("deadline_after")?50000001L:0),failure.equals("world_tick_changed")?78:77);}catch(IllegalStateException expected){failed=true;}
            ok(failed,"changed context/effect cannot return wait: "+failure);
            ok(c.effectAttempts<=1,"no automatic replay: "+failure);
            ok(!c.evidence.has("observation_recovery_zero_forward"),"no successful wait evidence after failure: "+failure);
        }
        c=controller(type);
        var health=c.healthGuard.sampleSource(3,3,211079773L,20);var observed=observe(type,c,health);
        ok(observed.get("health_value_semantics").getAsString().equals("current_recovery_sample"),"recovery observation is not a latch");
        ok(observed.get("health_sample_tick").getAsInt()==3,"recovery current sample tick");
        for(int i=2;i<=20;i++)health=c.healthGuard.sampleSource(2+i,2+i,161079773L+i*50000000L,20);
        c.currentTick=22;observed=observe(type,c,health);
        ok(observed.get("health_value_semantics").getAsString().equals("current_sample"),"completed recovery current healthy sample");
        health=c.healthGuard.sampleSource(23,23,1211079773L,18);
        c.currentTick=24;health=c.healthGuard.sampleSource(24,24,1261079773L,20);observed=observe(type,c,health);
        ok(observed.get("health_value_semantics").getAsString().equals("latched_trigger_metrics"),"later adverse event is really latched");
        ok(observed.get("health_sample_tick").getAsInt()==23,"later damage latch never inherits original gap tick");
        ok(observed.getAsJsonObject("health_diagnostics").getAsJsonObject("latch_trigger").get("sample_tick").getAsInt()==23,"outer and inner trigger evidence agree");
        JsonObject out=new JsonObject();out.addProperty("status","passed");out.addProperty("assertions",assertions);
        out.addProperty("scope","Unchanged compiled observationRecoveryStep/observeThreatGate/number/sampleHealth instruction streams with type aliases; actual production pure health/threat/Step classes; explicit Minecraft/shield/owner doubles; bytecode wiring checks for original effect and cleanup gates");
        out.addProperty("game_loader_world_network","NOT_RUN");Files.writeString(Path.of(args[1]),new GsonBuilder().setPrettyPrinting().create().toJson(out));System.out.println(out);
    }
}

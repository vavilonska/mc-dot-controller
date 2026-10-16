package io.github.campione01.mineclientbridge;

import com.google.gson.*;
import java.lang.invoke.MethodHandles;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import org.objectweb.asm.*;
import org.objectweb.asm.commons.*;
import org.objectweb.asm.tree.*;

/** Replays real compiled movement admission and frame fences with explicit engine/owner doubles. */
public final class ScopedRetreatControllerChecks {
    private static final String P="io/github/campione01/mineclientbridge/",H=P+"ScopedRetreatControllerChecks";
    private static int assertions,scenarios;
    private static Class<?> replayFrame;
    private static void ok(boolean condition,String message) {assertions++;if(!condition)throw new AssertionError(message);}
    public static class Clock {public static long now=50_000_000L;public static long nanoTime(){return now;}}
    public static class Vec {
        public final double x,y,z;
        public Vec(double x,double y,double z){this.x=x;this.y=y;this.z=z;}
        @Override public boolean equals(Object other){return other instanceof Vec v&&v.x==x&&v.y==y&&v.z==z;}
        @Override public int hashCode(){return Objects.hash(x,y,z);}
    }
    public static class Entity {
        public Vec position=new Vec(0,64,5);
        public Vec position(){return position;}
    }
    public static class Living extends Entity { }
    public static class Player extends Living {
        public Vec velocity=new Vec(0,0,0);public float yaw=180,pitch=65,health=20;public boolean ground=true;
        Player(){position=new Vec(0,64,0);}
        public double getX(){return position.x;}public double getY(){return position.y;}public double getZ(){return position.z;}
        public float getYRot(){return yaw;}public float getXRot(){return pitch;}public float getHealth(){return health;}
        public boolean onGround(){return ground;}public Vec getDeltaMovement(){return velocity;}
        public boolean isUsingItem(){return false;}public boolean isBlocking(){return false;}
    }
    public static class Level {public long tick=88;public long getGameTime(){return tick;}}
    public static class Mc {public Player player=new Player();public Level level=new Level();}
    public static class Request {public int targetId(){return 1;}public String targetUuid(){return "target";}}
    public static class Guard {
        public Living target=new Living();public boolean owner=true;public int checks,fences;public Runnable hook;
        public void check(Mc mc,boolean alive){checks++;if(hook!=null)hook.run();require(owner,"owner");}
        public void callbackFence(Mc mc,long started,long tick){fences++;require(owner,"owner");require(Clock.now-started>=0&&Clock.now-started<=50_000_000L&&mc.level.tick==tick,"existing_callback_50ms_same_tick");}
        public static void require(boolean valid,String reason){if(!valid)throw new IllegalStateException(reason);}
    }
    public static class Owner {
        public static Guard active;
        public static Guard scopedCombat(Controller combat){return active;}
        public static boolean ownsCombat(Controller combat){return active.owner;}
    }
    private static final FlatStepCorridor.Cell AIR=new FlatStepCorridor.Cell(FlatStepCorridor.Availability.LOADED,"minecraft:air",true,true,false,"minecraft:empty",false);
    private static final FlatStepCorridor.Cell SOLID=new FlatStepCorridor.Cell(FlatStepCorridor.Availability.LOADED,"minecraft:stone",true,false,true,"minecraft:empty",false);
    private static final FlatStepCorridor.Cell UNKNOWN=new FlatStepCorridor.Cell(FlatStepCorridor.Availability.UNKNOWN,null,false,false,false,null,false);
    public static class Controller {
        public int currentTick=2,retreatStartTick=1;public long retreatStartNanos=0;
        public float expectedYaw=180,expectedPitch=65;public double retreatDistance;
        public String safetyReason="caller_min_health";
        public CombatDetour.Point retreatGoal=new CombatDetour.Point(0,-3);
        public CombatThreats.HealthGuard healthGuard=new CombatThreats.HealthGuard(18);
        public Request request=new Request();public JsonObject evidence=new JsonObject();
        public CombatThreats.Snapshot threats;
        public CombatRetreatWindow.Metrics retreatWindowMetrics;public FlatStepCorridor.Result lastRouteTerrain;
        public CombatRetreatDiagnostics pendingRetreatDiagnostics;public JsonObject pendingRetreatEvidence;
        public boolean pendingRetreatPlan,shieldOwned,frameWasCleared;
        public String lastDecisionPhase;
        public int captures,windows,nearChecks,cacheGeneration;
        public boolean farBlocked,unknown,mutateDuringCapture;public long firstWindowNanos;
        public long tickPreludeNanos,tickRetreatNanos,tickObservationNanos;
        public Runnable windowHook,nearHook;
        public Controller(){healthGuard.enableObservationRecovery();healthGuard.sampleSource(1,87,0,20);threats=snapshot(1,0,5);}
        public void captureThreats(Mc mc,int tick){captures++;cacheGeneration++;threats=snapshot(tick,Clock.now,Owner.active.target.position.z);if(mutateDuringCapture)mc.player.position=new Vec(.1,64,0);}
        public static CombatDetour.Point point(Vec v){return new CombatDetour.Point(v.x,v.z);}
        public CombatDetour.EdgeResult retreatWindow(Mc mc,CombatDetour.Point a,CombatDetour.Point b){
            windows++;if(windows==1)Clock.now+=firstWindowNanos;if(windowHook!=null)windowHook.run();
            FlatStepCorridor.CellSource cells=(x,y,z)->z==-3&&unknown?UNKNOWN:z==-3&&y==64&&farBlocked?SOLID:y==63?SOLID:AIR;
            return CombatRetreatWindow.check(threats,Clock.now,currentTick,new FlatStepCorridor.Pose(a.x(),64,a.z(),true,mc.player.yaw),b,0,64,0,cells,List.of()).edge();
        }
        public CombatDetour.EdgeResult liveRouteEdge(Mc mc,CombatDetour.Point a,CombatDetour.Point b,boolean escape){nearChecks++;if(nearHook!=null)nearHook.run();return new CombatDetour.EdgeResult(true,1,"clear");}
        public JsonObject scopedRetreatEvidence(ScopedRetreatPlanning.Checked checked,String scope,boolean proposal){
            JsonObject data=new JsonObject();data.addProperty("complete",checked.clear());data.addProperty("windows",checked.windows());
            data.addProperty("hard_failure",checked.hardFailure());data.addProperty("movement_authorized",false);data.addProperty("soft",checked.softBudgetExceeded());return data;
        }
        public BoundedCombat.Step tickCombat(Mc mc,int tick) {
            try {
                var field=getClass().getField("pendingScopedRetreatFrame");frameWasCleared=field.get(this)==null;
                long originalStart=Clock.now;Clock.now+=tickPreludeNanos;
                var ctor=replayFrame.getDeclaredConstructor(getClass(),Mc.class,Guard.class,long.class,long.class);ctor.setAccessible(true);
                Object frame=ctor.newInstance(this,mc,Owner.active,originalStart,mc.level.tick);field.set(this,frame);
                threats=snapshot(tick,Clock.now,5);
                var bind=replayFrame.getDeclaredMethod("bind",Mc.class,CombatThreats.Snapshot.class);bind.setAccessible(true);bind.invoke(frame,mc,threats);
                Clock.now+=tickRetreatNanos;
                return new BoundedCombat.Step(1,null,"synthetic_full_route_complete");
            } catch(InvocationTargetException failure) {throw (RuntimeException)failure.getCause();}
            catch(ReflectiveOperationException failure) {throw new AssertionError(failure);}
        }
        public Living target(Mc mc){return Owner.active.target;}
        public void observeDecisionMotion(Mc mc,Living target,String phase){Clock.now+=tickObservationNanos;}
        public static void number(JsonObject object,String name,double value){object.addProperty(name,value);}
    }
    private static CombatThreats.Snapshot snapshot(int tick,long ns,double z){return new CombatThreats.Snapshot(List.of(new CombatThreats.Observed(1,"target","minecraft:zombie",0,64,z,.3,true,true)),ns,tick,false,true);}
    private static ClassNode read(Path file)throws Exception{var node=new ClassNode();new ClassReader(Files.readAllBytes(file)).accept(node,0);return node;}
    private static MethodNode method(ClassNode type,String name){return type.methods.stream().filter(m->m.name.equals(name)).findFirst().orElseThrow();}
    private static List<MethodInsnNode> calls(MethodNode method){List<MethodInsnNode> calls=new ArrayList<>();for(var i:method.instructions)if(i instanceof MethodInsnNode m)calls.add(m);return calls;}
    private static long count(MethodNode method,String owner,String name){return calls(method).stream().filter(m->m.owner.equals(owner)&&m.name.equals(name)).count();}
    private static Class<?> replay(Path classes,ClassNode combat)throws Exception {
        String replay=P+"CompiledRetreatMovementReplay",frame=P+"CompiledRetreatFrameReplay";
        Map<String,String> aliases=new HashMap<>();
        aliases.put(P+"BoundedCombat",replay);aliases.put(P+"BoundedCombat$ScopedRetreatFrame",frame);
        aliases.put(P+"ScopedCombat",H+"$Guard");aliases.put(P+"ClientActions",H+"$Owner");aliases.put(P+"BoundedCombatRequest",H+"$Request");
        aliases.put("net/minecraft/client/Minecraft",H+"$Mc");aliases.put("net/minecraft/client/player/LocalPlayer",H+"$Player");
        aliases.put("net/minecraft/client/multiplayer/ClientLevel",H+"$Level");aliases.put("net/minecraft/world/entity/Entity",H+"$Entity");
        aliases.put("net/minecraft/world/entity/LivingEntity",H+"$Living");aliases.put("net/minecraft/world/phys/Vec3",H+"$Vec");
        aliases.put("java/lang/System",H+"$Clock");
        Remapper remapper=new Remapper(){@Override public String map(String type){return aliases.getOrDefault(type,type);}
            @Override public String mapMethodName(String owner,String name,String desc){return name;}};
        ClassWriter writer=new ClassWriter(ClassWriter.COMPUTE_MAXS);
        writer.visit(Opcodes.V21,Opcodes.ACC_PUBLIC,replay,null,H+"$Controller",null);
        writer.visitField(Opcodes.ACC_PUBLIC,"pendingScopedRetreatFrame","L"+frame+";",null,null).visitEnd();
        for(String methodName:List.of("beforeScopedMovement","tick","sampleHealth")) {
        var original=method(combat,methodName);
        original.accept(new MethodRemapper(writer.visitMethod(Opcodes.ACC_PUBLIC,original.name,remapper.mapMethodDesc(original.desc),null,null),remapper){
            @Override public void visitMethodInsn(int opcode,String owner,String name,String descriptor,boolean itf) {
                // The explicit owner double accepts the public controller base type.
                if(owner.equals(P+"ClientActions")&&name.equals("scopedCombat"))descriptor="(L"+H+"$Controller;)L"+P+"ScopedCombat;";
                if(owner.equals(P+"ClientActions")&&name.equals("ownsCombat"))descriptor="(L"+H+"$Controller;)Z";
                super.visitMethodInsn(opcode,owner,name,descriptor,itf);
            }
        });
        }
        // The production lambda contains the exact full-window callback and final frame hook.
        for(var lambda:combat.methods)if(lambda.name.startsWith("lambda$beforeScopedMovement$"))
            lambda.accept(new MethodRemapper(writer.visitMethod(lambda.access,lambda.name,remapper.mapMethodDesc(lambda.desc),null,null),remapper));
        var init=writer.visitMethod(Opcodes.ACC_PUBLIC,"<init>","()V",null,null);init.visitCode();init.visitVarInsn(Opcodes.ALOAD,0);
        init.visitMethodInsn(Opcodes.INVOKESPECIAL,H+"$Controller","<init>","()V",false);init.visitInsn(Opcodes.RETURN);init.visitMaxs(1,1);init.visitEnd();writer.visitEnd();
        Class<?> replayType=MethodHandles.lookup().defineClass(writer.toByteArray());
        ClassWriter frameWriter=new ClassWriter(ClassWriter.COMPUTE_MAXS);
        new ClassReader(Files.readAllBytes(classes.resolve(P+"BoundedCombat$ScopedRetreatFrame.class"))).accept(new ClassRemapper(frameWriter,remapper),0);
        replayFrame=MethodHandles.lookup().defineClass(frameWriter.toByteArray());
        return replayType;
    }
    private static Controller controller(Class<?> type)throws Exception{Clock.now=50_000_000L;Owner.active=new Guard();return (Controller)type.getConstructor().newInstance();}
    private static void invoke(Class<?> type,Controller controller,Mc mc,float forward)throws Exception{
        try{type.getMethod("beforeScopedMovement",Mc.class,float.class).invoke(controller,mc,forward);}
        catch(InvocationTargetException e){if(e.getCause() instanceof RuntimeException failure)throw failure;throw new AssertionError(e.getCause());}
    }
    private static boolean permit(Controller controller){return controller.evidence.has("scoped_retreat_effect_validation")&&controller.evidence.getAsJsonObject("scoped_retreat_effect_validation").get("movement_authorized").getAsBoolean();}
    private static BoundedCombat.Step invokeTick(Class<?> type,Controller controller,Mc mc)throws Exception {
        try{return (BoundedCombat.Step)type.getMethod("tick",Mc.class,int.class).invoke(controller,mc,2);}
        catch(InvocationTargetException failure){if(failure.getCause() instanceof RuntimeException r)throw r;throw new AssertionError(failure.getCause());}
    }
    private static AbstractInsnNode previousCode(AbstractInsnNode node) {do{node=node.getPrevious();}while(node!=null&&node.getOpcode()<0);return node;}
    public static void main(String[] args)throws Exception {
        Path classes=Path.of(args[0]);var combat=read(classes.resolve(P+"BoundedCombat.class"));var before=method(combat,"beforeScopedMovement");
        scenarios++;
        ok(count(before,P+"BoundedCombat","captureThreats")==1,"real final callback captures fresh threats/cache");
        ok(count(before,P+"ScopedRetreatPlanning","validateAll")==1,"real final callback full remaining validation");
        ok(count(before,P+"BoundedCombat","liveRouteEdge")==1,"exact-heading .65m edge retained after full validation");
        var ordered=calls(before);int capture=-1,validate=-1,edge=-1;
        for(int i=0;i<ordered.size();i++){var c=ordered.get(i);if(c.name.equals("captureThreats"))capture=i;if(c.name.equals("validateAll"))validate=i;if(c.name.equals("liveRouteEdge"))edge=i;}
        ok(capture<validate&&validate<edge,"capture then full route then actual heading");
        var owner=read(classes.resolve(P+"ClientActions.class"));var input=method(owner,"input");boolean afterPermit=false;
        for(var i:input.instructions) {
            if(i instanceof MethodInsnNode c&&c.owner.equals(P+"BoundedCombat")&&c.name.equals("beforeScopedMovement"))afterPermit=true;
            if(afterPermit&&i instanceof MethodInsnNode c)ok(!(c.owner.equals(P+"ScopedCombat")&&c.name.equals("check")),"no mutable scoped guard after final permit");
            if(afterPermit&&i instanceof FieldInsnNode f&&f.name.equals("forwardImpulse")&&f.getOpcode()==Opcodes.PUTFIELD)break;
        }
        ok(afterPermit,"actual ClientActions invokes final callback");
        var safety=method(combat,"safetyRetreat");ok(count(safety,P+"BoundedCombat","scopedSafetyRetreat")==1,"scoped-only branch wired");
        ok(count(safety,P+"CombatRetreatPolicy","plan")==1,"legacy planner retained");
        var scoped=method(combat,"scopedSafetyRetreat");ok(count(scoped,P+"ScopedRetreatPlanning$Cursor","next")==1,"one cursor proposal per scoped tick");
        ok(count(scoped,P+"CombatRetreatPolicy","plan")==0,"scoped branch cannot fall back to legacy budget retry");
        boolean originalFrameClock=false;
        for(var i:scoped.instructions)if(i instanceof MethodInsnNode m&&m.owner.equals(P+"BoundedCombat$ScopedRetreatFrame")&&m.name.equals("<init>")) {
            var last=previousCode(i);var prior=previousCode(last);
            originalFrameClock=last instanceof VarInsnNode a&&a.getOpcode()==Opcodes.LLOAD&&a.var==5
                    &&prior instanceof VarInsnNode b&&b.getOpcode()==Opcodes.LLOAD&&b.var==3;
        }
        ok(originalFrameClock,"scope frame uses original callbackStarted/gameTick parameters, not a new budget");
        var tickMethod=method(combat,"tick");int observeAt=-1,finalFenceAt=-1,index=0;
        for(var i:tickMethod.instructions){if(i instanceof MethodInsnNode m){if(m.name.equals("observeDecisionMotion"))observeAt=index;
            if(m.owner.equals(P+"BoundedCombat$ScopedRetreatFrame")&&m.name.equals("check"))finalFenceAt=index;}index++;}
        ok(finalFenceAt>observeAt&&observeAt>=0,"same frame final check follows outer tick observations");
        Class<?> type=replay(classes,combat);
        scenarios++;var controller=controller(type);var mc=new Mc();controller.firstWindowNanos=15_439_656L;
        invoke(type,controller,mc,1);
        ok(permit(controller),"real callback authorizes only completed fresh full-route check");
        ok(controller.captures==1&&controller.cacheGeneration==1,"fresh per-callback capture");
        ok(controller.windows==5&&controller.nearChecks==1,"all five windows plus exact-heading window");
        ok(controller.evidence.getAsJsonObject("scoped_retreat_effect_validation").get("soft").getAsBoolean(),"cold 15ms remains diagnostic");
        scenarios++;controller=controller(type);mc=new Mc();controller.farBlocked=true;
        boolean refused=false;try{invoke(type,controller,mc,1);}catch(RuntimeException expected){refused=true;}
        ok(refused&&!permit(controller)&&controller.windows>1&&controller.nearChecks==0,"far obstacle refuses before actual input permission");
        scenarios++;controller=controller(type);mc=new Mc();controller.unknown=true;
        refused=false;try{invoke(type,controller,mc,1);}catch(RuntimeException expected){refused=true;}
        ok(refused&&!permit(controller),"unknown full-route terrain refuses without retry");
        scenarios++;
        for(String change:List.of("capture_pose","window_pose","window_target","window_velocity","window_yaw","window_tick","window_owner","window_deadline","near_pose","near_owner")) {
            controller=controller(type);mc=new Mc();final Controller held=controller;final Mc engine=mc;final Guard guard=Owner.active;
            Runnable mutation=()->{
                if(change.endsWith("pose"))engine.player.position=new Vec(.1,64,0);
                else if(change.endsWith("target"))guard.target.position=new Vec(0,64,5.1);
                else if(change.endsWith("velocity"))engine.player.velocity=new Vec(.1,0,0);
                else if(change.endsWith("yaw"))engine.player.yaw=179;
                else if(change.endsWith("tick"))engine.level.tick++;
                else if(change.endsWith("owner"))guard.owner=false;
                else if(change.endsWith("deadline"))Clock.now+=50_000_001L;
            };
            if(change.startsWith("capture"))controller.mutateDuringCapture=true;
            else if(change.startsWith("window"))controller.windowHook=mutation;
            else controller.nearHook=mutation;
            refused=false;try{invoke(type,controller,mc,1);}catch(RuntimeException expected){refused=true;}
            ok(refused&&!permit(controller),"mutating read/effect hook never inherits permit: "+change);
            ok(controller.captures==1,"no hidden second capture/retry: "+change);
        }
        scenarios++;controller=controller(type);mc=new Mc();controller.firstWindowNanos=50_000_001L;
        refused=false;try{invoke(type,controller,mc,1);}catch(RuntimeException expected){refused=true;}
        ok(refused&&!permit(controller)&&controller.windows==1,"real callback hard 50ms cannot be bypassed by clear result");
        controller=controller(type);mc=new Mc();invoke(type,controller,mc,0);ok(controller.captures==0&&controller.windows==0&&!permit(controller),"zero-forward wait creates no movement proof");
        scenarios++;
        for(long[] cost:new long[][]{{10_000_000L,10_000_000L,10_000_000L},{30_000_000L,25_000_000L,0},{10_000_000L,10_000_000L,35_000_001L}}) {
            controller=controller(type);mc=new Mc();controller.tickPreludeNanos=cost[0];controller.tickRetreatNanos=cost[1];controller.tickObservationNanos=cost[2];
            refused=false;try{invokeTick(type,controller,mc);}catch(RuntimeException expected){refused=true;}
            ok(refused==(cost[0]+cost[1]+cost[2]>50_000_000L),"single original 50ms across prelude, retreat and final JSON observations");
            ok(controller.frameWasCleared,"tick entry clears previous frame");
            ok(controller.evidence.has("decision_pose"),"final fence really follows complete outer decision observation");
        }
        JsonObject report=new JsonObject();report.addProperty("status","passed");report.addProperty("assertions",assertions);report.addProperty("scenarios",scenarios);
        report.addProperty("scope","Actual compiled beforeScopedMovement, its lambdas, outer tick, and complete ScopedRetreatFrame instruction streams remapped to explicit engine/owner/clock doubles; production pure validators; compiled original-start forwarding and ClientActions dispatch ordering");
        report.addProperty("engine_limit","captureThreats, retreatWindow readers, liveRouteEdge, tickCombat decision preparation and selected evidence construction use explicit doubles; no live physics, game initialization, loader or network");
        Files.writeString(Path.of(args[1]),new GsonBuilder().setPrettyPrinting().create().toJson(report));System.out.println(report);
    }
}

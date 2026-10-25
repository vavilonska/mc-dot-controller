package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.lang.reflect.Field;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicReference;
import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.multiplayer.MultiPlayerGameMode;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.world.phys.Vec3;

/** Real production native control; controlled dependency callbacks, no game or geometry proof. */
public final class ManagedWaterOwnerProbe {
    private static int checks,scenarios;
    private static Minecraft mc;
    private static ManagedNavigationLease.Request request;
    private static final Vec3 FORWARD=new Vec3(0,0,1);

    private static void check(boolean okay,String label){checks++;if(!okay)throw new AssertionError(label);}
    private static Field field(Class<?> type,String name)throws Exception {Field f=type.getDeclaredField(name);f.setAccessible(true);return f;}
    private static Object read(Object target,Class<?> type,String name)throws Exception{return field(type,name).get(target);}
    private static ManagedNavigationLease leases()throws Exception {
        return (ManagedNavigationLease)read(null,NativeManagedNavigation.class,"LEASES");
    }
    private static ManagedNavigationLease.Entry entry()throws Exception{return leases().active();}
    private static JsonObject status(){
        JsonObject value=NativeManagedNavigation.status();
        check(value.keySet().equals(java.util.Set.of("managed_navigation_schema_version","input_owned","unknown_outcome_quarantined","execution_authority","no_auto_resume",
            "operation_id","owner_id","owner_generation","job_id","action_session","world_generation","player_uuid","dimension","state","reason","start_attempted","stop_attempted",
            "cancel_accepted","goal_reached","settings_restored","control_released","idle_samples","admission_tick","source_tick","remaining_ms","unloaded_terrain_certified","goal_x","goal_y","goal_z","external_controller")),
            "actual native owner status preserves exact closed Resident wire fields");
        return value;
    }
    /** Counters are private diagnostics, intentionally absent from the closed public wire. */
    private static JsonObject dry()throws Exception{
        Object data=read(null,NativeManagedNavigation.class,"active");JsonObject value=new JsonObject();
        value.addProperty("checks",(Long)read(data,data.getClass(),"dryChecks"));
        value.addProperty("authorized_acceleration_inputs",(Long)read(data,data.getClass(),"dryTravelInputs"));
        value.addProperty("authorized_jump_inputs",(Long)read(data,data.getClass(),"dryJumpInputs"));
        value.addProperty("refusal",(String)read(data,data.getClass(),"dryRefusal"));return value;
    }
    private static Object input(){return baritone.api.BaritoneAPI.provider.primary.input;}
    private static boolean rejected(){return ManagedNavigationInputPolicy.reject(input(),"MOVE_FORWARD");}

    /** Reflection only clears test-static isolation; Data itself uses its real production constructor. */
    @SuppressWarnings("unchecked")
    private static void reset()throws Exception {
        scenarios++;
        field(NativeManagedNavigation.class,"active").set(null,null);
        ((Map<?,?>)read(null,NativeManagedNavigation.class,"history")).clear();
        ManagedNavigationLease leases=leases();
        field(ManagedNavigationLease.class,"active").set(leases,null);
        ((Map<?,?>)read(leases,ManagedNavigationLease.class,"history")).clear();
        field(ManagedNavigationInputPolicy.class,"owner").set(null,null);
        ((AtomicReference<String>)read(null,ManagedNavigationInputPolicy.class,"blocked")).set(null);
        ManagedNavigationInputPolicy.openAdmission();
        OwnerHarnessState.reset();
        baritone.api.BaritoneAPI.provider=new baritone.BaritoneProvider();
        mc=new Minecraft();mc.level=new ClientLevel();mc.player=new LocalPlayer(mc.level);mc.gameMode=new MultiPlayerGameMode();
        Minecraft.install(mc);request=makeRequest(mc.level.tick,System.nanoTime());
    }
    private static ManagedNavigationLease.Request makeRequest(long sourceTick,long sourceNano){
        var identity=new ExternalNavigationLease.Request(String.format("%032x",scenarios),"b".repeat(32),1,"test-job",
            OwnerHarnessState.session,mc.level.world,mc.player.uuid.toString(),"minecraft:overworld",sourceTick,sourceNano,120000);
        return new ManagedNavigationLease.Request(identity,8,70,0,20,10);
    }
    private static void running()throws Exception {
        reset();JsonObject answer=NativeManagedNavigation.start(request);
        check(answer.get("state").getAsString().equals("routing"),"real start reaches routing");
        check(OwnerHarnessState.startCalls==1&&entry().startAttempted,"start attempted exactly once");
    }
    private static void expectRejectedStart(String label)throws Exception {
        boolean refused=false;
        try{NativeManagedNavigation.start(request);}catch(ClientActionRequest.Rejected expected){refused=true;}
        check(refused,label);check(OwnerHarnessState.startCalls==0,label+" has no start effect");
        check(leases().active()==null,label+" never claims ownership");
    }
    private static void lateMutation(Runnable mutation,String label)throws Exception {
        OwnerHarnessState.onDryUnchanged=mutation;
        check(rejected(),label+" refuses nonneutral input");
        check(entry().phase==ManagedNavigationLease.Phase.STOPPING,label+" requests stop");
        check(dry().get("refusal").getAsString().equals("managed_navigation_dry_final_owner_or_context"),label+" truthful final-fence reason");
    }
    private static void unknownStatus(String label){
        JsonObject j=status();
        check(j.get("state").getAsString().equals("unknown"),label+" state unknown");
        check(j.get("unknown_outcome_quarantined").getAsBoolean(),label+" quarantine reported");
        check(j.get("input_owned").getAsBoolean()&&!j.get("control_released").getAsBoolean(),label+" ownership retained");
        check(!j.get("execution_authority").getAsBoolean()&&j.get("no_auto_resume").getAsBoolean(),label+" no invented authority or resume");
    }
    public static void main(String[] args)throws Exception {
        running();
        JsonObject nativeStatusRow=new JsonObject();nativeStatusRow.add("status",status());nativeStatusRow.add("command",residentCommand());
        long before=dry().get("checks").getAsLong();
        check(!rejected(),"one ordinary setter input authorized");
        check(dry().get("checks").getAsLong()==before+1,"one authorization records one dry proof");
        check(NativeManagedNavigation.dryTravelIntent(mc.player,FORWARD)==FORWARD,"accepted immutable travel argument preserved");
        check(!NativeManagedNavigation.refuseDryAcceleration(mc.player,.101f,FORWARD),"rounded acceleration ceiling admitted");
        check(!NativeManagedNavigation.refuseDryJump(mc.player,.42f,mc.player.delta),"ordinary exact jump admitted");
        check(dry().get("authorized_acceleration_inputs").getAsInt()==1&&dry().get("authorized_jump_inputs").getAsInt()==1,"truthful authorized counters");
        check(!status().get("goal_reached").getAsBoolean()&&!status().get("control_released").getAsBoolean(),"routing is not reported as success");

        running();lateMutation(()->OwnerHarnessState.revision++,"late owner revision");
        running();LocalPlayer original=mc.player;LocalPlayer replacement=new LocalPlayer(mc.level);replacement.uuid=original.uuid;
        final LocalPlayer replacementForLate=replacement;
        lateMutation(()->mc.player=replacementForLate,"late equal-UUID player replacement");
        running();ClientLevel replacementWorld=new ClientLevel();lateMutation(()->mc.level=replacementWorld,"late equal-generation world replacement");
        running();lateMutation(()->mc.player.uuid=UUID.fromString(mc.player.uuid.toString()),"late equal-value UUID reference replacement");
        running();lateMutation(()->mc.gameMode=new MultiPlayerGameMode(),"late game-mode owner replacement");
        running();lateMutation(()->OwnerHarnessState.session="replacement-session","late session replacement");
        running();lateMutation(ManagedNavigationInputPolicy::closeAdmission,"late bridge admission close");

        reset();request=makeRequest(mc.level.tick,System.nanoTime()-1_000_000_000L);expectRejectedStart("stale original source clock");
        reset();request=makeRequest(mc.level.tick-6,System.nanoTime());expectRejectedStart("stale original source tick");
        reset();request=makeRequest(mc.level.tick,System.nanoTime()-700_000_000L);
        OwnerHarnessState.onDryUnchanged=ManagedWaterOwnerProbe::waitUntilSourceStale;
        expectRejectedStart("original clock expires during admission dry reconciliation");
        reset();request=makeRequest(mc.level.tick,System.nanoTime()-700_000_000L);int[] reconciliations={0};
        OwnerHarnessState.onDryUnchanged=()->{if(++reconciliations[0]==2)waitUntilSourceStale();};
        NativeManagedNavigation.start(request);
        check(OwnerHarnessState.startCalls==0,"original clock expires during pre-start dry reconciliation without start effect");
        unknownStatus("pre-start source expiry remains conservatively quarantined");
        running();OwnerHarnessState.staleDry=true;
        check(rejected(),"stale final dry snapshot refused");
        check(dry().get("refusal").getAsString().equals("managed_navigation_dry_snapshot_stale"),"stale snapshot reason preserved");
        running();field(ManagedNavigationLease.Entry.class,"deadline").setLong(entry(),System.nanoTime()-1);
        check(rejected(),"expired routing deadline refuses input");
        check(entry().phase==ManagedNavigationLease.Phase.STOPPING,"deadline input refusal requests stop");
        running();leases().requestStop(entry(),"test-stop",System.nanoTime());int captures=OwnerHarnessState.dryCaptures;
        check(rejected()&&OwnerHarnessState.dryCaptures==captures,"STOPPING refuses before another dry proof");
        running();NativeManagedNavigation.contextLost();captures=OwnerHarnessState.dryCaptures;
        check(rejected()&&OwnerHarnessState.dryCaptures==captures,"UNKNOWN quarantines without another proof");unknownStatus("context lost");

        running();boolean[] nested={false};
        OwnerHarnessState.onDryUnchanged=()->nested[0]=rejected();
        check(rejected()&&nested[0],"nested check poisons both inner and outer input");
        OwnerHarnessState.onDryUnchanged=OwnerHarnessState.NOTHING;
        check(rejected(),"reentry poison persists");
        check(dry().get("refusal").getAsString().contains("reentrant")||entry().reason.contains("reentrant"),"reentry cause retained in lease or dry status");

        running();check(NativeManagedNavigation.refuseDryJump(mc.player,.43f,mc.player.delta),"boosted jump power refused");
        check(dry().get("authorized_jump_inputs").getAsInt()==0,"boosted jump not counted");
        running();check(NativeManagedNavigation.refuseDryJump(mc.player,Float.NaN,mc.player.delta),"nonfinite jump power refused");
        running();check(NativeManagedNavigation.refuseDryJump(mc.player,.42f,new Vec3(0,0,0)),"equal-value replaced original motion refused");
        running();Vec3 oldMotion=mc.player.delta;
        OwnerHarnessState.onDryUnchanged=()->mc.player.delta=new Vec3(.01,0,0);
        check(NativeManagedNavigation.refuseDryJump(mc.player,.42f,oldMotion),"motion argument replacement after final callback refused");
        check(dry().get("authorized_jump_inputs").getAsInt()==0,"replaced motion not counted");
        running();OwnerHarnessState.onMotionRead=()->{if(OwnerHarnessState.motionReads==2)OwnerHarnessState.revision++;};
        check(NativeManagedNavigation.refuseDryJump(mc.player,.42f,mc.player.delta),"owner rechecked after final local motion getter");
        check(dry().get("authorized_jump_inputs").getAsInt()==0,"late motion-getter owner change not counted");
        running();mc.player.input.jumping=false;
        check(!NativeManagedNavigation.refuseDryJump(mc.player,.42f,mc.player.delta),"already-cleared jump flag retains captured ordinary power");
        check(Math.abs(OwnerHarnessState.pendingJump-.42)<1e-6&&OwnerHarnessState.requiredStep,"latched pendingJump reaches world adapter independent of input flag");

        for(float amount:new float[]{.10101f,-.01f,Float.NaN,Float.POSITIVE_INFINITY}){
            running();captures=OwnerHarnessState.dryCaptures;
            check(NativeManagedNavigation.refuseDryAcceleration(mc.player,amount,FORWARD),"invalid acceleration bound "+amount);
            check(OwnerHarnessState.dryCaptures==captures&&dry().get("authorized_acceleration_inputs").getAsInt()==0,"invalid acceleration rejected before proof/counter");
        }
        running();check(!NativeManagedNavigation.refuseDryAcceleration(mc.player,.02f,FORWARD),"ordinary airborne acceleration admitted");
        running();check(NativeManagedNavigation.refuseDryAcceleration(mc.player,.1f,null),"missing acceleration argument refused");
        running();check(NativeManagedNavigation.refuseDryAcceleration(mc.player,.1f,new Vec3Child()),"nonconcrete acceleration vector refused");

        running();original=mc.player;replacement=new LocalPlayer(mc.level);replacement.input.forwardImpulse=.8f;replacement.input.jumping=true;
        final LocalPlayer replacementForCleanup=replacement;
        OwnerHarnessState.onDryUnchanged=()->mc.player=replacementForCleanup;
        check(!NativeManagedNavigation.neutralizeDryInput(original,FORWARD),"cleanup cannot acquire replacement player input");
        check(replacement.input.forwardImpulse==.8f&&replacement.input.jumping,"replacement input untouched by failed cleanup");
        running();original=mc.player;replacement=new LocalPlayer(mc.level);replacement.input.leftImpulse=.7f;
        final LocalPlayer replacementForTravel=replacement;
        OwnerHarnessState.onDryUnchanged=()->mc.player=replacementForTravel;
        check(NativeManagedNavigation.dryTravelIntent(original,FORWARD)==Vec3.ZERO,"old travel argument refused after replacement");
        check(replacement.input.leftImpulse==.7f&&FORWARD.z==1,"replacement input and old immutable argument unmodified");
        running();mc.player.input.forwardImpulse=.6f;OwnerHarnessState.staleDry=true;
        check(NativeManagedNavigation.neutralizeDryInput(mc.player,FORWARD),"same-owner unsafe call permits cleanup-only neutral write");
        check(mc.player.input.forwardImpulse==.6f,"guard itself grants cleanup without writing input");

        reset();OwnerHarnessState.throwStart=true;NativeManagedNavigation.start(request);unknownStatus("uncertain start");
        NativeManagedNavigation.start(request);NativeManagedNavigation.cancel(request);NativeManagedNavigation.tick(mc);
        check(OwnerHarnessState.startCalls==1&&OwnerHarnessState.cancelCalls==0,"uncertain start never retried or cancelled under lost authority");
        running();OwnerHarnessState.throwCancel=true;NativeManagedNavigation.cancel(request);unknownStatus("uncertain cancel");
        NativeManagedNavigation.cancel(request);NativeManagedNavigation.start(request);NativeManagedNavigation.tick(mc);
        check(OwnerHarnessState.startCalls==1&&OwnerHarnessState.cancelCalls==1,"uncertain cancel and start never retried");
        check(status().get("cancel_accepted").isJsonNull(),"uncertain cancel does not invent acceptance");
        running();OwnerHarnessState.cancelAccepted=false;NativeManagedNavigation.cancel(request);NativeManagedNavigation.cancel(request);
        check(OwnerHarnessState.cancelCalls==1,"known false cancel still not retried");
        check(status().get("state").getAsString().equals("stopping")&&!status().get("cancel_accepted").getAsBoolean(),"false cancel stays stopping truthfully");
        check(!status().get("control_released").getAsBoolean()&&status().get("input_owned").getAsBoolean(),"cancel return alone never releases control");

        running();mc.player.x=8.5;OwnerHarnessState.idle=true;OwnerHarnessState.customActive=false;
        mc.level.tick++;NativeManagedNavigation.tick(mc);
        check(!status().get("control_released").getAsBoolean(),"one idle sample cannot settle");
        mc.level.tick++;NativeManagedNavigation.tick(mc);
        JsonObject settled=status();
        check(settled.get("state").getAsString().equals("settled")&&settled.get("goal_reached").getAsBoolean(),"observed goal and two idle samples settle");
        check(settled.get("settings_restored").getAsBoolean()&&settled.get("control_released").getAsBoolean()&&!settled.get("input_owned").getAsBoolean(),"settlement/restoration/release status truthful");
        check(OwnerHarnessState.settingsRestores==1,"settings restore called once on proven settlement");
        NativeManagedNavigation.start(request);
        check(OwnerHarnessState.startCalls==1,"settled request ID is read-only and not resumed");

        JsonObject result=new JsonObject();result.addProperty("status","passed");result.addProperty("checks",checks);result.addProperty("scenarios",scenarios);
        result.addProperty("production_control","NativeManagedNavigation, lease, input policy, responses, and callback fence");
        result.addProperty("world_route_settings_geometry","controlled doubles; not certified by this probe");
        result.addProperty("private_Data","real constructor; no Unsafe");result.add("native_status_row",nativeStatusRow);System.out.println(result);
    }
    private static JsonObject residentCommand(){
        var id=request.identity();JsonObject c=new JsonObject();c.addProperty("op","managed_navigation_control");c.addProperty("operation","start");
        c.addProperty("operation_id",id.id());JsonObject owner=new JsonObject();owner.addProperty("owner_id",id.owner());owner.addProperty("owner_generation",id.generation());owner.addProperty("job_id",id.job());c.add("control_owner",owner);
        JsonObject context=new JsonObject();context.addProperty("action_session",id.session());context.addProperty("world_generation",id.world());context.addProperty("player_uuid",id.player());context.addProperty("dimension",id.dimension());c.add("expected_context",context);
        JsonObject source=new JsonObject();source.addProperty("source_tick",id.sourceTick());source.addProperty("source_nano",Long.toString(id.sourceNano()));c.add("source",source);
        JsonObject goal=new JsonObject();goal.addProperty("x",request.x());goal.addProperty("y",request.y());goal.addProperty("z",request.z());c.add("goal",goal);
        c.addProperty("timeout_ms",id.timeoutMs());c.addProperty("max_distance",request.radius());c.addProperty("min_health",request.minHealth());
        c.addProperty("expected_resident_session","test-resident");c.addProperty("request_id","test-request");c.addProperty("session_id","test-resident");c.addProperty("submitted_at",0);return c;
    }
    private static void waitUntilSourceStale(){
        long remaining=request.identity().sourceNano()+760_000_000L-System.nanoTime();
        while(remaining>0){java.util.concurrent.locks.LockSupport.parkNanos(remaining);remaining=request.identity().sourceNano()+760_000_000L-System.nanoTime();}
    }
    private static final class Vec3Child extends Vec3 {Vec3Child(){super(0,0,1);}}
}

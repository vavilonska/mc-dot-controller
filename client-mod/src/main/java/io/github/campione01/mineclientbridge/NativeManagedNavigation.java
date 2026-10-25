package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.lang.reflect.Method;
import java.util.HashMap;
import java.util.Map;
import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.player.LocalPlayer;

/** One actual API waypoint under the existing sole native input-owner fence. */
public final class NativeManagedNavigation {
    private static final ManagedNavigationLease LEASES=new ManagedNavigationLease();
    private static final Map<String,JsonObject> history=new HashMap<>();
    private static Data active;
    private static final class Data {
        final ManagedNavigationLease.Request request;
        final LocalPlayer player;final ClientLevel level;final Object mode;final java.util.UUID uuid;
        final long ownerRevision;final Object process,path,input,goal;
        final Method start,cancel;final ManagedNavigationSettings settings;
        final double x,y,z;final float initialHealth;
        String dryRefusal;long dryChecks,dryJumpInputs,dryTravelInputs;int dryCells;boolean dryChecking,dryPoisoned;
        ManagedNavigationLease.Entry entry;JsonObject proof;ManagedNavigationInputPolicy.Token inputToken;
        Data(Minecraft mc,ManagedNavigationLease.Request r) throws Exception {
            request=r;player=mc.player;level=mc.level;mode=mc.gameMode;uuid=player.getUUID();ownerRevision=ClientActions.externalOwnerRevision();
            require(inputFenceReady(),"managed_navigation_dry_fence_unavailable");ManagedDryRoute.verify();
            x=player.getX();y=player.getY();z=player.getZ();initialHealth=player.getHealth();
            require(Double.isFinite(x)&&Double.isFinite(y)&&Double.isFinite(z)&&Float.isFinite(initialHealth),"managed_navigation_initial_state_nonfinite");
            ClassLoader loader=NativeManagedNavigation.class.getClassLoader();settings=new ManagedNavigationSettings(loader);
            Class<?> api=Class.forName("baritone.api.BaritoneAPI",false,loader),providerType=Class.forName("baritone.api.IBaritoneProvider",false,loader),
                baritone=Class.forName("baritone.api.IBaritone",false,loader),custom=Class.forName("baritone.api.process.ICustomGoalProcess",false,loader),
                goalType=Class.forName("baritone.api.pathing.goals.Goal",false,loader);
            Object provider=api.getMethod("getProvider").invoke(null);exact(provider,"baritone.BaritoneProvider",loader);
            Object instance=providerType.getMethod("getPrimaryBaritone").invoke(provider);exact(instance,"baritone.a",loader);
            process=baritone.getMethod("getCustomGoalProcess").invoke(instance);exact(process,"baritone.ea",loader);
            path=baritone.getMethod("getPathingBehavior").invoke(instance);exact(path,"baritone.i",loader);
            input=baritone.getMethod("getInputOverrideHandler").invoke(instance);exact(input,"baritone.fj",loader);
            require(input instanceof ManagedNavigationInputFence,"managed_navigation_input_fence_unavailable");
            goal=Class.forName("baritone.api.pathing.goals.GoalBlock",false,loader).getConstructor(int.class,int.class,int.class)
                .newInstance(r.x(),r.y(),r.z());
            start=custom.getMethod("setGoalAndPath",goalType);
            cancel=Class.forName("baritone.api.behavior.IPathingBehavior",false,loader).getMethod("cancelEverything");
        }
    }
    private record Sample(long tick,boolean same,String hazard,boolean neutral,boolean atGoal,boolean grounded,
                          ExternalControllerProof.ManagedProof managed) {}
    static boolean blocksInput(){return LEASES.blocked();}
    static JsonObject start(ManagedNavigationLease.Request request){
        NativeRecoveryShortInput.requireLegacyAllowed();
        Minecraft mc=Minecraft.getInstance();thread(mc);
        var old=LEASES.existing(request);if(old!=null)return describe(old);
        require(BridgeServer.isRunning()&&ManagedNavigationInputPolicy.admissionOpen(),"managed_navigation_bridge_unavailable");
        require(!LEASES.blocked()&&!NativeExternalNavigation.blocksInput(),"managed_navigation_original_owner_unresolved");
        require(context(mc,request.identity())&&mdcFree(mc),"managed_navigation_admission_context");
        require(ExternalControllerGuard.idle(mc),"managed_navigation_external_idle_required");
        Data data;try{data=new Data(mc,request);}catch(Exception|LinkageError e){throw new ClientActionRequest.Rejected(409,"managed_navigation_supported_api_required");}
        require(Math.hypot(request.x()+.5-data.x,request.z()+.5-data.z)<=request.radius()
            &&Math.abs(request.y()-data.y)<=64,"managed_navigation_goal_bound");
        ManagedDryWorld.Frame dry=dryCapture(mc,data,null,false);
        Sample sample=sample(mc,data,false);long now=System.nanoTime();
        try{dry.unchanged(mc);}catch(Exception unavailable){throw new ClientActionRequest.Rejected(409,"managed_navigation_dry_admission_changed");}
        require(sample.same()&&sample.hazard()==null&&sample.grounded()&&sample.neutral()
            &&sample.managed().exactOwner()&&sample.managed().external().get("idle_proven").getAsBoolean(),"managed_navigation_admission_not_safe_idle");
        require(BridgeServer.isRunning()&&ManagedNavigationInputPolicy.admissionOpen()&&localBound(mc,data)&&!LEASES.blocked()&&!NativeExternalNavigation.blocksInput()&&localMdcFree(),"managed_navigation_final_admission_owner");
        now=System.nanoTime();fresh(request.identity(),sample.tick(),now);
        var entry=LEASES.claim(request,now,sample.tick());data.entry=entry;active=data;
        try {
            data.inputToken=ManagedNavigationInputPolicy.claim(data.input,()->inputAllowed(data));
            data.settings.install();
            // Resolve all settings/API callbacks, then recheck the original source and exact owner.
            ManagedDryWorld.Frame startDry=ManagedDryWorld.capture(mc,data.path,null,false);
            Sample ready=sample(mc,data,true);now=System.nanoTime();startDry.unchanged(mc);
            require(ready.same()&&ready.hazard()==null&&ready.grounded()&&ready.neutral()
                &&ready.managed().exactOwner()&&ready.managed().external().get("idle_proven").getAsBoolean(),"managed_navigation_start_context_changed");
            require(BridgeServer.isRunning()&&ManagedNavigationInputPolicy.admissionOpen()&&localBound(mc,data)&&active==data&&LEASES.owns(entry)&&localMdcFree(),"managed_navigation_start_owner_changed");
            now=System.nanoTime();fresh(request.identity(),ready.tick(),now);LEASES.startAttempt(entry);data.proof=ready.managed().external();
            data.start.invoke(data.process,data.goal);
        }catch(Exception|LinkageError failure){unknown(entry,"managed_navigation_start_outcome_unknown");}
        return describe(entry);
    }
    static JsonObject cancel(ManagedNavigationLease.Request request){
        Minecraft mc=Minecraft.getInstance();thread(mc);var entry=LEASES.existing(request);
        require(entry!=null&&entry==LEASES.active(),"managed_navigation_original_route_required");
        if(LEASES.owns(entry))LEASES.requestStop(entry,"managed_navigation_cancel_requested",System.nanoTime());
        tick(mc);return describe(entry);
    }
    static void tick(Minecraft mc){
        Data data=active;var entry=LEASES.active();if(data==null||data.entry!=entry||!LEASES.owns(entry))return;
        try {
            if(!BridgeServer.isRunning()||!ManagedNavigationInputPolicy.admissionOpen()||ManagedNavigationInputPolicy.bridgeClosed(data.inputToken))LEASES.bridgeStopping(entry,System.nanoTime());
            boolean unchanged=data.settings.unchanged();Sample sample=sample(mc,data,true);
            if(!unchanged||!sample.same()||!sample.managed().exactOwner()||sample.managed().input()!=data.input){
                unknown(entry,!unchanged?"managed_navigation_settings_changed_do_not_overwrite":"managed_navigation_owner_changed");return;}
            long now=System.nanoTime();data.proof=sample.managed().external();
            String blocked=ManagedNavigationInputPolicy.blockedReason();
            if(blocked!=null)LEASES.requestStop(entry,blocked,now);
            if(sample.hazard()!=null)LEASES.requestStop(entry,sample.hazard(),now);
            if(entry.phase==ManagedNavigationLease.Phase.ROUTING){
                try{ManagedDryWorld.Frame dry=ManagedDryWorld.capture(mc,data.path,null,false);dry.unchanged(mc);data.dryChecks++;data.dryCells=dry.decision.checkedCells();}
                catch(Exception|LinkageError unsafe){refuseDry(data,reason(unsafe));}
            }
            LEASES.deadlines(entry,now);if(!LEASES.owns(entry)){if(entry.phase==ManagedNavigationLease.Phase.UNKNOWN)ManagedNavigationInputPolicy.quarantine(data.inputToken);return;}
            boolean idle=sample.neutral()&&sample.managed().external().get("idle_proven").getAsBoolean();
            LEASES.sample(entry,true,idle,sample.atGoal()&&sample.grounded(),sample.tick(),now);
            if(entry.idleSamples>=2){
                // All reflection reads finish before the pure exact owner fence and restoration writes.
                boolean restore=data.settings.unchanged();
                require(restore&&localBound(mc,data)&&active==data&&LEASES.owns(entry)&&localMdcFree(),"managed_navigation_restore_owner_changed");
                data.settings.restore();entry.settingsRestored=true;LEASES.settle(entry);ManagedNavigationInputPolicy.settled(data.inputToken);
                history.put(entry.request.identity().id(),describe(entry));active=null;return;
            }
            if(entry.phase==ManagedNavigationLease.Phase.STOPPING&&!entry.stopAttempted){
                // No callback follows this local fence before the one safe cancellation attempt.
                require(localBound(mc,data)&&active==data&&LEASES.owns(entry)&&localMdcFree(),"managed_navigation_cancel_owner_changed");
                LEASES.stopAttempt(entry);Object answer=data.cancel.invoke(data.path);
                if(!(answer instanceof Boolean accepted))throw new IllegalStateException("managed_navigation_cancel_return_invalid");
                if(LEASES.owns(entry))entry.cancelAccepted=accepted;
            }
        }catch(Exception|LinkageError failure){unknown(entry,"managed_navigation_control_outcome_unknown");}
    }
    private static Sample sample(Minecraft mc,Data d,boolean owned){
        return ExternalNavigationFence.readThenCheck(() -> {
            boolean same=context(mc,d.request.identity())&&mdcFree(mc);
            var p=d.player;boolean grounded=p.onGround();double x=p.getX(),y=p.getY(),z=p.getZ();float health=p.getHealth();
            String hazard= !mc.isWindowActive()||mc.screen!=null||mc.isPaused()?"managed_navigation_attention_changed":
                !p.isAlive()||!Float.isFinite(health)||!Double.isFinite(x)||!Double.isFinite(y)||!Double.isFinite(z)||health<d.request.minHealth()||health<d.initialHealth?"managed_navigation_health_changed":
                p.isPassenger()||p.isFallFlying()||p.getAbilities().flying?"managed_navigation_movement_mode_changed":
                p.isInWater()||p.isInLava()||p.isOnFire()||p.getAirSupply()<80||p.fallDistance>1.5?"managed_navigation_environment_hazard":
                Math.hypot(x-d.x,z-d.z)>d.request.radius()+32||Math.abs(y-d.y)>64?"managed_navigation_route_bounds":null;
            boolean neutral=BridgeServer.heldInputsSnapshot(mc).get("neutral").getAsBoolean();
            boolean atGoal=Math.floor(x)==d.request.x()&&Math.floor(y)==d.request.y()&&Math.floor(z)==d.request.z();
            long tick=d.level.getGameTime();
            var proof=ExternalControllerProof.managed(new ExternalControllerProof.Context(mc,d.player,d.level,
                d.request.identity().session(),d.request.identity().world(),d.request.identity().player(),tick),d.process,d.goal);
            return new Sample(tick,same,hazard,neutral,atGoal,grounded,proof);
        },() -> localBound(mc,d)&&localMdcFree()&&(!owned||active==d&&LEASES.owns(d.entry)));
    }
    private static boolean localBound(Minecraft mc,Data d){return mc.player==d.player&&mc.level==d.level&&mc.gameMode==d.mode
        &&d.player.getUUID()==d.uuid&&d.player.level()==d.level
        &&ClientActions.externalOwnerRevision()==d.ownerRevision&&ClientActions.session().equals(d.request.identity().session())
        &&WorldGeneration.matches(d.level,d.request.identity().world());}
    private static boolean localMdcFree(){return !ClientActions.hasRuntimeAction()&&!NativeFallRescue.armedOrBlocked()
        &&!BridgeServer.hasHeldInputs()&&GuardedGameMovement.LEASES.status().ownerRequestId()==null;}
    private static boolean mdcFree(Minecraft mc){return mc.player!=null&&mc.level!=null&&mc.gameMode!=null&&CapabilityGuard.privateSingleplayer(mc)
        &&mc.gameMode.getPlayerMode()==net.minecraft.world.level.GameType.SURVIVAL&&localMdcFree();}
    private static boolean context(Minecraft mc,ExternalNavigationLease.Request r){return mc.player!=null&&mc.level!=null&&mc.gameMode!=null
        &&r.session().equals(ClientActions.session())&&r.world().equals(WorldGeneration.current(mc.level))
        &&r.player().equals(mc.player.getUUID().toString())&&r.dimension().equals(mc.level.dimension().location().toString());}
    private static void fresh(ExternalNavigationLease.Request r,long tick,long now){require(now>=r.sourceNano()&&now-r.sourceNano()<=750_000_000L
        &&tick>=r.sourceTick()&&tick-r.sourceTick()<=5,"managed_navigation_original_source_stale");}
    static void bridgeStopping(Minecraft mc,ManagedNavigationInputPolicy.Token shutdownToken){
        thread(mc);Data data=active;var entry=LEASES.active();
        if(data==null||data.entry!=entry||!LEASES.owns(entry)||!ManagedNavigationInputPolicy.shutdownOwns(shutdownToken,data.inputToken))return;
        LEASES.bridgeStopping(entry,System.nanoTime());tick(mc);
    }
    private static ManagedDryWorld.Frame dryCapture(Minecraft mc,Data data,net.minecraft.world.phys.Vec3 pending,boolean requireStep){
        try{return ManagedDryWorld.capture(mc,data.path,pending,requireStep);}
        catch(Exception|LinkageError unsafe){throw new ClientActionRequest.Rejected(409,reason(unsafe));}
    }
    private static String reason(Throwable failure){String s=failure.getMessage();return s!=null&&s.startsWith("managed_navigation_")?s:"managed_navigation_dry_proof_unavailable";}
    private static void refuseDry(Data data,String reason){
        if(active==data&&LEASES.owns(data.entry)){data.dryRefusal=reason;LEASES.requestStop(data.entry,reason,System.nanoTime());}
    }
    private static boolean inputAllowed(Data data){return inputAllowed(data,null,true);}
    private static boolean inputAllowed(Data data,net.minecraft.world.phys.Vec3 pending,boolean requireStep){return inputAllowed(data,pending,requireStep,0);}
    private static boolean inputAllowed(Data data,net.minecraft.world.phys.Vec3 pending,boolean requireStep,double pendingJump){
        Minecraft mc=Minecraft.getInstance();
        if(data.dryChecking){data.dryPoisoned=true;refuseDry(data,"managed_navigation_dry_reentrant_check");return false;}
        if(data.dryPoisoned||!BridgeServer.isRunning()||!ManagedNavigationInputPolicy.admissionOpen()||!mc.isSameThread()||active!=data
            ||!LEASES.owns(data.entry)||data.entry.phase!=ManagedNavigationLease.Phase.ROUTING||!data.entry.startAttempted)return false;
        data.dryChecking=true;
        try {
            ManagedDryWorld.Frame dry=ManagedDryWorld.capture(mc,data.path,pending,requireStep,pendingJump);
            boolean settings=data.settings.unchanged();Sample sample=sample(mc,data,true);
            // External controller/setting callbacks are complete before the pure original snapshot and owner fence.
            dry.unchanged(mc);
            boolean okay=!data.dryPoisoned&&settings&&sample.same()&&sample.hazard()==null
                &&(ManagedNavigationInputPolicy.movementOwner(sample.managed().exactOwner(),sample.managed().customActive(),sample.managed().input(),data.input)
                    ||!requireStep&&sample.managed().exactOwner()&&sample.managed().input()==data.input)
                &&localBound(mc,data)&&active==data&&localMdcFree()&&data.entry.phase==ManagedNavigationLease.Phase.ROUTING
                &&BridgeServer.isRunning()&&ManagedNavigationInputPolicy.admissionOpen()&&LEASES.permitsInput(data.entry,System.nanoTime());
            if(okay){data.dryChecks++;data.dryCells=dry.decision.checkedCells();}else refuseDry(data,"managed_navigation_dry_final_owner_or_context");
            return okay;
        }catch(Exception|LinkageError unavailable){refuseDry(data,reason(unavailable));return false;}
        finally{data.dryChecking=false;}
    }
    /** Final ordinary-input consumption seam. true authorizes only neutral writes to this exact old owner. */
    public static boolean neutralizeDryInput(LocalPlayer player,net.minecraft.world.phys.Vec3 pending){
        Minecraft mc=Minecraft.getInstance();Data data=active;
        if(data==null||data.player!=player||mc.player!=player||!mc.isSameThread())return false;
        boolean moving=pending==null||pending.x!=0||pending.y!=0||pending.z!=0||player.input.jumping;
        if(inputAllowed(data,pending,moving))return false;
        // Cleanup never regains authority after replacement; it does not invoke ordinary admission or another callback.
        return active==data&&LEASES.active()==data.entry&&data.entry.phase!=ManagedNavigationLease.Phase.SETTLED
            &&localBound(mc,data)&&localMdcFree()&&mc.player==player&&mc.level==data.level&&mc.gameMode==data.mode;
    }
    public static net.minecraft.world.phys.Vec3 dryTravelIntent(LocalPlayer player,net.minecraft.world.phys.Vec3 pending){
        Data data=active;if(data==null||data.player!=player)return pending;
        // Refusing this captured old call argument does not write a replacement owner's input state.
        return inputAllowed(data,pending,pending.x!=0||pending.y!=0||pending.z!=0)?pending:net.minecraft.world.phys.Vec3.ZERO;
    }
    public static boolean refuseDryAcceleration(LocalPlayer player,float amount,net.minecraft.world.phys.Vec3 pending){
        Data data=active;if(data==null||data.player!=player)return false;
        if(!Float.isFinite(amount)||amount<0||amount>.101f||pending==null||pending.getClass()!=net.minecraft.world.phys.Vec3.class){refuseDry(data,"managed_navigation_acceleration_unproven");return true;}
        if(!inputAllowed(data,pending,pending.x!=0||pending.y!=0||pending.z!=0))return true;
        if(amount>0&&(pending.x!=0||pending.z!=0))data.dryTravelInputs++;return false;
    }
    private static boolean finalDryOwner(Data data){Minecraft mc=Minecraft.getInstance();return active==data&&localBound(mc,data)&&localMdcFree()
        &&!data.dryPoisoned&&data.entry.phase==ManagedNavigationLease.Phase.ROUTING&&BridgeServer.isRunning()&&ManagedNavigationInputPolicy.admissionOpen()&&LEASES.permitsInput(data.entry,System.nanoTime());}
    public static boolean refuseDryJump(LocalPlayer player,float power,net.minecraft.world.phys.Vec3 originalMotion){
        Data data=active;if(data==null||data.player!=player)return false;
        if(!player.onGround()||!Float.isFinite(power)||Math.abs(power-.42f)>1e-6||originalMotion==null||originalMotion.getClass()!=net.minecraft.world.phys.Vec3.class
            ||player.getDeltaMovement()!=originalMotion){refuseDry(data,"managed_navigation_jump_power_unproven");return true;}
        var pending=new net.minecraft.world.phys.Vec3(player.xxa,0,player.zza);
        if(!inputAllowed(data,pending,true,power))return true;
        // Exact immutable local arguments remain bound after the last external callback.
        if(player.getDeltaMovement()!=originalMotion||!player.onGround()||!finalDryOwner(data))return true;
        data.dryJumpInputs++;return false;
    }
    private static void unknown(ManagedNavigationLease.Entry entry,String reason){
        LEASES.unknown(entry,reason);
        if(active!=null&&active.entry==entry&&entry.phase==ManagedNavigationLease.Phase.UNKNOWN)
            ManagedNavigationInputPolicy.quarantine(active.inputToken);
    }
    static void contextLost(){var e=LEASES.active();unknown(e,"managed_navigation_context_changed");}
    private static boolean inputFenceReady(){
        try{return ManagedNavigationInputFence.class.isAssignableFrom(Class.forName("baritone.fj",false,NativeManagedNavigation.class.getClassLoader()))
            &&ManagedDryInputFence.class.isAssignableFrom(LocalPlayer.class)&&ManagedDryTravelFence.class.isAssignableFrom(LocalPlayer.class)
            &&ManagedDryAccelerationFence.class.isAssignableFrom(LocalPlayer.class);}
        catch(ClassNotFoundException|LinkageError unavailable){return false;}
    }
    static JsonObject capabilities(){JsonObject j=new JsonObject();j.addProperty("schema_version",1);j.addProperty("version","managed-navigation-owner-control/1");
        j.addProperty("input_fence_ready",inputFenceReady());j.addProperty("max_goal_distance",200);j.addProperty("max_timeout_ms",120000);j.addProperty("normal_chunk_loading",true);
        j.addProperty("dry_step_profile","managed-dry-current-step-v1");j.addProperty("dry_step_max_cells",128);j.addProperty("surface_rescue",false);
        j.addProperty("unloaded_terrain_certified",false);j.addProperty("walking_only",true);j.addProperty("no_auto_resume",true);return j;}
    static JsonObject status(){thread(Minecraft.getInstance());return describe(LEASES.active());}
    private static JsonObject describe(ManagedNavigationLease.Entry e){
        if(e!=null&&history.containsKey(e.request.identity().id()))return history.get(e.request.identity().id()).deepCopy();
        return ManagedNavigationResponses.status(e,active!=null&&active.entry==e?active.proof:null,System.nanoTime());
    }

    private static void exact(Object o,String type,ClassLoader loader)throws Exception{require(o!=null&&o.getClass()==Class.forName(type,false,loader),"managed_navigation_api_receiver_changed");}
    private static void thread(Minecraft mc){require(mc.isSameThread(),"minecraft_thread_required");}
    private static void require(boolean okay,String reason){if(!okay)throw new ClientActionRequest.Rejected(409,reason);}
    private NativeManagedNavigation(){}
}

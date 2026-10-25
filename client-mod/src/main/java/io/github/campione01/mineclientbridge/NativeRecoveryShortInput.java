package io.github.campione01.mineclientbridge;

import com.google.gson.*;
import java.util.*;
import java.util.concurrent.*;
import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.player.Input;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.phys.AABB;

/** Startup-only exclusive recovery: legacy finite Input plus explicitly typed vanilla interactions.
 * No direct position, velocity or world-state writes. Normal physics and damage remain gameplay. */
final class NativeRecoveryShortInput {
    static final String ROOT="/control/recovery-short-input/v1/";
    static final boolean LEGACY_ENABLED=Boolean.parseBoolean(System.getProperty("mineclientBridge.recoveryShortInputV1","false"));
    static final boolean ENABLED=LEGACY_ENABLED||RecoveryInteraction.ENABLED||RecoveryInteraction.V2_ENABLED||RecoveryInteraction.V3_ENABLED||RecoveryNavigationV4.ENABLED||RecoveryMaintenanceV5.ENABLED||RecoverySurvivalV6.ENABLED;
    private static RecoveryShortInputLedger ledger;
    private static volatile Capture capture;
    private static Challenge observation;
    private static long tick;
    private static ScheduledExecutorService watchdog;
    private record Capture(RecoveryShortInputLedger.Entry entry,LocalPlayer player,ClientLevel level,
                           Object gameMode,Object server,Input input,Challenge source,RecoveryInteraction.Capture interaction) {}
    private record Challenge(String id,LocalPlayer player,ClientLevel level,long nano,long tick,
                             double x,double y,double z,float yaw,float pitch) {}
    private NativeRecoveryShortInput(){}
    static void requireLegacyAllowed(){if(ENABLED)throw new ClientActionRequest.Rejected(409,"recovery_short_input_exclusive_mode");}
    static synchronized void open(){
        if((LEGACY_ENABLED?1:0)+(RecoveryInteraction.ENABLED?1:0)+(RecoveryInteraction.V2_ENABLED?1:0)+(RecoveryInteraction.V3_ENABLED?1:0)+(RecoveryNavigationV4.ENABLED?1:0)+(RecoveryMaintenanceV5.ENABLED?1:0)+(RecoverySurvivalV6.ENABLED?1:0)>1)throw new IllegalStateException("recovery_profiles_mutually_exclusive");
        if(!ENABLED||ledger!=null)return;
        var capacity=RecoverySurvivalV6.ENABLED?RecoveryShortInputLedger.CapacityMode.SURVIVAL_V6:
            RecoveryMaintenanceV5.ENABLED?RecoveryShortInputLedger.CapacityMode.MAINTENANCE_V5:RecoveryShortInputLedger.CapacityMode.LEGACY;
        ledger=new RecoveryShortInputLedger(new RecoveryShortInputLedger.FileStore(
            BridgeConfigStore.configPath().resolveSibling("recovery-short-input-v1.ledger"),capacity),System::nanoTime,RecoveryInteraction.ENABLED||RecoveryInteraction.V2_ENABLED||RecoveryInteraction.V3_ENABLED||RecoveryNavigationV4.ENABLED||RecoveryMaintenanceV5.ENABLED||RecoverySurvivalV6.ENABLED,capacity);
        watchdog=Executors.newSingleThreadScheduledExecutor(r->{Thread t=new Thread(r,"RecoveryShortInput-Deadline");t.setDaemon(true);return t;});
        watchdog.scheduleAtFixedRate(()->{
            try{
                var e=ledger.active();if(e==null)return;
                boolean live=ledger.live(e);
                if(!live)requestCleanup(e,"deadline_or_stop");
            }catch(RuntimeException ignored){/* Ledger retains UNKNOWN, never replay. */}
        },25,25,TimeUnit.MILLISECONDS);
    }
    /** UI-only atomic idle claim; never mutates historical actions, owner or journal. */
    static boolean claimDeathScreenUi(LocalPlayer player){
        var l=ledger;if(l==null||!RecoveryDeathScreenUi.enabled())return false;
        Minecraft mc=Minecraft.getInstance();
        if(!mc.isSameThread()||mc.player!=player||!player.isDeadOrDying()||!neutral(player.input)
            ||ClientActions.hasRuntimeAction()||NativeFallRescue.armedOrBlocked()||NativeExternalNavigation.blocksInput()
            ||GuardedGameMovement.LEASES.status().ownerRequestId()!=null||BridgeServer.hasHeldInputs()
            ||ClientInputIsolation.statistics().heldKeys()!=0||!BridgeServer.isRunning())return false;
        synchronized(l){return mc.player==player&&RecoveryDeathScreenUi.claimIdle(l,player,capture==null);}
    }
    static boolean blocksInput(){return ENABLED;}
    static void close(){
        if(!ENABLED||ledger==null)return;
        try{ledger.close();}catch(RuntimeException failure){ledger.unknown(ledger.active(),"bridge_stop_journal_failed");}
        finally{
            var e=ledger.active();if(e!=null)requestCleanup(e,"bridge_stopping");
            if(watchdog!=null)watchdog.shutdownNow();
        }
    }
    private static RecoveryShortInputLedger journal(){
        if(!ENABLED||ledger==null)throw new IllegalArgumentException("recovery_short_input_disabled");return ledger;
    }
    /** Read-only client-thread DTO. No I/O, external getter or callback under the ledger monitor. */
    static JsonObject diagnosticSnapshot(){
        var l=ledger;if(l==null)return diagnosticFields(null,null,0,0,false);
        synchronized(l){return diagnosticFields(l.owner(),l.active(),l.nextGeneration(),l.diagnosticEntryCount(),l.locked());}
    }
    private static JsonObject diagnosticFields(String owner,RecoveryShortInputLedger.Entry e,long next,int count,boolean locked){
        JsonObject j=new JsonObject();j.addProperty("enabled",ENABLED);j.addProperty("owner_id",owner);j.addProperty("active_id",e==null?null:e.request.id());j.addProperty("profile",e==null?null:e.request.profile());j.addProperty("state",e==null?null:e.state);j.addProperty("applied_count",e==null?0:e.applied);j.addProperty("next_generation",next);j.addProperty("entry_count",count);j.addProperty("unknown_lock",locked);return j;
    }
    static JsonObject start(JsonObject body){return start(body,false);}
    static JsonObject start(JsonObject body,boolean interaction){return start(body,oldRoute(interaction));}
    static JsonObject start(JsonObject body,String profile){
        requireProfile(profile);
        if(!RecoverySurvivalV6.ENABLED&&!profile.equals(activeProfile()))throw new IllegalArgumentException("profile_not_enabled");
        var l=journal();var request=!profile.equals(RecoveryShortInputLedger.PROFILE)?parseInteractionStart(body,profile):parseStart(body);
        RecoveryShortInputLedger.Entry entry;
        synchronized(l){
            boolean fresh=!l.contains(request.id());
            if(!profile.equals(activeProfile())&&(!RecoverySurvivalV6.ENABLED||fresh))throw new IllegalArgumentException("profile_not_enabled");
            if(fresh&&RecoveryDeathScreenUi.blocksStarts())throw new IllegalArgumentException("recovery_respawn_ui_pending_or_unknown");
            entry=l.submit(request);
            // Only QUEUED may enqueue admission. Duplicate callbacks themselves carry the exact ticket
            // and have no effect until the single native per-tick input hook.
            if(fresh&&entry.state.equals("QUEUED"))Minecraft.getInstance().execute(()->admit(entry));
            return describe(entry);
        }
    }
    static JsonObject status(JsonObject query){return status(query,false);}
    static JsonObject status(JsonObject query,boolean interaction){return status(query,oldRoute(interaction));}
    static JsonObject status(JsonObject query,String profile){
        requireProfile(profile);
        exactKeys(query,"id","session","owner_id","owner_generation");
        var l=journal();synchronized(l){var e=l.lookup(string(query,"id"),string(query,"session"),string(query,"owner_id"),integer(query,"owner_generation"));checkStatusRoute(e,profile);return describe(e);}
    }
    static JsonObject stop(JsonObject body){return stop(body,false);}
    static JsonObject stop(JsonObject body,boolean interaction){return stop(body,oldRoute(interaction));}
    static JsonObject stop(JsonObject body,String profile){
        requireProfile(profile);
        exactKeys(body,"schema_version","profile","id","session","owner_id","owner_generation");header(body,profile);
        var l=journal();RecoveryShortInputLedger.Entry e;
        synchronized(l){e=l.lookup(string(body,"id"),string(body,"session"),string(body,"owner_id"),integer(body,"owner_generation"));checkRoute(e,profile);l.stop(e,"explicit_stop");e.cleanupBlocked=false;}
        // Invalidation is already committed on the HTTP thread; cleanup never confers authority.
        requestCleanup(e,"explicit_stop");
        synchronized(l){return describe(e);}
    }
    private static void admit(RecoveryShortInputLedger.Entry e){
        Minecraft mc=Minecraft.getInstance();var l=journal();
        synchronized(l){if(!l.live(e))return;if(capture!=null&&capture.entry()==e)return;}
        String problem=contextProblem(mc);
        if(problem==null&&(!e.request.world().equals(WorldGeneration.current(mc.level))||!e.request.player().equals(mc.player.getUUID().toString())))problem="world_or_player_mismatch";
        if(problem!=null){l.rejectQueued(e,problem);return;}
        Challenge source=observation;
        if(source==null||!source.id().equals(e.request.observationId())){
            if(v3(e.request.profile()))l.recordObservationRefusal(e,new RecoveryChallengeLease.Refusal("admit",null,null,source==null?-1:-2,RecoveryShortInputLedger.twoSecondLeaseProfile(e.request.profile())));
            l.rejectQueued(e,"observation_stale_or_moved");return;
        }
        if(!freshFor(mc,source,e,"admit")){
            l.rejectQueued(e,"observation_stale_or_moved");return;
        }
        Capture c=new Capture(e,mc.player,mc.level,mc.gameMode,mc.getSingleplayerServer(),mc.player.input,source,e.request.kind().equals("move")?null:new RecoveryInteraction.Capture(e,mc));
        if(c.interaction()!=null){problem=RecoveryInteraction.problem(c.interaction(),true);if(problem!=null){l.rejectQueued(e,problem);return;}}
        synchronized(l){if(l.live(e)&&capture==null&&bound(mc,c))capture=c;else l.rejectQueued(e,"admission_owner_changed");}
    }
    static void preTick(){
        if(!ENABLED||ledger==null)return;tick++;
        RecoveryDeathScreenUi.observeLifecycle(Minecraft.getInstance());
        if(capture!=null&&capture.entry().settled())capture=null;
        var l=ledger;var e=l.active();if(e==null)return;
        Capture c=capture;
        if(e.state.equals("UNKNOWN")&&e.cleanupBlocked)return;
        // Do not rely on vanilla KeyboardInput overwriting a prior sample if a Post hook was missed.
        if(c!=null&&c.entry()==e&&c.interaction()==null&&l.residualInput(e)){
            cleanup(e,"pre_tick_residual_release",false);
            if(l.active()!=e)return;
        }
        if(!l.live(e)){cleanup(e,"deadline_or_stop",true);return;}
        if(c!=null&&c.entry()==e){
            String reason=contextProblem(Minecraft.getInstance());
            if(reason!=null||!bound(Minecraft.getInstance(),c)){l.stop(e,reason==null?"context_changed":reason);cleanup(e,reason==null?"context_changed":reason,true);return;}
            if(c.interaction()!=null){
                try{interactionTick(c);}catch(RuntimeException|Error failure){
                    if(!e.effectFenced)l.rejectQueued(e,"interaction_pre_effect_check_failed");
                    else l.unknown(e,"interaction_callback_threw");
                    cleanup(e,"interaction_callback_threw",true);
                }
            }
        }
    }
    static void input(LocalPlayer player,Input input){
        if(!ENABLED||ledger==null)return;
        var l=ledger;Capture c=capture;if(c==null)return;var e=c.entry();Minecraft mc=Minecraft.getInstance();
        if(e.cleanupBlocked||c.interaction()!=null)return;
        String problem=contextProblem(mc);
        if(problem!=null){l.stop(e,problem);cleanup(e,problem,true);return;}
        boolean exact=player==c.player()&&input==c.input()&&bound(mc,c)&&neutral(input)
            &&(e.applied>0||freshFor(mc,c.source(),e,"first_input"));
        synchronized(l){
            // No callback-backed world/entity/registry reads occur after this final exact fence.
            exact=exact&&capture==c&&mc.player==c.player()&&mc.level==c.level()&&mc.gameMode==c.gameMode()&&c.player().input==input;
            final boolean jump=e.request.jumpFirst()&&e.applied==0;
            try{l.sample(e,tick,exact,()->{
                input.forwardImpulse=(float)e.request.forward();input.leftImpulse=(float)e.request.strafe();
                input.up=e.request.forward()>0;input.down=e.request.forward()<0;
                input.left=e.request.strafe()>0;input.right=e.request.strafe()<0;
                input.jumping=jump;input.shiftKeyDown=false;
            });}catch(RuntimeException failure){cleanup(e,"input_failure",true);}
        }
    }
    static void postTick(){if(!ENABLED||ledger==null)return;var e=ledger.active();if(e!=null&&e.request.kind().equals("move"))cleanup(e,"samples_complete",false);}
    static void contextLost(String reason){
        if(!ENABLED||ledger==null)return;var e=ledger.active();if(e==null)return;
        ledger.stop(e,reason);Minecraft mc=Minecraft.getInstance();
        if(mc.isSameThread())cleanup(e,reason,true);else requestCleanup(e,reason);
    }
    private static void requestCleanup(RecoveryShortInputLedger.Entry e,String reason){
        var l=ledger;if(l==null)return;
        synchronized(l){
            Capture c=capture;
            if(c==null||c.entry()!=e||e.cleanupBlocked||!l.claimCleanup(e))return;
        }
        // execute may inline on the game thread: do not carry any outer ledger monitor into abort callbacks.
        try{Minecraft.getInstance().execute(()->{
            try{cleanup(e,reason,true);}finally{l.completeCleanup(e);}
        });}catch(RuntimeException failure){l.completeCleanup(e);l.unknown(e,"cleanup_enqueue_failed");}
    }
    private static void cleanup(RecoveryShortInputLedger.Entry e,String reason,boolean finish){
        Minecraft mc=Minecraft.getInstance();if(!mc.isSameThread())throw new IllegalStateException("native_game_thread_required");
        var l=ledger;Capture c=capture;if(c==null||c.entry()!=e)return;
        synchronized(l){
            if(capture!=c||e.cleanupBlocked||e.callRunning)return;
            // A queued rejection/cancel already proves no effect; it never owned mining progress to abort.
            if(e.settled()){capture=null;return;}
        }
        // Callback-backed vanilla abort is OUTSIDE the journal monitor. Stop remains responsive.
        boolean exact=c.player().input==c.input()&&!ClientActions.hasRuntimeAction()
            &&!NativeFallRescue.armedOrBlocked()&&!NativeExternalNavigation.blocksInput();
        if(c.interaction()!=null){
            try{exact=exact&&(RecoverySurvivalV6.hasUse(c.interaction())?RecoverySurvivalV6.release(c.interaction()):RecoveryInteraction.release(c.interaction()));}
            catch(RuntimeException|Error failure){l.unknown(e,RecoverySurvivalV6.hasUse(c.interaction())?"native_food_release_threw":"native_mining_release_threw");e.cleanupBlocked=true;return;}
        }
        synchronized(l){
            if(capture!=c)return;
            l.release(e,exact,()->{if(c.interaction()==null)neutralize(c.input());},finish,reason);
            if(e.released&&c.interaction()!=null)RecoverySurvivalV6.released(c.interaction());
            if(e.settled()||(e.state.equals("UNKNOWN")&&e.released))capture=null;
            else if(e.state.equals("UNKNOWN"))e.cleanupBlocked=true;
        }
    }
    private static void interactionTick(Capture c){
        var e=c.entry();var l=ledger;Minecraft mc=Minecraft.getInstance();
        if(!l.live(e))return;
        String problem=e.applied==0&&!freshFor(mc,c.source(),e,"first_interaction_tick")?"observation_stale_or_moved":RecoveryInteraction.problem(c.interaction(),e.applied==0);
        if(problem!=null){l.stop(e,problem);cleanup(e,problem,true);return;}
        if(RecoverySurvivalV6.profile(e.request.profile())&&RecoverySurvivalV6.callKind(e.request.kind())){
            if(e.applied==0){
                if(!l.claimCall(e,tick,bound(mc,c)&&capture==c&&RecoverySurvivalV6.finalBinding(c.interaction())))return;
                try{
                    if(e.request.kind().equals("attack_blaze"))RecoverySurvivalV6.attack(c.interaction());
                    else RecoverySurvivalV6.startUse(c.interaction(),tick);
                    l.completeCall(e);
                }catch(RuntimeException|Error failure){l.failedCall(e);cleanup(e,"survival_call_threw",true);return;}
            }
            if(e.request.kind().equals("attack_blaze")||!l.live(e)||RecoverySurvivalV6.useFinished(c.interaction(),tick)){
                l.stop(e,e.request.kind().equals("attack_blaze")?"attack_attempt_finished":"bread_use_finished_or_bounded");cleanup(e,"survival_attempt_finished",true);
            }
            return;
        }
        if(e.request.kind().equals("place_block")){
            if(!l.claimCall(e,tick,bound(mc,c)&&capture==c&&RecoveryInteraction.finalBinding(c.interaction(),true)))return;
            try{RecoveryMaintenancePlacementDispatch.use(c.interaction());l.completeCall(e);}
            catch(RuntimeException|Error failure){l.failedCall(e);cleanup(e,"placement_call_threw",true);return;}
            l.stop(e,"placement_attempt_finished");cleanup(e,"placement_attempt_finished",true);return;
        }
        if(!e.request.kind().equals("break_block")){
            try{l.sample(e,tick,bound(mc,c)&&capture==c&&RecoveryInteraction.finalBinding(c.interaction(),true),()->RecoveryInteraction.rawOneShot(c.interaction()));}
            catch(RuntimeException|Error failure){l.unknown(e,"one_shot_failed");}
            cleanup(e,"one_shot_complete",true);return;
        }
        // Durable fence+claim, then native callback stack without the journal monitor held.
        if(!l.claimCall(e,tick,bound(mc,c)&&capture==c&&RecoveryInteraction.finalBinding(c.interaction(),e.applied==0)))return;
        try{RecoveryInteraction.mine(c.interaction());l.completeCall(e);}
        catch(RuntimeException|Error failure){l.failedCall(e);cleanup(e,"mining_call_threw",true);return;}
        boolean finished=RecoveryInteraction.finished(c.interaction());
        e.gameplay=RecoveryInteraction.gameplay(c.interaction());
        if(finished||!l.live(e)||e.applied>=e.request.samples()){
            l.stop(e,finished?"mining_attempt_finished":"mining_bound_or_stop");cleanup(e,"mining_attempt_finished",true);
        }
    }
    static boolean suppressMiningAbort(){
        Capture c=capture;
        return (RecoveryInteraction.ENABLED||RecoveryInteraction.V2_ENABLED||RecoveryInteraction.V3_ENABLED||RecoveryMaintenanceV5.ENABLED)&&c!=null&&c.interaction()!=null&&c.entry().request.kind().equals("break_block")
            &&ledger.active()==c.entry()&&!c.entry().released&&!c.entry().cleanupBlocked
            &&c.interaction().sameCurrentContext()&&c.interaction().gameMode.isDestroying()&&c.interaction().ownsMining();
    }

    private static boolean bound(Minecraft mc,Capture c){return mc.player==c.player()&&mc.level==c.level()&&mc.gameMode==c.gameMode()
        &&mc.getSingleplayerServer()==c.server()&&c.player().input==c.input()&&WorldGeneration.matches(mc.level,c.entry().request.world());}
    private static boolean fresh(Minecraft mc,Challenge c){
        long age=System.nanoTime()-c.nano();
        return age>=0&&age<=250_000_000L&&tick-c.tick()>=0&&tick-c.tick()<=5&&mc.player==c.player()&&mc.level==c.level()
            &&Math.abs(c.player().getX()-c.x())<=.05&&Math.abs(c.player().getY()-c.y())<=.05&&Math.abs(c.player().getZ()-c.z())<=.05
            &&Math.abs(Math.IEEEremainder(c.player().getYRot()-c.yaw(),360))<=.1&&Math.abs(c.player().getXRot()-c.pitch())<=.1;
    }
    private static boolean v3(String profile){return RecoveryShortInputLedger.extendedLeaseProfile(profile);}
    private static boolean freshFor(Minecraft mc,Challenge source,RecoveryShortInputLedger.Entry e,String stage){
        if(!v3(e.request.profile()))return fresh(mc,source);
        var refusal=RecoveryShortInputLedger.twoSecondLeaseProfile(e.request.profile())?freshV5(mc,source,stage):freshV3(mc,source,stage);if(refusal!=null)ledger.recordObservationRefusal(e,refusal);return refusal==null;
    }
    /** Identical short-circuit reads to legacy fresh; only the explicit V3 time/tick lease differs. */
    private static RecoveryChallengeLease.Refusal freshV3(Minecraft mc,Challenge c,String stage){
        long age=System.nanoTime()-c.nano(),delta=tick-c.tick();int mask=RecoveryChallengeLease.windowMask(age,delta);
        if(mask==15&&mc.player==c.player())mask=31;
        if(mask==31&&mc.level==c.level())mask=63;
        if(mask==63&&Math.abs(c.player().getX()-c.x())<=.05&&Math.abs(c.player().getY()-c.y())<=.05&&Math.abs(c.player().getZ()-c.z())<=.05)mask=127;
        if(mask==127&&Math.abs(Math.IEEEremainder(c.player().getYRot()-c.yaw(),360))<=.1&&Math.abs(c.player().getXRot()-c.pitch())<=.1)mask=255;
        return mask==255?null:new RecoveryChallengeLease.Refusal(stage,age,delta,mask);
    }
    private static RecoveryChallengeLease.Refusal freshV5(Minecraft mc,Challenge c,String stage){
        long age=System.nanoTime()-c.nano(),delta=tick-c.tick();int mask=RecoveryChallengeLease.windowMask(age,delta,true);
        if(mask==15&&mc.player==c.player())mask=31;
        if(mask==31&&mc.level==c.level())mask=63;
        if(mask==63&&Math.abs(c.player().getX()-c.x())<=.05&&Math.abs(c.player().getY()-c.y())<=.05&&Math.abs(c.player().getZ()-c.z())<=.05)mask=127;
        if(mask==127&&Math.abs(Math.IEEEremainder(c.player().getYRot()-c.yaw(),360))<=.1&&Math.abs(c.player().getXRot()-c.pitch())<=.1)mask=255;
        return mask==255?null:new RecoveryChallengeLease.Refusal(stage,age,delta,mask,true);
    }
    private static JsonElement refusalJson(RecoveryChallengeLease.Refusal refusal){
        if(refusal==null)return JsonNull.INSTANCE;JsonObject j=new JsonObject();j.addProperty("stage",refusal.stage());
        j.addProperty("age_ns",refusal.ageNs());j.addProperty("tick_delta",refusal.tickDelta());j.addProperty("predicate_mask",refusal.predicateMask());return j;
    }
    private static String contextProblem(Minecraft mc){
        if(!mc.isSameThread())return "native_game_thread_required";
        if(RecoveryDeathScreenUi.blocksStarts())return "recovery_respawn_ui_pending_or_unknown";
        if(!BridgeServer.isRunning())return "bridge_closed";
        if(mc.player==null||mc.level==null||mc.gameMode==null)return "not_in_world";
        if(!CapabilityGuard.privateSingleplayer(mc))return "private_singleplayer_required";
        if(!mc.player.isAlive())return "player_dead";
        if(mc.isPaused()||mc.screen!=null)return "paused_or_screen_open";
        if(!ClientInputIsolation.enabled())return "isolated_input_required";
        if(ClientActions.hasRuntimeAction()||NativeFallRescue.armedOrBlocked()||NativeExternalNavigation.blocksInput()
            ||GuardedGameMovement.LEASES.status().ownerRequestId()!=null||BridgeServer.hasHeldInputs()
            ||ClientInputIsolation.statistics().heldKeys()!=0)return "competing_input_owner";
        if(!RecoverySurvivalV6.ownedInput(mc)&&!BridgeServer.heldInputsSnapshot(mc).get("neutral").getAsBoolean())return "held_input_present";
        // Prototype runtime excludes Baritone entirely. This is controller isolation, not a world safety predicate.
        JsonObject external=ExternalControllerGuard.snapshot(mc);
        if(!external.get("status").getAsString().equals("absent"))return "external_controller_must_be_absent";
        return null;
    }
    static JsonObject observe(){return observe(false);}
    static JsonObject observe(boolean interaction){return observe(oldRoute(interaction));}
    static JsonObject observe(String profile){
        requireProfile(profile);boolean interaction=!profile.equals(RecoveryShortInputLedger.PROFILE);
        if(RecoveryShortInputLedger.geometryProfile(profile))observation=null; // A failed new capture never leaves an older v4 ticket usable.
        Minecraft mc=Minecraft.getInstance();var l=journal();JsonObject out=base(profile);
        if(mc.player==null||mc.level==null){observation=null;return describeNoWorld(mc.isPaused(),mc.screen!=null,profile);}
        out.addProperty("client_tick",tick);
        var sourcePlayer=mc.player;var sourceLevel=mc.level;
        long sourceNano=System.nanoTime(),sourceTick=tick;
        double sourceX=sourcePlayer==null?0:sourcePlayer.getX(),sourceY=sourcePlayer==null?0:sourcePlayer.getY(),sourceZ=sourcePlayer==null?0:sourcePlayer.getZ();
        float sourceYaw=sourcePlayer==null?0:sourcePlayer.getYRot(),sourcePitch=sourcePlayer==null?0:sourcePlayer.getXRot();
        String problem=!profile.equals(activeProfile())?"profile_not_enabled":contextProblem(mc);
        if(problem==null&&RecoveryMaintenanceV5.profile(profile)&&!RecoveryMaintenancePlacementDispatch.ready())problem="maintenance_placement_hooks_unavailable";
        if(problem==null&&RecoverySurvivalV6.profile(profile)&&!RecoverySurvivalV6.ready())problem="survival_use_hook_unavailable";
        if(problem==null&&interaction&&!RecoverySurvivalV6.profile(profile)&&!RecoveryShortInputLedger.navigationProfile(profile)&&!RecoveryInteraction.hooksReady(mc.gameMode))problem="mining_hooks_unavailable";
        synchronized(l){
            out.addProperty("session",l.session);out.addProperty("owner_generation",l.nextGeneration());out.addProperty("bound_owner_id",l.owner());
            out.addProperty("unknown_lock",l.locked());out.addProperty("active_id",l.active()==null?null:l.active().request.id());
            if(l.locked())problem=l.lockReason();else if(l.closed())problem="bridge_closed";else if(l.active()!=null)problem="one_in_flight";
        }
        out.addProperty("ready",problem==null);out.addProperty("reason",problem==null?"ready":problem);
        out.addProperty("world_generation",WorldGeneration.current(mc.level));out.addProperty("player_uuid",mc.player==null?null:mc.player.getUUID().toString());
        out.addProperty("paused",mc.isPaused());out.addProperty("screen_open",mc.screen!=null);
        out.addProperty("alive",mc.player!=null&&mc.player.isAlive());
        JsonArray blocks=new JsonArray(),entities=new JsonArray();boolean terrainComplete=true,truncated=false;
        RecoveryNavigationV4.Geometry geometry=RecoveryShortInputLedger.geometryProfile(profile)?new RecoveryNavigationV4.Geometry(mc.player):null;
        if(mc.player!=null&&mc.level!=null){
            var p=mc.player;JsonObject pose=xyz(p.getX(),p.getY(),p.getZ());pose.addProperty("yaw",p.getYRot());pose.addProperty("pitch",p.getXRot());out.add("pose",pose);
            var v=p.getDeltaMovement();out.add("velocity",xyz(v.x,v.y,v.z));out.addProperty("on_ground",p.onGround());out.addProperty("health",p.getHealth());
            BlockPos center=p.blockPosition();for(int dy=-2;dy<=(interaction?3:2);dy++)for(int dz=-2;dz<=2;dz++)for(int dx=-2;dx<=2;dx++){
                BlockPos pos=center.offset(dx,dy,dz);JsonObject b=new JsonObject();b.addProperty("dx",dx);b.addProperty("dy",dy);b.addProperty("dz",dz);
                boolean loaded=mc.level.hasChunkAt(pos);b.addProperty("loaded",loaded);terrainComplete&=loaded;
                if(loaded){var state=mc.level.getBlockState(pos);b.addProperty("id",BuiltInRegistries.BLOCK.getKey(state.getBlock()).toString());
                    if(geometry==null)b.addProperty("collision",!state.getCollisionShape(mc.level,pos).isEmpty());else geometry.cell(b,state,mc.level,pos);
                    b.addProperty("fluid",BuiltInRegistries.FLUID.getKey(state.getFluidState().getType()).toString());}
                else{b.add("id",JsonNull.INSTANCE);b.add("collision",JsonNull.INSTANCE);b.add("fluid",JsonNull.INSTANCE);if(geometry!=null)geometry.unloaded(b);}blocks.add(b);
            }
            for(var entity:mc.level.getEntitiesOfClass(LivingEntity.class,new AABB(p.getX()-8,p.getY()-8,p.getZ()-8,p.getX()+8,p.getY()+8,p.getZ()+8))){
                if(entity==p||entity.distanceToSqr(p)>64)continue;if(entities.size()==32){truncated=true;break;}
                JsonObject j=xyz(entity.getX(),entity.getY(),entity.getZ());j.addProperty("id",entity.getId());j.addProperty("type",BuiltInRegistries.ENTITY_TYPE.getKey(entity.getType()).toString());j.addProperty("alive",entity.isAlive());entities.add(j);
            }
        }else{out.add("pose",JsonNull.INSTANCE);out.add("velocity",JsonNull.INSTANCE);out.add("on_ground",JsonNull.INSTANCE);out.add("health",JsonNull.INSTANCE);terrainComplete=false;}
        if(geometry!=null){geometry.describe(out,terrainComplete&&blocks.size()==150);if(!out.get("collision_boxes_complete").getAsBoolean()&&problem==null){problem="navigation_geometry_incomplete";out.addProperty("ready",false);out.addProperty("reason",problem);}}
        out.add("local_blocks",blocks);out.add("nearby_living",entities);out.addProperty("nearby_truncated",truncated);out.addProperty("terrain_complete",terrainComplete);
        if(interaction)RecoveryInteraction.observation(out,mc,RecoveryShortInputLedger.planProfile(profile));
        if(RecoveryMaintenanceV5.profile(profile)){var primed=RecoveryMaintenanceV5.primed(mc);out.add("local_primed_tnt",primed.json());RecoveryMaintenanceV5.eyePosition(out,mc);RecoveryMaintenanceV5.latestTarget(out,mc,l);RecoveryMaintenanceV5.rayWitness(out,mc);if(!out.get("ready").getAsBoolean()&&problem==null)problem=out.get("reason").getAsString();}
        if(RecoverySurvivalV6.profile(profile)){out.add("local_primed_tnt",RecoveryMaintenanceV5.primed(mc).json());JsonObject facts=RecoverySurvivalV6.observation(mc);out.add("survival",facts);if(!facts.get("complete").getAsBoolean()&&problem==null){problem="survival_observation_incomplete";out.addProperty("ready",false);out.addProperty("reason",problem);}}
        Challenge source=new Challenge(UUID.randomUUID().toString(),sourcePlayer,sourceLevel,sourceNano,sourceTick,sourceX,sourceY,sourceZ,sourceYaw,sourcePitch);
        out.addProperty("observation_id",source.id());
        RecoveryChallengeLease.Refusal refusal=problem==null&&v3(profile)?(RecoveryShortInputLedger.twoSecondLeaseProfile(profile)?freshV5(mc,source,"observe"):freshV3(mc,source,"observe")):null;
        Challenge accepted=problem==null&&(v3(profile)?refusal==null:fresh(mc,source))?source:null;
        if(!RecoveryShortInputLedger.geometryProfile(profile))observation=accepted;
        if(v3(profile))out.add("observation_refusal",refusalJson(refusal));
        if(problem==null&&accepted==null){out.addProperty("ready",false);out.addProperty("reason","observation_context_changed");}
        if(RecoveryShortInputLedger.geometryProfile(profile)){RecoveryNavigationV4.checkResponseBudget(out);observation=accepted;}
        return out;
    }
    /** Actual no-world observation branch, also usable by offline production-code wire tests. */
    static JsonObject describeNoWorld(boolean paused,boolean screenOpen){return describeNoWorld(paused,screenOpen,false);}
    static JsonObject describeNoWorld(boolean paused,boolean screenOpen,boolean interaction){return describeNoWorld(paused,screenOpen,oldRoute(interaction));}
    static JsonObject describeNoWorld(boolean paused,boolean screenOpen,String profile){
        requireProfile(profile);boolean interaction=!profile.equals(RecoveryShortInputLedger.PROFILE);var l=journal();synchronized(l){
            JsonObject j=base(profile);j.addProperty("session",l.session);j.addProperty("owner_generation",l.nextGeneration());
            j.addProperty("bound_owner_id",l.owner());j.addProperty("unknown_lock",l.locked());j.addProperty("active_id",l.active()==null?null:l.active().request.id());
            j.addProperty("ready",false);j.addProperty("reason",l.locked()?l.lockReason():"not_in_world");
            j.add("client_tick",JsonNull.INSTANCE);
            j.add("world_generation",JsonNull.INSTANCE);j.add("player_uuid",JsonNull.INSTANCE);j.addProperty("paused",paused);j.addProperty("screen_open",screenOpen);
            j.addProperty("alive",false);j.add("pose",JsonNull.INSTANCE);j.add("velocity",JsonNull.INSTANCE);j.add("on_ground",JsonNull.INSTANCE);j.add("health",JsonNull.INSTANCE);
            j.add("local_blocks",new JsonArray());j.add("nearby_living",new JsonArray());j.addProperty("nearby_truncated",false);j.addProperty("terrain_complete",false);
            j.addProperty("observation_id",UUID.randomUUID().toString());
            if(v3(profile))j.add("observation_refusal",JsonNull.INSTANCE);
            if(RecoverySurvivalV6.profile(profile)){j.add("survival",RecoverySurvivalV6.unavailable());j.add("local_primed_tnt",new RecoveryMaintenanceV5.PrimedFacts(0,false,false).json());}
            if(RecoveryMaintenanceV5.profile(profile)){j.add("eye_position",JsonNull.INSTANCE);j.add("ray_target_witness",JsonNull.INSTANCE);j.add("latest_target_witness",JsonNull.INSTANCE);j.add("local_primed_tnt",new RecoveryMaintenanceV5.PrimedFacts(0,false,false).json());}
            if(RecoveryShortInputLedger.geometryProfile(profile)){j.addProperty("collision_boxes_complete",false);j.add("step_height",JsonNull.INSTANCE);j.add("sprinting",JsonNull.INSTANCE);}
            if(interaction){j.add("player_bbox",JsonNull.INSTANCE);j.add("selected_slot",JsonNull.INSTANCE);j.add("hotbar",new JsonArray());j.add("ray",JsonNull.INSTANCE);}return j;
        }
    }
    static JsonObject describe(RecoveryShortInputLedger.Entry e){
        var l=journal();synchronized(l){
            var r=e.request;boolean interaction=r.operation()!=null;JsonObject j=base(r.profile());if(interaction)j.addProperty("kind",r.kind());
            if(RecoveryShortInputLedger.planProfile(r.profile())){j.addProperty("plan_version",r.operation().planVersion());j.addProperty("plan_sha256",r.operation().planSha256());}
            j.addProperty("session",r.session());j.addProperty("owner_id",r.ownerId());j.addProperty("id",r.id());
            j.addProperty("world_generation",r.world());j.addProperty("player_uuid",r.player());j.addProperty("owner_generation",r.generation());
            j.addProperty("payload_digest",r.digest());j.addProperty("state",e.state);j.addProperty("protocol_state",e.state);j.addProperty("reason",e.reason);
            j.addProperty(interaction?"requested_calls":"requested_samples",r.samples());j.addProperty(interaction?"applied_calls":"applied_samples",e.applied);j.addProperty("cancellation_generation",e.cancellationGeneration);
            j.addProperty("input_invalidated",e.invalidated);j.addProperty("release_proven",e.released);j.addProperty("settled",e.settled());j.addProperty("unknown_lock",l.locked());
            j.addProperty("protocol_terminal",e.settled());
            j.addProperty("effect_state",e.state.equals("UNKNOWN")?"unknown":e.applied>0?(interaction?"calls_completed":"samples_written"):"not_started");
            j.addProperty("release_state",e.released?(e.effectFenced?"proven":"not_needed"):e.state.equals("UNKNOWN")?"unknown":"pending");
            if(v3(r.profile()))j.add("observation_refusal",refusalJson(e.observationRefusal));
            if(RecoveryShortInputLedger.geometryProfile(r.profile()))j.addProperty("stage_id",r.operation().stageId());
            j.addProperty("settlement_state","not_observed");j.addProperty("gameplay_outcome",interaction&&(r.kind().equals("break_block")||r.kind().equals("place_block")||RecoverySurvivalV6.callKind(r.kind()))?e.gameplay:"not_assessed");return j;
        }
    }
    private static JsonObject base(String profile){JsonObject j=new JsonObject();j.addProperty("schema_version",1);j.addProperty("profile",profile);return j;}
    private static JsonObject xyz(double x,double y,double z){JsonObject j=new JsonObject();j.addProperty("x",x);j.addProperty("y",y);j.addProperty("z",z);return j;}
    private static boolean neutral(Input i){return i!=null&&i.forwardImpulse==0&&i.leftImpulse==0&&!i.up&&!i.down&&!i.left&&!i.right&&!i.jumping&&!i.shiftKeyDown;}
    private static void neutralize(Input i){i.forwardImpulse=i.leftImpulse=0;i.up=i.down=i.left=i.right=i.jumping=i.shiftKeyDown=false;}
    private static RecoveryShortInputLedger.Request parseStart(JsonObject j){
        exactKeys(j,"schema_version","profile","id","session","owner_id","owner_generation","world_generation","player_uuid","forward","strafe","samples","jump_first","ttl_ms","observation_id");header(j);
        return new RecoveryShortInputLedger.Request(string(j,"id"),string(j,"session"),string(j,"owner_id"),integer(j,"owner_generation"),string(j,"world_generation"),string(j,"player_uuid"),number(j,"forward"),number(j,"strafe"),Math.toIntExact(integer(j,"samples")),bool(j,"jump_first"),Math.toIntExact(integer(j,"ttl_ms")),string(j,"observation_id"));
    }
    private static void checkStatusRoute(RecoveryShortInputLedger.Entry e,String profile){if(profile.equals(RecoveryShortInputLedger.INTERACTION_V3_PROFILE)&&RecoveryShortInputLedger.geometryProfile(e.request.profile()))return;checkRoute(e,profile);}
    private static void checkRoute(RecoveryShortInputLedger.Entry e,String profile){if(!e.request.profile().equals(profile))throw new IllegalArgumentException("stored_profile_route_mismatch");}
    static RecoveryShortInputLedger.Request parseInteractionStart(JsonObject j){return parseInteractionStart(j,RecoveryShortInputLedger.INTERACTION_PROFILE);}
    static RecoveryShortInputLedger.Request parseInteractionStart(JsonObject j,String profile){
        if(!Set.of(RecoveryShortInputLedger.INTERACTION_PROFILE,RecoveryShortInputLedger.INTERACTION_V2_PROFILE,RecoveryShortInputLedger.INTERACTION_V3_PROFILE,RecoveryShortInputLedger.NAVIGATION_V4_PROFILE,RecoveryShortInputLedger.MAINTENANCE_V5_PROFILE,RecoveryShortInputLedger.SURVIVAL_V6_PROFILE).contains(profile))throw new IllegalArgumentException("unsupported_profile_schema");
        header(j,profile);String kind=string(j,"kind");
        if(RecoveryShortInputLedger.navigationProfile(profile)&&!Set.of("move","look").contains(kind))throw new IllegalArgumentException("invalid_kind");
        Set<String> keys=new HashSet<>(Set.of("schema_version","profile","kind","id","session","owner_id","owner_generation","world_generation","player_uuid","ttl_ms","observation_id"));
        String[] extra=switch(kind){case "move"->new String[]{"forward","strafe","samples","jump_first"};case "look"->new String[]{"yaw","pitch"};case "attack_blaze"->new String[]{"target_entity_id","target_uuid","target_type","stack_fingerprint"};case "consume_bread"->new String[]{"stack_fingerprint","max_use_ticks"};case "select_hotbar"->new String[]{"slot","stack_fingerprint"};case "break_block"->new String[]{"x","y","z","face","block_id","stack_fingerprint","max_calls"};case "place_block"->new String[]{"x","y","z","anchor_x","anchor_y","anchor_z","anchor_block_id","face","hit_x","hit_y","hit_z","item_id","stack_fingerprint"};default->throw new IllegalArgumentException("invalid_kind");};
        keys.addAll(Arrays.asList(extra));if(RecoveryShortInputLedger.planProfile(profile))keys.addAll(Set.of("plan_version","plan_sha256"));if(RecoveryShortInputLedger.geometryProfile(profile))keys.add("stage_id");if(!j.keySet().equals(keys))throw new IllegalArgumentException("invalid_closed_schema");
        double forward=0,strafe=0,yaw=0,pitch=0;int samples=1,slot=0,x=0,y=0,z=0;boolean jump=false;String fp="",face="",block="";RecoveryShortInputLedger.Placement placement=null;RecoveryShortInputLedger.Survival survival=null;
        switch(kind){
            case "move"->{forward=number(j,"forward");strafe=number(j,"strafe");samples=Math.toIntExact(integer(j,"samples"));jump=bool(j,"jump_first");}
            case "look"->{yaw=number(j,"yaw");pitch=number(j,"pitch");}
            case "attack_blaze"->{survival=new RecoveryShortInputLedger.Survival(signedInt(j,"target_entity_id"),string(j,"target_uuid"),string(j,"target_type"),0);fp=string(j,"stack_fingerprint");}
            case "consume_bread"->{survival=new RecoveryShortInputLedger.Survival(0,"","",Math.toIntExact(integer(j,"max_use_ticks")));fp=string(j,"stack_fingerprint");}
            case "select_hotbar"->{slot=Math.toIntExact(integer(j,"slot"));fp=string(j,"stack_fingerprint");}
            case "place_block"->{if(!RecoveryMaintenanceV5.profile(profile))throw new IllegalArgumentException("invalid_kind");placement=new RecoveryShortInputLedger.Placement(signedInt(j,"x"),signedInt(j,"y"),signedInt(j,"z"),signedInt(j,"anchor_x"),signedInt(j,"anchor_y"),signedInt(j,"anchor_z"),string(j,"anchor_block_id"),string(j,"face"),number(j,"hit_x"),number(j,"hit_y"),number(j,"hit_z"),string(j,"item_id"));fp=string(j,"stack_fingerprint");}
            case "break_block"->{x=signedInt(j,"x");y=signedInt(j,"y");z=signedInt(j,"z");face=string(j,"face");block=string(j,"block_id");fp=string(j,"stack_fingerprint");samples=Math.toIntExact(integer(j,"max_calls"));
                if(profile.equals(RecoveryShortInputLedger.INTERACTION_PROFILE)&&!RecoveryInteraction.TARGETS.contains(new BlockPos(x,y,z)))throw new IllegalArgumentException("unsupported_task_break_target");}
        }
        return new RecoveryShortInputLedger.Request(string(j,"id"),string(j,"session"),string(j,"owner_id"),integer(j,"owner_generation"),string(j,"world_generation"),string(j,"player_uuid"),forward,strafe,samples,jump,Math.toIntExact(integer(j,"ttl_ms")),string(j,"observation_id"),new RecoveryShortInputLedger.Operation(kind,yaw,pitch,slot,fp,x,y,z,face,block,profile,RecoveryShortInputLedger.planProfile(profile)?Math.toIntExact(integer(j,"plan_version")):0,RecoveryShortInputLedger.planProfile(profile)?string(j,"plan_sha256"):"",RecoveryShortInputLedger.geometryProfile(profile)?string(j,"stage_id"):"",placement,survival));
    }
    private static int signedInt(JsonObject j,String key){double n=number(j,key);if(n!=Math.rint(n)||n<Integer.MIN_VALUE||n>Integer.MAX_VALUE)throw new IllegalArgumentException("invalid_"+key);return (int)n;}
    private static void header(JsonObject j){header(j,false);}
    private static void header(JsonObject j,boolean interaction){header(j,oldRoute(interaction));}
    private static String oldRoute(boolean interaction){return interaction?RecoveryShortInputLedger.INTERACTION_PROFILE:RecoveryShortInputLedger.PROFILE;}
    static String activeProfile(){return RecoverySurvivalV6.ENABLED?RecoveryShortInputLedger.SURVIVAL_V6_PROFILE:RecoveryMaintenanceV5.ENABLED?RecoveryShortInputLedger.MAINTENANCE_V5_PROFILE:RecoveryNavigationV4.ENABLED?RecoveryShortInputLedger.NAVIGATION_V4_PROFILE:RecoveryInteraction.V3_ENABLED?RecoveryShortInputLedger.INTERACTION_V3_PROFILE:RecoveryInteraction.V2_ENABLED?RecoveryShortInputLedger.INTERACTION_V2_PROFILE:RecoveryInteraction.ENABLED?RecoveryShortInputLedger.INTERACTION_PROFILE:RecoveryShortInputLedger.PROFILE;}
    private static void requireProfile(String profile){if(!Set.of(RecoveryShortInputLedger.PROFILE,RecoveryShortInputLedger.INTERACTION_PROFILE,RecoveryShortInputLedger.INTERACTION_V2_PROFILE,RecoveryShortInputLedger.INTERACTION_V3_PROFILE,RecoveryShortInputLedger.NAVIGATION_V4_PROFILE,RecoveryShortInputLedger.MAINTENANCE_V5_PROFILE,RecoveryShortInputLedger.SURVIVAL_V6_PROFILE).contains(profile))throw new IllegalArgumentException("unsupported_profile_schema");}
    private static void header(JsonObject j,String profile){if(integer(j,"schema_version")!=1||!profile.equals(string(j,"profile")))throw new IllegalArgumentException("unsupported_profile_schema");}
    private static void exactKeys(JsonObject j,String... keys){if(!j.keySet().equals(Set.of(keys)))throw new IllegalArgumentException("invalid_closed_schema");}
    private static String string(JsonObject j,String k){JsonElement v=j.get(k);if(v==null||!v.isJsonPrimitive()||!v.getAsJsonPrimitive().isString()||!v.getAsString().matches("[A-Za-z0-9._:-]{1,128}"))throw new IllegalArgumentException("invalid_"+k);return v.getAsString();}
    private static double number(JsonObject j,String k){JsonElement v=j.get(k);if(v==null||!v.isJsonPrimitive()||!v.getAsJsonPrimitive().isNumber()||!Double.isFinite(v.getAsDouble()))throw new IllegalArgumentException("invalid_"+k);return v.getAsDouble();}
    private static long integer(JsonObject j,String k){double n=number(j,k);if(n!=Math.rint(n)||n<0||n>9_007_199_254_740_991d)throw new IllegalArgumentException("invalid_"+k);return (long)n;}
    private static boolean bool(JsonObject j,String k){JsonElement v=j.get(k);if(v==null||!v.isJsonPrimitive()||!v.getAsJsonPrimitive().isBoolean())throw new IllegalArgumentException("invalid_"+k);return v.getAsBoolean();}
}

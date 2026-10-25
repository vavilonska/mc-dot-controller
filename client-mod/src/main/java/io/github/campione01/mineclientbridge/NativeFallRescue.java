package io.github.campione01.mineclientbridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;
import net.minecraft.client.KeyMapping;
import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.player.Input;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.tags.FluidTags;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.item.Items;
import net.minecraft.world.level.GameType;
import net.minecraft.world.level.Level;
import net.minecraft.world.phys.BlockHitResult;
import net.neoforged.neoforge.client.ClientHooks;

/** Dedicated, explicitly armed ordinary-input fall rescue. Existing grounded/use_item APIs are unchanged. */
final class NativeFallRescue {
    private static final SingleInputArbiter ARBITER=new SingleInputArbiter();
    private static final FallRescueFence OPERATIONS=new FallRescueFence();
    private static final Map<String,FallRescuePolicy.Arm> SEEN_ARMS=new LinkedHashMap<>();
    private static FallRescuePolicy.Arm authorization,lastAuthorization;
    private static LocalPlayer player;
    private static ClientLevel level;
    private static Object serverIdentity;
    private static long deadline;
    private static int armRevision, tick, usedEpisodes;
    private static boolean airborneLatched;
    private static String state="disarmed",reason="not_armed";
    private static Episode current;
    private static JsonObject lastEpisode,lastObservation,supersededCallbackFailure;
    private static final class Episode {
        final FallRescueEpisode proof;
        final SingleInputArbiter.Lease lease;
        final FallRescueServerEvidence server=new FallRescueServerEvidence();
        final int slot;
        final net.minecraft.world.item.ItemStack bucketStack;
        final LocalPlayer player;
        final ClientLevel level;
        FallRescueGeometry.Landing landing;
        int baselineTick=-1,dispatchTick=-1,lastEvidenceTick=-1;
        boolean beforeEffect,preemptionVerified;
        String interactionResult;
        JsonObject interrupted;
        Episode(LocalPlayer player,ClientLevel level,int slot,net.minecraft.world.item.ItemStack bucketStack,
                FallRescueGeometry.Landing landing,String id,int startTick){
            proof=new FallRescueEpisode(id,startTick);
            lease=ARBITER.claim(id);this.slot=slot;this.landing=landing;this.player=player;this.level=level;
            this.bucketStack=bucketStack; // All callback-backed reads preceded the final ownership fence.
        }
    }
    static JsonObject arm(FallRescuePolicy.Arm request){
        NativeRecoveryShortInput.requireLegacyAllowed();
        Minecraft mc=Minecraft.getInstance();thread(mc);long operation=OPERATIONS.stamp();
        FallRescuePolicy.Arm seen=SEEN_ARMS.get(request.id());
        if(seen!=null){require(seen.equals(request),"fall_rescue_arm_id_conflict");require(authorization==seen,"fall_rescue_arm_id_retired");return status();}
        require(authorization==null&&!ARBITER.blocked(),"fall_rescue_owner_busy");
        require(SEEN_ARMS.size()<128,"fall_rescue_arm_history_full_restart_required");
        require(request.session().equals(ClientActions.session()),"fall_rescue_action_session_changed");
        require(mc.player!=null&&mc.level!=null,"fall_rescue_not_in_world");
        require(request.world().equals(WorldGeneration.current(mc.level))&&request.player().equals(mc.player.getUUID().toString()),"fall_rescue_context_binding_changed");
        LocalPlayer armPlayer=mc.player;ClientLevel armLevel=mc.level;
        String problem=context(mc,false);require(problem==null,problem);
        require(NativeFallRescueDispatch.ready(),"fall_rescue_native_fences_unavailable");
        require(ExternalControllerGuard.idle(mc),"fall_rescue_external_controller_unknown");
        require(bucketSlot(mc)>=0,"fall_rescue_water_bucket_required_in_hotbar");
        ClientActions.requireFallRescueAdmission(request.permittedActionIds());
        require(!BridgeServer.hasHeldInputs()&&GuardedGameMovement.LEASES.status().ownerRequestId()==null,"fall_rescue_unregistered_input_owner");
        if(!ClientActions.hasRuntimeAction())require(neutral(mc),"fall_rescue_unregistered_input_owner");
        require(request.world().equals(WorldGeneration.current(mc.level))&&request.player().equals(mc.player.getUUID().toString()),"fall_rescue_final_arm_binding_changed");
        Object capturedServer=mc.getSingleplayerServer();
        require(ExternalControllerGuard.idle(mc),"fall_rescue_external_controller_unknown");
        require(mc.player==armPlayer&&mc.level==armLevel&&authorization==null&&!ARBITER.blocked()&&!NativeExternalNavigation.blocksInput(),"fall_rescue_reentrant_owner_changed");
        OPERATIONS.commit(operation);
        player=mc.player;level=mc.level;serverIdentity=capturedServer;authorization=request;
        deadline=System.nanoTime()+request.ttlMs()*1_000_000L;armRevision=1;usedEpisodes=0;airborneLatched=false;
        SEEN_ARMS.put(request.id(),request);lastAuthorization=request;lastEpisode=null;lastObservation=null;state="armed";reason="monitoring_local_ticks";return status();
    }
    static JsonObject renew(FallRescuePolicy.Renew r){
        Minecraft mc=Minecraft.getInstance();thread(mc);long operation=OPERATIONS.stamp();require(authorization!=null,"fall_rescue_not_armed");
        require(authorization.id().equals(r.id())&&authorization.owner().equals(r.owner()),"fall_rescue_owner_changed");
        require(r.revision()==armRevision,"fall_rescue_arm_revision_changed");
        require(System.nanoTime()<deadline,"fall_rescue_lease_expired");
        String problem=context(mc,true);require(problem==null,problem);
        require(ExternalControllerGuard.idle(mc),"fall_rescue_external_controller_unknown");
        require(authorization!=null&&authorization.id().equals(r.id())&&authorization.owner().equals(r.owner())&&System.nanoTime()<deadline&&!NativeExternalNavigation.blocksInput(),"fall_rescue_renew_owner_changed");
        OPERATIONS.commit(operation);deadline=System.nanoTime()+r.ttlMs()*1_000_000L;armRevision++;return status();
    }
    static JsonObject disarm(FallRescuePolicy.Stop r){
        thread(Minecraft.getInstance());
        if(authorization!=null)require(authorization.id().equals(r.id())&&authorization.owner().equals(r.owner()),"fall_rescue_owner_changed");
        else require(SEEN_ARMS.containsKey(r.id())&&SEEN_ARMS.get(r.id()).owner().equals(r.owner()),"fall_rescue_unknown_arm");
        stop("explicit_disarm");return status();
    }
    private static final FallRescueAdjudication.Ledger ADJUDICATIONS=new FallRescueAdjudication.Ledger();
    private static boolean adjudicationPrivateContext(Minecraft mc,FallRescuePolicy.Arm original,
            LocalPlayer expectedPlayer,ClientLevel expectedLevel,Object expectedServer){
        // Re-read after external/input callbacks. Vanilla leaf getters below are cooperative;
        // the final pure owner/world fence still rejects reentrant MDC/context changes.
        return context(mc,false)==null && mc.player==expectedPlayer && mc.level==expectedLevel
            && expectedServer instanceof net.minecraft.client.server.IntegratedServer server
            && mc.getSingleplayerServer()==server && mc.hasSingleplayerServer() && !server.isPublished()
            && original.player().equals(expectedPlayer.getUUID().toString());
    }
    static JsonObject adjudicationSnapshot(){
        Minecraft mc=Minecraft.getInstance();thread(mc);var original=lastAuthorization;var ended=lastEpisode;
        long operation=OPERATIONS.stamp(),revision=ARBITER.revision(),actionRevision=ClientActions.externalOwnerRevision();
        var capturedPlayer=mc.player;var capturedLevel=mc.level;var capturedMode=mc.gameMode;var capturedServer=serverIdentity;
        JsonObject source=status();boolean eligible=false;
        try{
            eligible=original!=null&&ended!=null&&authorization==null&&current==null&&capturedPlayer==player&&capturedLevel==level
                &&FallRescueAdjudicationFence.prove(()->ExternalControllerGuard.idle(mc),()->neutral(mc),
                    ()->adjudicationPrivateContext(mc,original,capturedPlayer,capturedLevel,capturedServer),
                    ()->lastAuthorization==original&&lastEpisode==ended&&authorization==null&&current==null
                        &&mc.player==capturedPlayer&&mc.level==capturedLevel&&mc.gameMode==capturedMode&&mc.screen==null
                        &&serverIdentity==capturedServer&&OPERATIONS.stamp()==operation&&ARBITER.revision()==revision
                        &&ClientActions.externalOwnerRevision()==actionRevision&&!ClientActions.hasRuntimeAction()&&!NativeExternalNavigation.blocksInput()
                        &&original.session().equals(ClientActions.session())&&WorldGeneration.matches(capturedLevel,original.world()));
        }catch(RuntimeException unavailable){eligible=false;}
        JsonObject j=new JsonObject();j.addProperty("adjudication_schema_version",1);j.addProperty("arbiter_revision",revision);
        j.addProperty("current_neutral_context_proven",eligible);j.add("native_status",source);return j;
    }
    private static JsonObject adjudicationEnvelope(JsonObject receipt){
        JsonObject j=new JsonObject();j.addProperty("adjudication_schema_version",1);j.add("receipt",receipt);
        j.add("inspection",adjudicationSnapshot());return j;
    }
    static JsonObject adjudicationReceipt(String id){thread(Minecraft.getInstance());return adjudicationEnvelope(ADJUDICATIONS.read(id));}
    static JsonObject adjudicate(FallRescueAdjudication.Request r){
        Minecraft mc=Minecraft.getInstance();thread(mc);ADJUDICATIONS.requireNew(r.id());
        var original=lastAuthorization;var ended=lastEpisode;long operation=OPERATIONS.stamp();
        var originalPlayer=player;var originalLevel=level;var originalMode=mc.gameMode;var originalServer=serverIdentity;
        long actionRevision=ClientActions.externalOwnerRevision();
        require(authorization==null&&current==null&&original!=null&&ended!=null,"fall_adjudication_ended_original_required");
        require(ARBITER.revision()==r.revision()&&"native_fall_rescue_original_action_quarantined".equals(ARBITER.reason()),"fall_adjudication_exact_quarantine_required");
        require(original.id().equals(r.arm())&&original.owner().equals(r.owner())&&original.session().equals(r.session())
            &&original.world().equals(r.world())&&original.player().equals(r.player())&&original.permittedActionIds().equals(java.util.Set.of(r.action())),"fall_adjudication_original_binding_changed");
        require(ended.get("episode_id").getAsString().equals(r.episode())&&ended.get("rescue_confirmed").getAsBoolean()
            &&ended.has("interrupted_action")&&ended.getAsJsonObject("interrupted_action").has("action_id")
            &&ended.getAsJsonObject("interrupted_action").get("action_id").getAsString().equals(r.action()),"fall_adjudication_confirmed_rescue_required");
        require(FallRescueAdjudicationFence.prove(()->ExternalControllerGuard.idle(mc),()->neutral(mc),
            ()->adjudicationPrivateContext(mc,original,originalPlayer,originalLevel,originalServer),
            ()->authorization==null&&current==null&&lastAuthorization==original&&lastEpisode==ended
                &&OPERATIONS.stamp()==operation&&mc.player==originalPlayer&&mc.level==originalLevel&&mc.gameMode==originalMode&&mc.screen==null
                &&serverIdentity==originalServer&&ClientActions.externalOwnerRevision()==actionRevision&&!ClientActions.hasRuntimeAction()&&!NativeExternalNavigation.blocksInput()
                &&r.session().equals(ClientActions.session())&&WorldGeneration.matches(originalLevel,r.world())
                &&ARBITER.revision()==r.revision()),"fall_adjudication_current_context_or_owner_unproven");
        // All callback-backed reads precede this pure CAS. Preserve the old action and episode.
        JsonObject proof=FallRescueAdjudication.receipt(r,r.revision()+1);
        ADJUDICATIONS.requireNew(r.id());ARBITER.adjudicateOriginal(r.revision());OPERATIONS.changed();
        reason="operator_adjudicated_original_effects_unknown";state="disarmed";
        ADJUDICATIONS.commit(r.id(),proof);return adjudicationEnvelope(proof.deepCopy());
    }
    static boolean blocksInput(){return ARBITER.blocked();}
    static boolean armedOrBlocked(){return authorization!=null||ARBITER.blocked();} // Pure final input-owner fence.
    static void requireOrdinaryAdmission(){if(ARBITER.blocked())throw new ClientActionRequest.Rejected(409,ARBITER.reason());}
    static void stop(String stopReason){
        Minecraft mc=Minecraft.getInstance();thread(mc);
        OPERATIONS.changed();authorization=null;reason=stopReason;state="disarmed";
        Episode e=current;current=null; // Detach before callbacks, so nested stop cannot clean twice.
        if(e==null){ARBITER.stop();if(ARBITER.quarantined())state="quarantined";return;}
        e.proof.end(stopReason);
        try{
            // Unknown is latched before cleanup can throw or admit a replacement owner.
            if(!ARBITER.stopAndCleanup(quarantineReason(e),()->cleanup(mc,e)))reason="fall_rescue_stop_cleanup_unconfirmed";
        }finally{
            lastEpisode=episodeStatus(e);
            if(ARBITER.quarantined())state="quarantined";
        }
    }
    private static String quarantineReason(Episode e){
        if(e.proof.attempted()&&!e.proof.confirmed())return "native_fall_rescue_unknown_outcome_quarantined";
        if(!e.preemptionVerified)return "native_fall_rescue_input_release_unconfirmed";
        if(e.interrupted!=null&&e.interrupted.has("requires_reconciliation_before_retry")&&e.interrupted.get("requires_reconciliation_before_retry").getAsBoolean())return "native_fall_rescue_original_action_quarantined";
        return null;
    }
    static void preTick(Minecraft mc){
        tick++;
        if(authorization==null)return;
        FallRescuePolicy.Arm tickAuthorization=authorization;long operation=OPERATIONS.stamp();
        LocalPlayer tickPlayer=mc.player;ClientLevel tickLevel=mc.level;Episode affected=current;
        if(System.nanoTime()>=deadline){stop("arm_lease_expired");return;}
        try{
            String problem=context(mc,true);
            if(!FallRescueFence.sameContext(tickAuthorization,operation,affected,authorization,OPERATIONS.stamp(),current))return;
            if(problem!=null){stop(problem);return;}
            JsonObject observation=new JsonObject();observation.addProperty("client_tick",tick);observation.addProperty("health",tickPlayer.getHealth());
            observation.addProperty("fall_distance",tickPlayer.fallDistance);observation.addProperty("velocity_y",tickPlayer.getDeltaMovement().y);
            observation.addProperty("velocity_x",tickPlayer.getDeltaMovement().x);observation.addProperty("velocity_z",tickPlayer.getDeltaMovement().z);
            observation.addProperty("on_ground",tickPlayer.onGround());
            if(!FallRescueFence.sameContext(tickAuthorization,operation,affected,authorization,OPERATIONS.stamp(),current))return;
            lastObservation=observation;
            if(current!=null){advance(mc,current);return;}
            boolean landed=tickPlayer.onGround()||tickPlayer.isInWater();
            if(!FallRescueFence.sameContext(tickAuthorization,operation,affected,authorization,OPERATIONS.stamp(),current))return;
            if(landed){airborneLatched=false;return;}
            if(airborneLatched||usedEpisodes>=authorization.episodes())return;
            FallRescueGeometry.Landing landing=FallRescueGeometry.forecast(mc);
            if(!FallRescueFence.sameContext(tickAuthorization,operation,affected,authorization,OPERATIONS.stamp(),current))return;
            if(landing==null){reason="no_supported_loaded_landing";return;}
            if(!FallRescuePolicy.dangerous(mc.player.fallDistance,landing.descent(),mc.player.getHealth()))return;
            int slot=bucketSlot(mc);
            if(!FallRescueFence.sameContext(tickAuthorization,operation,affected,authorization,OPERATIONS.stamp(),current))return;
            if(slot<0){reason="water_bucket_unavailable";return;}
            require(ExternalControllerGuard.idle(mc),"fall_rescue_external_controller_unknown");
            ClientActions.requireFallRescueAdmission(authorization.permittedActionIds());
            require(!BridgeServer.hasHeldInputs()&&GuardedGameMovement.LEASES.status().ownerRequestId()==null,"fall_rescue_unregistered_input_owner");
            if(!ClientActions.hasRuntimeAction())require(neutral(mc),"fall_rescue_unregistered_input_owner");
            var episodeStack=tickPlayer.getInventory().getItem(slot);
            require(episodeStack.is(Items.WATER_BUCKET)&&episodeStack.getCount()==1,"fall_rescue_bucket_changed");
            require(ExternalControllerGuard.idle(mc),"fall_rescue_external_controller_unknown");
            require(authorization==tickAuthorization&&OPERATIONS.stamp()==operation&&mc.player==tickPlayer&&mc.level==tickLevel
                &&System.nanoTime()<deadline&&!ARBITER.blocked()&&!NativeExternalNavigation.blocksInput(),"fall_rescue_preemption_owner_changed");
            Episode e=new Episode(tickPlayer,tickLevel,slot,episodeStack,landing,tickAuthorization.id()+":"+(usedEpisodes+1),tick);
            usedEpisodes++;current=e;affected=e;airborneLatched=true;state="rescuing";
            Object cleanupGameMode=mc.gameMode;
            e.interrupted=ClientActions.preemptForFallRescue(authorization.permittedActionIds(),
                ()->FallRescueFence.sameContext(tickAuthorization,operation,e,authorization,OPERATIONS.stamp(),current)
                    &&owns(e)&&mc.player==e.player&&mc.level==e.level&&mc.gameMode==cleanupGameMode&&mc.screen==null
                    &&tickAuthorization.session().equals(ClientActions.session())&&WorldGeneration.matches(e.level,tickAuthorization.world())
                    &&System.nanoTime()<deadline&&!e.proof.timedOut(tick)&&!e.preemptionVerified&&!e.proof.attempted());
            var inventory=e.player.getInventory();
            require(ExternalControllerGuard.idle(mc),"fall_rescue_external_controller_unknown");
            require(owns(e),"fall_rescue_owner_changed_during_preemption");
            require(FallRescueFence.afterHook(()->neutral(mc)&&e.player.getInventory()==inventory,
                ()->owns(e)&&mc.player==e.player&&mc.level==e.level&&System.nanoTime()<deadline
                &&!e.proof.timedOut(tick)),"fall_rescue_input_release_unconfirmed");
            e.preemptionVerified=true;
            inventory.selected=slot; // Captured original inventory; no getter after the final fence.
            require(FallRescueFence.afterHook(()->e.player.getMainHandItem()==e.bucketStack&&e.bucketStack.is(Items.WATER_BUCKET),
                ()->owns(e)&&mc.player==e.player&&mc.level==e.level&&System.nanoTime()<deadline),"fall_rescue_bucket_selection_unconfirmed");
            reason="tracking_fall";requestSample(mc,e);advance(mc,e);
        }catch(RuntimeException failure){fail(mc,failure,tickAuthorization,operation,affected);}
    }
    static void postTick(Minecraft mc){
        Episode e=current;FallRescuePolicy.Arm expected=authorization;long operation=OPERATIONS.stamp();
        if(e==null||expected==null)return;
        try{advance(mc,e);}catch(RuntimeException failure){fail(mc,failure,expected,operation,e);}
    }
    static boolean input(Minecraft mc,Input input){
        if(current==null||!owns(current))return false;
        // Quarantine blocks automated admissions only; explicit stop returns manual control.
        input.forwardImpulse=input.leftImpulse=0;
        input.up=input.down=input.left=input.right=input.jumping=input.shiftKeyDown=false;
        return true;
    }
    private static void advance(Minecraft mc,Episode e){
        if(!owns(e))return;
        FallRescuePolicy.Arm expected=authorization;long operation=OPERATIONS.stamp();
        String problem=context(mc,true);
        if(!FallRescueFence.sameContext(expected,operation,e,authorization,OPERATIONS.stamp(),current))return;
        if(problem!=null){stop(problem);return;}
        require(ExternalControllerGuard.idle(mc),"fall_rescue_external_controller_unknown");
        require(owns(e)&&mc.player==e.player&&mc.level==e.level&&System.nanoTime()<deadline,"fall_rescue_tracking_owner_changed");
        if(e.proof.timedOut(tick)){terminal(mc,e,"episode_time_budget_exhausted");return;}
        var sample=e.server.latest();
        if(sample!=null&&sample.episode().equals(e.proof.id)&&sample.target().equals(e.landing.water())&&sample.valid()){
            if(!e.proof.attempted()&&sample.air()&&sample.waterBucket())e.baselineTick=sample.tick();
            if(e.proof.attempted()&&sample.tick()>e.baselineTick&&sample.tick()>e.lastEvidenceTick){
                e.lastEvidenceTick=sample.tick();
                if(!sample.alive()){terminal(mc,e,"player_died_rescue_not_confirmed");return;}
                e.proof.serverObservation(sample.water(),sample.emptyBucket(),sample.landed());
                if(e.proof.confirmed()){terminal(mc,e,e.proof.outcome());return;}
            }
        }
        if(e.proof.attempted()){
            e.proof.predictedWater(mc.level.getFluidState(e.landing.water()).is(FluidTags.WATER));
            requestSample(mc,e);return;
        }
        if(mc.player.onGround()||mc.player.isInWater()){terminal(mc,e,"landed_before_dispatch");return;}
        var forecast=FallRescueGeometry.forecast(mc);
        if(!owns(e))return;
        if(forecast==null){reason="landing_forecast_unavailable";return;}
        if(!forecast.support().equals(e.landing.support())){e.landing=forecast;e.baselineTick=-1;}
        else e.landing=forecast;
        requestSample(mc,e);
        if(mc.player.getDeltaMovement().y>=0||!FallRescueGeometry.reachable(mc,e.landing)||e.baselineTick<0)return;
        require(ExternalControllerGuard.idle(mc),"fall_rescue_external_controller_unknown");
        require(FallRescueFence.afterHook(()->neutral(mc)&&mc.player.getInventory().selected==e.slot
            &&mc.player.getMainHandItem()==e.bucketStack&&e.bucketStack.is(Items.WATER_BUCKET)&&e.bucketStack.getCount()==1,
            ()->owns(e)&&mc.player==e.player&&mc.level==e.level&&System.nanoTime()<deadline&&!e.proof.timedOut(tick)),"fall_rescue_input_or_bucket_changed");
        FallRescueGeometry.aim(e.player,e.landing.aim(),()->owns(e)&&mc.player==e.player&&mc.level==e.level
            &&System.nanoTime()<deadline&&!e.proof.timedOut(tick));
        require(owns(e),"fall_rescue_aim_owner_changed");
        var ray=FallRescueGeometry.currentRay(mc,e.landing.support());
        if(!owns(e))return;
        if(ray==null){reason="native_eye_ray_not_supported_top";return;}
        var event=ClientHooks.onClickInput(1,mc.options.keyUse,InteractionHand.MAIN_HAND);
        require(!event.isCanceled(),"fall_rescue_use_cancelled_by_mod");
        beforeEffect(e,false); // Revalidate after hooks. No held key or offhand fallback.
        e.proof.attempt();e.dispatchTick=tick;
        InteractionResult result=NativeFallRescueDispatch.use(e,()->mc.gameMode.useItem(e.player,InteractionHand.MAIN_HAND));
        e.interactionResult=result.name().toLowerCase(Locale.ROOT);
        if(!owns(e))return;
        // FAIL is not proof of no effect, and SUCCESS is not server acknowledgement.
        e.proof.predictedWater(e.level.getFluidState(e.landing.water()).is(FluidTags.WATER));
        if(!owns(e))return;
        reason="observing_authoritative_outcome";requestSample(mc,e);
    }
    private static void requestSample(Minecraft mc,Episode e){
        require(mc.getSingleplayerServer()==serverIdentity,"fall_rescue_server_changed");
        e.server.request(mc.getSingleplayerServer(),e.level.dimension(),e.player.getUUID(),e.slot,e.landing.water(),e.proof.id);
    }
    static void beforeEffect(Object token,boolean actualEffect){
        Episode e=(Episode)token;Minecraft mc=Minecraft.getInstance();
        require(owns(e),"fall_rescue_effect_owner_changed");
        String problem=context(mc,true);require(problem==null,problem);
        require(tick-e.proof.startTick<FallRescuePolicy.MAX_EPISODE_TICKS&&System.nanoTime()<deadline,"fall_rescue_effect_expired");
        require(mc.player.getInventory().selected==e.slot&&mc.player.getMainHandItem().is(Items.WATER_BUCKET)
            &&mc.player.getMainHandItem().getCount()==1&&!mc.player.getCooldowns().isOnCooldown(Items.WATER_BUCKET),"fall_rescue_bucket_changed");
        require(FallRescueGeometry.targetClear(mc,e.landing.support()),"fall_rescue_target_changed");
        require(FallRescueGeometry.currentRay(mc,e.landing.support())!=null,"fall_rescue_eye_ray_changed");
        require(ExternalControllerGuard.idle(mc),"fall_rescue_external_controller_unknown");
        require(FallRescueFence.afterHook(()->neutral(mc)&&mc.player.getMainHandItem()==e.bucketStack
            &&e.bucketStack.is(Items.WATER_BUCKET)&&e.bucketStack.getCount()==1,
            ()->owns(e)&&mc.player==e.player&&mc.level==e.level
            &&System.nanoTime()<deadline&&!e.proof.timedOut(tick)),"fall_rescue_final_effect_fence_changed");
        if(actualEffect){require(!e.beforeEffect,"fall_rescue_duplicate_effect_forbidden");e.beforeEffect=true;}
    }
    static void bucketEffect(Object token,Object bucket,Player p,Level l,BlockPos target,BlockHitResult hit,net.minecraft.world.item.ItemStack stack,boolean finalEffect){
        Episode e=(Episode)token;
        require(bucket==Items.WATER_BUCKET&&stack==e.bucketStack&&p==e.player&&p.getMainHandItem()==stack
            &&stack.is(Items.WATER_BUCKET)&&stack.getCount()==1&&l==e.level&&target.equals(e.landing.water())&&hit!=null
            &&hit.getBlockPos().equals(e.landing.support())&&hit.getDirection()==net.minecraft.core.Direction.UP,"fall_rescue_bucket_target_changed");
        beforeEffect(e,finalEffect);
    }
    static void packet(Object token,net.minecraft.network.protocol.game.ServerboundUseItemPacket packet){
        Episode e=(Episode)token;Minecraft mc=Minecraft.getInstance();
        require(owns(e)&&e.proof.attempted()&&e.beforeEffect,"fall_rescue_packet_owner_changed");
        String problem=context(mc,true);require(problem==null,problem);
        require(packet.getHand()==InteractionHand.MAIN_HAND&&mc.player.getInventory().selected==e.slot
            &&packet.getYRot()==e.player.getYRot()&&packet.getXRot()==e.player.getXRot(),"fall_rescue_packet_binding_changed");
        require(FallRescueGeometry.currentRay(mc,e.landing.support())!=null,"fall_rescue_packet_ray_changed");
        require(ExternalControllerGuard.idle(mc),"fall_rescue_external_controller_unknown");
        require(owns(e)&&mc.player==e.player&&mc.level==e.level&&System.nanoTime()<deadline
            &&!e.proof.timedOut(tick),"fall_rescue_packet_owner_or_deadline_changed");e.proof.packet();
    }
    private static boolean owns(Episode e){return current==e&&authorization!=null&&ARBITER.owns(e.lease)&&!NativeExternalNavigation.blocksInput();}
    private static void terminal(Minecraft mc,Episode e,String outcome){
        if(current!=e)return;OPERATIONS.changed();e.proof.end(outcome);
        current=null;
        String pending=quarantineReason(e);
        try{ARBITER.stopAndCleanup(pending,()->cleanup(mc,e));}
        finally{
            ARBITER.release(e.lease);lastEpisode=episodeStatus(e);reason=outcome;
            if(ARBITER.quarantined()){authorization=null;state="quarantined";}
            else if(authorization==null||usedEpisodes>=authorization.episodes()){authorization=null;state="disarmed";}
            else state="armed";
        }
    }
    private static void fail(Minecraft mc,RuntimeException failure,FallRescuePolicy.Arm expected,long operation,Episode affected){
        String failureReason=failure instanceof ClientActionRequest.Rejected?failure.getMessage():"fall_rescue_native_callback_failed";
        if(!FallRescueFence.sameContext(expected,operation,affected,authorization,OPERATIONS.stamp(),current)){
            // One bounded diagnostic; a stale stack cannot stop or clear the replacement owner.
            JsonObject evidence=new JsonObject();evidence.addProperty("schema_version",1);
            evidence.addProperty("arm_id",expected.id());evidence.addProperty("operation_revision",operation);
            evidence.addProperty("reason",failureReason);evidence.addProperty("diagnostic_only",true);
            evidence.addProperty("original_outcome","unknown_superseded_callback");
            evidence.addProperty("dispatch_attempted",affected!=null&&affected.proof.attempted());
            evidence.addProperty("replacement_touched",false);
            if(affected!=null)evidence.addProperty("episode_id",affected.proof.id);
            supersededCallbackFailure=evidence;return;
        }
        reason=failureReason;
        if(affected!=null)terminal(mc,affected,reason);else stop(reason);
    }
    private static void cleanup(Minecraft mc,Episode e){
        // Only our neutral fields, no restoration of a previous action/slot/aim and no replay.
        inputNeutral(e.player.input);mc.options.keyUse.setDown(false);mc.options.keyAttack.setDown(false);
    }
    private static void inputNeutral(Input i){if(i!=null){i.forwardImpulse=i.leftImpulse=0;i.up=i.down=i.left=i.right=i.jumping=i.shiftKeyDown=false;}}
    private static int bucketSlot(Minecraft mc){for(int i=0;i<9;i++){var stack=mc.player.getInventory().getItem(i);if(stack.is(Items.WATER_BUCKET)&&stack.getCount()==1)return i;}return -1;}
    private static boolean neutral(Minecraft mc){
        if(BridgeServer.hasHeldInputs()||ClientInputIsolation.statistics().heldKeys()!=0||mc.player.isUsingItem()||GuardedGameMovement.LEASES.status().ownerRequestId()!=null)return false;
        for(KeyMapping key:mc.options.keyMappings)if(key.isDown())return false;
        Input i=mc.player.input;return i!=null&&i.forwardImpulse==0&&i.leftImpulse==0&&!i.up&&!i.down&&!i.left&&!i.right&&!i.jumping&&!i.shiftKeyDown;
    }
    private static String context(Minecraft mc,boolean binding){
        if(mc.player==null||mc.level==null||mc.gameMode==null)return "fall_rescue_not_in_world";
        if(!CapabilityGuard.privateSingleplayer(mc)||mc.level.players().size()!=1||mc.gameMode.getPlayerMode()!=GameType.SURVIVAL)return "fall_rescue_private_singleplayer_survival_required";
        if(binding&&(mc.player!=player||mc.level!=level||mc.getSingleplayerServer()!=serverIdentity
                ||!authorization.session().equals(ClientActions.session())||!authorization.world().equals(WorldGeneration.current(mc.level))))return "fall_rescue_context_changed";
        if(mc.isPaused()||mc.screen!=null)return "fall_rescue_user_pause_or_screen";
        var p=mc.player;
        if(!p.isAlive()||p.isDeadOrDying()||p.getHealth()<=0)return "fall_rescue_player_unavailable";
        if(mc.level.dimension()!=Level.OVERWORLD&&mc.level.dimension()!=Level.END||mc.level.dimensionType().ultraWarm())return "fall_rescue_dimension_unsupported";
        if(p.isPassenger()||p.isFallFlying()||p.getAbilities().flying||p.getAbilities().mayfly||p.noPhysics||p.isNoGravity()
                ||p.isInLava()||p.onClimbable()||Math.abs(p.getGravity()-.08)>1e-8||!p.getActiveEffects().isEmpty())return "fall_rescue_physics_unsupported";
        if(mc.getCameraEntity()!=p||!FallRescueGeometry.finite(p.position())||!FallRescueGeometry.finite(p.getDeltaMovement()))return "fall_rescue_player_pose_unknown";
        return null;
    }
    private static boolean externalControllerUnknown(){
        // Capability discovery off the game thread cannot manufacture an idle proof.
        // Coherent state snapshots and every admission/effect query again on the game thread.
        try{return !ExternalControllerGuard.idle(Minecraft.getInstance());}
        catch(RuntimeException|LinkageError unknown){return true;}
    }
    static JsonObject status(){
        JsonObject j=new JsonObject();j.addProperty("fall_rescue_schema_version",1);j.addProperty("status",state);j.addProperty("reason",reason);
        j.addProperty("armed",authorization!=null);j.addProperty("input_owned",current!=null&&owns(current));j.addProperty("automation_blocked",ARBITER.blocked());j.addProperty("unknown_outcome_quarantined",ARBITER.quarantined());
        j.addProperty("arm_revision",armRevision);j.addProperty("episodes_used",usedEpisodes);j.addProperty("no_auto_resume",true);
        j.addProperty("remaining_ms",authorization==null?0:Math.max(0,(deadline-System.nanoTime())/1_000_000));
        FallRescuePolicy.Arm identity=authorization!=null?authorization:lastAuthorization;
        if(identity!=null){j.addProperty("arm_id",identity.id());j.addProperty("owner_id",identity.owner());j.addProperty("action_session",identity.session());j.addProperty("world_generation",identity.world());j.addProperty("player_uuid",identity.player());}
        if(lastObservation!=null)j.add("last_client_observation",lastObservation.deepCopy());
        if(supersededCallbackFailure!=null)j.add("superseded_callback_failure",supersededCallbackFailure.deepCopy());
        if(current!=null)j.add("episode",episodeStatus(current));else if(lastEpisode!=null)j.add("last_episode",lastEpisode.deepCopy());
        return j;
    }
    private static JsonObject episodeStatus(Episode e){
        var p=e.proof;JsonObject j=new JsonObject();j.addProperty("episode_id",p.id);j.addProperty("outcome",p.outcome());
        j.addProperty("age_ticks",tick-p.startTick);j.addProperty("hotbar_slot",e.slot);j.addProperty("dispatch_attempted",p.attempted());
        j.addProperty("packet_send_fence_passed",p.packetSent());j.addProperty("client_prediction_water",p.clientWater());
        j.addProperty("server_water_observed",p.serverWater());j.addProperty("server_bucket_transition_observed",p.serverBucket());
        j.addProperty("server_landed_alive_observed",p.landedAlive());j.addProperty("rescue_confirmed",p.confirmed());
        j.addProperty("confirmation_basis","correlated_readonly_integrated_server_state_after_pre_dispatch_baseline");
        j.addProperty("interaction_result",e.interactionResult);j.addProperty("baseline_server_tick",e.baselineTick);
        JsonObject target=new JsonObject();target.addProperty("x",e.landing.water().getX());target.addProperty("y",e.landing.water().getY());target.addProperty("z",e.landing.water().getZ());j.add("water_target",target);
        if(e.interrupted!=null)j.add("interrupted_action",e.interrupted.deepCopy());return j;
    }
    static JsonObject capabilities(){
        JsonObject j=new JsonObject();j.addProperty("schema_version",1);j.addProperty("explicit_arm_required",true);
        j.addProperty("default_ttl_ms",FallRescuePolicy.DEFAULT_TTL_MS);j.addProperty("min_ttl_ms",FallRescuePolicy.MIN_TTL_MS);j.addProperty("max_ttl_ms",FallRescuePolicy.MAX_TTL_MS);
        j.addProperty("max_episodes",FallRescuePolicy.MAX_EPISODES);j.addProperty("max_episode_ticks",FallRescuePolicy.MAX_EPISODE_TICKS);
        j.addProperty("owner_renewable",true);j.addProperty("private_integrated_server_only",true);j.addProperty("multiplayer",false);
        j.addProperty("native_fences_ready",NativeFallRescueDispatch.ready());j.addProperty("external_controller_unknown",externalControllerUnknown());j.addProperty("external_controller_policy","fresh_pinned_external_idle_proof_required_v1");
        j.addProperty("physical_guarantee",false);j.addProperty("native_use_item_once_per_episode",true);j.addProperty("unknown_outcome_retry",false);
        JsonArray dimensions=new JsonArray();dimensions.add("minecraft:overworld");dimensions.add("minecraft:the_end");j.add("dimensions",dimensions);
        j.addProperty("surface_scope","supported_vanilla_inert_full_solid_top_and_two_air_cells");return j;
    }
    private static void require(boolean ok,String reason){FallRescuePolicy.require(ok,reason);}
    private static void thread(Minecraft mc){require(mc.isSameThread(),"fall_rescue_minecraft_thread_required");}
    private NativeFallRescue() { }
}

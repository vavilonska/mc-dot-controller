package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import net.minecraft.client.Minecraft;

/** Explicit stop-only native owner. It never starts a path, clears keys, or force-cancels. */
final class NativeExternalNavigation {
    private static final ExternalNavigationLease LEASES=new ExternalNavigationLease();
    private static Object player,level,gameMode;
    private static final java.util.Map<String,JsonObject> proofs=new java.util.HashMap<>();
    private static long ownerRevision;
    static boolean blocksInput(){return LEASES.blocked()||NativeManagedNavigation.blocksInput();}
    static void requireOrdinaryAdmission(){require(!blocksInput(),"external_navigation_original_owner_unresolved");}
    static JsonObject stop(ExternalNavigationLease.Request request) {
        Minecraft mc=Minecraft.getInstance();thread(mc);
        var existing=LEASES.existing(request);
        if(existing!=null)return describe(existing); // Exact original ID is read-only, never re-dispatched.
        require(!blocksInput(),"external_navigation_original_owner_unresolved");
        require(sameRequestContext(mc,request)&&mdcFree(mc),"external_navigation_existing_owner_or_context");
        var capturedPlayer=mc.player;var capturedLevel=mc.level;var capturedMode=mc.gameMode;
        long revision=ClientActions.externalOwnerRevision();
        var prior=LEASES.active();String session=ClientActions.session();
        JsonObject proof=ExternalControllerGuard.snapshot(mc);
        require(proof.get("supported").getAsBoolean() && !proof.get("status").getAsString().equals("absent")
            && proof.getAsJsonObject("facts").get("context_matches").getAsBoolean()
            && proof.getAsJsonObject("facts").get("instances").getAsInt()==1,
            "external_navigation_supported_api_required");
        // All receivers were pinned by the fresh proof; resolve the exact public pathing object.
        Pathing path=pathingObject();
        Readings readings=ExternalNavigationFence.readThenCheck(() -> readings(mc,request,
            capturedPlayer,capturedLevel,false),
            () -> localBound(mc,capturedPlayer,capturedLevel,capturedMode,revision,session,request.world())
                &&LEASES.active()==prior&&!blocksInput()&&localMdcFree());
        long now=System.nanoTime();
        require(readings.same(),"external_navigation_final_context_changed");
        proof=readings.proof();
        require(proof.get("supported").getAsBoolean()&&proof.getAsJsonObject("facts").get("context_matches").getAsBoolean()
            &&proof.getAsJsonObject("facts").get("instances").getAsInt()==1,"external_navigation_final_proof_changed");
        require(now>=request.sourceNano()&&now-request.sourceNano()<=750_000_000L
            &&readings.tick()>=request.sourceTick()&&readings.tick()-request.sourceTick()<=5,
            "external_navigation_original_source_stale");
        var entry=LEASES.claim(request,now,readings.tick());player=capturedPlayer;level=capturedLevel;gameMode=capturedMode;
        ownerRevision=revision;proofs.put(entry.request.id(),proof.deepCopy());
        if(!proof.get("idle_proven").getAsBoolean()) {
            LEASES.attempt(entry);
            try {
                // The one documented safe-interruption request. A true return is NOT idle proof.
                Object answer=path.cancel().invoke(path.receiver());
                if(!(answer instanceof Boolean accepted))throw new IllegalStateException("external_navigation_cancel_result_invalid");
                if(LEASES.owns(entry))entry.cancelAccepted=accepted;
            } catch(Exception|LinkageError failure){LEASES.unknown(entry,"external_navigation_stop_outcome_unknown");}
        }
        return describe(entry);
    }
    private record Pathing(Object receiver,java.lang.reflect.Method cancel) {}
    private static Pathing pathingObject() {
        try {
            ClassLoader loader=NativeExternalNavigation.class.getClassLoader();
            Class<?> api=Class.forName("baritone.api.BaritoneAPI",false,loader);
            Object provider=api.getMethod("getProvider").invoke(null);
            require(provider.getClass()==Class.forName("baritone.BaritoneProvider",false,loader),"external_navigation_provider_changed");
            Object primary=Class.forName("baritone.api.IBaritoneProvider",false,loader).getMethod("getPrimaryBaritone").invoke(provider);
            require(primary.getClass()==Class.forName("baritone.a",false,loader),"external_navigation_primary_changed");
            Object path=Class.forName("baritone.api.IBaritone",false,loader).getMethod("getPathingBehavior").invoke(primary);
            require(path.getClass()==Class.forName("baritone.i",false,loader),"external_navigation_pathing_changed");
            return new Pathing(path,Class.forName("baritone.api.behavior.IPathingBehavior",false,loader)
                .getMethod("cancelEverything"));
        }catch(ReflectiveOperationException|LinkageError e){throw new ClientActionRequest.Rejected(409,"external_navigation_api_unavailable");}
    }
    private record Readings(boolean same,boolean neutral,long tick,JsonObject proof) {}
    private static Readings readings(Minecraft mc,ExternalNavigationLease.Request r,Object p,Object l,boolean sampleNeutral) {
        boolean same=sameRequestContext(mc,r)&&mdcFree(mc);
        boolean neutral=!sampleNeutral||BridgeServer.heldInputsSnapshot(mc).get("neutral").getAsBoolean();
        long tick=mc.level.getGameTime();
        // The pinned read-only API scan is last: earlier context/key/tick callbacks
        // cannot start a new external path after an already-captured idle proof.
        JsonObject proof=ExternalControllerProof.snapshot(new ExternalControllerProof.Context(mc,p,l,
            r.session(),r.world(),r.player(),tick));
        return new Readings(same,neutral,tick,proof);
    }
    static void tick(Minecraft mc) {
        NativeManagedNavigation.tick(mc);
        var entry=LEASES.active();if(entry==null||!LEASES.owns(entry))return;
        Object capturedPlayer=player,capturedLevel=level,capturedMode=gameMode;
        long revision=ownerRevision;String session=entry.request.session();
        try {
            Readings readings=ExternalNavigationFence.readThenCheck(() -> readings(mc,entry.request,
                capturedPlayer,capturedLevel,true),
                () -> localBound(mc,capturedPlayer,capturedLevel,capturedMode,revision,session,entry.request.world())
                    &&player==capturedPlayer&&level==capturedLevel&&gameMode==capturedMode
                    &&ownerRevision==revision&&LEASES.owns(entry)&&localMdcFree());
            boolean idle=readings.same()&&readings.proof().get("idle_proven").getAsBoolean()&&readings.neutral();
            proofs.put(entry.request.id(),readings.proof().deepCopy());
            LEASES.sample(entry,readings.same(),idle,readings.tick(),System.nanoTime());
        }catch(RuntimeException|LinkageError failure){LEASES.unknown(entry,"external_navigation_idle_proof_unknown");}
    }
    private static boolean localBound(Minecraft mc,Object p,Object l,Object mode,long revision,String session,String world) {
        return mc.player==p&&mc.level==l&&mc.gameMode==mode
            &&ClientActions.externalOwnerRevision()==revision&&ClientActions.session().equals(session)
            &&WorldGeneration.matches(l,world);
    }
    private static boolean localMdcFree(){return !ClientActions.hasRuntimeAction()&&!NativeFallRescue.armedOrBlocked()
        &&!BridgeServer.hasHeldInputs()&&GuardedGameMovement.LEASES.status().ownerRequestId()==null;}
    static void contextLost(){NativeManagedNavigation.contextLost();var entry=LEASES.active();if(LEASES.owns(entry))LEASES.unknown(entry,"external_navigation_context_changed");}
    private static boolean sameRequestContext(Minecraft mc,ExternalNavigationLease.Request r){return mc.player!=null&&mc.level!=null&&mc.gameMode!=null
        &&r.session().equals(ClientActions.session())&&r.world().equals(WorldGeneration.current(mc.level))
        &&r.player().equals(mc.player.getUUID().toString())&&r.dimension().equals(mc.level.dimension().location().toString());}
    private static boolean mdcFree(Minecraft mc){return mc.player!=null&&mc.level!=null&&mc.gameMode!=null
        &&CapabilityGuard.privateSingleplayer(mc)&&!ClientActions.hasRuntimeAction()&&!NativeFallRescue.blocksInput()
        &&!NativeFallRescue.status().get("armed").getAsBoolean()&&!BridgeServer.hasHeldInputs()
        &&GuardedGameMovement.LEASES.status().ownerRequestId()==null;}
    static JsonObject capabilities(){JsonObject j=new JsonObject();j.addProperty("schema_version",1);
        j.addProperty("version","external-navigation-owner-control/1");j.addProperty("stop_only",true);
        j.addProperty("single_owner_fences",true);j.addProperty("no_auto_resume",true);return j;}
    static JsonObject status(){thread(Minecraft.getInstance());return describe(LEASES.active());}
    private static JsonObject describe(ExternalNavigationLease.Entry e){
        return ExternalNavigationResponses.status(e,e==null?null:proofs.get(e.request.id()),System.nanoTime());
    }
    private static void thread(Minecraft mc){require(mc.isSameThread(),"minecraft_thread_required");}
    private static void require(boolean ok,String reason){if(!ok)throw new ClientActionRequest.Rejected(409,reason);}
    private NativeExternalNavigation(){}
}

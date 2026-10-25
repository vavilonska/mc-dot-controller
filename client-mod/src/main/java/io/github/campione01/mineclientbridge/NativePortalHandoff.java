package io.github.campione01.mineclientbridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.util.Set;
import java.util.UUID;
import java.util.function.BooleanSupplier;
import net.minecraft.client.Minecraft;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.entity.Mob;
import net.minecraft.world.entity.monster.Enemy;
import net.minecraft.world.item.Items;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.Vec3;

/** One explicit cross-dimension authorization. All physical owners remain ordinary ActionRegistry entries. */
final class NativePortalHandoff {
    record Plan(String from,String to,int ttl,int defendMs,int routeMs,AABB landing,JsonArray route,JsonObject guard) { }
    static final class Permit {
        final Plan plan;final Object server;final String player,session,sourceWorld;
        final ActionRegistry.Entry source;final long deadline;
        ActionRegistry.Entry child;String childId,defenseId,routeId;String state="ARMED_SOURCE",reason="waiting_exact_world_transition";
        boolean defenseSubmitted,routeSubmitted,landingAccepted;Vec3 landingOrigin;
        Permit(Plan p,Minecraft mc,ActionRegistry.Entry e){this(p,mc.getSingleplayerServer(),mc.player.getUUID().toString(),ClientActions.session(),WorldGeneration.current(mc.level),e,System.nanoTime());}
        Permit(Plan p,Object server,String player,String session,String sourceWorld,ActionRegistry.Entry e,long now){this.plan=p;this.server=server;this.player=player;
            this.session=session;this.sourceWorld=sourceWorld;source=e;deadline=now+p.ttl()*1_000_000L;}
    }
    private static Permit permit,last;
    private static ClientActionRequest authorizedRequest;
    private static Permit authorizedPermit;
    private static boolean executing;
    private static ClientActionRequest inFlightRequest;
    private static Permit inFlightPermit;
    static Plan validate(ClientActionRequest r){
        if(!r.original().has("portal_handoff"))return null;
        check(r.action().equals("follow_path")&&r.original().has("blaze_guard"),"portal_handoff_requires_escorted_follow");
        var value=r.original().get("portal_handoff");check(value.isJsonObject(),"portal_handoff_object_required");var j=value.getAsJsonObject();
        check(j.keySet().equals(Set.of("schema_version","from_dimension","to_dimension","ttl_ms","defend_ms","destination_timeout_ms","landing_min","landing_max","destination_waypoints","destination_guard")),"portal_handoff_closed_fields");
        check(ClientActionRequest.integer(j,"schema_version",0)==1,"portal_handoff_schema");
        String from=ClientActionRequest.string(j,"from_dimension"),to=ClientActionRequest.string(j,"to_dimension");
        check(Set.of("minecraft:overworld","minecraft:the_nether").contains(from)&&Set.of("minecraft:overworld","minecraft:the_nether").contains(to)&&!from.equals(to),"portal_handoff_exact_nether_pair_required");
        int ttl=ClientActionRequest.integer(j,"ttl_ms",0),defend=ClientActionRequest.integer(j,"defend_ms",0),routeMs=ClientActionRequest.integer(j,"destination_timeout_ms",0);
        check(ttl>=1000&&ttl<=120000&&defend>=100&&defend<=3000&&routeMs>=1000&&routeMs<=120000,"portal_handoff_time_bounds");
        JsonObject lo=object(j,"landing_min"),hi=object(j,"landing_max");
        AABB box=new AABB(n(lo,"x"),n(lo,"y"),n(lo,"z"),n(hi,"x"),n(hi,"y"),n(hi,"z"));
        check(n(hi,"x")>n(lo,"x")&&n(hi,"y")>n(lo,"y")&&n(hi,"z")>n(lo,"z")&&box.getXsize()<=8&&box.getYsize()<=6&&box.getZsize()<=8,"portal_handoff_landing_bounds");
        check(j.get("destination_waypoints").isJsonArray(),"portal_handoff_route_array");var route=j.getAsJsonArray("destination_waypoints").deepCopy();
        check(route.size()>0&&route.size()<=16,"portal_handoff_short_route_required");
        var guard=object(j,"destination_guard").deepCopy();check(ClientActionRequest.bool(guard,"creeper_escape",false),"portal_handoff_creeper_escape_required");
        check(ClientActionRequest.integer(guard,"arrival_hold_ms",-1)==0,"portal_handoff_destination_is_departure_not_return_loop");
        // Parse the real ordinary destination contract, without an invented live binding or any input.
        var proof=r.original().deepCopy();proof.remove("portal_handoff");proof.add("waypoints",route);proof.add("blaze_guard",guard);
        JsonObject origin=new JsonObject();origin.addProperty("x",box.getCenter().x);origin.addProperty("y",box.getCenter().y);origin.addProperty("z",box.getCenter().z);proof.add("expected_origin",origin);
        ClientActionRequest.parse(proof);
        return new Plan(from,to,ttl,defend,routeMs,box,route,guard);
    }
    static void requireSource(Minecraft mc,ClientActionRequest r){if(!r.original().has("portal_handoff"))return;Plan p=validate(r);
        check(permit==null,"portal_handoff_already_armed");check(mc.getSingleplayerServer()!=null&&!mc.getSingleplayerServer().isPublished(),"portal_handoff_private_only");
        check(mc.player.isAlive()&&mc.level.dimension().location().toString().equals(p.from()),"portal_handoff_source_context");}
    static void activate(Minecraft mc,ActionRegistry.Entry e){if(!e.request.original().has("portal_handoff"))return;
        permit=last=new Permit(validate(e.request),mc,e);e.result.addProperty("portal_handoff_armed",true);}
    static void beforeStart(ClientActionRequest r){
        boolean child=r.action().equals("portal_defend")||r.original().has("portal_handoff_parent");
        if(child){check(r==authorizedRequest&&permit!=null&&permit==authorizedPermit&&executing,"portal_handoff_internal_request_required");inFlightRequest=r;inFlightPermit=permit;authorizedRequest=null;authorizedPermit=null;}
        else if(permit!=null&&!r.id().equals(permit.source.request.id()))revoke("new_explicit_action");
    }
    static void requireFinal(ClientActionRequest r){if(r.action().equals("portal_defend")||r.original().has("portal_handoff_parent"))
        check(executing&&inFlightRequest==r&&permit!=null&&inFlightPermit==permit&&System.nanoTime()<permit.deadline&&exactTransition(permit.source),"portal_handoff_authorization_revoked_or_expired");}
    static void registered(ActionRegistry.Entry e){if(e.request==inFlightRequest){requireFinal(e.request);permit.child=e;}}
    static boolean knownReleased(ActionRegistry.Entry e){return e!=null&&Set.of("succeeded","failed","cancelled").contains(e.status)&&truth(e.result,"input_release_confirmed")
        &&!unsafe(e.result,"unknown_outcome")&&!unsafe(e.result,"requires_handoff")&&!unsafe(e.result,"no_auto_resume");}
    static boolean exactTransition(ActionRegistry.Entry e){return knownReleased(e)&&e.status.equals("cancelled")&&e.reason.equals("world_transition");}
    static void tick(Minecraft mc){Permit p=permit;if(p==null||executing)return;
        try {
            String problem=contextProblem(p,System.nanoTime(),mc.getSingleplayerServer(),ClientActions.session(),mc.player==null?null:mc.player.getUUID().toString(),mc.player==null||mc.player.isAlive());
            if(problem!=null){revoke(problem);return;}
            if(p.source.running())return;
            if(!exactTransition(p.source)){revoke("original_not_exact_known_released_transition");return;}
            if(mc.level==null||mc.player==null||mc.gameMode==null)return;
            if(mc.getSingleplayerServer()!=p.server){revoke("server_unavailable");return;}
            String dim=mc.level.dimension().location().toString();
            if(dim.equals(p.plan.from()))return;
            if(!dim.equals(p.plan.to())||WorldGeneration.current(mc.level).equals(p.sourceWorld)){revoke("unexpected_destination");return;}
            if(!locationAllowed(p,mc.player.position())){revoke(p.landingAccepted?"outside_authorized_departure_corridor":"outside_authorized_landing");return;}
            if(mc.isPaused()){revoke("paused");return;}
            if(mc.screen!=null){if(mc.screen.getClass().getName().equals("net.minecraft.client.gui.screens.ReceivingLevelScreen"))return;revoke("screen_opened");return;}
            if(p.child!=null){
                if(p.child.running())return;
                if(!knownReleased(p.child)){revoke("child_outcome_or_release_unknown");return;}
                if(p.routeSubmitted){p.state="DONE";p.reason="destination_action_ended:"+p.child.reason;permit=null;return;}
                if(!p.child.status.equals("succeeded")||!p.child.reason.equals("portal_defense_navigation_ready")){revoke("defense_not_settled");return;}
            }
            if(ClientActions.hasRuntimeAction()||NativeFallRescue.blocksInput()||NativeExternalNavigation.blocksInput())return;
            if(!BridgeServer.heldInputsSnapshot(mc).get("neutral").getAsBoolean()){revoke("unowned_inputs_not_neutral");return;}
            ObservationClockBridge.sample();
            if(!p.defenseSubmitted){p.defenseSubmitted=true;p.state="DEFENDING_NEW_CONTEXT";submit(mc,p,true);return;}
            if(!NavigationPositionGuard.snapshot(mc).get("rebind_ready").getAsBoolean()){revoke("navigation_not_ready_after_defense");return;}
            if(!p.routeSubmitted){p.routeSubmitted=true;p.state="DESTINATION_ROUTE";submit(mc,p,false);}
        }catch(RuntimeException uncertain){if(permit==p)revoke("handoff_failed_no_retry:"+uncertain.getClass().getSimpleName());}
    }
    private static void submit(Minecraft mc,Permit p,boolean defend){
        var body=new JsonObject();String id=UUID.randomUUID().toString();p.childId=id;if(defend)p.defenseId=id;else p.routeId=id;
        body.addProperty("action_id",id);body.addProperty("action",defend?"portal_defend":"follow_path");
        long remaining=Math.max(0,(p.deadline-System.nanoTime())/1_000_000L);
        check(remaining>=1000,"portal_handoff_remaining_deadline");body.addProperty("timeout_ms",Math.min(remaining,defend?p.plan.defendMs():p.plan.routeMs()));
        body.addProperty("portal_handoff_parent",p.source.request.id());
        body.addProperty("expected_action_session",p.session);body.addProperty("expected_world_generation",WorldGeneration.current(mc.level));body.addProperty("expected_player_uuid",p.player);
        if(!defend){body.addProperty("expected_navigation_epoch",NavigationPositionGuard.epoch());var o=new JsonObject();o.addProperty("x",mc.player.getX());o.addProperty("y",mc.player.getY());o.addProperty("z",mc.player.getZ());body.add("expected_origin",o);
            body.add("waypoints",p.plan.route().deepCopy());body.add("blaze_guard",p.plan.guard().deepCopy());body.addProperty("sneak",false);}
        ClientActionRequest request=ClientActionRequest.parse(body);authorizedRequest=request;authorizedPermit=p;executing=true;
        try {ClientActions.start(request);p.child=ClientActions.portalEntry(id);p.reason="new_uuid_submitted_once";}
        catch(RuntimeException failure){try{p.child=ClientActions.portalEntry(id);}catch(RuntimeException absent){/* No dispatch retry, even if absent. */}throw failure;}
        finally{authorizedRequest=null;authorizedPermit=null;inFlightRequest=null;inFlightPermit=null;executing=false;}
    }
    static boolean locationAllowed(Permit p,Vec3 position){
        if(!Double.isFinite(position.x+position.y+position.z))return false;
        if(!p.landingAccepted){
            if(!p.plan.landing().contains(position))return false;
            p.landingOrigin=position;p.landingAccepted=true;return true;
        }
        // The registered destination route has its own original per-step corridor/support checks.
        if(p.routeSubmitted)return true;
        var first=p.plan.route().get(0).getAsJsonObject();Vec3 goal=new Vec3(n(first,"x"),n(first,"y"),n(first,"z"));
        return NativeBlazeEscort.horizontalSegmentDistance(position,p.landingOrigin,goal)<=1.25
            &&position.y>=Math.min(p.landingOrigin.y,goal.y)-1.5
            &&position.y<=Math.max(p.landingOrigin.y,goal.y)+2.0;
    }
    static String contextProblem(Permit p,long now,Object server,String session,String player,boolean alive){
        if(now>=p.deadline)return "authorization_expired";
        if(server!=null&&server!=p.server)return "server_changed";
        if(!p.session.equals(session))return "action_session_changed";
        if(player!=null&&(!alive||!p.player.equals(player)))return "player_dead_or_changed";
        return null;
    }
    static boolean allowedClone(boolean oldAlive,boolean newAlive,String oldUuid,String newUuid,String expectedUuid,
            String oldDim,String newDim,String from,String to,boolean originalTransition) {
        return oldAlive&&newAlive&&expectedUuid.equals(oldUuid)&&expectedUuid.equals(newUuid)
            &&from.equals(oldDim)&&to.equals(newDim)&&!oldDim.equals(newDim)&&originalTransition;
    }
    static void playerClone(LocalPlayer oldPlayer,LocalPlayer newPlayer){Permit p=permit;if(p==null)return;
        if(oldPlayer==null||newPlayer==null||!allowedClone(!oldPlayer.isDeadOrDying(),!newPlayer.isDeadOrDying(),
                oldPlayer.getUUID().toString(),newPlayer.getUUID().toString(),p.player,
                oldPlayer.level().dimension().location().toString(),newPlayer.level().dimension().location().toString(),
                p.plan.from(),p.plan.to(),exactTransition(p.source)))revoke("player_clone_not_authorized_transition");
    }
    static void cancelId(String id){if(permit!=null&&(permit.source.request.id().equals(id)||id.equals(permit.childId)))revoke("explicit_cancel");}
    static void revoke(String why){Permit p=permit;if(p==null)return;permit=null;authorizedRequest=null;authorizedPermit=null;p.state="DISARMED";p.reason=why;
        if(p.child!=null&&p.child.running())ClientActions.cancelPortalChild(p.child);}
    static JsonObject status(){var j=new JsonObject();Permit p=last;j.addProperty("armed",permit!=null);if(p==null)return j;j.addProperty("state",p.state);j.addProperty("reason",p.reason);
        j.addProperty("landing_accepted",p.landingAccepted);
        if(p.landingOrigin!=null){var origin=new JsonObject();origin.addProperty("x",p.landingOrigin.x);origin.addProperty("y",p.landingOrigin.y);origin.addProperty("z",p.landingOrigin.z);j.add("accepted_landing_origin",origin);}
        j.addProperty("parent_action_id",p.source.request.id());j.addProperty("child_action_id",p.childId);j.addProperty("defense_action_id",p.defenseId);j.addProperty("route_action_id",p.routeId);j.addProperty("defense_submitted",p.defenseSubmitted);j.addProperty("route_submitted",p.routeSubmitted);j.addProperty("deadline_nano",Long.toString(p.deadline));return j;}
    static final class Defense {
        final LocalPlayer player;final ClientLevel level;final JsonObject result;final BooleanSupplier owner;boolean shield;int ticks;
        Defense(Minecraft mc,JsonObject result,BooleanSupplier owner){player=mc.player;level=mc.level;this.result=result;this.owner=owner;}
        void check(Minecraft mc){if(!owner.getAsBoolean()||mc.player!=player||mc.level!=level||mc.gameMode==null)throw new IllegalStateException("portal_defense_owner_changed");}
        NativeBlazeEscort.Step tick(Minecraft mc){check(mc);ticks++;var near=mc.level.getEntitiesOfClass(Mob.class,player.getBoundingBox().inflate(16),e->e instanceof Enemy&&e.isAlive());
            near.sort(java.util.Comparator.comparingDouble(e->e.distanceToSqr(player)));var imminent=NativeThreatObservation.creeper(mc);
            net.minecraft.world.entity.Entity aimEntity=imminent==null?null:mc.level.getEntity(imminent.id());
            if(aimEntity==null&&!near.isEmpty())aimEntity=near.get(0);
            if(aimEntity!=null){Vec3 d=aimEntity.getBoundingBox().getCenter().subtract(player.getEyePosition());float yaw=(float)Math.toDegrees(Math.atan2(-d.x,d.z));
                player.setYRot(yaw);check(mc);player.setYHeadRot(yaw);check(mc);player.setXRot((float)-Math.toDegrees(Math.atan2(d.y,Math.hypot(d.x,d.z))));check(mc);}
            if(player.getOffhandItem().is(Items.SHIELD)&&!player.getCooldowns().isOnCooldown(Items.SHIELD)&&!player.isUsingItem()){
                shield=true;NativeBlazeEscort.inputAttempt(result,()->mc.gameMode.useItem(player,InteractionHand.OFF_HAND),owner);check(mc);mc.options.keyUse.setDown(true);check(mc);}
            result.addProperty("blocking",player.isBlocking());result.addProperty("health",player.getHealth());
            boolean ready=NavigationPositionGuard.snapshot(mc).get("rebind_ready").getAsBoolean();check(mc);
            return ready&&ticks>=6?NativeBlazeEscort.Step.end("succeeded","portal_defense_navigation_ready"):NativeBlazeEscort.Step.waitFor("portal_defense_waiting_navigation");}
        void release(Minecraft mc,Runnable fence){if(!shield)return;fence.run();mc.options.keyUse.setDown(false);fence.run();if(mc.player==player&&mc.gameMode!=null&&player.isUsingItem())mc.gameMode.releaseUsingItem(player);fence.run();shield=false;}
    }
    private static boolean unsafe(JsonObject j,String k){return j.has(k)&&(!j.get(k).isJsonPrimitive()||!j.get(k).getAsJsonPrimitive().isBoolean()||j.get(k).getAsBoolean());}
    private static boolean truth(JsonObject j,String k){return j.has(k)&&j.get(k).isJsonPrimitive()&&j.get(k).getAsJsonPrimitive().isBoolean()&&j.get(k).getAsBoolean();}
    private static JsonObject object(JsonObject j,String k){check(j.has(k)&&j.get(k).isJsonObject(),"portal_handoff_invalid_"+k);return j.getAsJsonObject(k);}
    private static double n(JsonObject j,String k){check(j.has(k)&&j.get(k).isJsonPrimitive()&&j.get(k).getAsJsonPrimitive().isNumber(),"portal_handoff_number");double v=j.get(k).getAsDouble();check(Double.isFinite(v),"portal_handoff_finite");return v;}
    private static void check(boolean ok,String reason){if(!ok)throw new ClientActionRequest.Rejected(409,reason);}
}

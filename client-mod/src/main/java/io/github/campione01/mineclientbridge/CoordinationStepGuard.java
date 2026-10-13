package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.util.Set;
import net.minecraft.client.Minecraft;

/** Opt-in, one-block controlled-floor guard, not general navigation or threat safety. */
final class CoordinationStepGuard {
    static final Set<String> SUPPORT = Set.of("minecraft:stone", "minecraft:cobblestone", "minecraft:dirt", "minecraft:grass_block");
    private final ClientActionRequest.Point start, end;
    private float health;
    private long sourceTick, sourceNano;
    private net.minecraft.client.player.LocalPlayer player;
    private net.minecraft.client.multiplayer.ClientLevel level;
    private double checkedX,checkedY,checkedZ;

    private CoordinationStepGuard(ClientActionRequest.Point start, ClientActionRequest.Point end, float health) {
        this.start=start; this.end=end; this.health=health;
    }
    static boolean requested(JsonObject body) { return body.has("coordination_step"); }
    static void validate(ClientActionRequest request) {
        if (!requested(request.original())) return;
        var body=request.original();
        ClientActionRequest.require(body.get("coordination_step").isJsonObject(),"coordination_step_invalid");
        var spec=body.getAsJsonObject("coordination_step");
        ClientActionRequest.require(spec.keySet().equals(Set.of("schema_version","source_tick","source_nano"))
                && ClientActionRequest.integer(spec,"schema_version",-1)==1,"coordination_step_invalid");
        sourceTick(spec); sourceNano(spec);
        ClientActionRequest.require(Set.of("action_id","action","timeout_ms","waypoints","expected_origin",
                "expected_navigation_epoch","expected_world_generation","expected_player_uuid","expected_action_session",
                "coordination_step","sprint","jump","sneak").containsAll(body.keySet()),"coordination_step_unknown_field");
        ClientActionRequest.require(request.action().equals("follow_path") && request.waypoints().size()==1
                && request.timeoutMs()<=1000 && !request.jump() && !request.sneak()
                && request.hotbarSlot()==-1 && !request.waypoints().get(0).jump()
                && !ClientActionRequest.bool(body,"sprint",false),"coordination_step_scope");
        ClientActionRequest.require(body.has("expected_origin") && body.get("expected_origin").isJsonObject()
                && body.has("expected_navigation_epoch") && body.has("expected_world_generation")
                && body.has("expected_player_uuid") && body.has("expected_action_session"),"coordination_step_binding_required");
        var p=point(body.getAsJsonObject("expected_origin")); var q=request.waypoints().get(0);
        ClientActionRequest.require(centered(p) && centered(q) && p.y()==q.y()
                && Math.abs(p.x()-q.x())+Math.abs(p.z()-q.z())==1,"coordination_step_one_cardinal_block");
    }
    static CoordinationStepGuard start(Minecraft mc, ClientActionRequest request) {
        if (!requested(request.original())) return null;
        validate(request);
        long tick=sourceTick(request.original().getAsJsonObject("coordination_step"));
        long now=mc.level.getGameTime();
        if (!CoordinationStepPolicy.ageValid(System.nanoTime(),sourceNano(request.original().getAsJsonObject("coordination_step")))) throw new ClientActionRequest.Rejected(409,"coordination_step_source_age");
        if (now<tick || now-tick>5) throw new ClientActionRequest.Rejected(409,"coordination_step_source_expired");
        var guard=new CoordinationStepGuard(point(request.original().getAsJsonObject("expected_origin")),
                request.waypoints().get(0),mc.player.getHealth());
        guard.sourceTick=tick;guard.sourceNano=sourceNano(request.original().getAsJsonObject("coordination_step"));
        guard.player=mc.player;guard.level=mc.level;
        String denied=guard.check(mc);
        if (denied!=null) throw new ClientActionRequest.Rejected(409,denied);
        guard.requireFresh(mc);
        return guard;
    }
    void requireFresh(Minecraft mc) {
        if (!CoordinationStepPolicy.ageValid(System.nanoTime(),sourceNano))
            throw new ClientActionRequest.Rejected(409,"coordination_step_source_age");
        if (mc.level==null || mc.level.getGameTime()<sourceTick || mc.level.getGameTime()-sourceTick>5)
            throw new ClientActionRequest.Rejected(409,"coordination_step_source_expired");
    }
    String afterHooks(Minecraft mc) {
        if (mc.player!=player || mc.level!=level) return "coordination_step_context_changed";
        if (!privateSingleplayer(mc) || mc.isPaused() || !mc.isWindowActive() || mc.screen!=null
                || !player.onGround() || player.isPassenger() || player.isSpectator() || !player.isAlive())
            return "coordination_step_lifecycle";
        if (player.getX()!=checkedX || player.getY()!=checkedY || player.getZ()!=checkedZ)
            return "coordination_step_pose_changed_during_check";
        if (player.hurtTime>0 || !Float.isFinite(player.getHealth()) || player.getHealth()<health)
            return "coordination_step_motion_or_damage";
        return null;
    }
    String check(Minecraft mc) {
        if (mc.player==null || mc.level==null) return "coordination_step_player_unavailable";
        var p=mc.player; var bounds=p.getBoundingBox();
        checkedX=p.getX();checkedY=p.getY();checkedZ=p.getZ();
        var state=new CoordinationStepPolicy.State(p.getX(),p.getY(),p.getZ(),p.getYRot(),p.onGround(),p.isAlive(),
                privateSingleplayer(mc) && !mc.isPaused() && mc.isWindowActive() && mc.screen==null
                && !p.isSpectator() && !p.isPassenger(),p.isSprinting(),p.getDeltaMovement().horizontalDistance(),
                p.getHealth(),bounds.getXsize(),bounds.getZsize(),bounds.getYsize(),entityCount(mc));
        if (p.hurtTime > 0) return "coordination_step_motion_or_damage";
        String denied=CoordinationStepPolicy.check(start,end,health,state,TerrainReader.flatCellSource(mc));
        if (denied==null) denied=afterHooks(mc);
        if (denied==null && entityCount(mc)!=0) denied="coordination_step_entity_nearby";
        if (denied==null) denied=afterHooks(mc);
        if (denied==null) health=p.getHealth(); // Preserve each observed recovery before detecting any later drop.
        return denied;
    }
    private static int entityCount(Minecraft mc) {
        int count=0;
        var envelope=mc.player.getBoundingBox().inflate(8);
        for (var e : mc.level.entitiesForRendering()) {
            if (e==mc.player) continue; // Only self is excluded. Items/projectiles/players all reject.
            if (e.getBoundingBox().intersects(envelope)) count++;
        }
        return count;
    }
    static JsonObject observation(Minecraft mc, long sourceTick, long sourceNano) {
        return sampleEvidence(sourceTick,sourceNano,WorldGeneration.current(mc.level),ClientActions.session(),
                mc.player.getUUID().toString(),entityCount(mc),privateSingleplayer(mc));
    }
    private static boolean privateSingleplayer(Minecraft mc) {
        return mc.hasSingleplayerServer() && mc.getSingleplayerServer()!=null && !mc.getSingleplayerServer().isPublished();
    }
    static JsonObject sampleEvidence(long sourceTick,long sourceNano,String world,String session,String player,
                                     int otherEntities,boolean singleplayer) {
        JsonObject out=new JsonObject();
        out.addProperty("schema_version",1); out.addProperty("contract","controlled_single_step_v1");
        out.addProperty("source_tick",sourceTick); out.addProperty("source_nano",Long.toString(sourceNano));
        out.addProperty("world_generation",world); out.addProperty("action_session",session);
        out.addProperty("player_uuid",player); out.addProperty("entity_scope","loaded_client_aabb8_excluding_self");
        out.addProperty("entity_count",otherEntities); out.addProperty("radius",8);
        out.addProperty("singleplayer",singleplayer);
        return out;
    }
    private static ClientActionRequest.Point point(JsonObject p) {
        ClientActionRequest.require(p.keySet().equals(Set.of("x","y","z")),"coordination_step_origin");
        for (String key : Set.of("x","y","z")) ClientActionRequest.require(p.get(key).isJsonPrimitive()
                && p.get(key).getAsJsonPrimitive().isNumber(),"coordination_step_origin");
        try { return new ClientActionRequest.Point(p.get("x").getAsDouble(),p.get("y").getAsDouble(),p.get("z").getAsDouble(),false); }
        catch (RuntimeException e) { throw new ClientActionRequest.Rejected(400,"coordination_step_origin"); }
    }
    private static boolean centered(ClientActionRequest.Point p) {
        return Double.isFinite(p.x()) && Double.isFinite(p.y()) && Double.isFinite(p.z())
                && Math.abs(p.x())<=30000000 && Math.abs(p.z())<=30000000 && Math.abs(p.y())<=2048
                && p.x()-Math.floor(p.x())==.5 && p.z()-Math.floor(p.z())==.5 && p.y()==Math.rint(p.y());
    }
    private static long sourceNano(JsonObject spec) {
        String text=ClientActionRequest.string(spec,"source_nano");
        ClientActionRequest.require(text.matches("-?(0|[1-9][0-9]{0,18})"),"coordination_step_nano");
        try { return Long.parseLong(text); }
        catch (NumberFormatException e) { throw new ClientActionRequest.Rejected(400,"coordination_step_nano"); }
    }
    private static long sourceTick(JsonObject spec) {
        var v=spec.get("source_tick");
        ClientActionRequest.require(v!=null && v.isJsonPrimitive() && v.getAsJsonPrimitive().isNumber(),"coordination_step_tick");
        double n=v.getAsDouble();
        ClientActionRequest.require(Double.isFinite(n) && n==Math.rint(n) && n>=0 && n<=9007199254740991L,"coordination_step_tick");
        return (long)n;
    }
}

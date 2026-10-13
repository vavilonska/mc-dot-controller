package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.UUID;

/** Pure policy shared by actual wire admission and fresh native encounter-route snapshots.
 * Its target set is an exemption scope for movement, never a new attack allowlist. */
final class CapabilityEncounterPolicy {
    static final String FIELD="encounter_route_guard";
    static final int SCHEMA_VERSION=1,MAX_EXAMINED=1024;
    static final long MAX_SCAN_NANOS=8_000_000L;
    static final Set<String> TARGET_TYPES=Set.of("minecraft:enderman","minecraft:blaze",
            "minecraft:creeper","minecraft:spider","minecraft:cave_spider");
    // These vanilla damaging species do not implement Enemy or NeutralMob. This is
    // encounter danger only; no passive harvesting or attack whitelist is changed.
    private static final Set<String> POTENTIAL_DANGERS=Set.of("minecraft:shulker","minecraft:goat",
            "minecraft:rabbit","minecraft:pufferfish");
    private static final Set<String> PROJECTILES=Set.of("minecraft:arrow","minecraft:spectral_arrow",
            "minecraft:small_fireball","minecraft:fireball","minecraft:dragon_fireball",
            "minecraft:shulker_bullet","minecraft:trident","minecraft:wither_skull","minecraft:potion",
            "minecraft:wind_charge","minecraft:breeze_wind_charge");
    record Target(int id,String uuid,String type) {}
    record Point(double x,double y,double z) {
        boolean finite() {return Double.isFinite(x)&&Double.isFinite(y)&&Double.isFinite(z);}
    }
    record Observed(int id,String uuid,String type,Point position,boolean alive,boolean dangerous,
                    boolean projectile,boolean cloud,boolean calmPumpkinEnderman,boolean fuseRisk,
                    boolean powered,boolean targetShieldWindow,double targetMinimum,String targetProblem) {}

    static Target validate(ClientActionRequest request) {
        JsonObject body=request.original();
        if(!body.has(FIELD))return null;
        ClientActionRequest.require(request.action().equals("follow_path")
                &&CapabilityGuard.requested(body)&&ClientActionRequest.bool(body,"capability_route",false),
                "encounter_route_requires_capability_path");
        ClientActionRequest.require(body.has("expected_origin")&&body.has("expected_navigation_epoch"),
                "encounter_route_binding_required");
        ClientActionRequest.require(request.waypoints().size()<=2,"encounter_route_max_two_segments");
        ClientActionRequest.require(body.get(FIELD).isJsonObject(),"invalid_encounter_route_guard");
        JsonObject spec=body.getAsJsonObject(FIELD);
        Set<String> keys=spec.keySet();
        ClientActionRequest.require(keys.equals(Set.of("schema_version"))||keys.equals(Set.of("schema_version",
                "target_entity_id","target_uuid","target_type")),"invalid_encounter_route_guard");
        ClientActionRequest.require(ClientActionRequest.integer(spec,"schema_version",-1)==SCHEMA_VERSION,
                "unsupported_encounter_route_guard");
        // A guarded route has a finite reserve, even when called without the Python planner.
        if(body.has("min_health"))CapabilityPlacement.number(body,"min_health",12,20);
        JsonObject origin=body.getAsJsonObject("expected_origin");
        Point from=new Point(origin.get("x").getAsDouble(),origin.get("y").getAsDouble(),origin.get("z").getAsDouble());
        for(var p:request.waypoints()) {
            Point to=new Point(p.x(),p.y(),p.z());
            ClientActionRequest.require(from.finite()&&to.finite()&&distance(from,to)<=2.5,
                    "encounter_route_segment_too_long");
            from=to;
        }
        if(!spec.has("target_entity_id"))return null;
        int id=ClientActionRequest.integer(spec,"target_entity_id",-1);
        String uuid=ClientActionRequest.string(spec,"target_uuid"),type=ClientActionRequest.string(spec,"target_type");
        ClientActionRequest.require(id>=0,"invalid_encounter_route_target_id");
        try {ClientActionRequest.require(UUID.fromString(uuid).toString().equals(uuid),"invalid_encounter_route_target_uuid");}
        catch(IllegalArgumentException bad) {throw new ClientActionRequest.Rejected(400,"invalid_encounter_route_target_uuid");}
        ClientActionRequest.require(TARGET_TYPES.contains(type),"unsupported_encounter_route_target");
        return new Target(id,uuid,type);
    }
    static boolean dangerous(String type,boolean nativeDangerous) {
        return nativeDangerous||CombatThreats.observableThreat(type)||POTENTIAL_DANGERS.contains(type);
    }
    static boolean projectile(String type,boolean nativeProjectile) {return nativeProjectile||PROJECTILES.contains(type);}
    static String check(ClientActionRequest request,Point player,List<Observed> rows,
                        long capturedTick,long capturedNano,long tick,long now,boolean complete) {
        if(!request.original().has(FIELD))return null;
        Target target=validate(request);
        if(!complete||rows==null||rows.size()>MAX_EXAMINED)return "encounter_route_observation_incomplete";
        long age=now-capturedNano;
        if(age<0||age>MAX_SCAN_NANOS||capturedTick!=tick)return "encounter_route_observation_stale";
        if(player==null||!player.finite())return "encounter_route_position_unknown";
        boolean shieldBlaze=target!=null&&target.type().equals("minecraft:blaze")&&rows.stream().anyMatch(row->
                row!=null&&row.id()==target.id()&&target.uuid().equals(row.uuid())&&target.type().equals(row.type())
                        &&row.targetShieldWindow());
        Set<Integer> ids=new HashSet<>();Set<String> uuids=new HashSet<>();boolean found=target==null;
        for(Observed row:rows) {
            if(row==null||row.id()<0||row.uuid()==null||row.uuid().isBlank()||row.type()==null
                    ||row.position()==null||!row.position().finite()||!ids.add(row.id())||!uuids.add(row.uuid()))
                return "encounter_route_entity_unknown";
            boolean targetIdentity=target!=null&&(row.id()==target.id()||row.uuid().equals(target.uuid()));
            if(targetIdentity) {
                if(row.id()!=target.id()||!row.uuid().equals(target.uuid())||!row.type().equals(target.type()))
                    return "encounter_route_target_changed";
                if(!row.alive())return "encounter_route_target_missing";
                found=true;
                if(row.targetProblem()!=null)return row.targetProblem();
                if(!Double.isFinite(row.targetMinimum())||row.targetMinimum()<0)return "encounter_route_target_state_unknown";
                if(clearance(request,player,row.position())<row.targetMinimum())return "encounter_route_target_clearance";
                continue;
            }
            if(!row.alive())continue;
            double distance=clearance(request,player,row.position());
            if(shieldBlaze&&dangerous(row.type(),row.dangerous())&&distance<32)
                return "encounter_route_blaze_isolation_guard";
            if(shieldBlaze&&row.type().equals("minecraft:small_fireball")&&distance<=32)
                return "encounter_route_blaze_fireball_guard";
            if(row.type().equals("minecraft:enderman")&&!row.calmPumpkinEnderman()&&distance<=48)
                return "encounter_route_enderman_gaze_guard";
            if(row.fuseRisk()&&row.type().equals("minecraft:creeper")&&distance<(row.powered()?18:14))
                return "encounter_route_creeper_fuse_guard";
            if(projectile(row.type(),row.projectile())&&distance<5)return "encounter_route_projectile_near";
            if((row.cloud()||row.type().equals("minecraft:area_effect_cloud"))&&distance<10)
                return "encounter_route_effect_cloud_near";
            if(!row.calmPumpkinEnderman()&&dangerous(row.type(),row.dangerous())&&distance<8)
                return "encounter_route_non_target_threat";
        }
        return found?null:"encounter_route_target_missing";
    }
    private static double clearance(ClientActionRequest request,Point player,Point entity) {
        double min=distance(player,entity);
        JsonObject origin=request.original().getAsJsonObject("expected_origin");
        Point from=new Point(origin.get("x").getAsDouble(),origin.get("y").getAsDouble(),origin.get("z").getAsDouble());
        for(var point:request.waypoints()) {
            Point to=new Point(point.x(),point.y(),point.z());
            min=Math.min(min,segment(entity,from,to));from=to;
        }
        return min;
    }
    private static double distance(Point a,Point b) {return Math.sqrt(sq(a.x-b.x)+sq(a.y-b.y)+sq(a.z-b.z));}
    private static double segment(Point p,Point a,Point b) {
        double dx=b.x-a.x,dy=b.y-a.y,dz=b.z-a.z,d=sq(dx)+sq(dy)+sq(dz);
        double t=d==0?0:Math.max(0,Math.min(1,((p.x-a.x)*dx+(p.y-a.y)*dy+(p.z-a.z)*dz)/d));
        return distance(p,new Point(a.x+t*dx,a.y+t*dy,a.z+t*dz));
    }
    private static double sq(double n) {return n*n;}
    private CapabilityEncounterPolicy() {}
}

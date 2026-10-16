package io.github.campione01.mineclientbridge;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.nio.charset.StandardCharsets;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import static io.github.campione01.mineclientbridge.ScopedEntityPolicy.*;

/** Route-only, versioned observed geometry. An attacker verdict permits only terminal input release. */
final class ScopedRouteThreatPolicy {
    static final String PROFILE="movement-local-segment-spatial-threat-v1", POLICY="route-spatial-threat-v1";
    static final String SCOPE="all-client-loaded-route-swept-body-and-threats";
    static final String ZOMBIE="minecraft:zombie", ZOMBIE_CLASS="net.minecraft.world.entity.monster.Zombie";
    static final double DEFENSE_RANGE=3, OTHER_ZOMBIE_RANGE=8;
    // Capability replies contain the stop proof in all three action siblings. A full
    // 192 KiB stop cannot fit the existing 256 KiB response limit even once alongside
    // its admission witness. Bound the complete proof, not only its nested frame:
    // repeated identity strings in the outer envelope must not escape the reserve.
    static final int MAX_STOP_FRAME_BYTES=32*1024, MAX_STOP_PROOF_BYTES=32*1024;
    static final int STOP_GROWTH_BYTES=MAX_STOP_PROOF_BYTES+TERMINAL_GROWTH_BYTES;
    private static final Gson WIRE=new GsonBuilder().serializeNulls().disableHtmlEscaping().create();
    private static final Set<String> LIVING_KEYS=Set.of("schema_version","entity_uuid","entity_id","entity_type","dimension",
        "world_generation","player_uuid","known","source","reason","current_target_known","coverage_complete","inspected",
        "sample_tick","sample_nano","source_tick","source_nano","sample_age_ms","alive","aggressive","current_target");
    static Box swept(ScopedLocalSegmentPolicy.Bounds b){
        return new Box(Math.min(b.startX(),b.endX())+.5-.400002,Math.min(b.startY(),b.endY())-.000001,
            Math.min(b.startZ(),b.endZ())+.5-.400002,Math.max(b.startX(),b.endX())+.5+.400002,
            b.startY()+(b.dy()>0?1.26:0)+1.800002,Math.max(b.startZ(),b.endZ())+.5+.400002);
    }
    record Row(int id,String uuid,String type,String className,boolean removed,V position,Box box,V velocity,V target,
               Flags flags,Box projected,JsonObject nativeLiving){
        Row {
            require(uuid!=null&&UUID.fromString(uuid).toString().equals(uuid)&&type!=null&&!type.isBlank()
                &&className!=null&&!className.isBlank(),"route_spatial_identity_invalid");
            if(removed)require(position==null&&box==null&&velocity==null&&target==null&&flags==null&&projected==null&&nativeLiving==null,
                "route_spatial_removed_shape");
            else {
                boolean zombie=ZOMBIE.equals(type);
                require(!type.equals("minecraft:rabbit"),"route_spatial_rabbit_variant_unreviewed");
                require(className.equals(zombie?ZOMBIE_CLASS:CLASSES.get(type)),"route_spatial_entity_unsupported");
                boolean living=!type.equals("minecraft:boat")&&!type.equals("minecraft:chest_minecart")&&!type.equals("minecraft:item");
                require(position!=null&&box!=null&&velocity!=null&&target!=null&&flags!=null&&projected!=null&&box.contains(position),
                    "route_spatial_geometry_missing");
                require(flags.living()==living&&flags.alive()&&!flags.dying()&&!flags.passenger()&&!flags.hasPassengers()
                    &&!flags.leashed()&&!flags.noPhysics()&&!flags.onFire()&&flags.activeEffects()==0&&flags.hurtTime()==0
                    &&flags.target()==null,"route_spatial_entity_state_unknown");
                require(zombie==(nativeLiving!=null),"route_spatial_native_target_facts_required");
                if(nativeLiving!=null)nativeLiving=nativeLiving.deepCopy();
            }
        }
        JsonObject json(boolean attacker){
            JsonObject j=new JsonObject();j.addProperty("id",id);j.addProperty("uuid",uuid);j.addProperty("type",type);
            j.addProperty("class",className);j.addProperty("removed",removed);
            if(!removed){j.add("position",position.json());j.add("aabb",box.json());j.add("velocity",velocity.json());
                j.add("lerp_target",target.json());j.add("flags",flags.json());j.add("projected_aabb",projected.json());
                j.addProperty("verdict",attacker?"selected_attacker":"outside");if(nativeLiving!=null)j.add("native_living",nativeLiving.deepCopy());}
            return j;
        }
    }
    record Frame(long tick,long nano,int horizon,int selfCount,Box prism,Box swept,V player,String playerUuid,
                 String world,String dimension,String selectedUuid,List<Row> rows,boolean allowProjectedAttacker){
        Frame {
            require(tick>=0&&horizon>=0&&horizon<=MAX_TICKS&&selfCount==1&&rows!=null&&rows.size()+1<=LIMIT,
                "route_spatial_coverage_invalid");
            require(selectedUuid!=null&&UUID.fromString(selectedUuid).toString().equals(selectedUuid),"route_spatial_selected_uuid_invalid");
            rows=List.copyOf(rows);var ids=new HashSet<Integer>();var uuids=new HashSet<String>();Row previous=null;int attackers=0;
            for(Row row:rows){
                require(ids.add(row.id)&&uuids.add(row.uuid)&&!row.uuid.equals(playerUuid),"route_spatial_duplicate_identity");
                require(previous==null||ORDER.compare(previous,row)<0,"route_spatial_order_invalid");previous=row;
                if(row.removed)continue;
                require(project(row.box,row.position,row.velocity,row.target,horizon).equals(row.projected),"route_spatial_projection_changed");
                boolean selectedAttacker=false;
                if(row.nativeLiving!=null){
                    boolean active=active(row,tick,nano,playerUuid,world,dimension);
                    double distance=distance(player,row.position);
                    if(active){
                        require(row.uuid.equals(selectedUuid),"route_spatial_nontarget_active_attacker");
                        require(distance<=DEFENSE_RANGE,"route_spatial_attacker_outside_defense_range");
                        selectedAttacker=true;attackers++;
                    } else require(row.uuid.equals(selectedUuid)||distance>OTHER_ZOMBIE_RANGE,"route_spatial_other_threat_near");
                }
                // Only zero-motion admission may exempt the selected attacker's future projection.
                require(!selectedAttacker||row.box.separate(swept),"route_spatial_attacker_current_body_conflict");
                require(selectedAttacker&&allowProjectedAttacker||row.projected.separate(swept),"route_spatial_projected_body_conflict");
            }
            require(attackers<=1,"route_spatial_multiple_selected_attackers");
        }
        int population(){return rows.size()+1;}
        Row attacker(){for(Row r:rows)if(!r.removed&&r.nativeLiving!=null&&active(r,tick,nano,playerUuid,world,dimension))return r;return null;}
        JsonObject json(){
            Row attacker=attacker();JsonObject j=new JsonObject();j.addProperty("schema_version",1);j.addProperty("policy",POLICY);
            j.addProperty("source","native-client-loaded-level");j.addProperty("scope",SCOPE);j.addProperty("guarantee","same-callback-current-facts-only");
            j.addProperty("future_dynamics_certified",false);j.addProperty("server_confirmed",false);j.addProperty("entity_limit",LIMIT);
            j.addProperty("enumerated_count",population());j.addProperty("self_count",1);int removed=(int)rows.stream().filter(Row::removed).count();
            j.addProperty("live_other_count",rows.size()-removed);j.addProperty("removed_count",removed);j.addProperty("unsupported_count",0);
            j.addProperty("source_tick",tick);j.addProperty("source_nano",Long.toString(nano));j.addProperty("maximum_action_ticks",MAX_TICKS);
            j.addProperty("remaining_projection_ticks",horizon);j.add("prism",prism.json());j.add("swept_aabb",swept.json());
            j.add("player_position",player.json());j.addProperty("selected_target_uuid",selectedUuid);j.addProperty("stop_only",attacker!=null);
            JsonArray a=new JsonArray();for(Row r:rows){JsonObject row=r.json(r==attacker);
                if(r==attacker)row.addProperty("projected_overlap",!r.projected.separate(swept));a.add(row);
            }j.add("rows",a);
            require(WIRE.toJson(j).getBytes(StandardCharsets.UTF_8).length<=MAX_FRAME_BYTES,"route_spatial_evidence_too_large");return j;
        }
        JsonObject stop(boolean preemptedBeforeMotion){
            Row r=attacker();if(r==null)return null;JsonObject out=new JsonObject();out.addProperty("schema_version",1);
            out.addProperty("profile",PROFILE);out.addProperty("policy",POLICY);out.addProperty("target_uuid",r.uuid);
            out.addProperty("entity_id",r.id);out.addProperty("entity_type",r.type);out.addProperty("player_uuid",playerUuid);
            out.addProperty("world_generation",world);out.addProperty("dimension",dimension);out.addProperty("before_next_effect",true);
            out.addProperty("action_tick",MAX_TICKS-horizon);out.addProperty("preempted_before_motion",preemptedBeforeMotion);
            JsonObject guard=json();require(WIRE.toJson(guard).getBytes(StandardCharsets.UTF_8).length<=MAX_STOP_FRAME_BYTES,"route_spatial_stop_evidence_too_large");
            out.add("entity_guard",guard);
            require(WIRE.toJson(out).getBytes(StandardCharsets.UTF_8).length<=MAX_STOP_PROOF_BYTES,
                "route_spatial_stop_evidence_too_large");return out;
        }
    }
    static final java.util.Comparator<Row> ORDER=java.util.Comparator.comparingInt(Row::id).thenComparing(Row::uuid).thenComparing(Row::className);
    static boolean active(Row row,long tick,long frameNano,String playerUuid,String world,String dimension){
        try{return checkedActive(row,tick,frameNano,playerUuid,world,dimension);}
        catch(IllegalArgumentException rejected){
            throw new RouteThreatDiagnostics.FailedRow(rejected,row,tick,frameNano,playerUuid,world,dimension);
        }
    }
    private static boolean checkedActive(Row row,long tick,long frameNano,String playerUuid,String world,String dimension){
        JsonObject n=row.nativeLiving;
        require(n!=null&&n.keySet().equals(LIVING_KEYS)&&n.get("schema_version").getAsInt()==1
            &&n.get("known").getAsBoolean()&&n.get("coverage_complete").getAsBoolean()&&n.get("alive").getAsBoolean()
            &&n.get("current_target_known").getAsBoolean()&&n.get("source").getAsString().equals("integrated_server_tick")
            &&n.get("reason").getAsString().equals("observed")&&n.get("entity_uuid").getAsString().equals(row.uuid)
            &&n.get("entity_id").getAsInt()==row.id&&n.get("entity_type").getAsString().equals(row.type)
            &&n.get("player_uuid").getAsString().equals(playerUuid)&&n.get("world_generation").getAsString().equals(world)
            &&n.get("dimension").getAsString().equals(dimension)&&n.get("inspected").getAsInt()>=1&&n.get("inspected").getAsInt()<=4096,
            "route_spatial_native_target_unconfirmed");
        long sample=nano(n,"sample_nano"),source=nano(n,"source_nano"),sourceTick=n.get("source_tick").getAsLong();
        double age=n.get("sample_age_ms").getAsDouble();
        require(n.get("sample_tick").getAsLong()==tick&&sourceTick>=0&&Math.abs(tick-sourceTick)<=5
            &&sample>=source&&sample-source<=250_000_000L&&sample>=frameNano&&sample-frameNano<=250_000_000L
            &&Double.isFinite(age)&&age>=0&&age<=250&&Math.abs(age-(sample-source)/1_000_000.)<=.000001,
            "route_spatial_native_target_stale");
        if(n.get("current_target").isJsonNull()){require(!n.get("aggressive").getAsBoolean(),"route_spatial_targetless_aggression_unknown");return false;}
        require(n.get("current_target").isJsonObject(),"route_spatial_target_unknown");JsonObject target=n.getAsJsonObject("current_target");
        require(target.keySet().equals(Set.of("uuid","entity_id","type"))&&target.get("uuid").getAsString().equals(playerUuid)
            &&target.get("type").getAsString().equals("minecraft:player")&&target.get("entity_id").getAsInt()>=0,
            "route_spatial_other_target_unknown");return true;
    }
    static void requireResponseSizes(int standalone,int capability,int responseLimit){
        require(standalone>=0&&capability>=0&&responseLimit>=3*STOP_GROWTH_BYTES
            &&standalone<=responseLimit-STOP_GROWTH_BYTES&&capability<=responseLimit-3*STOP_GROWTH_BYTES,
            "scoped_movement_response_evidence_too_large");
    }
    private static long nano(JsonObject object,String key){
        var value=object.get(key);require(value!=null&&value.isJsonPrimitive()&&value.getAsJsonPrimitive().isString()
            &&value.getAsString().matches("-?(0|[1-9][0-9]{0,18})"),"route_spatial_clock_invalid");return Long.parseLong(value.getAsString());
    }
    private static double distance(V a,V b){return Math.hypot(Math.hypot(a.x()-b.x(),a.z()-b.z()),a.y()-b.y());}
    private ScopedRouteThreatPolicy(){}
}

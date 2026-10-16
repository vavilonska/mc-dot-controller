package io.github.campione01.mineclientbridge;

import com.google.gson.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import static io.github.campione01.mineclientbridge.ScopedEntityPolicy.*;

/** Versioned default-stop geometry. Exact far passives are never an unknown-far exemption. */
final class ScopedRouteStopPolicy {
    static final String PROFILE="movement-local-segment-spatial-stop-v1", POLICY="route-spatial-stop-v1";
    static final String PROFILE_V2="movement-local-segment-spatial-stop-v2", POLICY_V2="route-spatial-stop-v2";
    static final String SCOPE_V2="all-client-loaded-route-swept-and-far-passives-and-calm-bees";
    static final String BEE="minecraft:bee", BEE_CLASS="net.minecraft.world.entity.animal.Bee";
    static final String SCOPE="all-client-loaded-route-swept-and-far-passives";
    static final Map<String,String> FAR_CLASSES=Map.ofEntries(
        Map.entry("minecraft:bat","net.minecraft.world.entity.ambient.Bat"),
        Map.entry("minecraft:cod","net.minecraft.world.entity.animal.Cod"),
        Map.entry("minecraft:salmon","net.minecraft.world.entity.animal.Salmon"),
        Map.entry("minecraft:tropical_fish","net.minecraft.world.entity.animal.TropicalFish"),
        Map.entry("minecraft:squid","net.minecraft.world.entity.animal.Squid"),
        Map.entry("minecraft:glow_squid","net.minecraft.world.entity.GlowSquid"),
        Map.entry("minecraft:turtle","net.minecraft.world.entity.animal.Turtle"),
        Map.entry("minecraft:cat","net.minecraft.world.entity.animal.Cat"),
        Map.entry("minecraft:ocelot","net.minecraft.world.entity.animal.Ocelot"),
        Map.entry("minecraft:parrot","net.minecraft.world.entity.animal.Parrot"),
        Map.entry("minecraft:horse","net.minecraft.world.entity.animal.horse.Horse"),
        Map.entry("minecraft:donkey","net.minecraft.world.entity.animal.horse.Donkey"),
        Map.entry("minecraft:mule","net.minecraft.world.entity.animal.horse.Mule"),
        Map.entry("minecraft:villager","net.minecraft.world.entity.npc.Villager"),
        Map.entry("minecraft:wandering_trader","net.minecraft.world.entity.npc.WanderingTrader"));
    static final Map<String,String> NEAR_CLASSES;
    static {var near=new HashMap<>(ScopedEntityPolicy.CLASSES);near.remove("minecraft:rabbit");NEAR_CLASSES=Map.copyOf(near);}
    private static final Gson WIRE=new GsonBuilder().serializeNulls().disableHtmlEscaping().create();
    static boolean far(String type){return BEE.equals(type)||FAR_CLASSES.containsKey(type);}
    static String expectedClass(String type){return BEE.equals(type)?BEE_CLASS:far(type)?FAR_CLASSES.get(type):NEAR_CLASSES.get(type);}
    static Box swept(ScopedLocalSegmentPolicy.Bounds route){return ScopedRouteThreatPolicy.swept(route);}
    record Row(int id,String uuid,String type,String className,boolean removed,V position,Box box,V velocity,V target,Flags flags,Box projected,JsonObject nativeLiving){
        Row(int id,String uuid,String type,String className,boolean removed,V position,Box box,V velocity,V target,Flags flags,Box projected){this(id,uuid,type,className,removed,position,box,velocity,target,flags,projected,null);}
        Row {
            require(uuid!=null&&UUID.fromString(uuid).toString().equals(uuid)&&type!=null&&!type.isBlank()
                &&className!=null&&!className.isBlank(),"route_stop_identity_invalid");
            if(removed)require(position==null&&box==null&&velocity==null&&target==null&&flags==null&&projected==null&&nativeLiving==null,"route_stop_removed_shape");
            else {
                require(className.equals(expectedClass(type)),"route_stop_entity_unsupported");
                boolean living=!Set.of("minecraft:boat","minecraft:chest_minecart","minecraft:item").contains(type);
                require(position!=null&&box!=null&&velocity!=null&&target!=null&&flags!=null&&projected!=null&&box.contains(position),"route_stop_geometry_missing");
                require(flags.living()==living&&flags.alive()&&!flags.dying()&&!flags.passenger()&&!flags.hasPassengers()
                    &&!flags.leashed()&&!flags.noPhysics()&&!flags.onFire()&&flags.activeEffects()==0&&flags.hurtTime()==0&&flags.target()==null,
                    "route_stop_entity_state_unknown");
                require(BEE.equals(type)==(nativeLiving!=null),"route_bee_native_unconfirmed");
                if(nativeLiving!=null)nativeLiving=nativeLiving.deepCopy();
            }
        }
        JsonObject json(){
            JsonObject j=new JsonObject();j.addProperty("id",id);j.addProperty("uuid",uuid);j.addProperty("type",type);j.addProperty("class",className);j.addProperty("removed",removed);
            if(!removed){j.add("position",position.json());j.add("aabb",box.json());j.add("velocity",velocity.json());j.add("lerp_target",target.json());j.add("flags",flags.json());j.add("projected_aabb",projected.json());j.addProperty("verdict",far(type)?"outside_context":"outside_swept");if(nativeLiving!=null)j.add("native_living",nativeLiving.deepCopy());}return j;
        }
    }
    record Frame(long tick,long nano,int horizon,int selfCount,Box prism,Box swept,List<Row> rows,boolean bees,String playerUuid,String world,String dimension){
        Frame(long tick,long nano,int horizon,int selfCount,Box prism,Box swept,List<Row> rows){this(tick,nano,horizon,selfCount,prism,swept,rows,false,null,null,null);}
        Frame {
            require(tick>=0&&horizon>=0&&horizon<=MAX_TICKS&&selfCount==1&&rows!=null&&rows.size()+1<=LIMIT,"route_stop_coverage_invalid");
            rows=List.copyOf(rows);var ids=new HashSet<Integer>();var uuids=new HashSet<String>();Row previous=null;
            for(Row row:rows){
                require(ids.add(row.id)&&uuids.add(row.uuid),"route_stop_duplicate_identity");
                require(previous==null||ORDER.compare(previous,row)<0,"route_stop_order_invalid");previous=row;
                if(row.removed)continue;
                require(bees||!BEE.equals(row.type),"route_stop_entity_unsupported");
                if(BEE.equals(row.type))ScopedRouteBeePolicy.validate(row,tick,nano,playerUuid,world,dimension);
                validateGeometry(row,prism,swept,horizon);
            }
        }
        int population(){return rows.size()+1;}
        JsonObject json(){
            JsonObject j=new JsonObject();j.addProperty("schema_version",bees?2:1);j.addProperty("policy",bees?POLICY_V2:POLICY);j.addProperty("source","native-client-loaded-level");j.addProperty("scope",bees?SCOPE_V2:SCOPE);j.addProperty("guarantee","same-callback-current-facts-only");
            j.addProperty("future_dynamics_certified",false);j.addProperty("server_confirmed",false);j.addProperty("entity_limit",LIMIT);j.addProperty("enumerated_count",population());j.addProperty("self_count",1);
            int removed=(int)rows.stream().filter(Row::removed).count();j.addProperty("live_other_count",rows.size()-removed);j.addProperty("removed_count",removed);j.addProperty("unsupported_count",0);
            j.addProperty("source_tick",tick);j.addProperty("source_nano",Long.toString(nano));j.addProperty("maximum_action_ticks",MAX_TICKS);j.addProperty("remaining_projection_ticks",horizon);j.add("prism",prism.json());j.add("swept_aabb",swept.json());
            JsonArray a=new JsonArray();for(Row r:rows)a.add(r.json());j.add("rows",a);require(WIRE.toJson(j).getBytes(StandardCharsets.UTF_8).length<=MAX_FRAME_BYTES,"route_stop_evidence_too_large");return j;
        }
    }
    static void validateGeometry(Row row,Box prism,Box swept,int horizon){
        if(row.removed)return;
        require(project(row.box,row.position,row.velocity,row.target,horizon).equals(row.projected),"route_stop_projection_changed");
        require(row.projected.separate(far(row.type)?prism:swept),far(row.type)?"route_stop_far_context_conflict":"route_stop_projected_body_conflict");
    }
    static final Comparator<Row> ORDER=Comparator.comparingInt(Row::id).thenComparing(Row::uuid).thenComparing(Row::className);
    private ScopedRouteStopPolicy(){}
}

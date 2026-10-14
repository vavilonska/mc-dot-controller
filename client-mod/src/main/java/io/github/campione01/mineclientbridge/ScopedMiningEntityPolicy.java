package io.github.campione01.mineclientbridge;

import com.google.gson.JsonArray;
import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonNull;
import com.google.gson.JsonObject;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/** Pure observed-frame geometry/serialization. Projects observed motion; never certifies future physics. */
final class ScopedMiningEntityPolicy {
    static final String POLICY="mining-observed-items-v1";
    private static final Gson WIRE=new GsonBuilder().serializeNulls().disableHtmlEscaping().create();
    static final int LIMIT=1024, MAX_TICKS=160, MAX_FRAME_BYTES=192*1024, TERMINAL_GROWTH_BYTES=8192;
    static final Map<String,String> CLASSES=Map.of(
        "minecraft:sheep","net.minecraft.world.entity.animal.Sheep",
        "minecraft:cow","net.minecraft.world.entity.animal.Cow",
        "minecraft:chicken","net.minecraft.world.entity.animal.Chicken",
        "minecraft:pig","net.minecraft.world.entity.animal.Pig",
        "minecraft:rabbit","net.minecraft.world.entity.animal.Rabbit",
        "minecraft:frog","net.minecraft.world.entity.animal.frog.Frog",
        "minecraft:boat","net.minecraft.world.entity.vehicle.Boat",
        "minecraft:chest_minecart","net.minecraft.world.entity.vehicle.MinecartChest",
        "minecraft:item","net.minecraft.world.entity.item.ItemEntity");
    record V(double x,double y,double z) {
        V { require(finite(x,y,z),"scoped_movement_entity_nonfinite"); }
        JsonArray json(){return array(x,y,z);}
    }
    record Box(double minX,double minY,double minZ,double maxX,double maxY,double maxZ) {
        Box { require(finite(minX,minY,minZ,maxX,maxY,maxZ) && minX<maxX && minY<maxY && minZ<maxZ,
                "scoped_movement_entity_box_invalid"); }
        boolean contains(V p){return p.x>=minX && p.x<=maxX && p.y>=minY && p.y<=maxY && p.z>=minZ && p.z<=maxZ;}
        boolean separate(Box p){return maxX<p.minX || minX>p.maxX || maxY<p.minY || minY>p.maxY || maxZ<p.minZ || minZ>p.maxZ;}
        JsonArray json(){return array(minX,minY,minZ,maxX,maxY,maxZ);}
    }
    record Flags(boolean living,boolean alive,boolean dying,boolean passenger,boolean hasPassengers,
            boolean leashed,boolean noPhysics,boolean onFire,int activeEffects,int hurtTime,String target) {
        JsonObject json(){
            JsonObject j=new JsonObject();j.addProperty("living",living);j.addProperty("alive",alive);
            j.addProperty("dying",dying);j.addProperty("passenger",passenger);j.addProperty("has_passengers",hasPassengers);
            j.addProperty("leashed",leashed);j.addProperty("no_physics",noPhysics);j.addProperty("on_fire",onFire);
            j.addProperty("active_effect_count",activeEffects);j.addProperty("hurt_time",hurtTime);
            if(target==null)j.add("mob_target_uuid",JsonNull.INSTANCE);else j.addProperty("mob_target_uuid",target);
            return j;
        }
    }
    record Row(int id,String uuid,String type,String className,boolean removed,V position,Box box,V velocity,
            V target,Flags flags,Box projected) {
        Row {
            require(uuid!=null && type!=null && !type.isBlank() && className!=null && !className.isBlank(),
                    "scoped_movement_entity_identity_missing");
            try { require(UUID.fromString(uuid).toString().equals(uuid),"scoped_movement_entity_uuid_invalid"); }
            catch(IllegalArgumentException bad){throw rejected("scoped_movement_entity_uuid_invalid");}
            if(removed)require(position==null && box==null && velocity==null && target==null && flags==null && projected==null,
                    "scoped_movement_removed_entity_shape");
            else {
                require(className.equals(CLASSES.get(type)),"scoped_movement_entity_unsupported");
                boolean living=!type.equals("minecraft:boat") && !type.equals("minecraft:chest_minecart") && !type.equals("minecraft:item");
                require(position!=null && box!=null && velocity!=null && target!=null && flags!=null && projected!=null
                        && box.contains(position),"scoped_movement_entity_geometry_missing");
                require(flags.living==living && flags.alive && !flags.dying && !flags.passenger && !flags.hasPassengers
                        && !flags.leashed && !flags.noPhysics && !flags.onFire && flags.activeEffects==0 && flags.hurtTime==0
                        && flags.target==null,"scoped_movement_entity_state_unknown");
            }
        }
        JsonObject json(){
            JsonObject j=new JsonObject();j.addProperty("id",id);j.addProperty("uuid",uuid);j.addProperty("type",type);
            j.addProperty("class",className);j.addProperty("removed",removed);
            if(!removed){j.add("position",position.json());j.add("aabb",box.json());j.add("velocity",velocity.json());
                j.add("lerp_target",target.json());j.add("flags",flags.json());j.add("projected_aabb",projected.json());j.addProperty("verdict",type.equals("minecraft:item")?"passive_item":"outside");}
            return j;
        }
    }
    record Frame(long tick,long nano,int horizon,int selfCount,Box prism,List<Row> rows) {
        Frame {
            require(horizon>=0 && horizon<=MAX_TICKS && selfCount==1 && rows!=null && rows.size()+selfCount<=LIMIT,
                    "scoped_movement_entity_coverage_invalid");
            rows=List.copyOf(rows);
            var ids=new HashSet<Integer>();var uuids=new HashSet<String>();Row previous=null;
            for(Row row:rows){
                require(ids.add(row.id) && uuids.add(row.uuid),"scoped_movement_entity_duplicate_identity");
                require(previous==null || ORDER.compare(previous,row)<0,"scoped_movement_entity_order_invalid");
                if(!row.removed){
                    require(project(row.box,row.position,row.velocity,row.target,horizon).equals(row.projected),
                            "scoped_movement_entity_projection_changed");
                    require(row.type.equals("minecraft:item") || row.projected.separate(prism),"scoped_movement_entity_projected_corridor_conflict");
                }
                previous=row;
            }
        }
        int population(){return selfCount+rows.size();}
        JsonObject json(){
            JsonObject j=new JsonObject();j.addProperty("schema_version",1);j.addProperty("policy",POLICY);
            j.addProperty("source","native-client-loaded-level");
            j.addProperty("scope","all-client-loaded-mining-prism-with-passive-items");
            j.addProperty("guarantee","same-callback-current-facts-only");
            j.addProperty("future_dynamics_certified",false);j.addProperty("server_confirmed",false);
            j.addProperty("entity_limit",LIMIT);j.addProperty("enumerated_count",population());j.addProperty("self_count",selfCount);
            int removed=(int)rows.stream().filter(Row::removed).count();
            j.addProperty("live_other_count",rows.size()-removed);j.addProperty("removed_count",removed);j.addProperty("unsupported_count",0);
            j.addProperty("source_tick",tick);j.addProperty("source_nano",Long.toString(nano));
            j.addProperty("maximum_action_ticks",MAX_TICKS);j.addProperty("remaining_projection_ticks",horizon);
            j.add("prism",prism.json());JsonArray a=new JsonArray();for(Row row:rows)a.add(row.json());j.add("rows",a);
            require(WIRE.toJson(j).getBytes(StandardCharsets.UTF_8).length<=MAX_FRAME_BYTES,
                    "scoped_movement_entity_evidence_too_large");
            return j;
        }
    }
    static final Comparator<Row> ORDER=Comparator.comparingInt(Row::id).thenComparing(Row::uuid).thenComparing(Row::className);
    static Frame frame(long tick,long nano,int horizon,int self,Box prism,List<Row> rows){
        var sorted=new ArrayList<>(rows);sorted.sort(ORDER);return new Frame(tick,nano,horizon,self,prism,sorted);
    }
    static Box project(Box box,V position,V velocity,V target,int horizon){
        require(horizon>=0 && horizon<=MAX_TICKS,"scoped_movement_entity_horizon_invalid");
        double lx=target.x-position.x,ly=target.y-position.y,lz=target.z-position.z;
        double mx=horizon*velocity.x,my=horizon*velocity.y,mz=horizon*velocity.z;
        require(finite(lx,ly,lz,mx,my,mz),"scoped_movement_entity_projection_nonfinite");
        return new Box(extreme(box.minX,lx,mx,false),extreme(box.minY,ly,my,false),extreme(box.minZ,lz,mz,false),
                extreme(box.maxX,lx,mx,true),extreme(box.maxY,ly,my,true),extreme(box.maxZ,lz,mz,true));
    }
    private static double extreme(double b,double l,double m,boolean maximum){
        double bl=b+l,bm=b+m,blm=bl+m;
        require(finite(bl,bm,blm),"scoped_movement_entity_projection_nonfinite");
        return maximum?Math.max(Math.max(b,bl),Math.max(bm,blm)):Math.min(Math.min(b,bl),Math.min(bm,blm));
    }
    /** Pure transport-bound predicate shared by the real pre-effect preview and finite fixtures. */
    static void requireResponseSizes(int standalone,int capability,int responseLimit){
        require(standalone>=0 && capability>=0 && responseLimit>=3*TERMINAL_GROWTH_BYTES
                && standalone<=responseLimit-TERMINAL_GROWTH_BYTES
                && capability<=responseLimit-3*TERMINAL_GROWTH_BYTES,
                "scoped_movement_response_evidence_too_large");
    }
    private static JsonArray array(double...v){JsonArray a=new JsonArray();for(double n:v)a.add(n);return a;}
    private static boolean finite(double...v){for(double n:v)if(!Double.isFinite(n))return false;return true;}
    static void require(boolean ok,String reason){if(!ok)throw rejected(reason);}
    private static IllegalArgumentException rejected(String reason){return new IllegalArgumentException(reason);}
    private ScopedMiningEntityPolicy() { }
}

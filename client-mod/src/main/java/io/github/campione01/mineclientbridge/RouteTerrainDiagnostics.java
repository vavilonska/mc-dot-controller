package io.github.campione01.mineclientbridge;

import com.google.gson.*;
import java.util.List;
import java.util.Set;

/** Bounded evidence for one actual rejected cell. It confers no movement or known-outcome authority. */
final class RouteTerrainDiagnostics {
    static final String POLICY="local-segment-terrain-equivalence-v1";
    static final List<String> FIELDS=List.of("loaded","id","state","fluid_empty","full_cube","collision_empty","friction");
    static final Set<String> CODES=Set.of("local_segment_unknown_corridor_cell","local_segment_fluid_present",
        "local_segment_floor_unsupported","local_segment_special_friction","local_segment_clearance_or_hazard_changed",
        "local_segment_footprint_changed","local_segment_corridor_unloaded_after_hooks","local_segment_corridor_changed_after_hooks");
    private final JsonObject original,current=new JsonObject();
    private final String phase,profile;
    private boolean bounded=true;
    RouteTerrainDiagnostics(JsonObject original,String phase){
        this(original,phase,ScopedRouteStopPolicy.PROFILE);
    }
    RouteTerrainDiagnostics(JsonObject original,String phase,String profile){
        this.original=original.deepCopy();this.phase=phase;this.profile=profile;
        current.addProperty("loaded",false);current.addProperty("role",original.get("role").getAsString());
        for(String key:FIELDS)if(!key.equals("loaded"))current.add(key,JsonNull.INSTANCE);
    }
    void loaded(boolean loaded){current.addProperty("loaded",loaded);}
    void flag(String key,boolean value){current.addProperty(key,value);}
    void state(String id,String state){
        if(id==null||id.length()>128||state==null||state.length()>512){bounded=false;return;}
        current.addProperty("id",id);current.addProperty("state",state);
    }
    void friction(float value){if(Float.isFinite(value))current.addProperty("friction",value);}
    void validated(JsonObject row){
        loaded(true);state(row.get("id").getAsString(),row.get("state").getAsString());flag("fluid_empty",true);
        flag("full_cube",row.get("full_cube").getAsBoolean());flag("collision_empty",!row.get("full_cube").getAsBoolean());
        friction(row.get("friction").getAsFloat());
    }
    ClientActionRequest.Rejected attach(ClientActionRequest.Rejected failure){
        if(!bounded||!CODES.contains(failure.getMessage())||original.get("id").getAsString().length()>128
                ||original.get("state").getAsString().length()>512)return failure;
        JsonObject out=new JsonObject(),cell=new JsonObject(),baseline=new JsonObject();
        out.addProperty("schema_version",1);out.addProperty("profile",profile);out.addProperty("policy",POLICY);
        out.addProperty("phase",phase);out.addProperty("rejection_code",failure.getMessage());
        for(String key:List.of("x","y","z"))cell.add(key,original.get(key).deepCopy());
        out.add("cell",cell);out.add("original",original.deepCopy());out.add("current",current.deepCopy());
        baseline.addProperty("loaded",true);baseline.add("id",original.get("id"));baseline.add("state",original.get("state"));
        baseline.addProperty("fluid_empty",true);baseline.add("full_cube",original.get("full_cube"));
        baseline.addProperty("collision_empty",!original.get("full_cube").getAsBoolean());baseline.add("friction",original.get("friction"));
        JsonArray changed=new JsonArray();for(String key:FIELDS)if(!current.get(key).isJsonNull()&&!baseline.get(key).equals(current.get(key)))changed.add(key);
        out.add("changed_fields",changed);
        return new ClientActionRequest.Rejected(failure.httpStatus,failure.getMessage(),failure.capabilitySourceFreshness,
            failure.scopedMovementResponseSize,failure.routeEntityRejection,out);
    }
}

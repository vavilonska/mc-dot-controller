package io.github.campione01.mineclientbridge;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonElement;
import com.google.gson.JsonNull;
import com.google.gson.JsonObject;
import java.nio.charset.StandardCharsets;
import java.util.Set;
import java.util.UUID;

/** Detached, bounded refusal facts. No live readers, admission decision, or replay authority. */
final class RouteThreatDiagnostics {
    static final int MAX_BYTES=4096;
    private static final Gson WIRE=new GsonBuilder().serializeNulls().disableHtmlEscaping().create();
    private static final Set<String> CODES=Set.of("route_spatial_native_target_unconfirmed",
        "route_spatial_native_target_stale","route_spatial_clock_invalid","route_spatial_targetless_aggression_unknown",
        "route_spatial_target_unknown","route_spatial_other_target_unknown");
    private static final Set<String> PHASES=Set.of("capture","recheck","final_fence");
    private static final Set<String> REASONS=Set.of("observed","context_unavailable","dimension_changed",
        "inspection_limit","row_limit","duplicate_entity_uuid","native_read_failed","entity_not_observed",
        "entity_identity_changed","source_expired","source_tick_mismatch","invalid_anger_time","invalid_rabbit_variant");

    /** Wraps only an already-failed check and retains its original machine reason. */
    static final class FailedRow extends IllegalArgumentException {
        final ScopedRouteThreatPolicy.Row row;
        final long tick,nano;
        final Long finalCheckNano;
        final String player,world,dimension;
        FailedRow(IllegalArgumentException original,ScopedRouteThreatPolicy.Row row,long tick,long nano,
                String player,String world,String dimension){
            this(original,row,tick,nano,player,world,dimension,null);
        }
        FailedRow(IllegalArgumentException original,ScopedRouteThreatPolicy.Row row,long tick,long nano,
                String player,String world,String dimension,Long finalCheckNano){
            super(original.getMessage(),original);this.row=row;this.tick=tick;this.nano=nano;
            this.player=player;this.world=world;this.dimension=dimension;this.finalCheckNano=finalCheckNano;
        }
    }

    static ClientActionRequest.Rejected rejection(FailedRow failed,NativeLivingSnapshot.Batch batch,
            Object capturedContext,String selectedUuid,String phase){
        return new ClientActionRequest.Rejected(409,failed.getMessage(),null,null,null,null,
            json(failed,batch,capturedContext,selectedUuid,phase));
    }
    static JsonObject json(FailedRow failed,NativeLivingSnapshot.Batch batch,Object capturedContext,
            String selectedUuid,String phase){
        try{return bounded(failed,batch,capturedContext,selectedUuid,phase);}
        catch(RuntimeException unavailable){return null;} // Never replace the original refusal.
    }
    private static JsonObject bounded(FailedRow f,NativeLivingSnapshot.Batch batch,Object context,
            String selectedUuid,String phase){
        if(f==null||f.row==null||!CODES.contains(f.getMessage()==null?"":f.getMessage())||!PHASES.contains(phase)
                ||!ScopedRouteThreatPolicy.ZOMBIE.equals(f.row.type())||!uuid(f.row.uuid())
                ||!uuid(f.player)||!uuid(f.world)||!uuid(selectedUuid)||!resource(f.dimension)||f.tick<0
                ||phase.equals("final_fence")!=(f.finalCheckNano!=null))return null;
        JsonObject j=new JsonObject();j.addProperty("schema_version",1);
        j.addProperty("profile",ScopedRouteThreatPolicy.PROFILE);j.addProperty("policy",ScopedRouteThreatPolicy.POLICY);
        j.addProperty("rejection_code",f.getMessage());j.addProperty("phase",phase);
        JsonObject e=new JsonObject();e.addProperty("id",f.row.id());e.addProperty("uuid",f.row.uuid());
        e.addProperty("type",f.row.type());e.addProperty("selected",f.row.uuid().equals(selectedUuid));j.add("entity",e);
        JsonObject c=new JsonObject();c.addProperty("dimension",f.dimension);c.addProperty("world_generation",f.world);
        c.addProperty("player_uuid",f.player);c.addProperty("selected_target_uuid",selectedUuid);
        c.addProperty("frame_tick",f.tick);c.addProperty("frame_nano",Long.toString(f.nano));
        if(f.finalCheckNano==null)c.add("final_check_nano",JsonNull.INSTANCE);else c.addProperty("final_check_nano",Long.toString(f.finalCheckNano));j.add("context",c);
        JsonObject original=f.row.nativeLiving(),n=new JsonObject();n.addProperty("present",original!=null);
        n.add("known",bool(original,"known"));n.addProperty("reason",reason(string(original,"reason")));
        n.add("coverage_complete",bool(original,"coverage_complete"));n.add("inspected",integer(original,"inspected",0,4097));
        n.add("sample_tick",integer(original,"sample_tick",Long.MIN_VALUE,Long.MAX_VALUE));
        n.add("sample_nano",nano(original,"sample_nano"));
        n.add("source_tick",integer(original,"source_tick",Long.MIN_VALUE,Long.MAX_VALUE));
        n.add("source_nano",nano(original,"source_nano"));n.add("sample_age_ms",number(original,"sample_age_ms"));
        n.add("alive",bool(original,"alive"));n.add("current_target_known",bool(original,"current_target_known"));j.add("native",n);
        // Source facts refer to precisely the captured immutable batch. Never refresh a failed witness.
        NativeLivingSnapshot.Row row=batch==null?null:batch.rows().get(f.row.uuid());
        JsonObject s=new JsonObject();s.addProperty("batch_present",batch!=null);
        s.addProperty("batch_context_matches",batch!=null&&context!=null&&batch.context()==context);
        s.addProperty("row_present",row!=null);
        s.addProperty("row_identity_matches",row!=null&&f.row.uuid().equals(row.uuid())&&f.row.id()==row.entityId()&&f.row.type().equals(row.type()));
        s.add("batch_complete",batch==null?JsonNull.INSTANCE:WIRE.toJsonTree(batch.complete()));
        s.addProperty("batch_reason",reason(batch==null?null:batch.reason()));
        if(row==null){s.add("row_tick",JsonNull.INSTANCE);s.add("row_nano",JsonNull.INSTANCE);}
        else{s.addProperty("row_tick",row.tick());s.addProperty("row_nano",Long.toString(row.nano()));}
        j.add("source",s);
        return WIRE.toJson(j).getBytes(StandardCharsets.UTF_8).length<=MAX_BYTES?j:null;
    }
    private static boolean uuid(String v){try{return v!=null&&UUID.fromString(v).toString().equals(v);}catch(IllegalArgumentException e){return false;}}
    private static boolean resource(String v){return v!=null&&v.length()<=128&&v.matches("[a-z0-9_.-]+:[a-z0-9_./-]+");}
    private static String reason(String v){return v==null?"unavailable":REASONS.contains(v)?v:"unrecognized";}
    private static JsonElement value(JsonObject j,String key){return j==null?null:j.get(key);}
    private static String string(JsonObject j,String key){var v=value(j,key);return v!=null&&v.isJsonPrimitive()&&v.getAsJsonPrimitive().isString()?v.getAsString():null;}
    private static JsonElement bool(JsonObject j,String key){var v=value(j,key);return v!=null&&v.isJsonPrimitive()&&v.getAsJsonPrimitive().isBoolean()?v.deepCopy():JsonNull.INSTANCE;}
    private static JsonElement number(JsonObject j,String key){var v=value(j,key);return v!=null&&v.isJsonPrimitive()&&v.getAsJsonPrimitive().isNumber()&&Double.isFinite(v.getAsDouble())?v.deepCopy():JsonNull.INSTANCE;}
    private static JsonElement integer(JsonObject j,String key,long min,long max){var v=value(j,key);
        if(v==null||!v.isJsonPrimitive()||!v.getAsJsonPrimitive().isNumber())return JsonNull.INSTANCE;
        try{String raw=v.getAsString();if(!raw.matches("0|-?[1-9][0-9]{0,18}"))return JsonNull.INSTANCE;
            long n=Long.parseLong(raw);return n>=min&&n<=max?v.deepCopy():JsonNull.INSTANCE;
        }catch(NumberFormatException invalid){return JsonNull.INSTANCE;}}
    private static JsonElement nano(JsonObject j,String key){String v=string(j,key);
        if(v==null||!v.matches("0|-?[1-9][0-9]{0,18}"))return JsonNull.INSTANCE;
        try{Long.parseLong(v);return value(j,key).deepCopy();}catch(NumberFormatException invalid){return JsonNull.INSTANCE;}}
    private RouteThreatDiagnostics(){}
}

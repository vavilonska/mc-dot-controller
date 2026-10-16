package io.github.campione01.mineclientbridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonNull;
import com.google.gson.JsonObject;
import java.nio.charset.StandardCharsets;
import java.util.Set;
import java.util.UUID;

/** Closed, bounded refusal evidence only. Never participates in an admission decision. */
final class RouteBeeDiagnostics {
    static final int MAX_BYTES=8192;
    private static final Set<String> REASONS=Set.of("observed","context_unavailable","dimension_changed",
        "inspection_limit","row_limit","duplicate_entity_uuid","native_read_failed","entity_not_observed",
        "entity_identity_changed","source_expired","source_tick_mismatch","invalid_anger_time","invalid_rabbit_variant");
    private static final Set<String> READ_STATUSES=Set.of("observed","not_exact_bee","hive_position_class_untrusted",
        "flower_position_class_untrusted","positions_class_untrusted","not_recorded");
    record Context(String dimension,String worldGeneration,String playerUuid,long tick,long nano,
                   double playerX,double playerY,double playerZ,ScopedEntityPolicy.Box prism,ScopedEntityPolicy.Box swept) { }
    static JsonObject json(ScopedRouteStopPolicy.Row entity,NativeLivingObservation.Frame frame,Context context){
        try { return bounded(entity,frame,context); }
        catch(RuntimeException unavailable){return null;} // A diagnostic failure never replaces the original refusal.
    }
    private static JsonObject bounded(ScopedRouteStopPolicy.Row entity,NativeLivingObservation.Frame frame,Context c){
        if(entity==null||c==null||!ScopedRouteStopPolicy.BEE.equals(entity.type())||!uuid(entity.uuid())
                ||!uuid(c.worldGeneration())||!uuid(c.playerUuid())||c.dimension()==null||c.dimension().length()>128
                ||!c.dimension().matches("[a-z0-9_.-]+:[a-z0-9_./-]+")
                ||!finite(c.playerX(),c.playerY(),c.playerZ())||c.prism()==null||c.swept()==null)return null;
        JsonObject j=new JsonObject();j.addProperty("schema_version",1);
        JsonObject e=new JsonObject();e.addProperty("id",entity.id());e.addProperty("uuid",entity.uuid());e.addProperty("type",entity.type());
        boolean geometry=entity.position()!=null&&entity.box()!=null&&entity.velocity()!=null&&entity.target()!=null;
        e.add("position",geometry?entity.position().json():JsonNull.INSTANCE);e.add("aabb",geometry?entity.box().json():JsonNull.INSTANCE);
        e.add("velocity",geometry?entity.velocity().json():JsonNull.INSTANCE);e.add("lerp_target",geometry?entity.target().json():JsonNull.INSTANCE);j.add("entity",e);
        NativeLivingSnapshot.Batch batch=frame==null?null:frame.batch();
        NativeLivingSnapshot.Row row=batch==null?null:batch.rows().get(entity.uuid());
        JsonObject original=entity.nativeLiving(),n=new JsonObject();n.addProperty("present",original!=null);
        n.add("known",bool(original,"known"));n.add("coverage_complete",bool(original,"coverage_complete"));
        String reason=string(original,"reason");n.addProperty("reason",original==null?"unavailable":REASONS.contains(reason==null?"":reason)?reason:"unrecognized");
        n.add("inspected",integer(original,"inspected",0,4097));
        n.add("sample_tick",integer(original,"sample_tick",Long.MIN_VALUE,Long.MAX_VALUE));
        n.add("sample_nano",nano(original,"sample_nano"));n.add("sample_age_ms",number(original,"sample_age_ms"));
        if(row==null){n.add("source_tick",integer(original,"source_tick",Long.MIN_VALUE,Long.MAX_VALUE));n.add("source_nano",nano(original,"source_nano"));}
        else {n.addProperty("source_tick",row.tick());n.addProperty("source_nano",Long.toString(row.nano()));}
        j.add("native",n);
        JsonObject route=new JsonObject();route.addProperty("present",original!=null&&original.has("bee_route")&&original.get("bee_route").isJsonObject());
        route.addProperty("captured",row!=null&&row.beeRoute()!=null);
        String status=row==null?"row_unavailable":row.beeRouteReadStatus();
        route.addProperty("read_status",row==null?"row_unavailable":READ_STATUSES.contains(status==null?"":status)?status:"not_recorded");j.add("route",route);
        JsonObject source=new JsonObject();source.addProperty("context_current",frame!=null&&NativeLivingObservation.current(frame));
        source.addProperty("batch_present",batch!=null);source.addProperty("batch_context_matches",batch!=null&&frame.context()!=null&&batch.context()==frame.context());
        source.addProperty("row_present",row!=null);source.addProperty("row_identity_matches",row!=null&&row.uuid().equals(entity.uuid())&&row.entityId()==entity.id()&&row.type().equals(entity.type()));
        source.addProperty("source_radius_blocks",128);j.add("source",source);
        JsonObject context=new JsonObject();context.addProperty("dimension",c.dimension());context.addProperty("world_generation",c.worldGeneration());
        context.addProperty("player_uuid",c.playerUuid());context.addProperty("client_tick",c.tick());context.addProperty("frame_nano",Long.toString(c.nano()));
        context.add("player_position",array(c.playerX(),c.playerY(),c.playerZ()));context.add("prism",c.prism().json());context.add("swept_aabb",c.swept().json());j.add("context",context);
        return j.toString().getBytes(StandardCharsets.UTF_8).length<=MAX_BYTES?j:null;
    }
    private static JsonArray array(double... values){var a=new JsonArray();for(double v:values)a.add(v);return a;}
    private static boolean uuid(String v){try{return v!=null&&UUID.fromString(v).toString().equals(v);}catch(IllegalArgumentException e){return false;}}
    private static boolean finite(double... values){for(double v:values)if(!Double.isFinite(v))return false;return true;}
    private static JsonElement value(JsonObject j,String key){return j==null?null:j.get(key);}
    private static String string(JsonObject j,String key){var v=value(j,key);return v!=null&&v.isJsonPrimitive()&&v.getAsJsonPrimitive().isString()?v.getAsString():null;}
    private static JsonElement bool(JsonObject j,String key){var v=value(j,key);return v!=null&&v.isJsonPrimitive()&&v.getAsJsonPrimitive().isBoolean()?v.deepCopy():JsonNull.INSTANCE;}
    private static JsonElement number(JsonObject j,String key){var v=value(j,key);return v!=null&&v.isJsonPrimitive()&&v.getAsJsonPrimitive().isNumber()&&Double.isFinite(v.getAsDouble())?v.deepCopy():JsonNull.INSTANCE;}
    private static JsonElement integer(JsonObject j,String key,long min,long max){var v=value(j,key);if(v==null||!v.isJsonPrimitive()||!v.getAsJsonPrimitive().isNumber())return JsonNull.INSTANCE;
        try {String raw=v.getAsString();if(!raw.matches("0|-?[1-9][0-9]{0,18}"))return JsonNull.INSTANCE;long n=Long.parseLong(raw);return n>=min&&n<=max?v.deepCopy():JsonNull.INSTANCE;}catch(NumberFormatException invalid){return JsonNull.INSTANCE;}}
    private static JsonElement nano(JsonObject j,String key){String v=string(j,key);if(v==null||!v.matches("0|-?[1-9][0-9]{0,18}"))return JsonNull.INSTANCE;
        try {Long.parseLong(v);return value(j,key).deepCopy();}catch(NumberFormatException invalid){return JsonNull.INSTANCE;}}
    private RouteBeeDiagnostics(){}
}

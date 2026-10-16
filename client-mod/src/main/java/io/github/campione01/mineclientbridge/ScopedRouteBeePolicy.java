package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.util.Set;
import static io.github.campione01.mineclientbridge.ScopedEntityPolicy.require;

/** Closed route-v2 authority: current complete server facts plus full client geometry; never future AI safety. */
final class ScopedRouteBeePolicy {
    private static final Set<String> KEYS=Set.of("schema_version","entity_uuid","entity_id","entity_type","dimension",
        "world_generation","player_uuid","known","source","reason","current_target_known","coverage_complete","inspected",
        "sample_tick","sample_nano","source_tick","source_nano","sample_age_ms","alive","aggressive","current_target","bee","bee_route");
    static void validate(ScopedRouteStopPolicy.Row row,long tick,long frameNano,String playerUuid,String world,String dimension){
        JsonObject n=row.nativeLiving();
        require(n!=null&&n.keySet().equals(KEYS)&&n.get("schema_version").getAsInt()==1
            &&n.get("known").getAsBoolean()&&n.get("coverage_complete").getAsBoolean()&&n.get("alive").getAsBoolean()
            &&n.get("current_target_known").getAsBoolean()&&n.get("source").getAsString().equals("integrated_server_tick")
            &&n.get("reason").getAsString().equals("observed")&&n.get("entity_uuid").getAsString().equals(row.uuid())
            &&n.get("entity_id").getAsInt()==row.id()&&n.get("entity_type").getAsString().equals(row.type())
            &&n.get("player_uuid").getAsString().equals(playerUuid)&&n.get("world_generation").getAsString().equals(world)
            &&n.get("dimension").getAsString().equals(dimension)&&n.get("inspected").getAsInt()>=1&&n.get("inspected").getAsInt()<=4096,
            "route_bee_native_unconfirmed");
        long sample=nano(n,"sample_nano"),source=nano(n,"source_nano"),sourceTick=n.get("source_tick").getAsLong();
        double age=n.get("sample_age_ms").getAsDouble();
        require(n.get("sample_tick").getAsLong()==tick&&sourceTick>=0&&Math.abs(tick-sourceTick)<=5
            &&sample>=source&&sample-source<=NativeLivingSnapshot.MAX_AGE_NANOS&&sample>=frameNano&&sample-frameNano<=NativeLivingSnapshot.MAX_AGE_NANOS
            &&Double.isFinite(age)&&age>=0&&age<=250&&Math.abs(age-(sample-source)/1_000_000.)<=.000001,"route_bee_native_stale");
        JsonObject bee=n.getAsJsonObject("bee"),route=n.getAsJsonObject("bee_route");
        require(bee!=null&&bee.keySet().equals(Set.of("angry","remaining_anger_ticks","persistent_anger_target_uuid"))
            &&route!=null&&route.keySet().equals(Set.of("schema_version","server_class","has_stung","has_nectar","hive_pos","flower_pos"))
            &&route.get("schema_version").getAsInt()==1&&route.get("server_class").getAsString().equals(ScopedRouteStopPolicy.BEE_CLASS)
            &&route.get("has_nectar").isJsonPrimitive()&&route.getAsJsonPrimitive("has_nectar").isBoolean(),"route_bee_native_unconfirmed");
        require(!n.get("aggressive").getAsBoolean()&&n.get("current_target").isJsonNull()&&!bee.get("angry").getAsBoolean()
            &&bee.get("remaining_anger_ticks").getAsInt()==0&&bee.get("persistent_anger_target_uuid").isJsonNull()
            &&!route.get("has_stung").getAsBoolean(),"route_bee_not_calm");
        position(route,"hive_pos");position(route,"flower_pos");
    }
    private static void position(JsonObject n,String key){
        var v=n.get(key);require(v!=null,"route_bee_native_unconfirmed");if(v.isJsonNull())return;
        require(v.isJsonObject()&&v.getAsJsonObject().keySet().equals(Set.of("x","y","z")),"route_bee_native_unconfirmed");
        for(String axis:ListHolder.AXES){var e=v.getAsJsonObject().get(axis);require(e.isJsonPrimitive()&&e.getAsJsonPrimitive().isNumber()
            &&e.getAsDouble()==e.getAsInt(),"route_bee_native_unconfirmed");}
    }
    private static final class ListHolder {static final String[] AXES={"x","y","z"};}
    static long nano(JsonObject object,String key){var value=object.get(key);require(value!=null&&value.isJsonPrimitive()&&value.getAsJsonPrimitive().isString()
        &&value.getAsString().matches("-?(0|[1-9][0-9]{0,18})"),"route_bee_native_unconfirmed");return Long.parseLong(value.getAsString());}
    private ScopedRouteBeePolicy(){}
}

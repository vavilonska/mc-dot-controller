package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.util.Set;

/** Closed public native wire. Request IDs are original operation IDs, never retries. */
final class ExternalNavigationControl {
    static ExternalNavigationLease.Request parse(JsonObject body) {
        require(body.keySet().equals(Set.of("external_navigation_schema_version","operation_id","owner_id","owner_generation",
            "job_id","expected_action_session","expected_world_generation","expected_player_uuid","expected_dimension",
            "source_tick","source_nano","timeout_ms")),"invalid_external_navigation_fields");
        require(integer(body,"external_navigation_schema_version",1,1)==1,"invalid_external_navigation_schema");
        String id=text(body,"operation_id"),owner=text(body,"owner_id");
        require(id.matches("[0-9a-f]{32}")&&owner.matches("[0-9a-f]{32}"),"invalid_external_navigation_identity");
        String nano=text(body,"source_nano");require(nano.matches("-?(0|[1-9][0-9]{0,18})"),"invalid_external_navigation_source_nano");
        long source;try{source=Long.parseLong(nano);}catch(NumberFormatException e){throw new ClientActionRequest.Rejected(400,"invalid_external_navigation_source_nano");}
        return new ExternalNavigationLease.Request(id,owner,integer(body,"owner_generation",1,9007199254740991L),
            text(body,"job_id"),text(body,"expected_action_session"),text(body,"expected_world_generation"),
            text(body,"expected_player_uuid"),text(body,"expected_dimension"),integer(body,"source_tick",0,9007199254740991L),
            source,(int)integer(body,"timeout_ms",1000,10000));
    }
    private static String text(JsonObject b,String key){var e=b.get(key);require(e!=null&&e.isJsonPrimitive()&&e.getAsJsonPrimitive().isString(),"invalid_"+key);String s=e.getAsString();require(!s.isBlank()&&s.length()<=128,"invalid_"+key);return s;}
    private static long integer(JsonObject b,String key,long min,long max){var e=b.get(key);require(e!=null&&e.isJsonPrimitive()&&e.getAsJsonPrimitive().isNumber(),"invalid_"+key);double n=e.getAsDouble();require(Double.isFinite(n)&&n==Math.rint(n)&&n>=min&&n<=max,"invalid_"+key);return (long)n;}
    private static void require(boolean value,String reason){if(!value)throw new ClientActionRequest.Rejected(400,reason);}
    private ExternalNavigationControl(){}
}

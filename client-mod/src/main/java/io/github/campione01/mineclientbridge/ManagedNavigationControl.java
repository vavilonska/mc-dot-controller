package io.github.campione01.mineclientbridge;
import com.google.gson.JsonObject;
import java.util.Set;
/** Closed bounded waypoint wire. No chat command or arbitrary Baritone settings. */
final class ManagedNavigationControl {
    static ManagedNavigationLease.Request parse(JsonObject b){
        need(b.keySet().equals(Set.of("managed_navigation_schema_version","operation_id","owner_id","owner_generation","job_id",
            "expected_action_session","expected_world_generation","expected_player_uuid","expected_dimension","source_tick","source_nano",
            "timeout_ms","goal_x","goal_y","goal_z","max_distance","min_health")),"managed_navigation_closed_fields");
        number(b,"managed_navigation_schema_version",1,1);String id=text(b,"operation_id"),owner=text(b,"owner_id"),job=text(b,"job_id");
        need(id.matches("[0-9a-f]{32}")&&owner.matches("[0-9a-f]{32}")&&job.matches("[A-Za-z0-9_-]{1,80}"),"managed_navigation_identity");
        String nano=text(b,"source_nano");need(nano.matches("-?(0|[1-9][0-9]{0,18})"),"managed_navigation_source");
        long source;try{source=Long.parseLong(nano);}catch(NumberFormatException e){throw new ClientActionRequest.Rejected(400,"managed_navigation_source");}
        var identity=new ExternalNavigationLease.Request(id,owner,number(b,"owner_generation",1,9007199254740991L),job,
            text(b,"expected_action_session"),text(b,"expected_world_generation"),text(b,"expected_player_uuid"),text(b,"expected_dimension"),
            number(b,"source_tick",0,9007199254740991L),source,(int)number(b,"timeout_ms",1000,120000));
        return new ManagedNavigationLease.Request(identity,(int)number(b,"goal_x",-29999984,29999984),(int)number(b,"goal_y",-2048,2048),
            (int)number(b,"goal_z",-29999984,29999984),(int)number(b,"max_distance",1,200),(float)number(b,"min_health",6,20));
    }
    private static String text(JsonObject b,String k){var v=b.get(k);need(v!=null&&v.isJsonPrimitive()&&v.getAsJsonPrimitive().isString(),"invalid_"+k);String s=v.getAsString();need(!s.isBlank()&&s.length()<=128,"invalid_"+k);return s;}
    private static long number(JsonObject b,String k,long lo,long hi){var v=b.get(k);need(v!=null&&v.isJsonPrimitive()&&v.getAsJsonPrimitive().isNumber(),"invalid_"+k);double n=v.getAsDouble();need(Double.isFinite(n)&&n==Math.rint(n)&&n>=lo&&n<=hi,"invalid_"+k);return(long)n;}
    private static void need(boolean v,String r){if(!v)throw new ClientActionRequest.Rejected(400,r);}
    private ManagedNavigationControl(){}
}

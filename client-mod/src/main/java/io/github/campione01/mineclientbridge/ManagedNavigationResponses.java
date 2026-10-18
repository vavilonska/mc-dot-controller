package io.github.campione01.mineclientbridge;
import com.google.gson.JsonObject;
/** Production route model shared by endpoint and canonical wire fixture. */
final class ManagedNavigationResponses {
    static JsonObject status(ManagedNavigationLease.Entry e,JsonObject proof,long now){
        JsonObject j=new JsonObject();j.addProperty("managed_navigation_schema_version",1);j.addProperty("input_owned",e!=null&&e.phase!=ManagedNavigationLease.Phase.SETTLED);
        j.addProperty("unknown_outcome_quarantined",e!=null&&e.phase==ManagedNavigationLease.Phase.UNKNOWN);j.addProperty("execution_authority",false);j.addProperty("no_auto_resume",true);
        if(e==null){j.addProperty("state","idle");return j;}
        var r=e.request.identity();j.addProperty("operation_id",r.id());j.addProperty("owner_id",r.owner());j.addProperty("owner_generation",r.generation());j.addProperty("job_id",r.job());
        j.addProperty("action_session",r.session());j.addProperty("world_generation",r.world());j.addProperty("player_uuid",r.player());j.addProperty("dimension",r.dimension());
        j.addProperty("state",e.phase.name().toLowerCase(java.util.Locale.ROOT));j.addProperty("reason",e.reason);j.addProperty("start_attempted",e.startAttempted);
        j.addProperty("stop_attempted",e.stopAttempted);j.addProperty("cancel_accepted",e.cancelAccepted);j.addProperty("goal_reached",e.goalReached);
        j.addProperty("settings_restored",e.settingsRestored);j.addProperty("control_released",e.phase==ManagedNavigationLease.Phase.SETTLED);
        j.addProperty("idle_samples",e.idleSamples);j.addProperty("admission_tick",e.admissionTick);j.addProperty("source_tick",e.lastTick);
        j.addProperty("remaining_ms",Math.max(0,(e.deadline-now)/1_000_000L));j.addProperty("unloaded_terrain_certified",false);
        j.addProperty("goal_x",e.request.x());j.addProperty("goal_y",e.request.y());j.addProperty("goal_z",e.request.z());
        if(proof!=null)j.add("external_controller",proof.deepCopy());
        return j;
    }
    private ManagedNavigationResponses(){}
}

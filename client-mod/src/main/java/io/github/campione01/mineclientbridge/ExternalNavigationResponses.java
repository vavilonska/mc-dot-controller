package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;

/** Production stop status model, shared by native endpoints and wire fixtures. */
final class ExternalNavigationResponses {
    static JsonObject status(ExternalNavigationLease.Entry e,JsonObject proof,long now){JsonObject j=new JsonObject();
        j.addProperty("external_navigation_schema_version",1);j.addProperty("input_owned",e!=null&&e.phase!=ExternalNavigationLease.Phase.SETTLED);
        j.addProperty("unknown_outcome_quarantined",e!=null&&e.phase==ExternalNavigationLease.Phase.UNKNOWN);
        j.addProperty("no_auto_resume",true);j.addProperty("execution_authority",false);
        if(e==null){j.addProperty("state","idle");return j;}
        var r=e.request;j.addProperty("operation_id",r.id());j.addProperty("owner_id",r.owner());
        j.addProperty("owner_generation",r.generation());j.addProperty("job_id",r.job());
        j.addProperty("action_session",r.session());j.addProperty("world_generation",r.world());
        j.addProperty("player_uuid",r.player());j.addProperty("dimension",r.dimension());
        j.addProperty("state",e.phase.name().toLowerCase(java.util.Locale.ROOT));j.addProperty("reason",e.reason);
        j.addProperty("stop_attempted",e.attempted);j.addProperty("cancel_accepted",e.cancelAccepted);
        j.addProperty("control_released",e.phase==ExternalNavigationLease.Phase.SETTLED);
        j.addProperty("admission_tick",e.admissionTick);j.addProperty("idle_samples",e.idleSamples);j.addProperty("source_tick",e.lastTick);
        j.addProperty("remaining_ms",Math.max(0,(e.deadline-now)/1_000_000L));
        if(proof!=null)j.add("external_controller",proof.deepCopy());return j;}
    private ExternalNavigationResponses(){}
}

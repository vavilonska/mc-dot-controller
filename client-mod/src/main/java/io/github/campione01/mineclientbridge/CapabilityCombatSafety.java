package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;

/** Shared live combat constraints. Caller reserves may strengthen, never weaken native policy. */
final class CapabilityCombatSafety {
    static double minimum(JsonObject body,double fallback) {
        return body.has("min_health")?CapabilityPlacement.number(body,"min_health",8,20):fallback;
    }
    static boolean healthy(double current,double minimum) {
        return Double.isFinite(current)&&Double.isFinite(minimum)&&current>minimum;
    }
    /** Raw synchronized closure wins over a lingering client opening/closing animation. */
    static boolean shellOpen(int rawPeek,double clientPeek) {
        return rawPeek>0&&rawPeek<=100&&Double.isFinite(clientPeek)&&clientPeek>0&&clientPeek<=1;
    }
    static JsonObject capabilities() {
        JsonObject value=new JsonObject();value.addProperty("schema_version",1);
        value.addProperty("encounter_route_guard_schema_version",1);
        value.addProperty("shulker_open_shell_guard_schema_version",1);
        value.addProperty("caller_health_reserve_guard_schema_version",1);
        return value;
    }
    private CapabilityCombatSafety() {}
}

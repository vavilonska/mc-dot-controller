package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.util.Set;

/** Closed nonoffensive mode. Numbers bound an episode, never certify physical safety. */
record DefensiveCombatPolicy(String mode,int windowMs,double maxDistance,double minimumSeparationGain) {
    static final String PROFILE="combat-defensive-local-v1";
    static final Set<String> MODES=Set.of("shield_only","immediate_evade");
    static DefensiveCombatPolicy parseOptional(JsonObject body) {
        if(!body.has("defensive_policy"))return null;
        ClientActionRequest.require(body.get("defensive_policy").isJsonObject(),"defensive_policy_object_required");
        JsonObject p=body.getAsJsonObject("defensive_policy");
        ClientActionRequest.require(p.keySet().equals(Set.of("schema_version","mode","window_ms","max_distance","minimum_separation_gain")),"defensive_policy_closed_fields");
        strictInt(p,"schema_version");strictInt(p,"window_ms");
        String mode=ClientActionRequest.string(p,"mode");
        int window=ClientActionRequest.integer(p,"window_ms",0);
        double distance=number(p,"max_distance"),gain=number(p,"minimum_separation_gain");
        ClientActionRequest.require(ClientActionRequest.integer(p,"schema_version",0)==1 && MODES.contains(mode),"defensive_policy_version_or_mode");
        ClientActionRequest.require(window>=300 && window<=2500,"defensive_window_300_to_2500ms");
        ClientActionRequest.require(mode.equals("shield_only")?distance==0 && gain==0:distance>=1 && distance<=4 && gain>=.1 && gain<=2 && gain<distance,"defensive_distance_or_gain_bounds");
        int timeout=ClientActionRequest.integer(body,"timeout_ms",0);
        ClientActionRequest.require(timeout>=window+250 && timeout<=3000,"defensive_original_deadline_bounds");
        ClientActionRequest.require(!ClientActionRequest.bool(body,"approach",true)
            && ClientActionRequest.bool(body,"shield",false)==mode.equals("shield_only")
            && !body.has("encounter_mode") && !body.has("encounter_scope"),"defensive_offensive_or_encounter_fields");
        return new DefensiveCombatPolicy(mode,window,distance,gain);
    }
    static boolean shieldWindowObserved(int samples,boolean exactShieldActive,boolean blocking){return samples>=3 && exactShieldActive && blocking;}
    static boolean useAllowed(boolean sameCall,boolean attack,boolean exactPlayer,boolean offhand,boolean onBlock){return sameCall && !attack && exactPlayer && offhand && !onBlock;}
    boolean shieldOnly(){return mode.equals("shield_only");}
    double proposalDistance(){return Math.min(3,maxDistance-.65);}
    boolean elapsed(long started,long now){return now-started>=windowMs*1_000_000L;}
    boolean mayMove(double observedDistance){return !shieldOnly() && Double.isFinite(observedDistance) && observedDistance>=0 && observedDistance+.65<=maxDistance;}
    boolean separationObserved(double initial,double current){return Double.isFinite(initial) && Double.isFinite(current) && current-initial>=minimumSeparationGain;}
    JsonObject json(){JsonObject p=new JsonObject();p.addProperty("schema_version",1);p.addProperty("mode",mode);p.addProperty("window_ms",windowMs);p.addProperty("max_distance",maxDistance);p.addProperty("minimum_separation_gain",minimumSeparationGain);return p;}
    private static double number(JsonObject p,String key){var v=p.get(key);ClientActionRequest.require(v!=null && v.isJsonPrimitive() && v.getAsJsonPrimitive().isNumber() && Double.isFinite(v.getAsDouble()),"defensive_finite_number_"+key);return v.getAsDouble();}
    private static void strictInt(JsonObject p,String key){var v=p.get(key);ClientActionRequest.require(v!=null && v.isJsonPrimitive() && v.getAsJsonPrimitive().isNumber() && v.getAsString().matches("0|[1-9][0-9]*"),"defensive_integer_"+key);}
}

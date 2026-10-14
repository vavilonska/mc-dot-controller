package io.github.campione01.mineclientbridge;
import com.google.gson.JsonObject;
/** Calls production native intent validator without constructing Minecraft. */
public final class ScopedCombatIntentChecks {
    static int checks;
    static JsonObject intent(){
        JsonObject body=new JsonObject();
        for(String key:new String[]{"action","action_id","target_uuid","target_type","expected_world_generation","expected_dimension","expected_player_uuid","expected_action_session"})body.addProperty(key,"fixture");
        body.addProperty("target_entity_id",9);body.addProperty("timeout_ms",1000);body.addProperty("expected_hotbar_slot",0);
        body.addProperty("approach",true);body.addProperty("shield",true);body.addProperty("min_health",14);
        body.add("expected_held_item",new JsonObject());JsonObject guard=new JsonObject();
        guard.addProperty("schema_version",1);guard.addProperty("source_tick",7);guard.addProperty("source_nano","100");body.add("capability_guard",guard);return body;
    }
    static void deny(JsonObject body){boolean denied=false;try{ScopedCombat.validateIntent(body);}catch(RuntimeException expected){denied=true;}checks++;if(!denied)throw new AssertionError("intent "+checks);}
    public static void main(String[] args){
        ScopedCombat.validateIntent(intent());checks++;
        for(String key:new String[]{"target_entity_id","timeout_ms","expected_hotbar_slot"}){
            var b=intent();b.addProperty(key,9.0);deny(b);
            b=intent();b.addProperty(key,true);deny(b);
            b=intent();b.addProperty(key,"9");deny(b);
        }
        var b=intent();b.addProperty("encounter_mode","extra");deny(b);
        b=intent();b.remove("shield");deny(b);
        b=intent();b.getAsJsonObject("capability_guard").addProperty("source_tick",7.0);deny(b);
        b=intent();b.getAsJsonObject("capability_guard").addProperty("source_nano",100);deny(b);
        b=intent();b.getAsJsonObject("capability_guard").addProperty("source_nano","01");deny(b);
        b=intent();b.addProperty("expected_navigation_epoch",1);deny(b);
        System.out.println("ScopedCombatIntentChecks passed: "+checks);
    }
}

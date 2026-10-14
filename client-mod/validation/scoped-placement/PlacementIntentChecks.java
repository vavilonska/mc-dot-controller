package io.github.campione01.mineclientbridge;
import com.google.gson.*;
import java.util.function.Consumer;
/** Executable tests against the production intent validator, no game bootstrap. */
public final class PlacementIntentChecks {
    static int checks;
    static JsonObject valid(){
        return JsonParser.parseString("""
        {"action_id":"placement-native-test","action":"place_block","timeout_ms":2000,
        "support":{"x":1,"y":64,"z":2},"face":"up","expected_support_id":"minecraft:stone",
        "expected_support_properties":{},"expected_target_id":"minecraft:air","expected_target_properties":{},
        "expected_block_id":"minecraft:cobblestone","expected_block_properties":{},
        "placement_hit":{"x":1.5,"y":65.0,"z":2.5},
        "placement_footprint":[{"position":{"x":1,"y":65,"z":2},"expected_id":"minecraft:air","expected_properties":{},"block_id":"minecraft:cobblestone","properties":{}}],
        "expected_navigation_epoch":0,"expected_origin":{"x":0.5,"y":65.0,"z":0.5},"capability_guard":{},
        "expected_world_generation":"world","expected_dimension":"minecraft:overworld","expected_player_uuid":"player",
        "expected_action_session":"session","expected_hotbar_slot":0,"expected_held_item":{}}
        """).getAsJsonObject();
    }
    static void denied(Consumer<JsonObject> mutate){JsonObject b=valid();mutate.accept(b);try{ScopedPlacementIntent.validate(b);throw new AssertionError("accepted "+b);}catch(ClientActionRequest.Rejected expected){checks++;}}
    public static void main(String[] args){
        ScopedPlacementIntent.validate(valid());checks++;
        var explicit=valid();explicit.addProperty("hotbar_slot",-1);explicit.addProperty("jump",false);explicit.addProperty("sneak",false);ScopedPlacementIntent.validate(explicit);checks++;
        for(String k:valid().keySet())denied(b->b.remove(k));
        for(String k:new String[]{"capability_bridge","coordination_step","placement_yaw","automatic_retry","op","waypoints","min_health"})denied(b->b.addProperty(k,true));
        for(int t:new int[]{0,49,2001,8000})denied(b->b.addProperty("timeout_ms",t));
        denied(b->b.addProperty("timeout_ms",50.5));denied(b->b.addProperty("hotbar_slot",0));
        denied(b->b.addProperty("jump",true));denied(b->b.addProperty("sneak",true));denied(b->b.addProperty("action","break_block"));
        denied(b->b.addProperty("expected_block_id","minecraft:stone"));denied(b->b.addProperty("expected_target_id","minecraft:cave_air"));
        denied(b->b.getAsJsonObject("expected_block_properties").addProperty("foo","bar"));
        denied(b->b.getAsJsonObject("support").addProperty("x",1.5));denied(b->b.getAsJsonObject("support").addProperty("x",30000001));
        denied(b->b.getAsJsonObject("placement_hit").addProperty("x",1.49));denied(b->b.getAsJsonArray("placement_footprint").add(b.getAsJsonArray("placement_footprint").get(0).deepCopy()));
        denied(b->b.getAsJsonArray("placement_footprint").get(0).getAsJsonObject().getAsJsonObject("position").addProperty("y",66));
        denied(b->b.addProperty("face","invalid"));
        System.out.println("PASS production placement intent boundaries: "+checks);
    }
}

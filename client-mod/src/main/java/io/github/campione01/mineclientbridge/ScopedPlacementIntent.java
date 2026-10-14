package io.github.campione01.mineclientbridge;
import com.google.gson.JsonObject;
import com.google.gson.JsonArray;
import java.util.Set;
/** Pure closed schema used by the actual native admission; no game bootstrap. */
final class ScopedPlacementIntent {
    private static final int MAX_TIMEOUT=2000;
    static void validate(JsonObject b) {
        var fields=new java.util.HashSet<>(b.keySet());fields.removeAll(Set.of("hotbar_slot","jump","sneak"));
        require(fields.equals(Set.of("action_id","action","timeout_ms","support","face",
            "expected_support_id","expected_support_properties","expected_target_id","expected_target_properties",
            "expected_block_id","expected_block_properties","placement_hit","placement_footprint",
            "expected_navigation_epoch","expected_origin","capability_guard","expected_world_generation","expected_dimension","expected_player_uuid",
            "expected_action_session","expected_hotbar_slot","expected_held_item")),"placement_intent_fields");
        require(ClientActionRequest.string(b,"action").equals("place_block")
            && ClientActionRequest.integer(b,"timeout_ms",0)>=50 && ClientActionRequest.integer(b,"timeout_ms",0)<=MAX_TIMEOUT
            && ClientActionRequest.integer(b,"hotbar_slot",-1)==-1 && !ClientActionRequest.bool(b,"jump",false)
            && !ClientActionRequest.bool(b,"sneak",false),"placement_request_outside_profile");
        require(ClientActionRequest.string(b,"expected_block_id").equals("minecraft:cobblestone")
            && ClientActionRequest.string(b,"expected_target_id").equals("minecraft:air"),"placement_exact_block_required");
        for(String k:Set.of("expected_support_properties","expected_target_properties","expected_block_properties"))
            require(b.has(k)&&b.get(k).isJsonObject()&&b.getAsJsonObject(k).size()==0,"placement_exact_properties_required");
        JsonObject support=b.getAsJsonObject("support");require(support!=null&&support.keySet().equals(Set.of("x","y","z")),"placement_support_fields");
        int x=coordinate(support,"x",-30000000,30000000),y=coordinate(support,"y",-2048,2048),z=coordinate(support,"z",-30000000,30000000);
        String face=ClientActionRequest.string(b,"face");require(ClientActionRequest.FACES.contains(face),"placement_face_invalid");
        int[] d=switch(face){case "up"->new int[]{0,1,0};case "down"->new int[]{0,-1,0};case "north"->new int[]{0,0,-1};case "south"->new int[]{0,0,1};case "east"->new int[]{1,0,0};default->new int[]{-1,0,0};};
        JsonObject target=new JsonObject();target.addProperty("x",x+d[0]);target.addProperty("y",y+d[1]);target.addProperty("z",z+d[2]);
        JsonObject h=new JsonObject();h.addProperty("x",x+.5+d[0]*.5);
        h.addProperty("y",y+.5+d[1]*.5);h.addProperty("z",z+.5+d[2]*.5);
        require(h.equals(b.get("placement_hit")),"placement_face_center_required");
        JsonObject cell=new JsonObject();cell.add("position",target);cell.addProperty("expected_id","minecraft:air");
        cell.add("expected_properties",new JsonObject());cell.addProperty("block_id","minecraft:cobblestone");cell.add("properties",new JsonObject());
        JsonArray cells=new JsonArray();cells.add(cell);require(cells.equals(b.get("placement_footprint")),"placement_single_cell_required");
    }
    private static int coordinate(JsonObject o,String key,int min,int max){
        int v=ClientActionRequest.integer(o,key,0);require(v>=min&&v<=max,"placement_coordinate_out_of_bounds");return v;
    }
    private static void require(boolean ok,String reason){if(!ok)throw new ClientActionRequest.Rejected(409,reason);}
    private ScopedPlacementIntent(){}
}

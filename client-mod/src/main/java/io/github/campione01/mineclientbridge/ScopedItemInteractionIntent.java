package io.github.campione01.mineclientbridge;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.util.Set;
/** Closed one-use goals. No arbitrary item, property subset, footprint or hand. */
final class ScopedItemInteractionIntent {
    static final Set<String> COMMON=Set.of("action_id","action","timeout_ms","expected_navigation_epoch","expected_origin","capability_guard",
        "expected_world_generation","expected_dimension","expected_player_uuid","expected_action_session","expected_hotbar_slot","expected_held_item");
    static void validate(JsonObject b){
        var fields=new java.util.HashSet<>(b.keySet());fields.removeAll(Set.of("hotbar_slot","jump","sneak"));
        var allowed=new java.util.HashSet<>(COMMON);allowed.addAll(Set.of("target","face","expected_block_id","expected_block_properties","typed_item_interaction","item_hit","item_footprint"));
        need(fields.equals(allowed),"item_interaction_intent_fields");
        need(ClientActionRequest.string(b,"action").equals("interact_block")&&ClientActionRequest.integer(b,"timeout_ms",0)>=50
            &&ClientActionRequest.integer(b,"timeout_ms",0)<=3000&&ClientActionRequest.integer(b,"hotbar_slot",-1)==-1
            &&!ClientActionRequest.bool(b,"jump",false)&&!ClientActionRequest.bool(b,"sneak",false)
            &&ClientActionRequest.string(b,"face").equals("up"),"item_interaction_request_outside_profile");
        JsonObject target=b.getAsJsonObject("target"),m=b.getAsJsonObject("typed_item_interaction");xyz(target);
        String kind=ClientActionRequest.string(m,"kind");JsonArray expected=new JsonArray();
        if(kind.equals("ignite_nether_portal")){
            need(Set.of("minecraft:overworld","minecraft:the_nether").contains(ClientActionRequest.string(b,"expected_dimension")),"item_interaction_ignition_dimension");
            need(m.keySet().equals(Set.of("kind","interior_base","axis","width","height")),"item_interaction_ignition_metadata");
            JsonObject base=m.getAsJsonObject("interior_base");xyz(base);String axis=ClientActionRequest.string(m,"axis");
            int w=ClientActionRequest.integer(m,"width",0),h=ClientActionRequest.integer(m,"height",0);
            need(Set.of("x","z").contains(axis)&&w>=2&&w<=4&&h>=3&&h<=4,"item_interaction_portal_geometry");
            need(target.equals(offset(base,0,-1,0))&&ClientActionRequest.string(b,"expected_block_id").equals("minecraft:obsidian")
                &&b.getAsJsonObject("expected_block_properties").size()==0,"item_interaction_ignition_target");
            for(int u=0;u<w;u++)for(int v:new int[]{-1,h})expected.add(row(point(base,axis,u,v),"minecraft:obsidian",new JsonObject(),"minecraft:obsidian",new JsonObject()));
            for(int u:new int[]{-1,w})for(int v=0;v<h;v++)expected.add(row(point(base,axis,u,v),"minecraft:obsidian",new JsonObject(),"minecraft:obsidian",new JsonObject()));
            JsonObject props=new JsonObject();props.addProperty("axis",axis);
            for(int u=0;u<w;u++)for(int v=0;v<h;v++)expected.add(row(point(base,axis,u,v),"minecraft:air",new JsonObject(),"minecraft:nether_portal",props));
        }else{
            need(ClientActionRequest.string(b,"expected_dimension").equals("minecraft:overworld"),"item_interaction_eye_dimension");
            need(kind.equals("insert_end_eye")&&m.keySet().equals(Set.of("kind","interior_corner")),"item_interaction_eye_metadata");
            JsonObject base=m.getAsJsonObject("interior_corner");xyz(base);JsonArray rows=b.getAsJsonArray("item_footprint");
            need(rows!=null&&rows.size()==21,"item_interaction_end_ring_coverage");int missing=0;boolean found=false;
            for(int i=0;i<3;i++)for(int side=0;side<4;side++){
                JsonObject p=switch(side){case 0->offset(base,i,0,-1);case 1->offset(base,i,0,3);case 2->offset(base,-1,0,i);default->offset(base,3,0,i);};
                String facing=new String[]{"south","north","east","west"}[side];JsonObject r=rows.get(i*4+side).getAsJsonObject();
                JsonObject props=r.getAsJsonObject("expected_properties");need(props!=null&&props.keySet().equals(Set.of("facing","eye"))
                    &&ClientActionRequest.string(props,"facing").equals(facing)&&Set.of("true","false").contains(ClientActionRequest.string(props,"eye")),"item_interaction_end_frame_state");
                if(ClientActionRequest.string(props,"eye").equals("false"))missing++;
                JsonObject after=props.deepCopy();if(p.equals(target)){need(ClientActionRequest.string(props,"eye").equals("false"),"item_interaction_eye_already_filled");after.addProperty("eye","true");found=true;
                    need(b.getAsJsonObject("expected_block_properties").equals(props),"item_interaction_eye_target_properties");}
                expected.add(row(p,"minecraft:end_portal_frame",props,"minecraft:end_portal_frame",after));
            }
            need(found&&ClientActionRequest.string(b,"expected_block_id").equals("minecraft:end_portal_frame"),"item_interaction_eye_target");
            for(int x=0;x<3;x++)for(int z=0;z<3;z++)expected.add(row(offset(base,x,0,z),"minecraft:air",new JsonObject(),missing==1?"minecraft:end_portal":"minecraft:air",new JsonObject()));
        }
        JsonObject hit=new JsonObject();hit.addProperty("x",target.get("x").getAsInt()+.5);hit.addProperty("y",target.get("y").getAsInt()+(kind.equals("insert_end_eye")?13.0/16:1));hit.addProperty("z",target.get("z").getAsInt()+.5);
        need(hit.equals(b.get("item_hit"))&&expected.equals(b.get("item_footprint")),"item_interaction_exact_hit_and_footprint");
    }
    static JsonObject offset(JsonObject p,int x,int y,int z){JsonObject v=new JsonObject();v.addProperty("x",p.get("x").getAsInt()+x);v.addProperty("y",p.get("y").getAsInt()+y);v.addProperty("z",p.get("z").getAsInt()+z);xyz(v);return v;}
    private static JsonObject point(JsonObject p,String axis,int u,int v){return offset(p,axis.equals("x")?u:0,v,axis.equals("z")?u:0);}
    private static JsonObject row(JsonObject p,String before,JsonObject props,String after,JsonObject finalProps){JsonObject r=new JsonObject();r.add("position",p);r.addProperty("expected_id",before);r.add("expected_properties",props.deepCopy());r.addProperty("block_id",after);r.add("properties",finalProps.deepCopy());return r;}
    static void xyz(JsonObject p){need(p!=null&&p.keySet().equals(Set.of("x","y","z")),"item_interaction_coordinate_fields");for(String k:Set.of("x","y","z")){int v=ClientActionRequest.integer(p,k,0);need(Math.abs((long)v)<=(k.equals("y")?2048:30000000),"item_interaction_coordinate_bounds");}}
    static void need(boolean ok,String reason){if(!ok)throw new ClientActionRequest.Rejected(409,reason);}
    private ScopedItemInteractionIntent(){}
}

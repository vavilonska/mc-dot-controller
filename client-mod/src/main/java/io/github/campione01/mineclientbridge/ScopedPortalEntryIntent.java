package io.github.campione01.mineclientbridge;
import com.google.gson.JsonObject;
import java.util.Set;
/** Only an exact expected-dimension portal entry, never a general path exemption. */
final class ScopedPortalEntryIntent {
    static final String CONTRACT="flat-supported-max-two-blocks-v1";
    static void validate(JsonObject b){
        var fields=new java.util.HashSet<>(b.keySet());fields.removeAll(Set.of("hotbar_slot","jump","sneak"));
        var allowed=new java.util.HashSet<>(ScopedItemInteractionIntent.COMMON);allowed.addAll(Set.of("waypoints","typed_portal_entry"));
        need(fields.equals(allowed)&&ClientActionRequest.string(b,"action").equals("follow_path")
            &&ClientActionRequest.integer(b,"timeout_ms",0)>=5000&&ClientActionRequest.integer(b,"timeout_ms",0)<=8000
            &&ClientActionRequest.integer(b,"hotbar_slot",-1)==-1&&!ClientActionRequest.bool(b,"jump",false)&&!ClientActionRequest.bool(b,"sneak",false),"portal_entry_closed_intent");
        JsonObject p=b.getAsJsonObject("typed_portal_entry");need(p!=null&&p.keySet().equals(Set.of("portal_cell","portal_id","portal_properties","destination","entry_contract"))
            &&ClientActionRequest.string(p,"entry_contract").equals(CONTRACT),"portal_entry_exact_metadata");
        JsonObject cell=p.getAsJsonObject("portal_cell");ScopedItemInteractionIntent.xyz(cell);
        String from=ClientActionRequest.string(b,"expected_dimension"),to=ClientActionRequest.string(p,"destination"),id=ClientActionRequest.string(p,"portal_id");
        boolean nether=from.equals("minecraft:overworld")&&to.equals("minecraft:the_nether")||from.equals("minecraft:the_nether")&&to.equals("minecraft:overworld");
        boolean end=from.equals("minecraft:overworld")&&to.equals("minecraft:the_end")||from.equals("minecraft:the_end")&&to.equals("minecraft:overworld");
        JsonObject props=p.getAsJsonObject("portal_properties");need(nether&&id.equals("minecraft:nether_portal")&&props!=null&&props.keySet().equals(Set.of("axis"))&&Set.of("x","z").contains(ClientActionRequest.string(props,"axis"))
            ||end&&id.equals("minecraft:end_portal")&&props!=null&&props.size()==0,"portal_entry_dimension_pair_and_state");
        var points=b.getAsJsonArray("waypoints");need(points!=null&&points.size()==1&&points.get(0).isJsonObject(),"portal_entry_single_point");JsonObject point=points.get(0).getAsJsonObject();
        JsonObject expected=new JsonObject();expected.addProperty("x",cell.get("x").getAsInt()+.5);expected.addProperty("y",cell.get("y").getAsInt());expected.addProperty("z",cell.get("z").getAsInt()+.5);expected.addProperty("jump",false);
        need(point.equals(expected),"portal_entry_exact_waypoint");
    }
    static void need(boolean ok,String reason){if(!ok)throw new ClientActionRequest.Rejected(409,reason);}
    private ScopedPortalEntryIntent(){}
}

package io.github.campione01.mineclientbridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

/** Calls the actual root parser/registry; no Minecraft types, loader or game. */
public final class NativeActionWire {
    public static void main(String[] args) {
        JsonObject out=new JsonObject();
        JsonArray actions=new JsonArray();
        ClientActionRequest.ACTIONS.stream().sorted().forEach(actions::add);
        out.add("native_actions",actions);
        JsonArray legacy=new JsonArray();
        ClientActionRequest.LEGACY_ACTIONS.stream().sorted().forEach(legacy::add);
        out.add("legacy_actions",legacy);
        JsonArray cases=new JsonArray();
        String[] bodies={
            "{\"action_id\":\"recovery-default\",\"action\":\"recover_environment\",\"waypoints\":[]}",
            "{\"action_id\":\"recovery-zero\",\"action\":\"recover_environment\",\"waypoints\":[],\"timeout_ms\":0}",
            "{\"action_id\":\"recovery-finite\",\"action\":\"recover_environment\",\"waypoints\":[],\"timeout_ms\":50}",
            "{\"action_id\":\"path-zero\",\"action\":\"follow_path\",\"waypoints\":[{\"x\":0,\"y\":64,\"z\":1}],\"timeout_ms\":0}",
            "{\"action_id\":\"path-finite\",\"action\":\"follow_path\",\"waypoints\":[{\"x\":0,\"y\":64,\"z\":1}],\"timeout_ms\":50}",
            "{\"action_id\":\"unknown-zero\",\"action\":\"unknown\",\"waypoints\":[],\"timeout_ms\":0}"
        };
        for(String json:bodies) {
            JsonObject body=JsonParser.parseString(json).getAsJsonObject(),row=new JsonObject();
            row.add("input",body.deepCopy());
            try {
                ClientActionRequest parsed=ClientActionRequest.parse(body);
                row.addProperty("accepted",true);row.addProperty("timeout_ms",parsed.timeoutMs());
                row.add("original",parsed.original());
                if(parsed.action().equals("recover_environment")) {
                    ActionRegistry registry=new ActionRegistry();
                    ActionRegistry.Entry owner=registry.begin(parsed);
                    if(registry.begin(ClientActionRequest.parse(body))!=owner)
                        throw new AssertionError("same ID/body must retain the owner");
                    row.add("running_receipt",registry.status(parsed.id()));
                    registry.finish("cancelled","cancel_requested");
                    row.add("cancelled_receipt",registry.status(parsed.id()));
                }
            } catch(ClientActionRequest.Rejected error) {
                row.addProperty("accepted",false);row.addProperty("reason",error.getMessage());
            }
            cases.add(row);
        }
        out.add("cases",cases);System.out.println(out);
    }
}

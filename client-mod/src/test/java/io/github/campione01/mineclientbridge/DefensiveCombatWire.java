package io.github.campione01.mineclientbridge;
import com.google.gson.JsonObject;
import com.google.gson.JsonArray;
/** Production parser, evidence, registry and exact HTTP codec; terminal outcome is modeled, not game proof. */
public final class DefensiveCombatWire {
    private static void wire(JsonObject row,String name,BridgeServer.EndpointResult response)throws Exception {
        row.addProperty(name+"_status",response.status());row.addProperty(name+"_http",BridgeJson.toJson(response.body()));
    }
    public static void main(String[] args)throws Exception {JsonArray rows=new JsonArray();for(String mode:DefensiveCombatPolicy.MODES){
        JsonObject body=DefensiveCombatPolicyTest.body(mode,1000,mode.equals("shield_only")?0:4,mode.equals("shield_only")?0:.5);
        body.addProperty("action_id","fixture_"+mode);body.addProperty("action","combat_entity");
        body.addProperty("expected_world_generation","11111111-1111-4111-8111-111111111111");body.addProperty("expected_player_uuid","22222222-2222-4222-8222-222222222222");
        body.addProperty("expected_action_session","33333333-3333-4333-8333-333333333333");body.addProperty("target_uuid","44444444-4444-4444-8444-444444444444");
        body.addProperty("target_entity_id",9);body.addProperty("target_type","minecraft:zombie");body.addProperty("min_health",14);
        BoundedCombatRequest request=BoundedCombatRequest.parse(body);JsonObject evidence=new JsonObject();CombatInitialEvidence.initialize(request,evidence,6,20);
        ActionRegistry registry=new ActionRegistry();ActionRegistry.Entry entry=registry.begin(ClientActionRequest.parse(body));entry.result.add("combat",evidence);
        JsonObject row=new JsonObject();row.add("request",body);row.add("combat",evidence.deepCopy());
        wire(row,"running",BridgeServer.ActionResponses.result(()->registry.status(body.get("action_id").getAsString()),true));
        // Exercise actual serialization of a modeled terminal. This does not execute native gameplay.
        evidence.addProperty("defensive_completed",true);evidence.addProperty("defensive_blocking_samples",4);evidence.addProperty("defensive_separation_gain",1.);
        entry.ticks=20;registry.finishAfterCleanup("succeeded","fixture_terminal_model",true);
        wire(row,"terminal",BridgeServer.ActionResponses.result(()->registry.status(body.get("action_id").getAsString()),false));
        evidence.addProperty("initial_player_health",(String)null);
        wire(row,"nullable",BridgeServer.ActionResponses.result(()->registry.status(body.get("action_id").getAsString()),false));
        wire(row,"error",BridgeServer.ActionResponses.result(()->{throw new ClientActionRequest.Rejected(409,"defensive_profile_mode_binding");},true));
        rows.add(row);
    }JsonObject result=new JsonObject();result.addProperty("scope","production_parser_registry_ActionResponses_BridgeJson_with_modeled_terminal_no_game");result.add("rows",rows);System.out.println(BridgeJson.toJson(result));}
}

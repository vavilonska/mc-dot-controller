package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class BoatTransferRequestTest {
    static final String W="00000000-0000-0000-0000-000000000001", P="00000000-0000-0000-0000-000000000002",
            S="00000000-0000-0000-0000-000000000003", B="00000000-0000-0000-0000-000000000004";
    static JsonObject body(boolean mount) {
        JsonObject j=new JsonObject(); j.addProperty("action_id","transfer-1");j.addProperty("action",mount?"boat_mount":"boat_dismount");
        j.addProperty("boat_transfer_schema_version",1);j.addProperty("timeout_ms",2000);
        j.addProperty("expected_world_generation",W);j.addProperty("expected_player_uuid",P);j.addProperty("expected_action_session",S);
        j.addProperty("expected_game_time",100);j.addProperty("vehicle_uuid",B);j.addProperty("vehicle_entity_id",7);j.addProperty("vehicle_type","minecraft:boat");return j;
    }
    @Test void bothActionsParseThroughPublicActionContract() {for(boolean mount:new boolean[]{true,false}) {var b=body(mount);assertEquals(b.get("action").getAsString(),ClientActionRequest.parse(b).action());assertEquals(mount,BoatTransferRequest.parse(b).mounting());}}
    @Test void exactFieldsRequiredNoImplicitBudgetOrUnboundedExtension() {for(String key:body(true).keySet()) {var b=body(true);b.remove(key);assertThrows(ClientActionRequest.Rejected.class,()->BoatTransferRequest.parse(b),key);}for(String key:new String[]{"sneak","hotbar_slot","retry","waypoints","max_sneak_ticks","renew"}){var b=body(true);b.addProperty(key,true);assertThrows(ClientActionRequest.Rejected.class,()->BoatTransferRequest.parse(b));}}
    @Test void finiteTimeoutBoundaries() {for(int n:new int[]{1000,2000,5000}){var b=body(true);b.addProperty("timeout_ms",n);assertEquals(n,BoatTransferRequest.parse(b).timeoutMs());}for(int n:new int[]{-1,0,999,5001,120000}){var b=body(true);b.addProperty("timeout_ms",n);assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(b));}}
    @Test void malformedTicksRejected() {for(String n:new String[]{"-1","1.25","9007199254740992","NaN"}){var b=body(true);b.addProperty("expected_game_time",n);assertThrows(ClientActionRequest.Rejected.class,()->BoatTransferRequest.parse(b));}for(double n:new double[]{-1,1.25,Double.NaN,Double.POSITIVE_INFINITY,9007199254740992d}){var b=body(true);b.addProperty("expected_game_time",n);assertThrows(ClientActionRequest.Rejected.class,()->BoatTransferRequest.parse(b));}}
    @Test void identitySchemaAndTypeFailClosed() {for(String key:new String[]{"expected_world_generation","expected_player_uuid","expected_action_session","vehicle_uuid"}){var b=body(true);b.addProperty(key,"not-a-uuid");assertThrows(ClientActionRequest.Rejected.class,()->BoatTransferRequest.parse(b));}for(String type:new String[]{"minecraft:chest_boat","mod:boat","minecraft:pig"}){var b=body(true);b.addProperty("vehicle_type",type);assertThrows(ClientActionRequest.Rejected.class,()->BoatTransferRequest.parse(b));}var b=body(true);b.addProperty("boat_transfer_schema_version",2);assertThrows(ClientActionRequest.Rejected.class,()->BoatTransferRequest.parse(b));var bad=body(true);bad.addProperty("vehicle_entity_id",-1);assertThrows(ClientActionRequest.Rejected.class,()->BoatTransferRequest.parse(bad));}
    @Test void bindingChecksFreshnessAndEveryIdentity() {var r=BoatTransferRequest.parse(body(true));assertNull(r.binding(W,P,S,105,B,7,true));assertEquals("stale_boat_transfer_observation",r.binding(W,P,S,106,B,7,true));assertEquals("stale_boat_transfer_observation",r.binding(W,P,S,99,B,7,false));assertNull(r.binding(W,P,S,200,B,7,false));assertEquals("action_world_changed",r.binding(P,P,S,100,B,7,true));assertEquals("action_player_changed",r.binding(W,W,S,100,B,7,true));assertEquals("action_session_changed",r.binding(W,P,W,100,B,7,true));assertEquals("vehicle_changed",r.binding(W,P,S,100,P,7,true));assertEquals("vehicle_changed",r.binding(W,P,S,100,B,8,true));}
    @Test void registryReuseNeverCreatesASecondTransferAndPayloadMutationRejects() {var a=new ActionRegistry();var r=ClientActionRequest.parse(body(true));var first=a.begin(r);a.finishAfterCleanup("failed","deadline_exceeded",true);assertSame(first,a.existing(r));assertEquals("failed",a.status(r.id()).get("status").getAsString());assertFalse(a.status(r.id()).get("server_confirmed").getAsBoolean());var other=body(true);other.addProperty("timeout_ms",3000);assertThrows(ClientActionRequest.Rejected.class,()->a.existing(ClientActionRequest.parse(other)));}
}

package io.github.campione01.mineclientbridge;
import com.google.gson.*;
import java.util.Set;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class IncrementMobilityWireTest {
    static JsonObject placed() {
        var b=CapabilityGuardTest.request("place_block");
        b.add("support",JsonParser.parseString("{\"x\":0,\"y\":63,\"z\":0}"));b.addProperty("face","up");
        b.addProperty("expected_support_id","minecraft:stone");b.add("expected_support_properties",new JsonObject());
        b.addProperty("expected_target_id","minecraft:air");b.add("expected_target_properties",new JsonObject());
        b.addProperty("expected_block_id","minecraft:oak_stairs");
        b.add("expected_block_properties",JsonParser.parseString("{\"facing\":\"north\",\"half\":\"bottom\",\"shape\":\"straight\",\"waterlogged\":\"false\"}"));
        b.add("placement_hit",JsonParser.parseString("{\"x\":0.5,\"y\":64,\"z\":0.5}"));
        b.addProperty("placement_yaw",0);return b;
    }
    @Test void everyIncrementFieldRequiresNativeCapabilityGuard() {
        for(String field:Set.of("capability_route","capability_bridge","capability_descent","placement_hit","placement_yaw","placement_footprint","require_pumpkin")) {
            var b=JsonParser.parseString("{\"action_id\":\"a\",\"action\":\"break_block\",\"target\":{\"x\":0,\"y\":64,\"z\":0}}").getAsJsonObject();
            b.addProperty(field,true);assertEquals("capability_guard_required",assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(b)).getMessage());
        }
    }
    @Test void orientedPlacementHitMustStayOnTheRealSupportFace() {
        assertEquals("place_block",ClientActionRequest.parse(placed()).action());
        var b=placed();b.getAsJsonObject("placement_hit").addProperty("y",63.8);
        assertEquals("placement_hit_not_on_face",assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(b)).getMessage());
    }
    @Test void exactFootprintCannotAffectUnrelatedNeighbor() {
        var b=placed();b.add("placement_footprint",JsonParser.parseString("[{\"position\":{\"x\":8,\"y\":64,\"z\":0},\"expected_id\":\"minecraft:air\",\"expected_properties\":{},\"block_id\":\"minecraft:oak_stairs\",\"properties\":{}}]"));
        assertEquals("invalid_placement_footprint_position",assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(b)).getMessage());
    }
    @Test void guardedBoatEnvelopeIsAllowedWithoutBroadeningLegacySchema() {
        var b=BoatDriveRequestTest.body();var guard=CapabilityGuardTest.request("select_hotbar");
        for(String key:Set.of("capability_guard","expected_dimension","expected_hotbar_slot","expected_held_item"))b.add(key,guard.get(key).deepCopy());
        assertEquals("boat_drive",ClientActionRequest.parse(b).action());
        b.remove("capability_guard");assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(b));
    }
    @Test void gatewayActionMustBindRealGatewayAndHaveFreshCapabilityEnvelope() {
        var b=CapabilityGuardTest.request("gateway_pearl");b.add("target",JsonParser.parseString("{\"x\":3,\"y\":65,\"z\":0}"));
        b.addProperty("expected_block_id","minecraft:end_gateway");b.add("expected_block_properties",new JsonObject());b.addProperty("min_health",12);
        assertEquals("gateway_pearl",ClientActionRequest.parse(b).action());
        b.remove("capability_guard");assertEquals("capability_guard_required",assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(b)).getMessage());
    }
}

package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/** Runs production request admission and numeric target policy; never starts Minecraft. */
class CapabilityTargetActionTest {
    private static JsonObject request(String action,String type) {
        JsonObject value=new JsonObject();
        value.addProperty("action",action);value.addProperty("target_type",type);
        value.addProperty("target_entity_id",12);value.addProperty("timeout_ms",5000);
        for(String field:new String[]{"target_uuid","expected_world_generation","expected_player_uuid","expected_action_session"})
            value.addProperty(field,"00000000-0000-0000-0000-000000000001");
        return value;
    }
    @Test void explicitMeleeAndBowActionsValidate() {
        assertDoesNotThrow(()->CapabilityTargetAction.validate(request("attack_entity","minecraft:zombie")));
        assertDoesNotThrow(()->CapabilityTargetAction.validate(request("attack_entity","minecraft:shulker")));
        assertDoesNotThrow(()->CapabilityTargetAction.validate(request("shoot_entity","minecraft:end_crystal")));
    }
    @Test void noPlayerCreeperCrystalMeleeOrFlyingDragonBow() {
        for(String type:new String[]{"minecraft:player","minecraft:creeper","minecraft:enderman","minecraft:end_crystal"})
            assertThrows(ClientActionRequest.Rejected.class,()->CapabilityTargetAction.validate(request("attack_entity",type)));
        assertThrows(ClientActionRequest.Rejected.class,()->CapabilityTargetAction.validate(request("shoot_entity","minecraft:ender_dragon")));
    }
    @Test void onlyExplicitNonFlamingPerchedDragonPhaseAdmitted() {
        for(int phase=0;phase<11;phase++) {
            JsonObject value=request("attack_entity","minecraft:ender_dragon");value.addProperty("expected_dragon_phase",phase);
            if(phase==6 || phase==7)assertDoesNotThrow(()->CapabilityTargetAction.validate(value));
            else assertThrows(ClientActionRequest.Rejected.class,()->CapabilityTargetAction.validate(value));
        }
    }
    @Test void noImplicitSelectionUnboundedTimeoutOrPartialDraw() {
        JsonObject v=request("attack_entity","minecraft:zombie");v.addProperty("hotbar_slot",0);
        assertThrows(ClientActionRequest.Rejected.class,()->CapabilityTargetAction.validate(v));
        JsonObject timeout=request("shoot_entity","minecraft:end_crystal");timeout.addProperty("timeout_ms",10001);
        assertThrows(ClientActionRequest.Rejected.class,()->CapabilityTargetAction.validate(timeout));
        JsonObject partial=request("shoot_entity","minecraft:end_crystal");partial.addProperty("draw_ticks",19);
        assertThrows(ClientActionRequest.Rejected.class,()->CapabilityTargetAction.validate(partial));
        JsonObject health=request("shoot_entity","minecraft:end_crystal");health.addProperty("min_health",7.99);
        assertThrows(ClientActionRequest.Rejected.class,()->CapabilityTargetAction.validate(health));
    }
    @Test void geometryNeverAdmitsNonfiniteOrBlastRangeViolation() {
        for(double x:new double[]{Double.NaN,Double.POSITIVE_INFINITY,11.99,32.01})
            assertFalse(CapabilityTargetPolicy.crystalClear(x));
        assertTrue(CapabilityTargetPolicy.crystalClear(12));
        assertFalse(CapabilityTargetPolicy.meleeReach(3.01,5));
        assertFalse(CapabilityTargetPolicy.meleeReach(Double.NaN,3));
        assertTrue(Double.isNaN(CapabilityTargetPolicy.bowElevation(33,0)));
        assertTrue(Double.isFinite(CapabilityTargetPolicy.bowElevation(16,2)));
    }
}

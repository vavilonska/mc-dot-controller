package io.github.campione01.mineclientbridge;
import com.google.gson.JsonObject;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
class CapabilitySpeciesPolicyTest {
    JsonObject body(String action,String type,String flag) {
        var b=new JsonObject();b.addProperty("action",action);b.addProperty("target_type",type);b.addProperty("target_entity_id",1);b.addProperty("min_health",12);b.addProperty(flag,true);
        for(String k:new String[]{"target_uuid","expected_player_uuid","expected_world_generation","expected_action_session"})b.addProperty(k,"00000000-0000-0000-0000-000000000001");return b;
    }
    @Test void speciesAdmissionRequiresOwnFlagAndAttackMode() {
        for(String[] spec:new String[][]{{"minecraft:enderman","attack_entity","enderman_shelter_required"},{"minecraft:blaze","shoot_entity","fire_resistance_required"},{"minecraft:creeper","shoot_entity","creeper_safety_required"},{"minecraft:cave_spider","shoot_entity","poison_guard_required"}}) {
            var b=body(spec[1],spec[0],spec[2]);assertDoesNotThrow(()->CapabilityTargetAction.validate(b));
            var wrong=b.deepCopy();wrong.remove(spec[2]);assertThrows(ClientActionRequest.Rejected.class,()->CapabilityTargetAction.validate(wrong));
            var mode=b.deepCopy();mode.addProperty("action",spec[1].equals("shoot_entity")?"attack_entity":"shoot_entity");assertThrows(ClientActionRequest.Rejected.class,()->CapabilityTargetAction.validate(mode));
            var low=b.deepCopy();low.addProperty("min_health",11);assertThrows(ClientActionRequest.Rejected.class,()->CapabilityTargetAction.validate(low));
        }
    }
    @Test void creeperRequiresUnlitVanillaFuseAndChargedBlastClearance() {
        assertTrue(CapabilitySpeciesPolicy.creeper(12,false,false,0,-1,30,3));
        assertFalse(CapabilitySpeciesPolicy.creeper(12,true,false,0,-1,30,3));
        assertTrue(CapabilitySpeciesPolicy.creeper(16,true,false,0,-1,30,3));
        assertFalse(CapabilitySpeciesPolicy.creeper(20,false,true,0,-1,30,3));
        assertFalse(CapabilitySpeciesPolicy.creeper(20,false,false,1,-1,30,3));
        assertFalse(CapabilitySpeciesPolicy.creeper(20,false,false,0,1,30,3));
        assertFalse(CapabilitySpeciesPolicy.creeper(20,false,false,0,-1,10,3));
        assertFalse(CapabilitySpeciesPolicy.creeper(20,false,false,0,-1,30,8));
    }
    @Test void fireResistanceAndPoisonAreRealIndependentPrerequisites() {
        assertTrue(CapabilitySpeciesPolicy.blaze(12,true));assertFalse(CapabilitySpeciesPolicy.blaze(12,false));
        assertFalse(CapabilitySpeciesPolicy.blaze(11.99,true));assertFalse(CapabilitySpeciesPolicy.blaze(Double.NaN,true));
        assertTrue(CapabilitySpeciesPolicy.caveSpider(8,false));assertFalse(CapabilitySpeciesPolicy.caveSpider(8,true));
        assertFalse(CapabilitySpeciesPolicy.caveSpider(7.99,false));
    }
    @Test void shieldWindowNeedsExactShieldAndLongEnoughFiniteLifecycle() {
        var b=body("shoot_entity","minecraft:blaze","unused");b.remove("unused");
        b.addProperty("blaze_safety_mode","shield_window");b.addProperty("min_health",18);b.addProperty("timeout_ms",20000);
        var item=new JsonObject();item.addProperty("item_fingerprint","shield-snapshot");b.add("expected_offhand_item",item);
        assertDoesNotThrow(()->CapabilityTargetAction.validate(b));
        var noShield=b.deepCopy();noShield.remove("expected_offhand_item");assertThrows(ClientActionRequest.Rejected.class,()->CapabilityTargetAction.validate(noShield));
        var shortTime=b.deepCopy();shortTime.addProperty("timeout_ms",5000);assertThrows(ClientActionRequest.Rejected.class,()->CapabilityTargetAction.validate(shortTime));
        var low=b.deepCopy();low.addProperty("min_health",17.99);assertThrows(ClientActionRequest.Rejected.class,()->CapabilityTargetAction.validate(low));
    }
    @Test void coverNeverTerminatesEarlyOrWhileKnownFireRiskRemains() {
        assertFalse(BlazeShieldPolicy.range(15.99));assertTrue(BlazeShieldPolicy.range(16));
        assertFalse(BlazeShieldPolicy.ready(19,false,false));assertTrue(BlazeShieldPolicy.ready(20,false,false));
        assertFalse(BlazeShieldPolicy.ready(100,true,false));assertFalse(BlazeShieldPolicy.ready(100,false,true));
        assertFalse(BlazeShieldPolicy.ready(121,false,false));
        assertTrue(BlazeShieldPolicy.frontal(0,0,5));assertFalse(BlazeShieldPolicy.frontal(0,0,-5));
        assertFalse(BlazeShieldPolicy.frontal(Double.NaN,0,5));
    }
    @Test void shieldReserveRejectsPredictableMidCoverBreakBeforeUse() {
        assertTrue(BlazeShieldPolicy.reserve(336,272));assertFalse(BlazeShieldPolicy.reserve(336,273));
        assertFalse(BlazeShieldPolicy.reserve(336,335));assertFalse(BlazeShieldPolicy.reserve(0,0));
        assertFalse(BlazeShieldPolicy.reserve(336,-1));
    }
    @Test void firstVolleyMustActuallyBeObservedBeforeTheSingleDraw() {
        assertFalse(BlazeShieldPolicy.initialReady(false,100,false,false));
        assertFalse(BlazeShieldPolicy.initialReady(true,100,true,false));
        assertFalse(BlazeShieldPolicy.initialReady(true,100,false,true));
        assertTrue(BlazeShieldPolicy.initialReady(true,100,false,false));
        assertFalse(BlazeShieldPolicy.initialReady(true,241,false,false));
    }
}

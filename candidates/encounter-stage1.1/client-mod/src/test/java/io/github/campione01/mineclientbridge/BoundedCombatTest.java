package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class BoundedCombatTest {
    static JsonObject body() {
        return JsonParser.parseString("""
            {"action":"combat_entity","action_id":"combat-a","timeout_ms":20000,
             "expected_world_generation":"00000000-0000-4000-8000-000000000001",
             "expected_player_uuid":"00000000-0000-4000-8000-000000000002",
             "expected_action_session":"00000000-0000-4000-8000-000000000003",
             "target_uuid":"00000000-0000-4000-8000-000000000004","target_entity_id":4,
             "target_type":"minecraft:zombie","approach":true,"shield":true}
            """).getAsJsonObject();
    }
    @Test void selectedTargetAndBoundedLeaseParseWithoutWorldIo() {
        var action=ClientActionRequest.parse(body());
        assertEquals("combat_entity",action.action());assertEquals(20000,action.timeoutMs());
        var r=BoundedCombatRequest.parse(body());
        assertEquals(4,r.targetId());assertTrue(r.shield());assertTrue(r.approach());
    }
    @Test void limitsAndWireIdentityRejectBeforeInput() {
        for (int ttl:new int[]{0,49,30001,600000}) {
            var b=body();b.addProperty("timeout_ms",ttl);
            assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(b));
        }
        for (String key:new String[]{"expected_world_generation","expected_player_uuid","expected_action_session","target_uuid"}) {
            var b=body();b.addProperty(key,"unknown");
            assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(b));
        }
        var b=body();b.addProperty("shield","true");
        assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(b));
    }
    @Test void playersPetsNeutralBossesAndUnimplementedStrategiesAreExcluded() {
        for (String type:new String[]{"minecraft:player","minecraft:wolf","minecraft:cat","minecraft:spider",
                "minecraft:enderman","minecraft:witch","minecraft:warden","minecraft:ender_dragon","mod:mob"}) {
            var b=body();b.addProperty("target_type",type);
            assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(b));
        }
    }
    @Test void cooldownUsesObservedValueNotWeaponWallClock() {
        assertFalse(CombatRules.cooldownReady(.94));assertTrue(CombatRules.cooldownReady(.95));
        assertTrue(CombatRules.cooldownReady(1));assertFalse(CombatRules.cooldownReady(Double.NaN));
        assertFalse(CombatRules.cooldownReady(2));
    }
    @Test void eyeHitReachAndExactRayTargetAreBothRequired() {
        assertTrue(CombatRules.rayInReach(true,2.8,3));assertFalse(CombatRules.rayInReach(false,1,3));
        assertFalse(CombatRules.rayInReach(true,2.8,2.5));assertFalse(CombatRules.rayInReach(true,3.1,6));
        assertFalse(CombatRules.rayInReach(true,Double.NaN,3));
    }
    @Test void manualViewSupportsYawWrapButNotChangedOrInvalidView() {
        assertFalse(CombatRules.manualViewChanged(-179,5,181,5));
        assertTrue(CombatRules.manualViewChanged(-178,5,181,5));
        assertTrue(CombatRules.manualViewChanged(1,Double.NaN,1,2));
    }
    @Test void terminalIdsNeverRestartEvenForCombat() {
        var registry=new ActionRegistry();var request=ClientActionRequest.parse(body());
        registry.begin(request);registry.finish("cancelled","deadline_exceeded");
        assertEquals("cancelled",registry.begin(request).status);assertNull(registry.active());
    }
    @Test void runtimeContractKeepsExpiryReleaseAndLiveTerrainChecks() throws Exception {
        var dir=Path.of(System.getProperty("mineclientBridge.projectDir"),"src/main/java/io/github/campione01/mineclientbridge");
        String actions=Files.readString(dir.resolve("ClientActions.java"));
        String combat=Files.readString(dir.resolve("BoundedCombat.java"));
        String terrain=Files.readString(dir.resolve("TerrainReader.java"));
        assertTrue(actions.contains("System.nanoTime() >= active.deadline"));
        assertTrue(actions.contains("a.combat.release(Minecraft.getInstance())"));
        assertTrue(actions.contains("input.down = a.forward < 0"));
        assertTrue(combat.contains("mc.gameRenderer.pick(1.0F)"));
        assertTrue(combat.contains("getAttackStrengthScale(.5F)"));
        assertTrue(combat.contains("mc.gameMode.releaseUsingItem(mc.player)"));
        assertTrue(combat.contains("target_missing_not_a_kill"));
        assertTrue(combat.contains("if (separation > 8)"));
        assertTrue(terrain.contains("availability != TerrainScan.Availability.LOADED"));
        assertTrue(terrain.contains("return source::readFlatCell;"));
        assertTrue(terrain.contains("CollisionFacts collision = readCollision(block)"));
        assertTrue(terrain.contains("collision.known(), collision.empty(), collision.topFull()"));
    }
}

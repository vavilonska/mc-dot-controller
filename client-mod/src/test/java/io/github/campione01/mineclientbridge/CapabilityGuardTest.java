package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Set;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/** Executed wire/registry and source-wiring checks; no claim of game hook acceptance. */
class CapabilityGuardTest {
    static JsonObject request(String action) {
        JsonObject b=JsonParser.parseString("{\"action_id\":\"capability\",\"action\":\""+action+"\",\"hotbar_slot\":0,\"timeout_ms\":3000,\"expected_hotbar_slot\":0,\"expected_held_item\":{\"item_fingerprint\":\"item\"},\"expected_world_generation\":\"world\",\"expected_player_uuid\":\"player\",\"expected_action_session\":\"session\",\"expected_dimension\":\"minecraft:overworld\",\"capability_guard\":{\"schema_version\":1,\"source_tick\":1,\"source_nano\":\"1\"}}").getAsJsonObject();
        return b;
    }
    String source(String name)throws Exception{return Files.readString(Path.of(System.getProperty("mineclientBridge.projectDir"),"src/main/java/io/github/campione01/mineclientbridge",name+".java"));}
    @Test void addedActionsAreExactAndExplicitlyOptIn() {
        assertEquals(Set.of("interact_block","use_item","select_hotbar","close_menu","attack_entity","shoot_entity","gateway_pearl","movement_budget_start","movement_budget_finish"),ClientActionRequest.CAPABILITY_ACTIONS);
        assertEquals(18,ClientActionRequest.ACTIONS.size());
        JsonObject b=request("select_hotbar");
        assertEquals("select_hotbar",ClientActionRequest.parse(b).action());
        b.remove("capability_guard");
        assertEquals("capability_guard_required",assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(b)).getMessage());
    }
    @Test void oldUnboundActionsRemainAvailable() {
        JsonObject b=JsonParser.parseString("{\"action_id\":\"legacy\",\"action\":\"break_block\",\"target\":{\"x\":1,\"y\":64,\"z\":0}}").getAsJsonObject();
        assertFalse(CapabilityGuard.requested(ClientActionRequest.parse(b).original()));
    }
    @Test void capabilityWireRejectsMissingIdentityAndHeldBinding() {
        for(String field:Set.of("expected_world_generation","expected_player_uuid","expected_action_session","expected_dimension","expected_hotbar_slot","expected_held_item")) {
            JsonObject b=request("select_hotbar");b.remove(field);
            assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(b),field);
        }
    }
    @Test void admissionTimeWireIsStrictAndFinite() {
        for(String tick:Set.of("-1","1.25","9007199254740992","\"1\"","null","true")) {
            JsonObject b=request("select_hotbar");b.getAsJsonObject("capability_guard").add("source_tick",JsonParser.parseString(tick));
            assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(b),tick);
        }
        for(String nano:Set.of("9223372036854775808","not-a-number")) {
            JsonObject b=request("select_hotbar");b.getAsJsonObject("capability_guard").addProperty("source_nano",nano);
            assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(b),nano);
        }
        for(int timeout:new int[]{0,60001}) {
            JsonObject b=request("select_hotbar");b.addProperty("timeout_ms",timeout);
            assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(b));
        }
    }
    @Test void interactionRequiresExactTargetFaceAndBoundIdentity() {
        JsonObject b=request("interact_block");b.add("target",JsonParser.parseString("{\"x\":1,\"y\":64,\"z\":0}"));b.addProperty("face","north");b.addProperty("expected_block_id","minecraft:chest");
        assertEquals("north",ClientActionRequest.parse(b).face());
        b.addProperty("face","auto");assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(b));
    }
    @Test void consumedActionIdsAreNeverReplayed() {
        ActionRegistry registry=new ActionRegistry();var request=ClientActionRequest.parse(request("select_hotbar"));
        var entry=registry.begin(request);registry.finishAfterCleanup("succeeded","selected",true);
        assertSame(entry,registry.existing(request));assertNull(registry.active());
        JsonObject changed=request.original().deepCopy();changed.addProperty("hotbar_slot",1);
        assertThrows(ClientActionRequest.Rejected.class,()->registry.existing(ClientActionRequest.parse(changed)));
    }
    @Test void guardAndCleanupSurroundRealVanillaMutation()throws Exception {
        String actions=source("ClientActions"),guard=source("CapabilityGuard");
        assertTrue(actions.indexOf("CapabilityGuard.start(mc,request)")<actions.indexOf("BridgeServer.releaseAllInputs()"));
        assertTrue(actions.contains("enteredOwner.capabilityGuard.check(mc,enteredOwner.dispatched)"));
        assertTrue(actions.contains("managedCleanup = managedCleanup || a.capabilityGuard != null"));
        assertTrue(actions.contains("ACTIONS.finishAfterCleanup(status, reason, released)"));
        assertTrue(actions.contains("mc.gameMode.useItemOn(a.player,InteractionHand.MAIN_HAND,hit)"));
        assertTrue(actions.contains("mc.gameMode.useItem(a.player,InteractionHand.MAIN_HAND)"));
        assertTrue(guard.contains("elapsed>800_000_000L") && guard.contains("tick-sourceTick>5"));
        assertTrue(guard.contains("!mc.isWindowActive() || mc.isPaused()"));
        assertTrue(guard.contains("!mc.getSingleplayerServer().isPublished()"));
        assertTrue(guard.contains("activeSelection?selected:ClientActionRequest.integer"));
        assertTrue(guard.contains("current.setDamageValue(held.getDamageValue())"));
        assertTrue(guard.contains("capability_tool_changed"));
    }
    @Test void fingerprintsUseFullNativeComponentsNotHashOrLossyText()throws Exception {
        String binding=source("CapabilityItemBinding");
        assertTrue(binding.contains("ItemStack.isSameItemSameComponents"));
        assertTrue(binding.contains("value.copy()"));assertTrue(binding.contains("LIMIT=4096"));
        assertFalse(binding.contains("hashCode"));assertFalse(binding.contains("getComponents().toString"));
        String server=source("BridgeServer");
        for(String field:Set.of("focused","private_singleplayer","held_inputs","capability_guard","phase_id","dragon_parts","furnace","potion_effects"))assertTrue(server.contains("\""+field+"\""),field);
    }
}

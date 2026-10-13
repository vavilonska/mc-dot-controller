package io.github.campione01.mineclientbridge;

import static org.junit.jupiter.api.Assertions.*;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.Set;
import org.junit.jupiter.api.Test;

/** Cross-action preservation checks for the path-only v18 execution slice. */
class MainlinePathSliceTest {
    private JsonObject body(String fields) {
        return JsonParser.parseString("{\"action_id\":\"test-id\","+fields+"}").getAsJsonObject();
    }
    private ClientActionRequest path() {
        return ClientActionRequest.parse(body("\"action\":\"follow_path\",\"waypoints\":[{\"x\":1,\"y\":64,\"z\":1}]"));
    }
    private String source() throws Exception {
        return Files.readString(Path.of(System.getProperty("mineclientBridge.projectDir"),
                "src/main/java/io/github/campione01/mineclientbridge/ClientActions.java"));
    }
    private String hashRegion(String source,String first,String last) throws Exception {
        int start=source.indexOf(first),end=source.indexOf(last,start);
        assertTrue(start>=0 && end>start);
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                .digest(source.substring(start,end).getBytes(StandardCharsets.UTF_8)));
    }

    // Keep the original historical SHA assertion: remove only the enumerated
    // capability-only branches. Unexpected changes to vanilla legacy code still fail.
    private String withoutOptInCapabilityGates(String source) {
        source=source.replace("        if(!capabilityDispatchCheck(mc,a))return;\n", "");
        source=source.replace("        if(a.capabilityGuard!=null){hit=pick(mc,support,face);if(hit==null){finish(\"failed\",\"support_face_not_in_reach_or_visible\");return;}}\n", "");
        source=source.replace("""
            if (mc.level.getBlockState(target).getBlock() == a.placedBlock
                    && (a.capabilityGuard==null || CapabilityGuard.blockMatches(mc.level.getBlockState(target),
                        ClientActionRequest.string(a.entry.request.original(),"expected_block_id"),
                        a.entry.request.original().has("expected_block_properties")?a.entry.request.original().getAsJsonObject("expected_block_properties"):null))) {
""", "            if (mc.level.getBlockState(target).getBlock() == a.placedBlock) {\n");
        return source;
    }

    @Test void originalEightActionsRemainWithExactlyOneAddedCombatAction() {
        assertEquals(Set.of("follow_path","recover_environment","break_block","place_block","click_slot","boat_drive","boat_mount","boat_dismount","combat_entity"),ClientActionRequest.LEGACY_ACTIONS);
    }
    @Test void recoveryRetainsZeroLifetimeAndEmptyPathButPathCannotClaimThem() {
        JsonObject recovery=body("\"action\":\"recover_environment\",\"waypoints\":[]");
        assertEquals(0,ClientActionRequest.parse(recovery).timeoutMs());
        recovery.addProperty("timeout_ms",1000);assertEquals(1000,ClientActionRequest.parse(recovery).timeoutMs());
        recovery.addProperty("timeout_ms",0);assertEquals(0,ClientActionRequest.parse(recovery).timeoutMs());
        recovery.addProperty("action","follow_path");assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(recovery));
    }
    @Test void optionalSprintIsStrictlyBooleanAndOnlyForPath() {
        JsonObject path=path().original().deepCopy();
        for(boolean wanted:new boolean[]{false,true}) {path.addProperty("sprint",wanted);assertEquals(wanted,ClientActionRequest.bool(ClientActionRequest.parse(path).original(),"sprint",false));}
        for(String invalid:new String[]{"null","0","\"true\"","{}","[]"}) {
            path.add("sprint",JsonParser.parseString(invalid));assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(path));
        }
        path.remove("sprint");assertFalse(ClientActionRequest.bool(ClientActionRequest.parse(path).original(),"sprint",false));
        JsonObject recovery=body("\"action\":\"recover_environment\",\"waypoints\":[],\"sprint\":false");
        assertEquals("sprint_requires_follow_path",assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(recovery)).getMessage());
    }
    @Test void rejectedSprintCannotReplaceExistingRegistryOwner() {
        var registry=new ActionRegistry();var owner=registry.begin(path());
        JsonObject invalid=body("\"action\":\"break_block\",\"target\":{\"x\":0,\"y\":64,\"z\":0},\"sprint\":true");
        assertThrows(ClientActionRequest.Rejected.class,()->registry.begin(ClientActionRequest.parse(invalid)));
        assertSame(owner,registry.active());assertEquals("running",owner.status);
    }
    @Test void allNonPathActionsKeepLegacyTerminalFields() {
        for(String fields:new String[]{
                "\"action\":\"recover_environment\",\"waypoints\":[]",
                "\"action\":\"break_block\",\"target\":{\"x\":0,\"y\":64,\"z\":0}",
                "\"action\":\"place_block\",\"support\":{\"x\":0,\"y\":63,\"z\":0},\"face\":\"up\"",
                "\"action\":\"click_slot\",\"container_id\":0,\"slot\":1,\"button\":0,\"click_type\":\"pickup\""}) {
            var registry=new ActionRegistry();var entry=registry.begin(ClientActionRequest.parse(body(fields)));
            registry.finish("cancelled","legacy_reason");
            assertEquals("cancelled",entry.status);assertEquals("legacy_reason",entry.reason);
            assertFalse(entry.result.has("input_release_confirmed"));
            assertFalse(entry.result.has("requested_terminal_status"));assertNull(registry.active());
        }
    }
    @Test void pathCancelWithConfirmedReleaseRemainsCancelled() {
        var registry=new ActionRegistry();var entry=registry.begin(path());
        registry.finishAfterCleanup("cancelled","cancel_requested",true);
        assertEquals("cancelled",entry.status);assertEquals("cancel_requested",entry.reason);
        assertTrue(entry.result.get("input_release_confirmed").getAsBoolean());
        assertFalse(entry.result.has("requested_terminal_status"));assertNull(registry.active());
    }
    @Test void pathCancelWithFailedReleaseRetainsRequestedTerminalButNeverClaimsRelease() {
        var registry=new ActionRegistry();var entry=registry.begin(path());
        registry.finishAfterCleanup("cancelled","direct_takeover",false);
        assertEquals("failed",entry.status);assertEquals("input_release_unconfirmed",entry.reason);
        assertEquals("cancelled",entry.result.get("requested_terminal_status").getAsString());
        assertEquals("direct_takeover",entry.result.get("requested_terminal_reason").getAsString());
        assertFalse(entry.result.get("input_release_confirmed").getAsBoolean());
    }
    @Test void duplicateCompletedPathDoesNotReplaceNewOwner() {
        var registry=new ActionRegistry();var request=path();var old=registry.begin(request);
        registry.finishAfterCleanup("cancelled","cancel_requested",true);
        var next=request.original().deepCopy();next.addProperty("action_id","new-id");var owner=registry.begin(ClientActionRequest.parse(next));
        assertSame(old,registry.existing(request));assertSame(owner,registry.active());
    }
    @Test void mainEnvironmentAndStableMiningPlacementMethodsAreBytePreserved() throws Exception {
        String source=source();
        assertEquals("73043781ff81758d43c312d5103898daaaf06c213694b64dee322b7a98dbe77a",
                hashRegion(source,"    private static void recoverEnvironment(","    private static void mine("));
        assertEquals("f2f725bee48be569729079aea23db71172deed87e9b3058d6e37181d2f610272",
                hashRegion(withoutOptInCapabilityGates(source),"    private static void mine(","    private static void clickSlot("));
        assertTrue(source.contains("entry.request.timeoutMs() == 0 ? Long.MAX_VALUE"));
    }
    @Test void runtimeUsesConfirmedCleanupOnlyForPathOrBoatAndBeforeTerminalPublication() throws Exception {
        String source=source();String finish=source.substring(source.indexOf("    private static void finish("),source.indexOf("    private static boolean cleanup("));
        assertTrue(finish.contains("boolean pathAction = a.entry.request.action().equals(\"follow_path\")"));
        assertTrue(finish.contains("boolean managedCleanup = pathAction || a.boat != null || a.transfer != null"));
        int old=finish.indexOf("if (!managedCleanup) ACTIONS.finish(status, reason)");
        int inputs=finish.indexOf("a.input.forwardImpulse = a.input.leftImpulse = 0");
        int path=finish.indexOf("if (managedCleanup) {");
        int release=finish.indexOf("cleanup(() -> sprint(Minecraft.getInstance(), a, false))");
        int terminal=finish.indexOf("ACTIONS.finishAfterCleanup(status, reason, released)");
        assertTrue(old>=0 && inputs>old && path>inputs && release>path && terminal>release);
    }
}

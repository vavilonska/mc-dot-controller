package io.github.campione01.mineclientbridge;

import static org.junit.jupiter.api.Assertions.*;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Set;
import java.util.function.Consumer;
import org.junit.jupiter.api.Test;

/** Real parser/registry checks plus explicit source-wiring checks, not live Minecraft hook tests. */
class MainlineCoordinationSliceTest {
    private String source(String name) throws Exception {
        return Files.readString(Path.of(System.getProperty("mineclientBridge.projectDir"),
                "src/main/java/io/github/campione01/mineclientbridge",name+".java"));
    }
    private String region(String text,String first,String last) {
        int start=text.indexOf(first),end=text.indexOf(last,start);
        assertTrue(start>=0 && end>start,first);return text.substring(start,end);
    }
    private void rejected(Consumer<JsonObject> mutate) {
        var request=CoordinationStepGuardTest.request();mutate.accept(request);
        assertThrows(ClientActionRequest.Rejected.class,()->ClientActionRequest.parse(request),request.toString());
    }
    @Test void frozenRootRedPayloadIsNowRejectedBeforeRegistryAdmission() {
        var malformed=CoordinationStepGuardTest.request();
        malformed.addProperty("coordination_step","malformed-not-an-object");
        var registry=new ActionRegistry();
        var recovery=JsonParser.parseString("{\"action\":\"recover_environment\",\"action_id\":\"old\",\"waypoints\":[]}").getAsJsonObject();
        var old=registry.begin(ClientActionRequest.parse(recovery));
        assertEquals("coordination_step_invalid",assertThrows(ClientActionRequest.Rejected.class,
                ()->registry.begin(ClientActionRequest.parse(malformed))).getMessage());
        assertSame(old,registry.active());assertTrue(old.running());
    }
    @Test void explicitOptInRetainsNineActionsRecoveryAndLegacyExtras() {
        assertEquals(Set.of("follow_path","break_block","place_block","click_slot","recover_environment",
                "boat_drive","boat_mount","boat_dismount","combat_entity"),ClientActionRequest.LEGACY_ACTIONS);
        var legacy=CoordinationStepGuardTest.request();legacy.remove("coordination_step");
        legacy.addProperty("legacy_extra","kept");legacy.addProperty("timeout_ms",15000);
        var parsed=ClientActionRequest.parse(legacy);
        assertFalse(CoordinationStepGuard.requested(parsed.original()));assertEquals(legacy,parsed.original());
        var recovery=JsonParser.parseString("{\"action\":\"recover_environment\",\"action_id\":\"recover\",\"timeout_ms\":0,\"waypoints\":[]}").getAsJsonObject();
        assertEquals(0,ClientActionRequest.parse(recovery).timeoutMs());
    }
    @Test void schemaRangeBoundariesAndFalseOnlyOptionsAreStrict() {
        for(int timeout:new int[]{50,1000}) {
            var request=CoordinationStepGuardTest.request();request.addProperty("timeout_ms",timeout);
            for(String flag:new String[]{"sprint","jump","sneak"}) request.addProperty(flag,false);
            request.getAsJsonArray("waypoints").get(0).getAsJsonObject().addProperty("jump",false);
            assertEquals(timeout,ClientActionRequest.parse(request).timeoutMs());
        }
        for(int timeout:new int[]{0,49,1001}) rejected(p->p.addProperty("timeout_ms",timeout));
        rejected(p->p.remove("timeout_ms"));
        for(String flag:new String[]{"sprint","jump","sneak"}) {
            rejected(p->p.addProperty(flag,true));rejected(p->p.addProperty(flag,0));
        }
        rejected(p->p.getAsJsonArray("waypoints").get(0).getAsJsonObject().addProperty("jump",true));
        for(String field:new String[]{"hotbar_slot","expected_game_time","raw_key","combat","draft_plan"})
            rejected(p->p.addProperty(field,0));
        for(String field:new String[]{"expected_origin","expected_navigation_epoch","expected_world_generation","expected_player_uuid","expected_action_session"})
            rejected(p->p.remove(field));
    }
    @Test void sampleSchemaAndSignedNanoNeverCoerceOrRefreshSource() {
        for(String value:new String[]{"null","false","[]","\"x\""})
            rejected(p->p.add("coordination_step",JsonParser.parseString(value)));
        for(String field:new String[]{"schema_version","source_tick","source_nano"})
            rejected(p->p.getAsJsonObject("coordination_step").remove(field));
        rejected(p->p.getAsJsonObject("coordination_step").addProperty("extra",1));
        for(String value:new String[]{"0","2","1.5","\"1\"","null"})
            rejected(p->p.getAsJsonObject("coordination_step").add("schema_version",JsonParser.parseString(value)));
        for(String value:new String[]{"-1","1.25","9007199254740992","\"10\"","true","null"})
            rejected(p->p.getAsJsonObject("coordination_step").add("source_tick",JsonParser.parseString(value)));
        for(String value:new String[]{"-9223372036854775809","9223372036854775808","+1","01","1.0","NaN"})
            rejected(p->p.getAsJsonObject("coordination_step").addProperty("source_nano",value));
        for(long tick:new long[]{0,9_007_199_254_740_991L}) for(long nano:new long[]{Long.MIN_VALUE,-1,0,Long.MAX_VALUE}) {
            var request=CoordinationStepGuardTest.request();var spec=request.getAsJsonObject("coordination_step");
            spec.addProperty("source_tick",tick);spec.addProperty("source_nano",Long.toString(nano));
            assertEquals(request,ClientActionRequest.parse(request).original());
        }
    }
    @Test void onlyOneCenteredSameHeightCardinalStepIsAccepted() {
        for(String axis:new String[]{"x","y","z"})
            rejected(p->p.getAsJsonArray("waypoints").get(0).getAsJsonObject().addProperty(axis,64.25));
        rejected(p->p.getAsJsonArray("waypoints").add(p.getAsJsonArray("waypoints").get(0).deepCopy()));
        rejected(p->p.getAsJsonObject("expected_origin").addProperty("extra",1));
        rejected(p->p.getAsJsonArray("waypoints").get(0).getAsJsonObject().addProperty("x",.5));
        rejected(p->p.getAsJsonArray("waypoints").get(0).getAsJsonObject().addProperty("z",1.5));
    }
    @Test void coordinationUsesRootManagedPathCleanupAndCannotSucceedWithoutRelease() {
        var registry=new ActionRegistry();var entry=registry.begin(ClientActionRequest.parse(CoordinationStepGuardTest.request()));
        registry.finishAfterCleanup("succeeded","path_complete",false);
        assertEquals("failed",entry.status);assertEquals("input_release_unconfirmed",entry.reason);
        assertFalse(entry.result.get("input_release_confirmed").getAsBoolean());
        assertEquals("succeeded",entry.result.get("requested_terminal_status").getAsString());
        assertNull(registry.active());
    }
    @Test void coordinationDeadlineAndOwnerChecksSurroundAdmissionAndTransferHooks() throws Exception {
        String actions=source("ClientActions");
        String start=region(actions,"    static JsonObject start(","    static JsonObject status(");
        int captured=start.indexOf("long coordinationOwnerRevision = ownershipRevision");
        int binding=start.indexOf("NavigationPositionGuard.requireBinding(mc, request)");
        int guard=start.indexOf("CoordinationStepGuard.start(mc, request)");
        int transfer=start.indexOf("CoordinationStepPolicy.transfer(");
        int owner=start.indexOf("active = new RuntimeAction(");
        assertTrue(captured>=0 && captured<binding && binding<guard && guard<transfer && transfer<owner);
        assertTrue(start.contains("long coordinationDeadline = coordinationRequested"));
        assertTrue(start.indexOf("long coordinationDeadline")<binding);
        assertTrue(start.contains("coordinationStep.requireFresh(mc)"));
        assertTrue(start.contains("coordination_step_deadline_exceeded"));
        assertTrue(start.contains("ownershipRevision != coordinationOwnerRevision"));
        assertTrue(start.contains("mc.player != coordinationPlayer || mc.level != coordinationLevel"));
        assertTrue(start.indexOf("ownershipRevision++;",transfer)>transfer);
        assertTrue(start.indexOf("ownershipRevision++;",transfer)<owner);
        String constructor=region(actions,"        RuntimeAction(","    static synchronized void install()");
        assertTrue(constructor.contains("if (coordinationStep != null)"));
        assertTrue(constructor.contains("deadline=coordinationDeadline;"));
        assertTrue(constructor.contains("deadline = combat != null ? combatDeadline : entry.request.timeoutMs() == 0 ? Long.MAX_VALUE\n                    : System.nanoTime() + entry.request.timeoutMs() * 1_000_000L;"));
        String direct=region(actions,"    static void directTakeover()","    static void cancel(");
        assertTrue(direct.indexOf("ownershipRevision++")<direct.indexOf("cancel(\"direct_takeover\")"));
    }
    @Test void allCallbacksCheckTheSameOwnerAndDynamicGuardWithoutRefreshingAdmissionSource() throws Exception {
        String actions=source("ClientActions"),context=region(actions,"    private static boolean context(","    private static void preTick()");
        for(String call:new String[]{"context(mc,\"pre_tick\")","context(Minecraft.getInstance(),\"movement_input\")","context(mc,\"post_tick\")"})
            assertTrue(actions.contains(call),call);
        for(String check:new String[]{"RuntimeAction enteredOwner = active","if (active != enteredOwner) return false",
                "if (active != epochOwner) return false","checkedOwner.coordinationStep.check(mc)",
                "coordination_step_check_failed","if (active != checkedOwner) return false","checkedOwner.coordinationStep.afterHooks(mc)"})
            assertTrue(context.contains(check),check);
        assertFalse(context.contains("requireFresh"));
        assertFalse(context.contains("source_tick"));
        assertTrue(context.indexOf("checkedOwner.coordinationStep.check(mc)")<context.indexOf("System.nanoTime() >= active.deadline"));
        String server=source("BridgeServer");
        assertTrue(server.contains("obj.addProperty(\"coordination_step_protocol\", 1)"));
        assertTrue(server.contains("createStateSnapshot(radius, timing, coordination)"));
        assertTrue(actions.contains("active.entry.result.addProperty(\"coordination_step_schema_version\",1)"));
    }
}

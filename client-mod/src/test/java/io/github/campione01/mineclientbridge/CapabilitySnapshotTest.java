package io.github.campione01.mineclientbridge;

import com.google.gson.*;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import java.util.function.Consumer;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/** Synthetic immutable observations, actual assembler and HTTP encoder. No game entrypoint. */
class CapabilitySnapshotTest {
    static final Object LEVEL=new Object(),PLAYER=new Object(),MODE=new Object(),MENU=new Object();
    static final String UUID="00000000-0000-4000-8000-000000000009";
    static CapabilitySnapshot.Context context() {
        return new CapabilitySnapshot.Context(LEVEL,PLAYER,MODE,null,MENU,"world","player","minecraft:overworld","session",100);
    }
    static JsonObject protocol() { return JsonParser.parseString("{\"ok\":true,\"protocol\":\"mineclient-bridge\",\"schema_version\":2}").getAsJsonObject(); }
    static JsonObject[] siblings(boolean target,boolean persistent,boolean unknown) {
        JsonObject action=new ActionRegistry().status(null);action.addProperty("action_session","session");
        action.add("movement_budget",JsonParser.parseString("{\"schema_version\":1,\"status\":\"unarmed\"}"));
        JsonObject status=protocol(),state=protocol(),screen=protocol();
        JsonObject world=JsonParser.parseString("{\"world_generation\":\"world\",\"dimension\":\"minecraft:overworld\",\"game_time\":100}").getAsJsonObject();
        JsonObject player=JsonParser.parseString("{\"uuid\":\"player\",\"dimension\":\"minecraft:overworld\",\"x\":0,\"y\":64,\"z\":0,\"yaw\":0,\"pitch\":0}").getAsJsonObject();
        for(JsonObject sibling:new JsonObject[]{status,state}) {
            sibling.add("world",world.deepCopy());sibling.add("player",player.deepCopy());sibling.add("client_action",action.deepCopy());
        }
        status.addProperty("in_world",true);status.add("screen",JsonParser.parseString("{\"present\":false}"));
        state.addProperty("screen_open",false);screen.addProperty("open",false);
        JsonObject menu=JsonParser.parseString("{\"menu_class\":\"InventoryMenu\",\"container_id\":0,\"state_id\":7,\"slots\":[]}").getAsJsonObject();
        state.add("menu",menu);screen.add("menu",menu.deepCopy());
        state.add("movement_budget",action.get("movement_budget").deepCopy());
        state.add("capability_guard",CapabilityGuard.observation(100,1_050_000_000L));
        var nativeTarget=target?new NativeLivingSnapshot.Target("target",8,"minecraft:player"):null;
        var row=new NativeLivingSnapshot.Row(UUID,9,"minecraft:bee",99,1_000_000_000L,true,false,
                nativeTarget,new NativeLivingSnapshot.BeeState(false,0,persistent?"target":null));
        var batch=new NativeLivingSnapshot.Batch(LEVEL,new Object(),"minecraft:overworld",Map.of(UUID,row),true,1,"observed");
        JsonObject facts=NativeLivingSnapshot.json(unknown?null:batch,LEVEL,"minecraft:overworld","world","player",UUID,9,"minecraft:bee",100,1_050_000_000L);
        JsonObject entity=JsonParser.parseString("{\"entity_id\":9,\"type\":\"minecraft:bee\",\"x\":24,\"y\":64,\"z\":0,\"distance\":24}").getAsJsonObject();
        entity.addProperty("uuid",UUID);entity.add("native_living",facts);
        JsonArray entities=new JsonArray();entities.add(entity);
        JsonObject nearby=JsonParser.parseString("{\"radius\":48,\"total\":1,\"returned\":1,\"truncated\":false}").getAsJsonObject();
        nearby.add("entities",entities);state.add("nearby",nearby);
        return new JsonObject[]{status,action,state,screen};
    }
    static JsonObject bundle(JsonObject[] siblings) {
        return CapabilitySnapshot.assemble(context(),context(),siblings[0],siblings[1],siblings[2],siblings[3],siblings[1].deepCopy());
    }
    static JsonObject facts(JsonObject bundle) { return bundle.getAsJsonObject("state").getAsJsonObject("nearby").getAsJsonArray("entities").get(0).getAsJsonObject().getAsJsonObject("native_living"); }

    @Test void completeBundleKeepsAllSiblingShapesAndOriginalEntityCaptureEvidenceThroughHttp() throws Exception {
        for(boolean target:new boolean[]{false,true})for(boolean persistent:new boolean[]{false,true})for(boolean unknown:new boolean[]{false,true}) {
            var input=siblings(target,persistent,unknown);var original=input[2].deepCopy();var body=bundle(input);
            var exchange=TerrainCapabilityWireTest.http(body);assertEquals(200,exchange.status);var parsed=exchange.body();
            assertEquals(1,parsed.get("capability_snapshot_schema_version").getAsInt());
            assertEquals(JsonParser.parseString(BridgeJson.toJson(original)),parsed.get("state"));
            assertEquals(original,input[2]);
            for(String sibling:new String[]{"status","action","state","screen"}) {
                assertEquals("mineclient-bridge",parsed.getAsJsonObject(sibling).get("protocol").getAsString());
                assertEquals(2,parsed.getAsJsonObject(sibling).get("schema_version").getAsInt());
            }
            assertTrue(parsed.getAsJsonObject("action").get("action_id").isJsonNull());
            assertTrue(parsed.getAsJsonObject("state").getAsJsonObject("client_action").get("action_id").isJsonNull());
            if(!unknown) {
                var facts=facts(parsed);assertEquals("1000000000",facts.get("source_nano").getAsString());
                assertEquals(99,facts.get("source_tick").getAsInt());
                assertEquals(50.0,facts.get("sample_age_ms").getAsDouble());
                assertEquals(!target,facts.get("current_target").isJsonNull());
                assertEquals(!persistent,facts.getAsJsonObject("bee").get("persistent_anger_target_uuid").isJsonNull());
            } else { assertFalse(facts(parsed).get("known").getAsBoolean());assertFalse(facts(parsed).has("current_target")); }
        }
    }

    @Test void unrelatedNullsAndMissingTargetsAreNotInventedAtNewWrapperDepth() throws Exception {
        var input=siblings(false,false,false);JsonObject nativeFacts=input[2].getAsJsonObject("nearby").getAsJsonArray("entities").get(0).getAsJsonObject().getAsJsonObject("native_living");
        nativeFacts.remove("current_target");nativeFacts.add("other_null",JsonNull.INSTANCE);
        var parsed=TerrainCapabilityWireTest.http(bundle(input)).body();
        assertFalse(facts(parsed).has("current_target"));assertFalse(facts(parsed).has("other_null"));
        assertTrue(facts(parsed).getAsJsonObject("bee").get("persistent_anger_target_uuid").isJsonNull());
    }

    @Test void openContainerScreenKeepsFullMenuAndScreenShapeButRejectsChangedTitle() throws Exception {
        var s=siblings(false,false,false);Object screenToken=new Object();
        var c=new CapabilitySnapshot.Context(LEVEL,PLAYER,MODE,screenToken,MENU,"world","player","minecraft:overworld","session",100);
        var statusScreen=s[0].getAsJsonObject("screen");statusScreen.addProperty("present",true);
        for(JsonObject screen:new JsonObject[]{statusScreen,s[3]}) {
            screen.addProperty("class","net.minecraft.client.gui.screens.inventory.FurnaceScreen");screen.addProperty("title","Furnace");
        }
        s[2].addProperty("screen_open",true);s[3].addProperty("open",true);
        s[3].addProperty("container_id",5);s[3].addProperty("menu_class","net.minecraft.world.inventory.FurnaceMenu");
        s[3].add("slots",JsonParser.parseString("[{\"menu_index\":0,\"slot_index\":0,\"item\":{\"id\":\"minecraft:iron_ore\",\"count\":7}}]"));
        for(JsonObject sibling:new JsonObject[]{s[2],s[3]}) {
            sibling.getAsJsonObject("menu").addProperty("container_id",5);
            sibling.getAsJsonObject("menu").addProperty("menu_class","net.minecraft.world.inventory.FurnaceMenu");
            sibling.getAsJsonObject("menu").add("furnace",JsonParser.parseString("{\"is_lit\":true,\"burn_progress\":0.2,\"lit_progress\":0.8}"));
        }
        var body=CapabilitySnapshot.assemble(c,c,s[0],s[1],s[2],s[3],s[1].deepCopy());
        var parsed=TerrainCapabilityWireTest.http(body).body();
        assertEquals(s[3],parsed.get("screen"));assertEquals(s[2].get("menu"),parsed.getAsJsonObject("state").get("menu"));
        s[3].addProperty("title","Changed");
        assertEquals("capability_snapshot_incoherent",assertThrows(ClientActionRequest.Rejected.class,
                ()->CapabilitySnapshot.assemble(c,c,s[0],s[1],s[2],s[3],s[1])).getMessage());
    }

    @Test void contextIdentityTickAndActionChangesFailClosedWithoutRepair() {
        var c=context();var input=siblings(false,false,false);
        for(var changed:new CapabilitySnapshot.Context[]{
                new CapabilitySnapshot.Context(new Object(),PLAYER,MODE,null,MENU,"world","player","minecraft:overworld","session",100),
                new CapabilitySnapshot.Context(LEVEL,new Object(),MODE,null,MENU,"world","player","minecraft:overworld","session",100),
                new CapabilitySnapshot.Context(LEVEL,PLAYER,new Object(),null,MENU,"world","player","minecraft:overworld","session",100),
                new CapabilitySnapshot.Context(LEVEL,PLAYER,MODE,new Object(),MENU,"world","player","minecraft:overworld","session",100),
                new CapabilitySnapshot.Context(LEVEL,PLAYER,MODE,null,new Object(),"world","player","minecraft:overworld","session",100),
                new CapabilitySnapshot.Context(LEVEL,PLAYER,MODE,null,MENU,"changed","player","minecraft:overworld","session",100),
                new CapabilitySnapshot.Context(LEVEL,PLAYER,MODE,null,MENU,"world","other","minecraft:overworld","session",100),
                new CapabilitySnapshot.Context(LEVEL,PLAYER,MODE,null,MENU,"world","player","minecraft:the_nether","session",100),
                new CapabilitySnapshot.Context(LEVEL,PLAYER,MODE,null,MENU,"world","player","minecraft:overworld","other",100),
                new CapabilitySnapshot.Context(LEVEL,PLAYER,MODE,null,MENU,"world","player","minecraft:overworld","session",101)})
            assertEquals("capability_snapshot_context_changed",assertThrows(ClientActionRequest.Rejected.class,
                    ()->CapabilitySnapshot.assemble(c,changed,input[0],input[1],input[2],input[3],input[1])).getMessage());
        JsonObject later=input[1].deepCopy();later.addProperty("status","running");
        assertEquals("capability_snapshot_incoherent",assertThrows(ClientActionRequest.Rejected.class,
                ()->CapabilitySnapshot.assemble(c,c,input[0],input[1],input[2],input[3],later)).getMessage());
    }

    @Test void contradictorySiblingFieldsFailRatherThanBeingCopiedOver() {
        java.util.List<Consumer<JsonObject[]>> changes=java.util.List.of(
                s->s[0].getAsJsonObject("world").addProperty("game_time",101),
                s->s[2].getAsJsonObject("world").addProperty("world_generation","changed"),
                s->s[0].getAsJsonObject("player").addProperty("uuid","changed"),
                s->s[2].getAsJsonObject("player").addProperty("x",1),
                s->s[0].getAsJsonObject("client_action").addProperty("action_id","other"),
                s->s[2].getAsJsonObject("capability_guard").addProperty("source_tick",99),
                s->s[2].getAsJsonObject("capability_guard").addProperty("source_nano",123),
                s->s[3].getAsJsonObject("menu").addProperty("state_id",8),
                s->s[3].addProperty("open",true));
        for(var change:changes) {
            var input=siblings(false,false,false);change.accept(input);var before=input[2].deepCopy();
            assertEquals("capability_snapshot_incoherent",assertThrows(ClientActionRequest.Rejected.class,()->bundle(input)).getMessage());
            assertEquals(before,input[2]);
        }
    }

    @Test void globalHttpSizeGuardAndLegacyNullDefaultsRemainUnchanged() throws Exception {
        var body=bundle(siblings(false,false,false));body.getAsJsonObject("state").addProperty("oversized","x".repeat(256*1024));
        var exchange=TerrainCapabilityWireTest.http(body);assertEquals(500,exchange.status);
        assertEquals("response_too_large",exchange.body().get("error").getAsString());
        JsonObject legacy=protocol();legacy.add("state",JsonParser.parseString("{\"unrelated\":null}"));
        assertEquals(new GsonBuilder().disableHtmlEscaping().create().toJson(legacy),BridgeJson.toJson(legacy));
    }

    @Test void actualLedgerArmedStoppingSealedAndTerminalRegistryNullsStayEqualAcrossEverySibling() throws Exception {
        var cases=new JsonArray();
        for(String phase:new String[]{"armed","stopping","sealed"}) {
            var ledger=new MovementBudgetLedger("bundle","session","world","player",LEVEL,PLAYER,0,64,0,1000);
            if(phase.equals("stopping"))for(int i=1;i<=60;i++) {
                ledger.beginTick();ledger.beginMove(true,.5,0,0);ledger.position(i*.5,64,0);ledger.endMove();
            }
            if(phase.equals("sealed")) {
                for(int i=0;i<3;i++)ledger.sample(LEVEL,PLAYER,"session",0,64,0,true,true);
                ledger.seal(2000);
            }
            JsonObject budget=ledger.snapshot();assertEquals(phase,budget.get("status").getAsString());
            var registry=new ActionRegistry();var entry=registry.begin(ClientActionRequest.parse(CapabilityGuardTest.request("select_hotbar")));
            entry.result.add("unknown_metric",JsonNull.INSTANCE);entry.result.add("nested",JsonParser.parseString("{\"unknown\":null}"));
            registry.finishAfterCleanup("succeeded","selected",true);
            JsonObject action=registry.status(null);action.addProperty("action_session","session");action.add("movement_budget",budget);
            var s=siblings(false,false,false);s[1]=action;
            s[0].add("client_action",action.deepCopy());s[2].add("client_action",action.deepCopy());s[2].add("movement_budget",budget.deepCopy());
            var body=bundle(s);var exchange=TerrainCapabilityWireTest.http(body);var parsed=exchange.body();
            JsonObject parsedAction=parsed.getAsJsonObject("action").deepCopy();parsedAction.remove("protocol");parsedAction.remove("schema_version");
            assertEquals(action,parsedAction);assertEquals(parsedAction,parsed.getAsJsonObject("status").get("client_action"));
            assertEquals(parsedAction,parsed.getAsJsonObject("state").get("client_action"));
            assertEquals(budget,parsed.getAsJsonObject("state").get("movement_budget"));
            assertEquals(!phase.equals("sealed"),parsedAction.getAsJsonObject("movement_budget").get("ended_nano").isJsonNull());
            // Standalone endpoint defaults keep their pre-existing omission of ended_nano/result unknowns.
            var legacyAction=JsonParser.parseString(BridgeJson.toJson(action)).getAsJsonObject();
            assertFalse(legacyAction.getAsJsonObject("result").has("unknown_metric"));
            if(!phase.equals("sealed"))assertFalse(legacyAction.getAsJsonObject("movement_budget").has("ended_nano"));
            JsonObject row=new JsonObject();row.addProperty("name",phase);row.addProperty("response_json",exchange.bytes.toString(java.nio.charset.StandardCharsets.UTF_8));cases.add(row);
        }
        Path output=Path.of(System.getProperty("mineclientBridge.projectDir"),"build/validation/capability-meter-bundle-wire.json");
        Files.createDirectories(output.getParent());Files.writeString(output,cases.toString());
    }

    @Test void productionEndpointUsesOneCallbackAndRetainsOriginalDefaultEndpoints() throws Exception {
        String source=Files.readString(Path.of(System.getProperty("mineclientBridge.projectDir"),"src/main/java/io/github/campione01/mineclientbridge/BridgeServer.java"));
        String endpoint=source.substring(source.indexOf("private static void handleCapabilitySnapshot("),source.indexOf("private static CapabilitySnapshot.Context capabilityContext("));
        assertEquals(1,endpoint.split("callOnMinecraftThread\\(",-1).length-1);
        assertTrue(endpoint.contains("requireControlAccess(exchange,\"/control/capability-snapshot\",\"GET\")"));
        assertTrue(endpoint.contains("queryDouble(exchange,\"coordination_step\",0,0,1)==1"));
        assertTrue(source.contains("return createStateSnapshot(radius,timing,coordination,null)"));
        assertTrue(source.contains("return createControlStatus(null)"));
        String capture=source.substring(source.indexOf("private static EndpointResult createCapabilitySnapshot("),source.indexOf("private static void handleControlTerrain("));
        assertEquals(1,capture.split("ClientActions.status\\(null\\)",-1).length-1);
        assertTrue(capture.contains("ClientActions.statusWithoutObservation()"));
        assertFalse(capture.contains("System.nanoTime()"));
    }
}

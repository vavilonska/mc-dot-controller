package io.github.campione01.mineclientbridge;

import static org.junit.jupiter.api.Assertions.*;
import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonNull;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class BridgeJsonTest {
    private static final Gson LEGACY = new GsonBuilder().disableHtmlEscaping().create();
    private static final String REQUEST = "00000000-0000-0000-0000-000000000001";
    private JsonObject envelope(JsonObject guard) {
        JsonObject root = new JsonObject();root.addProperty("protocol","mineclient-bridge");
        root.addProperty("schema_version",2);root.addProperty("ok",true);root.add("guarded_movement",guard);return root;
    }
    private JsonObject guard(String owner,String action) {
        JsonObject guard = new JsonObject();guard.addProperty("schema_version",1);
        guard.addProperty("owner_request_id",owner);guard.addProperty("owner_action",action);
        guard.addProperty("sampled",false);guard.addProperty("released",true);return guard;
    }
    private JsonObject roundTrip(JsonObject root) throws Exception { return JsonParser.parseString(BridgeJson.toJson(root)).getAsJsonObject(); }

    @Test void biomeRegistryIdOrExplicitUnavailableNullSurvivesWireEncoding() throws Exception {
        JsonObject root = new JsonObject();
        JsonObject world = new JsonObject();
        world.addProperty("dimension", "minecraft:overworld");
        world.addProperty("biome_id", "minecraft:cherry_grove");
        world.addProperty("legacy_null", (String) null);
        root.add("world", world);
        JsonObject decoded = roundTrip(root).getAsJsonObject("world");
        assertEquals("minecraft:cherry_grove", decoded.get("biome_id").getAsString());
        assertFalse(decoded.has("legacy_null"));
        world.addProperty("biome_id", (String) null);
        decoded = roundTrip(root).getAsJsonObject("world");
        assertTrue(decoded.has("biome_id"));
        assertTrue(decoded.get("biome_id").isJsonNull());
        assertFalse(decoded.has("legacy_null"));
        world.remove("biome_id");
        assertFalse(roundTrip(root).getAsJsonObject("world").has("biome_id"));
    }

    @Test void biomeComesFromCurrentPlayerRegistryKeyNotTerrainInference() throws Exception {
        Path project = Path.of(System.getProperty("mineclientBridge.projectDir"));
        String source = Files.readString(project.resolve("src/main/java/io/github/campione01/mineclientbridge/BridgeServer.java"));
        String state = source.substring(source.indexOf("private static EndpointResult createStateSnapshot("),
                source.indexOf("private static JsonObject crosshairSnapshot("));
        assertTrue(state.contains("world.addProperty(\"biome_id\", mc.level.getBiome(mc.player.blockPosition())"));
        assertTrue(state.contains(".unwrapKey().map(key -> key.location().toString()).orElse(null)"));
    }

    @Test void reproducesLegacyWireOmissionRatherThanTestingOnlyJsonTree() {
        JsonObject root=envelope(guard(null,null));assertTrue(root.getAsJsonObject("guarded_movement").has("owner_request_id"));
        JsonObject decoded=JsonParser.parseString(LEGACY.toJson(root)).getAsJsonObject().getAsJsonObject("guarded_movement");
        assertFalse(decoded.has("owner_request_id"));assertFalse(decoded.has("owner_action"));
    }
    @Test void idleOwnershipSurvivesActualResponseSerialization() throws Exception {
        JsonObject decoded=roundTrip(envelope(guard(null,null))).getAsJsonObject("guarded_movement");
        assertTrue(decoded.has("owner_request_id"));assertTrue(decoded.get("owner_request_id").isJsonNull());
        assertTrue(decoded.has("owner_action"));assertTrue(decoded.get("owner_action").isJsonNull());
        assertFalse(decoded.get("sampled").getAsBoolean());assertTrue(decoded.get("released").getAsBoolean());
    }
    @Test void unavailableStateObservationIsExplicitNull() throws Exception {
        JsonObject owned=guard(REQUEST,"yaw");owned.addProperty("observation_id",(String)null);
        JsonObject decoded=roundTrip(envelope(owned)).getAsJsonObject("guarded_movement");
        assertEquals(REQUEST,decoded.get("owner_request_id").getAsString());assertEquals("yaw",decoded.get("owner_action").getAsString());
        assertTrue(decoded.has("observation_id"));assertTrue(decoded.get("observation_id").isJsonNull());
    }
    @Test void nonNullMovementTurnAndObservationValuesRemainExact() throws Exception {
        for(String action:new String[]{"forward_sample","yaw"}) {
            JsonObject owned=guard(REQUEST,action);owned.addProperty("observation_id",REQUEST);
            assertEquals(envelope(owned),roundTrip(envelope(owned)));
        }
    }
    @Test void missingGuardFactsAreNotInventedOrConvertedToIdle() throws Exception {
        JsonObject missing=new JsonObject();missing.addProperty("schema_version",1);
        JsonObject decoded=roundTrip(envelope(missing)).getAsJsonObject("guarded_movement");
        assertFalse(decoded.has("owner_request_id"));assertFalse(decoded.has("owner_action"));assertFalse(decoded.has("observation_id"));
        JsonObject absent=new JsonObject();absent.addProperty("ok",true);assertEquals(LEGACY.toJson(absent),BridgeJson.toJson(absent));
        JsonObject nullGuard=new JsonObject();nullGuard.add("guarded_movement",JsonNull.INSTANCE);
        assertEquals(LEGACY.toJson(nullGuard),BridgeJson.toJson(nullGuard));
    }
    @Test void nullPreservationDoesNotLeakToLegacySiblingsNestedObjectsOrConfigurationShape() throws Exception {
        JsonObject root=new JsonObject();root.addProperty("nullable_before",(String)null);
        root.add("guarded_movement",guard(null,null));root.addProperty("nullable_after",(String)null);
        JsonObject nested=new JsonObject();nested.addProperty("nullable_child",(String)null);nested.addProperty("enabled",true);
        root.add("player",nested);root.add("config",nested.deepCopy());
        JsonObject decoded=roundTrip(root);assertFalse(decoded.has("nullable_before"));assertFalse(decoded.has("nullable_after"));
        assertFalse(decoded.getAsJsonObject("player").has("nullable_child"));assertFalse(decoded.getAsJsonObject("config").has("nullable_child"));
        assertTrue(decoded.getAsJsonObject("guarded_movement").get("owner_request_id").isJsonNull());
    }
    @Test void noGuardResponseMatchesPreviousEncodingIncludingEscapingAndArrayNulls() throws Exception {
        JsonObject root=new JsonObject();root.addProperty("html","<&>='\"\\\n\t 星乃");root.addProperty("nullable",(String)null);
        root.addProperty("fraction",.5);root.addProperty("tick",9007199254740991L);root.addProperty("ok",false);
        JsonArray array=new JsonArray();array.add(JsonNull.INSTANCE);array.add("text");JsonObject nested=new JsonObject();nested.add("missing",JsonNull.INSTANCE);array.add(nested);root.add("array",array);
        assertEquals(LEGACY.toJson(root),BridgeJson.toJson(root));assertEquals("{}",BridgeJson.toJson(new JsonObject()));
    }
    @Test void encodingDoesNotMutateSourceAndReleasesWriterSettingsBetweenResponses() throws Exception {
        JsonObject root=envelope(guard(null,null));JsonObject before=root.deepCopy();String first=BridgeJson.toJson(root);
        assertEquals(before,root);assertEquals(first,BridgeJson.toJson(root));
        JsonObject ordinary=new JsonObject();ordinary.add("missing",JsonNull.INSTANCE);assertEquals("{}",BridgeJson.toJson(ordinary));
        assertEquals(first,BridgeJson.toJson(root));
    }
    @Test void actualLeaseStatusesSurviveWireRoundTripWithoutGameInitialization() throws Exception {
        GuardedMovement leases=new GuardedMovement(()->0);leases.openAdmission();
        assertStatus(leases.status(),null,null);
        String world=UUID.randomUUID().toString(),player=UUID.randomUUID().toString();
        var state=new GuardedMovement.State(world,player,1,.5,64,.5,0,true,true,true,true,true);
        String observation=leases.observe(state);
        var request=new GuardedMovement.Request(leases.session(),REQUEST,observation,world,player,1,.5,64,.5,0,100,100);
        var ticket=leases.submit(request,0,leases.session());assertStatus(leases.status(),REQUEST,"forward_sample");
        ticket.cancel("test_complete");assertStatus(leases.status(),null,null);
    }
    private void assertStatus(GuardedMovement.Status status,String owner,String action) throws Exception {
        JsonObject serialized=guard(status.ownerRequestId(),status.ownerAction());serialized.addProperty("sampled",status.sampled());serialized.addProperty("released",status.released());
        JsonObject decoded=roundTrip(envelope(serialized)).getAsJsonObject("guarded_movement");
        if(owner==null){assertTrue(decoded.get("owner_request_id").isJsonNull());assertTrue(decoded.get("owner_action").isJsonNull());}
        else{assertEquals(owner,decoded.get("owner_request_id").getAsString());assertEquals(action,decoded.get("owner_action").getAsString());}
    }
    @Test void everyHttpJsonResponseAndOversizeFallbackUseNarrowCodec() throws Exception {
        Path root=Path.of(System.getProperty("mineclientBridge.projectDir"));
        String source=Files.readString(root.resolve("src/main/java/io/github/campione01/mineclientbridge/BridgeServer.java"));
        int start=source.indexOf("private static void respondJson(");int end=source.indexOf("private static void respondBytes(",start);
        String responder=source.substring(start,end);assertTrue(responder.contains("BridgeJson.toJson(body)"));
        assertTrue(responder.contains("BridgeJson.toJson(error(\"response_too_large\""));assertFalse(source.contains("GSON.toJson"));
        String config=Files.readString(root.resolve("src/main/java/io/github/campione01/mineclientbridge/BridgeConfigStore.java"));
        assertFalse(config.contains("BridgeJson"));assertFalse(config.contains("serializeNulls"));
    }
}

package io.github.campione01.mineclientbridge;

import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.TypeAdapter;
import com.google.gson.stream.JsonWriter;
import java.io.IOException;
import java.io.StringWriter;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** HTTP encoding: one explicit nullable-contract table; all other nulls retain legacy omission. */
final class BridgeJson {
    private static final TypeAdapter<JsonElement> ELEMENTS = new GsonBuilder()
            .disableHtmlEscaping().create().getAdapter(JsonElement.class);
    private static final List<String> ENTITY_ARRAY_PATH = List.of("nearby", "entities");
    private static final List<String> ENTITY_ROW_PATH = List.of("nearby", "entities", "[]");
    private static final List<String> NATIVE_LIVING_PATH = List.of("nearby", "entities", "[]", "native_living");
    private static final List<String> NATIVE_BEE_PATH = List.of("nearby", "entities", "[]", "native_living", "bee");
    // Keys name exact containing objects. Empty sets are traversal-only parents.
    // [] is an array-element marker, never an object-field wildcard.
    // Iterating actual members never manufactures a missing contract field.
    private static final Map<List<String>,Set<String>> NULLABLE_FIELDS = Map.ofEntries(
            Map.entry(List.of(), Set.of("action_id")),
            Map.entry(List.of("world"), Set.of("biome_id")),
            Map.entry(List.of("external_navigation_status"), Set.of()),
            Map.entry(List.of("managed_navigation_status"), Set.of()),
            Map.entry(List.of("world_selection"), Set.of("reason", "data")),
            Map.entry(List.of("world_selection", "data"), Set.of("selected_list_index")),
            Map.entry(List.of("result"), Set.of()),
            Map.entry(List.of("result","combat"), Set.of()),
            Map.entry(List.of("result","combat","encounter"), Set.of("outcome_scope")),
            Map.entry(List.of("result","encounter_terminal_pause"), Set.of(
                    "pause_screen_installed","already_pause_screen","client_paused_observed")),
            Map.entry(List.of("result","combat","encounter","callback_interruption"), Set.of(
                    "last_tick_nanos","snapshot_captured_nanos","previous_callback_nanos",
                    "previous_callback_phase","callback_interval_nanos")),
            Map.entry(List.of("nearby"), Set.of()),
            Map.entry(ENTITY_ROW_PATH, Set.of()),
            Map.entry(NATIVE_LIVING_PATH, Set.of("current_target")),
            Map.entry(NATIVE_BEE_PATH, Set.of("persistent_anger_target_uuid")));
    // Existing whole-object contracts keep explicit nulls at all nested depths.
    private static final Set<String> ROOT_NULLABLE_OBJECTS = Set.of("guarded_movement","client_action");
    private static final Set<String> PAUSE_NULLABLE_FIELDS = Set.of("client_action","input_release_confirmed");
    private static final Set<String> CAPABILITY_SIBLINGS = Set.of("status","action","state","screen");

    static String toJson(JsonObject body) throws IOException {
        StringWriter buffer = new StringWriter();
        try (JsonWriter writer = new JsonWriter(buffer)) {
            writer.setLenient(true);
            writer.setHtmlSafe(false);
            writer.setSerializeNulls(false);
            writeObject(writer, body, List.of(), pauseEnvelope(body));
        }
        return buffer.toString();
    }

    private static boolean managedNavigationStatus(List<String> path,JsonObject object) {
        if(!path.isEmpty()&&!path.equals(List.of("managed_navigation_status")))return false;
        JsonElement version=object.get("managed_navigation_schema_version");
        return version!=null&&version.isJsonPrimitive()&&version.getAsJsonPrimitive().isNumber()
            &&version.getAsString().equals("1");
    }

    private static boolean externalNavigationStatus(List<String> path,JsonObject object) {
        if(!path.isEmpty()&&!path.equals(List.of("external_navigation_status")))return false;
        JsonElement version=object.get("external_navigation_schema_version");
        return version!=null&&version.isJsonPrimitive()&&version.getAsJsonPrimitive().isNumber()
            &&version.getAsString().equals("1");
    }

    private static boolean pauseEnvelope(JsonObject body) {
        return body.has("pause_schema_version") && body.get("pause_schema_version").isJsonPrimitive()
                && body.getAsJsonPrimitive("pause_schema_version").isNumber()
                && body.get("pause_schema_version").getAsDouble() == 1
                && body.has("action") && body.get("action").isJsonPrimitive()
                && body.getAsJsonPrimitive("action").isString()
                && body.get("action").getAsString().equals("ensure_paused");
    }

    private static void writeObject(JsonWriter writer, JsonObject object, List<String> path,
                                    boolean pauseEnvelope) throws IOException {
        writeObject(writer,object,path,pauseEnvelope,false);
    }

    private static void writeObject(JsonWriter writer, JsonObject object, List<String> path,
                                    boolean pauseEnvelope, boolean capabilityStateRoot) throws IOException {
        writer.beginObject();
        Set<String> nullable = NULLABLE_FIELDS.getOrDefault(path, Set.of());
        boolean nativeLivingContract = path.equals(NATIVE_LIVING_PATH) || path.equals(NATIVE_BEE_PATH);
        for (Map.Entry<String,JsonElement> field : object.entrySet()) {
            String key = field.getKey();
            JsonElement value = field.getValue();
            boolean wholeObject = path.isEmpty() && (ROOT_NULLABLE_OBJECTS.contains(key)
                    || capabilityStateRoot && key.equals("movement_budget")) && value.isJsonObject();
            // This new profile has an explicit nullable target in every complete entity row.
            // Existing profiles and unrelated result subtrees retain their exact legacy encoding.
            boolean observedMovementWitness = path.equals(List.of("result")) && (key.equals("scoped_native_preflight")||key.equals("route_threat_stop"))
                    && value.isJsonObject() && value.getAsJsonObject().has("profile")
                    && value.getAsJsonObject().get("profile").isJsonPrimitive()
                    && value.getAsJsonObject().get("profile").getAsJsonPrimitive().isString()
                    && (value.getAsJsonObject().get("profile").getAsString().equals(ScopedFlatMovement.PROFILE)
                        || value.getAsJsonObject().get("profile").getAsString().equals(ScopedStepDownMovement.PROFILE)
                        || value.getAsJsonObject().get("profile").getAsString().equals("movement-local-segment-observed-v1")
                        || value.getAsJsonObject().get("profile").getAsString().equals("movement-local-segment-spatial-threat-v1")
                        || value.getAsJsonObject().get("profile").getAsString().equals("movement-local-segment-spatial-stop-v1")
                        || value.getAsJsonObject().get("profile").getAsString().equals("movement-local-segment-spatial-stop-v2")
                        || value.getAsJsonObject().get("profile").getAsString().equals(ScopedPlacement.PROFILE)
                        || value.getAsJsonObject().get("profile").getAsString().equals(ScopedMining.PROFILE)
                        || value.getAsJsonObject().get("profile").getAsString().equals(ScopedCollectTarget.PROFILE));
            boolean terrainDiagnostic=path.equals(List.of("result"))&&key.equals("route_terrain_rejection")
                    &&value.isJsonObject()&&value.getAsJsonObject().has("profile")
                    &&value.getAsJsonObject().get("profile").isJsonPrimitive()
                    &&value.getAsJsonObject().getAsJsonPrimitive("profile").isString()
                    &&(value.getAsJsonObject().get("profile").getAsString().equals("movement-local-segment-spatial-stop-v1")
                        ||value.getAsJsonObject().get("profile").getAsString().equals("movement-local-segment-spatial-stop-v2"));
            boolean beeDiagnostic=(path.isEmpty()||path.equals(List.of("result")))&&key.equals("route_entity_rejection")&&routeBeeDiagnostic(value);
            boolean threatDiagnostic=path.isEmpty()&&key.equals("route_threat_rejection")&&routeThreatDiagnostic(value);
            writer.name(key);
            writer.setSerializeNulls(wholeObject || observedMovementWitness || terrainDiagnostic || beeDiagnostic || threatDiagnostic || nullable.contains(key) && (!nativeLivingContract || value.isJsonNull())
                    || path.isEmpty() && pauseEnvelope && PAUSE_NULLABLE_FIELDS.contains(key)
                    || (externalNavigationStatus(path,object)||managedNavigationStatus(path,object)) && key.equals("cancel_accepted")
                    || path.isEmpty() && readonlyClock(object) && Set.of("observation_clock","observation_clock_unavailable").contains(key));
            List<String> child = new ArrayList<>(path);child.add(key);
            if (path.isEmpty() && capabilityEnvelope(object) && CAPABILITY_SIBLINGS.contains(key) && value.isJsonObject()) {
                // These are complete existing endpoint bodies, each with its own exact nullable paths.
                if(key.equals("action")) {
                    // The same native action also appears under client_action, whose complete
                    // receipt contract includes nullable result/budget facts at every depth.
                    writer.setSerializeNulls(true);ELEMENTS.write(writer,value);
                } else writeObject(writer,value.getAsJsonObject(),List.of(),pauseEnvelope(value.getAsJsonObject()),key.equals("state"));
            } else if (value.isJsonArray() && child.equals(ENTITY_ARRAY_PATH)) {
                writeEntityArray(writer, value.getAsJsonArray(), pauseEnvelope);
            } else if (value.isJsonObject() && !wholeObject) {
                if (NULLABLE_FIELDS.containsKey(child)) writeObject(writer,value.getAsJsonObject(),child,pauseEnvelope);
                else ELEMENTS.write(writer,value);
            } else ELEMENTS.write(writer,value);
            writer.setSerializeNulls(false);
        }
        writer.endObject();
    }

    private static boolean routeThreatDiagnostic(JsonElement value) {
        if(!value.isJsonObject())return false;
        JsonObject j=value.getAsJsonObject();JsonElement version=j.get("schema_version"),profile=j.get("profile"),policy=j.get("policy");
        return version!=null&&version.isJsonPrimitive()&&version.getAsJsonPrimitive().isNumber()&&version.getAsDouble()==1
            &&profile!=null&&profile.isJsonPrimitive()&&profile.getAsJsonPrimitive().isString()
            &&profile.getAsString().equals("movement-local-segment-spatial-threat-v1")
            &&policy!=null&&policy.isJsonPrimitive()&&policy.getAsJsonPrimitive().isString()
            &&policy.getAsString().equals("route-spatial-threat-v1");
    }

    private static boolean routeBeeDiagnostic(JsonElement value) {
        if(!value.isJsonObject())return false;
        JsonObject j=value.getAsJsonObject();JsonElement version=j.get("schema_version"),profile=j.get("profile"),policy=j.get("policy"),type=j.get("entity_type");
        return version!=null&&version.isJsonPrimitive()&&version.getAsJsonPrimitive().isNumber()&&version.getAsDouble()==2
                &&profile!=null&&profile.isJsonPrimitive()&&profile.getAsJsonPrimitive().isString()&&profile.getAsString().equals("movement-local-segment-spatial-stop-v2")
                &&policy!=null&&policy.isJsonPrimitive()&&policy.getAsJsonPrimitive().isString()&&policy.getAsString().equals("route-spatial-stop-v2")
                &&type!=null&&type.isJsonPrimitive()&&type.getAsJsonPrimitive().isString()&&type.getAsString().equals("minecraft:bee")
                &&j.has("native_bee_diagnostic")&&j.get("native_bee_diagnostic").isJsonObject();
    }

    private static boolean capabilityEnvelope(JsonObject object) {
        JsonElement version=object.get("capability_snapshot_schema_version");
        return version!=null && version.isJsonPrimitive() && version.getAsJsonPrimitive().isNumber()
                && (version.getAsDouble()==1 || version.getAsDouble()==2 && readonlyClock(object));
    }

    private static boolean readonlyClock(JsonObject object) {
        JsonElement profile=object.get("observation_clock_profile");
        return profile!=null && profile.isJsonPrimitive() && profile.getAsJsonPrimitive().isString()
                && profile.getAsString().equals("read_only");
    }

    private static void writeEntityArray(JsonWriter writer, JsonArray entities, boolean pauseEnvelope) throws IOException {
        writer.beginArray();
        for (JsonElement entity : entities) {
            if (entity.isJsonObject()) writeObject(writer, entity.getAsJsonObject(), ENTITY_ROW_PATH, pauseEnvelope);
            else ELEMENTS.write(writer, entity);
        }
        writer.endArray();
    }

    private BridgeJson() { }
}

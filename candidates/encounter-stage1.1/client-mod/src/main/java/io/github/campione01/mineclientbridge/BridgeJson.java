package io.github.campione01.mineclientbridge;

import com.google.gson.GsonBuilder;
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
    // Keys name exact containing objects. Empty sets are traversal-only parents.
    // Iterating actual members never manufactures a missing contract field.
    private static final Map<List<String>,Set<String>> NULLABLE_FIELDS = Map.of(
            List.of(), Set.of("action_id"),
            List.of("world"), Set.of("biome_id"),
            List.of("result"), Set.of(),
            List.of("result","combat"), Set.of(),
            List.of("result","combat","encounter"), Set.of("outcome_scope"),
            List.of("result","encounter_terminal_pause"), Set.of(
                    "pause_screen_installed","already_pause_screen","client_paused_observed"),
            List.of("result","combat","encounter","callback_interruption"), Set.of(
                    "last_tick_nanos","snapshot_captured_nanos","previous_callback_nanos",
                    "previous_callback_phase","callback_interval_nanos"));
    // Existing whole-object contracts keep explicit nulls at all nested depths.
    private static final Set<String> ROOT_NULLABLE_OBJECTS = Set.of("guarded_movement","client_action");
    private static final Set<String> PAUSE_NULLABLE_FIELDS = Set.of("client_action","input_release_confirmed");

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
        writer.beginObject();
        Set<String> nullable = NULLABLE_FIELDS.getOrDefault(path, Set.of());
        for (Map.Entry<String,JsonElement> field : object.entrySet()) {
            String key = field.getKey();
            JsonElement value = field.getValue();
            boolean wholeObject = path.isEmpty() && ROOT_NULLABLE_OBJECTS.contains(key) && value.isJsonObject();
            writer.name(key);
            writer.setSerializeNulls(wholeObject || nullable.contains(key)
                    || path.isEmpty() && pauseEnvelope && PAUSE_NULLABLE_FIELDS.contains(key));
            if (value.isJsonObject() && !wholeObject) {
                List<String> child = new ArrayList<>(path);child.add(key);
                if (NULLABLE_FIELDS.containsKey(child)) writeObject(writer,value.getAsJsonObject(),child,pauseEnvelope);
                else ELEMENTS.write(writer,value);
            } else ELEMENTS.write(writer,value);
            writer.setSerializeNulls(false);
        }
        writer.endObject();
    }

    private BridgeJson() { }
}

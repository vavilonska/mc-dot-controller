package io.github.campione01.mineclientbridge;

import com.google.gson.GsonBuilder;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.TypeAdapter;
import com.google.gson.stream.JsonWriter;
import java.io.IOException;
import java.io.StringWriter;
import java.util.Map;

/** HTTP response encoding: preserve explicit guard nulls without changing legacy null omission. */
final class BridgeJson {
    private static final TypeAdapter<JsonElement> ELEMENTS = new GsonBuilder()
            .disableHtmlEscaping().create().getAdapter(JsonElement.class);

    static String toJson(JsonObject body) throws IOException {
        StringWriter buffer = new StringWriter();
        try (JsonWriter writer = new JsonWriter(buffer)) {
            // Match the previous Gson.toJson(JsonElement) writer settings.
            writer.setLenient(true);
            writer.setHtmlSafe(false);
            writer.setSerializeNulls(false);
            writer.beginObject();
            for (Map.Entry<String, JsonElement> entry : body.entrySet()) {
                writer.name(entry.getKey());
                // Ownership and an unavailable observation are explicitly nullable protocol facts.
                // An absent field must remain distinguishable from an explicit idle/unavailable null.
                writer.setSerializeNulls(((entry.getKey().equals("guarded_movement")
                        || entry.getKey().equals("client_action")) && entry.getValue().isJsonObject())
                        || entry.getKey().equals("action_id"));
                ELEMENTS.write(writer, entry.getValue());
                writer.setSerializeNulls(false);
            }
            writer.endObject();
        }
        return buffer.toString();
    }

    private BridgeJson() { }
}

package io.github.campione01.mineclientbridge;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.function.Consumer;

/** Actual production request parser + HTTP codec; supplied snapshots are synthetic. */
public final class InventoryRecoveryWireChecks {
    static int rejected=0;
    static void reject(JsonObject source, Consumer<JsonObject> mutation) {
        JsonObject value=source.deepCopy();mutation.accept(value);
        try {ClientActionRequest.parse(value);throw new AssertionError("malformed request accepted: "+value);}
        catch(ClientActionRequest.Rejected expected){rejected++;}
    }
    public static void main(String[] args) throws Exception {
        Path input=Path.of(args[0]), output=Path.of(args[1]);Files.createDirectories(output);
        int accepted=0;
        try(var files=Files.list(input)) {
            for(Path file:files.sorted().toList()) {
                JsonObject bundle=JsonParser.parseString(Files.readString(file)).getAsJsonObject();
                JsonObject intent=bundle.getAsJsonObject("intent");
                ClientActionRequest parsed=ClientActionRequest.parse(intent);
                if(!parsed.original().equals(intent))throw new AssertionError("parser changed request");
                String wire=BridgeJson.toJson(bundle);
                if(!JsonParser.parseString(wire).equals(bundle))throw new AssertionError("codec changed recovery contract");
                Files.writeString(output.resolve(file.getFileName()),wire);accepted++;
                for(String key: new String[]{"schema_version","phase","context","selected_slot","inventory","slots"})
                    reject(intent,b->b.getAsJsonObject("inventory_recovery").remove(key));
                for(String key:new String[]{"schema_version","menu_instance","screen_instance","screen_open"})
                    reject(intent,b->b.getAsJsonObject("inventory_recovery").getAsJsonObject("context").remove(key));
                reject(intent,b->b.getAsJsonObject("inventory_recovery").addProperty("schema_version",true));
                reject(intent,b->b.getAsJsonObject("inventory_recovery").addProperty("selected_slot",true));
                reject(intent,b->b.getAsJsonObject("inventory_recovery").addProperty("phase","drop"));
                reject(intent,b->b.getAsJsonObject("inventory_recovery").addProperty("unexpected",1));
                reject(intent,b->b.getAsJsonObject("inventory_recovery").getAsJsonArray("inventory").remove(40));
                reject(intent,b->b.getAsJsonObject("inventory_recovery").getAsJsonArray("inventory").get(0).getAsJsonObject().addProperty("slot",1));
                reject(intent,b->b.getAsJsonObject("inventory_recovery").getAsJsonArray("slots").get(0).getAsJsonObject().remove("active"));
                reject(intent,b->b.getAsJsonObject("inventory_recovery").getAsJsonArray("slots").get(0).getAsJsonObject().addProperty("menu_index",1));
                reject(intent,b->b.addProperty("slot",-999));
                reject(intent,b->b.addProperty("button",1));
                reject(intent,b->b.addProperty("click_type","quick_move"));
                reject(intent,b->b.remove("capability_guard"));
                JsonObject legacy=intent.deepCopy();legacy.remove("inventory_recovery");
                ClientActionRequest.parse(legacy); // Existing guarded vanilla clicks remain compatible.
            }
        }
        System.out.println("accepted="+accepted+" malformed_rejected="+rejected+" legacy_compatible="+accepted);
    }
}

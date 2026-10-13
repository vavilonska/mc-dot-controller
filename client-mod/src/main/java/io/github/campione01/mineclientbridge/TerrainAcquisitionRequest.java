package io.github.campione01.mineclientbridge;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.google.gson.stream.JsonReader;
import com.google.gson.stream.JsonToken;
import java.io.IOException;
import java.io.StringReader;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;
import java.util.Set;

/** The finite opt-in acquisition API. Owner strings correlate existing bearer authority. */
final class TerrainAcquisitionRequest {
    static final String VERSION = "native-full729-v1";
    static final String CLOCK_VERSION = "native-full729-client-clock-v1";
    static final String ROOT = "/control/terrain-acquisition/v1/";
    record Owner(String jobId, String ownerId) { }
    record Prepare(Owner owner, Long defenseEpoch,int schema) {
        Prepare(Owner owner,Long defenseEpoch){this(owner,defenseEpoch,1);}
        boolean clock(){return schema==2;}
    }
    record Activate(Owner owner, String aHash,int schema) {Activate(Owner owner,String hash){this(owner,hash,1);}}
    record Cancel(Owner owner, String cancelId,int schema) {Cancel(Owner owner,String id){this(owner,id,1);}}
    record Fetch(Owner owner, String part, String hash) { }

    /** All five lifecycle request shapes are flat; duplicate JSON keys cannot be hidden by a map. */
    static JsonObject parseBody(String raw) {
        try(JsonReader reader=new JsonReader(new StringReader(raw))) {
            reader.setLenient(false);reader.beginObject();JsonObject body=new JsonObject();
            while(reader.hasNext()) {
                String name=reader.nextName();require(!body.has(name),"acquisition_duplicate_field");
                switch(reader.peek()) {
                    case STRING -> body.addProperty(name,reader.nextString());
                    case NUMBER -> body.add(name,JsonParser.parseString(reader.nextString()));
                    case BOOLEAN -> body.addProperty(name,reader.nextBoolean());
                    case NULL -> {reader.nextNull();body.add(name,com.google.gson.JsonNull.INSTANCE);}
                    default -> throw failure(400,"acquisition_invalid_type");
                }
            }
            reader.endObject();require(reader.peek()==JsonToken.END_DOCUMENT,"acquisition_invalid_json");return body;
        } catch(IOException | IllegalStateException malformed) {throw failure(400,"acquisition_invalid_json");}
    }

    static Prepare prepare(JsonObject body) {
        int schema=schema(body);
        keys(body, schema==2?Set.of("acquisition_schema_version","job_id","owner_id","defense_epoch","radius","vertical","entity_radius","observation_clock"):
                Set.of("acquisition_schema_version","job_id","owner_id","defense_epoch","radius","vertical","entity_radius"));
        if(schema==2)require(string(body.get("observation_clock")).equals(ObservationClientClock.CONTRACT),"acquisition_clock_contract");
        require(integer(body.get("radius")) == 4 && integer(body.get("vertical")) == 4
                && integer(body.get("entity_radius")) == 48, "acquisition_fixed_bounds");
        JsonElement epoch = body.get("defense_epoch");
        Long defense = epoch.isJsonNull() ? null : integer(epoch);
        return new Prepare(owner(body), defense,schema);
    }
    static Activate activate(JsonObject body) {
        keys(body, Set.of("acquisition_schema_version","job_id","owner_id","a_sha256")); schema(body);
        return new Activate(owner(body), hash(body.get("a_sha256")),schema(body));
    }
    static Cancel cancel(JsonObject body) {
        keys(body, Set.of("acquisition_schema_version","job_id","owner_id","cancel_id")); schema(body);
        Owner owner=owner(body); String cancel=id(body.get("cancel_id"));
        require(cancel.equals(owner.jobId()), "acquisition_cancel_identity"); return new Cancel(owner,cancel,schema(body));
    }
    static Owner status(String query) {
        Map<String,String> values=query(query, Set.of("job_id","owner_id"));
        return new Owner(id(values.get("job_id")),id(values.get("owner_id")));
    }
    static Fetch fetch(String query) {
        Map<String,String> values=query(query, Set.of("job_id","owner_id","part","sha256"));
        String part=values.get("part"); require(Set.of("a","p0","p1","p2","p3","c").contains(part),"acquisition_invalid_part");
        String hash=values.get("sha256"); require(hash.matches("[0-9a-f]{64}"),"acquisition_invalid_hash");
        return new Fetch(new Owner(id(values.get("job_id")),id(values.get("owner_id"))),part,hash);
    }
    private static Map<String,String> query(String raw, Set<String> keys) {
        require(raw!=null && raw.length()<=512,"acquisition_invalid_query");
        Map<String,String> result=new HashMap<>();
        try {
            for(String part:raw.split("&",-1)) {
                String[] pair=part.split("=",2); require(pair.length==2,"acquisition_invalid_query");
                String key=URLDecoder.decode(pair[0],StandardCharsets.UTF_8);
                String value=URLDecoder.decode(pair[1],StandardCharsets.UTF_8);
                require(keys.contains(key) && result.putIfAbsent(key,value)==null,"acquisition_invalid_query");
            }
        } catch(IllegalArgumentException malformed) { throw failure(400,"acquisition_invalid_query"); }
        require(result.keySet().equals(keys),"acquisition_invalid_query"); return result;
    }
    private static Owner owner(JsonObject body) { return new Owner(id(body.get("job_id")),id(body.get("owner_id"))); }
    private static String id(JsonElement value) { return id(string(value)); }
    private static String id(String value) { require(value!=null && value.matches("[A-Za-z0-9_-]{1,80}"),"acquisition_invalid_id"); return value; }
    private static String hash(JsonElement value) { String text=string(value);require(text.matches("[0-9a-f]{64}"),"acquisition_invalid_hash");return text; }
    private static String string(JsonElement value) {
        require(value!=null && value.isJsonPrimitive() && value.getAsJsonPrimitive().isString(),"acquisition_invalid_type");return value.getAsString();
    }
    private static long integer(JsonElement value) {
        require(value!=null && value.isJsonPrimitive() && value.getAsJsonPrimitive().isNumber()
                && value.getAsString().matches("0|[1-9][0-9]{0,15}"),"acquisition_invalid_integer");
        long result=Long.parseLong(value.getAsString());require(result<=9_007_199_254_740_991L,"acquisition_invalid_integer");return result;
    }
    private static int schema(JsonObject body) {long value=integer(body.get("acquisition_schema_version"));require(value==1 || value==2,"acquisition_unsupported_schema");return (int)value;}
    private static void keys(JsonObject body,Set<String> keys) { require(body!=null && body.keySet().equals(keys),"acquisition_invalid_fields"); }
    private static void require(boolean value,String code) { if(!value)throw failure(400,code); }
    static TerrainScan.Failure failure(int status,String code) { return new TerrainScan.Failure(status,code); }
    private TerrainAcquisitionRequest() { }
}

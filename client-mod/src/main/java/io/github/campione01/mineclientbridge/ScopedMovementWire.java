package io.github.campione01.mineclientbridge;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonObject;
import java.nio.charset.StandardCharsets;

/** Pure representation of an already coherent observed-movement snapshot. No capture or action authority. */
final class ScopedMovementWire {
    static final String MARKER="scoped_movement_witness_encoding", ENCODING="single-authority-v1";
    static final String WITNESS="scoped_native_preflight", REFERENCE="scoped_native_preflight_ref";
    static final String TARGET="/action/result/scoped_native_preflight";
    private static final Gson FULL=new GsonBuilder().serializeNulls().disableHtmlEscaping().create();
    private static final String[] BINDINGS={"profile","action_id","action_session","owner_id","owner_generation",
        "job_id","defense_epoch","submitted_intent_sha256","command_sha256","source_tick","source_nano","admitted_nano"};

    /** Called only after CapabilitySnapshot's original full sibling coherence checks. */
    static JsonObject project(JsonObject coherent) {
        JsonObject action=coherent.getAsJsonObject("action");
        JsonObject result=action==null || !action.has("result") || !action.get("result").isJsonObject()
                ?null:action.getAsJsonObject("result");
        JsonObject witness=result==null || !result.has(WITNESS) || !result.get(WITNESS).isJsonObject()
                ?null:result.getAsJsonObject(WITNESS);
        if(witness==null || !witness.has("profile") || !witness.get("profile").isJsonPrimitive()
                || !witness.getAsJsonPrimitive("profile").isString()
                || !(witness.get("profile").getAsString().equals(ScopedFlatMovement.PROFILE)
                    || witness.get("profile").getAsString().equals(ScopedPlacement.PROFILE)
                    || witness.get("profile").getAsString().equals(ScopedMining.PROFILE)
                    || witness.get("profile").getAsString().equals(ScopedCollectTarget.PROFILE)))
            return coherent;
        require(!coherent.has(MARKER) && !result.has(REFERENCE));
        JsonObject ref=new JsonObject();ref.addProperty("schema_version",1);ref.addProperty("path",TARGET);
        for(String key:BINDINGS){require(witness.has(key));ref.add(key,witness.get(key).deepCopy());}
        // Detached copies: never remove witness facts from registry or shared sibling objects.
        JsonObject out=coherent.deepCopy();out.addProperty(MARKER,ENCODING);
        for(String name:new String[]{"status","state"}) {
            JsonObject sibling=out.getAsJsonObject(name).getAsJsonObject("client_action").getAsJsonObject("result");
            require(sibling!=null && !sibling.has(REFERENCE) && witness.equals(sibling.get(WITNESS)));
            sibling.remove(WITNESS);sibling.add(REFERENCE,ref.deepCopy());
        }
        return out;
    }

    /** Subtrees use the same explicit-null Gson element encoding as the final action-bearing wire contract. */
    static int fullBytes(JsonObject value){return FULL.toJson(value).getBytes(StandardCharsets.UTF_8).length;}

    static JsonObject sizeDiagnostic(JsonObject action,int standalone,int capability,int limit) {
        JsonObject witness=action.getAsJsonObject("result").getAsJsonObject(WITNESS);
        boolean mining=witness.get("profile").getAsString().equals(ScopedMining.PROFILE);
        boolean placement=witness.get("profile").getAsString().equals(ScopedPlacement.PROFILE);
        JsonObject footprint=witness.getAsJsonObject("facts").getAsJsonObject(placement?"placement":mining?"mining":"movement");
        JsonObject entities=footprint.getAsJsonObject("entity_guard");
        JsonObject out=new JsonObject();out.addProperty("schema_version",mining?2:1);
        if(mining)out.addProperty("profile",ScopedMining.PROFILE);
        if(placement){out.addProperty("schema_version",3);out.addProperty("profile",ScopedPlacement.PROFILE);}
        out.addProperty("standalone_bytes",standalone);out.addProperty("capability_bytes",capability);
        out.addProperty("response_limit",limit);
        out.addProperty("standalone_reserve_bytes",ScopedEntityPolicy.TERMINAL_GROWTH_BYTES);
        out.addProperty("capability_reserve_bytes",3*ScopedEntityPolicy.TERMINAL_GROWTH_BYTES);
        out.addProperty("witness_bytes",fullBytes(witness));out.addProperty("entity_frame_bytes",fullBytes(entities));
        out.addProperty("enumerated_count",entities.get("enumerated_count").getAsInt());
        out.addProperty("cell_count",footprint.getAsJsonArray("cells").size());
        return out;
    }
    private static void require(boolean condition){if(!condition)throw new ClientActionRequest.Rejected(409,"scoped_movement_wire_incoherent");}
    private ScopedMovementWire() { }
}

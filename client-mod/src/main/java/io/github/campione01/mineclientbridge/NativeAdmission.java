package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.util.concurrent.Callable;
import java.util.Locale;

/** Request-bound admission provenance. Once hooks may run, absence of effects is never asserted. */
final class NativeAdmission {
    // REGISTERED means registration boundary entered; ACTIONS.begin need not have completed.
    // Every non-VALIDATION stage is conservative possible-effect evidence only.
    enum Stage { VALIDATION, HOOKS_POSSIBLE, INPUT_TRANSFER, REGISTERED }
    private static final ThreadLocal<NativeAdmission> CURRENT = new ThreadLocal<>();
    private Stage stage = Stage.VALIDATION;
    private final JsonObject binding;
    NativeAdmission(JsonObject envelope, boolean scoped, String actionSession) {
        binding = new JsonObject();
        binding.addProperty("schema_version",1);
        binding.addProperty("action_session",actionSession);
        binding.addProperty("request_payload_sha256",ScopedNativePreflight.digest(envelope));
        binding.addProperty("digest_format","sorted-json-utf8/1");
        JsonObject intent = scoped && envelope.has("intent") && envelope.get("intent").isJsonObject()
            ? envelope.getAsJsonObject("intent") : envelope;
        for(String key:java.util.List.of("action_id","action"))
            if(intent.has(key) && intent.get(key).isJsonPrimitive() && intent.getAsJsonPrimitive(key).isString())
                binding.addProperty(key,intent.get(key).getAsString());
        if(scoped && envelope.has("preflight") && envelope.get("preflight").isJsonObject())
            binding.add("scope",envelope.getAsJsonObject("preflight").deepCopy());
    }
    static JsonObject run(JsonObject envelope, boolean scoped, String actionSession, Callable<JsonObject> call) throws Exception {
        NativeAdmission previous = CURRENT.get();
        if(previous != null) { previous.advance(Stage.HOOKS_POSSIBLE); throw new ClientActionRequest.Rejected(409,"native_admission_reentry"); }
        NativeAdmission admission = new NativeAdmission(envelope,scoped,actionSession);
        CURRENT.set(admission);
        try { return call.call(); }
        catch(ClientActionRequest.Rejected failure) { throw failure.withNativeAdmission(admission.proof(failure.getMessage())); }
        finally { CURRENT.remove(); }
    }
    static void mark(Stage stage) { NativeAdmission current=CURRENT.get(); if(current!=null)current.advance(stage); }
    void advance(Stage stage) { if(stage.ordinal()>this.stage.ordinal())this.stage=stage; }
    JsonObject proof(String reason) {
        JsonObject proof=binding.deepCopy();
        proof.addProperty("stage",stage.name().toLowerCase(Locale.ROOT));
        proof.addProperty("reason",reason);
        proof.addProperty("effects_none_proven",stage==Stage.VALIDATION);
        proof.addProperty("dispatch_authority",false);
        proof.addProperty("retry_authority",false);
        return proof;
    }
}

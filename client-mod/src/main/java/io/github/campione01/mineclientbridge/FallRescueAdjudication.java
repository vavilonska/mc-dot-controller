package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.util.LinkedHashMap;
import java.util.Set;

/** Explicit authority release only. Historical action/episode outcomes are never rewritten. */
final class FallRescueAdjudication {
    static final String ACK="release_authority_keep_original_effects_unknown_no_resume";
    record Request(String id,String arm,String owner,String episode,String action,String receipt,
                   String session,String world,String player,long revision) { }
    private static final Set<String> KEYS=Set.of("adjudication_schema_version","adjudication_id","arm_id","owner_id",
        "episode_id","original_action_id","original_receipt_sha256","expected_action_session","expected_world_generation",
        "expected_player_uuid","expected_arbiter_revision","acknowledgment");
    static Request parse(JsonObject j){
        require(j.keySet().equals(KEYS),"fall_adjudication_closed_fields_required");
        var schema=j.get("adjudication_schema_version");
        require(schema.isJsonPrimitive()&&schema.getAsJsonPrimitive().isNumber()&&schema.getAsString().equals("1"),"fall_adjudication_schema_required");
        require(ACK.equals(text(j,"acknowledgment")),"fall_adjudication_explicit_effects_unknown_ack_required");
        String hash=text(j,"original_receipt_sha256");require(hash.matches("[0-9a-f]{64}"),"fall_adjudication_receipt_digest_required");
        var revision=j.get("expected_arbiter_revision");
        require(revision.isJsonPrimitive()&&revision.getAsJsonPrimitive().isNumber()&&revision.getAsString().matches("[0-9]{1,16}"),"fall_adjudication_revision_required");
        long number=revision.getAsLong();require(number>=0&&number<=9007199254740990L,"fall_adjudication_revision_required");
        String id=text(j,"adjudication_id");require(id.matches("[A-Za-z0-9_-]{1,80}"),"fall_adjudication_id_required");
        return new Request(id,text(j,"arm_id"),text(j,"owner_id"),text(j,"episode_id"),
            text(j,"original_action_id"),hash,text(j,"expected_action_session"),text(j,"expected_world_generation"),text(j,"expected_player_uuid"),number);
    }
    static final class Ledger {
        private final LinkedHashMap<String,JsonObject> receipts=new LinkedHashMap<>();
        void requireNew(String id){require(!receipts.containsKey(id),"fall_adjudication_already_applied_read_original_id");require(receipts.size()<128,"fall_adjudication_identity_capacity_exhausted");}
        void commit(String id,JsonObject receipt){requireNew(id);receipts.put(id,receipt.deepCopy());}
        JsonObject read(String id){
            JsonObject receipt=receipts.get(id);if(receipt!=null)return receipt.deepCopy();
            JsonObject j=new JsonObject();j.addProperty("adjudication_schema_version",1);j.addProperty("adjudication_id",id);j.addProperty("status","not_found");return j;
        }
    }
    static JsonObject receipt(Request r,long after){
        JsonObject j=new JsonObject();j.addProperty("adjudication_schema_version",1);j.addProperty("adjudication_id",r.id());
        j.addProperty("status","authority_released_original_unknown");j.addProperty("arm_id",r.arm());j.addProperty("owner_id",r.owner());
        j.addProperty("episode_id",r.episode());j.addProperty("original_action_id",r.action());j.addProperty("original_receipt_sha256",r.receipt());
        j.addProperty("action_session",r.session());j.addProperty("world_generation",r.world());j.addProperty("player_uuid",r.player());
        j.addProperty("arbiter_revision_before",r.revision());j.addProperty("arbiter_revision_after",after);
        j.addProperty("acknowledgment",ACK);j.addProperty("original_effects","unknown");j.addProperty("input_neutral_observed",true);
        j.addProperty("rescue_ended",true);j.addProperty("authority_released",true);j.addProperty("no_auto_resume",true);j.addProperty("physical_safety_guaranteed",false);
        return j;
    }
    private static String text(JsonObject j,String key){String s=ClientActionRequest.string(j,key);require(!s.isBlank()&&s.length()<=128,"fall_adjudication_invalid_"+key);return s;}
    private static void require(boolean ok,String reason){FallRescuePolicy.require(ok,reason);}
    private FallRescueAdjudication() { }
}

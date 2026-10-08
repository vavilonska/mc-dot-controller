package io.github.campione01.mineclientbridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.util.HashSet;
import java.util.List;
import java.util.ArrayList;
import java.util.UUID;

/** Explicit opt-in; no acquisition, automatic replay, or permission expansion of the old API. */
record EncounterRequest(List<Identity> scope) {
    static final String MODE="two_zombie_retreat_v1";
    static final String ENABLE_PROPERTY="mineclientBridge.encounterRetreatStage1Enabled";
    record Identity(int entityId,String uuid,String type) {
        boolean matches(CombatThreats.Observed e) { return e.entityId()==entityId && e.uuid().equals(uuid) && e.type().equals(type); }
    }
    EncounterRequest { scope=List.copyOf(scope); }
    static boolean runtimeEnabled() { return Boolean.getBoolean(ENABLE_PROPERTY); }
    static EncounterRequest parseOptional(JsonObject body) {
        if(!body.has("encounter_mode")) {
            ClientActionRequest.require(!body.has("encounter_scope"),"encounter_scope_requires_mode");return null;
        }
        ClientActionRequest.require(ClientActionRequest.string(body,"encounter_mode").equals(MODE),"encounter_mode_unsupported");
        var allowed=java.util.Set.of("action","action_id","timeout_ms","expected_world_generation","expected_player_uuid",
                "expected_action_session","expected_origin","expected_navigation_epoch","target_uuid","target_entity_id",
                "target_type","approach","shield","encounter_mode","encounter_scope");
        ClientActionRequest.require(allowed.containsAll(body.keySet()),"encounter_unknown_fields");
        ClientActionRequest.require(body.has("approach") && !ClientActionRequest.bool(body,"approach",true)
                && body.has("shield") && !ClientActionRequest.bool(body,"shield",true),"encounter_offense_and_shield_must_be_disabled");
        for(String key:List.of("hotbar_slot","jump","sneak","sprint"))
            ClientActionRequest.require(!body.has(key),"encounter_forbidden_"+key);
        ClientActionRequest.require(body.has("encounter_scope") && body.get("encounter_scope").isJsonArray(),"invalid_encounter_scope");
        JsonArray entries=body.getAsJsonArray("encounter_scope");
        ClientActionRequest.require(entries.size()==2,"encounter_requires_two_zombies");
        ClientActionRequest.require(body.has("expected_origin")==body.has("expected_navigation_epoch"),"encounter_navigation_binding_pair_required");
        if(body.has("expected_origin")) {
            ClientActionRequest.require(body.get("expected_origin").isJsonObject(),"invalid_expected_origin");
            JsonObject origin=body.getAsJsonObject("expected_origin");
            ClientActionRequest.require(origin.keySet().equals(java.util.Set.of("x","y","z")),"invalid_expected_origin");
            for(String axis:java.util.List.of("x","y","z")) requireNumber(origin,axis,29999900,false);
            requireNumber(body,"expected_navigation_epoch",9007199254740991L,true);
        }
        var scope=new ArrayList<Identity>();var ids=new HashSet<Integer>();var uuids=new HashSet<String>();
        for(var value:entries) {
            ClientActionRequest.require(value.isJsonObject(),"invalid_encounter_identity");
            JsonObject identity=value.getAsJsonObject();
            ClientActionRequest.require(identity.keySet().equals(java.util.Set.of("entity_id","uuid","type")),"invalid_encounter_identity_fields");
            int id=ClientActionRequest.integer(identity,"entity_id",-1);
            String uuid=ClientActionRequest.string(identity,"uuid"),type=ClientActionRequest.string(identity,"type");
            try { ClientActionRequest.require(UUID.fromString(uuid).toString().equals(uuid),"invalid_encounter_uuid"); }
            catch(IllegalArgumentException e) { throw new ClientActionRequest.Rejected(400,"invalid_encounter_uuid"); }
            ClientActionRequest.require(id>=0 && ids.add(id) && uuids.add(uuid),"duplicate_or_invalid_encounter_identity");
            ClientActionRequest.require(type.equals("minecraft:zombie"),"encounter_requires_two_zombies");
            scope.add(new Identity(id,uuid,type));
        }
        ClientActionRequest.require(scope.stream().anyMatch(i->i.entityId()==ClientActionRequest.integer(body,"target_entity_id",-1)
                && i.uuid().equals(ClientActionRequest.string(body,"target_uuid"))
                && i.type().equals(ClientActionRequest.string(body,"target_type"))),"encounter_target_outside_scope");
        return new EncounterRequest(scope);
    }
    private static void requireNumber(JsonObject object,String key,double limit,boolean epoch) {
        var value=object.get(key);
        ClientActionRequest.require(value!=null && value.isJsonPrimitive() && value.getAsJsonPrimitive().isNumber(),"invalid_"+key);
        double number=value.getAsDouble();
        ClientActionRequest.require(Double.isFinite(number) && Math.abs(number)<=limit
                && (!epoch || number>=0 && number==Math.rint(number)),"invalid_"+key);
    }
    JsonArray json() {
        JsonArray result=new JsonArray();
        for(var identity:scope) {
            JsonObject item=new JsonObject();item.addProperty("entity_id",identity.entityId());
            item.addProperty("uuid",identity.uuid());item.addProperty("type",identity.type());result.add(item);
        }
        return result;
    }
}

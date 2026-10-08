package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.util.Set;
import java.util.UUID;

/** Non-toggling, identity-bound pause request. Screen installation is not world-pause proof. */
final class EncounterPause {
    static final String PAUSE_SCREEN = "net.minecraft.client.gui.screens.PauseScreen";
    record Request(String session, String world, String player, String actionId) { }
    record Context(boolean privateSingleplayer, String session, String world, String player,
                   boolean guardedOwner, String screen, JsonObject current, JsonObject expected) { }
    interface Adapter {
        Context context(String actionId);
        void openPauseScreen();
        boolean pauseScreenInstalled();
        boolean clientPaused();
        void cancelEncounter();
        JsonObject action(String actionId);
    }

    static Request parse(JsonObject body) {
        ClientActionRequest.require(body.keySet().equals(Set.of("pause_schema_version",
                "expected_action_session", "expected_world_generation", "expected_player_uuid",
                "expected_action_id")), "invalid_pause_fields");
        ClientActionRequest.require(ClientActionRequest.integer(body,"pause_schema_version",-1)==1,
                "unsupported_pause_schema");
        String session=canonicalUuid(body,"expected_action_session");
        String world=canonicalUuid(body,"expected_world_generation");
        String player=canonicalUuid(body,"expected_player_uuid");
        String id=ClientActionRequest.string(body,"expected_action_id");
        ClientActionRequest.require(id.matches("[A-Za-z0-9_-]{1,128}"),"invalid_pause_action_id");
        return new Request(session,world,player,id);
    }

    private static String canonicalUuid(JsonObject body,String key) {
        String value=ClientActionRequest.string(body,key);
        try { ClientActionRequest.require(UUID.fromString(value).toString().equals(value),"invalid_"+key); }
        catch(IllegalArgumentException failure) { throw new ClientActionRequest.Rejected(400,"invalid_"+key); }
        return value;
    }
    private static void require(boolean condition,String reason) {
        if(!condition) throw new ClientActionRequest.Rejected(409,reason);
    }
    private static String string(JsonObject value,String key) {
        return value!=null && value.has(key) && value.get(key).isJsonPrimitive()
                && value.getAsJsonPrimitive(key).isString() ? value.get(key).getAsString() : null;
    }
    private static JsonObject object(JsonObject value,String key) {
        return value!=null && value.has(key) && value.get(key).isJsonObject() ? value.getAsJsonObject(key) : null;
    }

    static JsonObject apply(Request request,Adapter adapter) {
        return apply(request,adapter,false);
    }

    // Only the native terminal hook's first synchronous call may use true.
    // There is no HTTP/request field that can bypass the prior-attempt check.
    static JsonObject apply(Request request,Adapter adapter,boolean originalTerminalHookCall) {
        Context context=adapter.context(request.actionId());
        require(context.privateSingleplayer(),"pause_requires_private_singleplayer");
        require(request.session().equals(context.session()),"action_session_changed");
        require(request.world().equals(context.world()),"action_world_changed");
        require(request.player().equals(context.player()),"action_player_changed");
        require(!context.guardedOwner(),"pause_foreign_guarded_owner");
        boolean currentRunning="running".equals(string(context.current(),"status"));
        require(!currentRunning || request.actionId().equals(string(context.current(),"action_id")),
                "pause_foreign_action_owner");
        require(context.screen()==null || PAUSE_SCREEN.equals(context.screen()),"pause_other_screen_open");
        JsonObject expected=context.expected();
        if(expected!=null) {
            JsonObject result=object(expected,"result"), combat=object(result,"combat"), encounter=object(combat,"encounter");
            require(request.actionId().equals(string(expected,"action_id"))
                    && request.session().equals(string(expected,"action_session"))
                    && request.world().equals(string(result,"world_generation"))
                    && "combat_entity".equals(string(expected,"action"))
                    && EncounterRequest.MODE.equals(string(encounter,"encounter_mode")),"pause_expected_encounter_mismatch");
            require(encounter.has("encounter_scope") && encounter.get("encounter_scope").isJsonArray()
                    && encounter.getAsJsonArray("encounter_scope").size()==2,"pause_expected_encounter_mismatch");
            String status=string(expected,"status");
            require(status!=null && Set.of("running","succeeded","failed","cancelled").contains(status),
                    "pause_expected_encounter_mismatch");
            require(!status.equals("running") || currentRunning,"pause_expected_owner_unconfirmed");
        } else require(!currentRunning,"pause_expected_action_missing_with_owner");
        JsonObject priorHook=object(object(expected,"result"),EncounterTerminalPause.EVIDENCE);
        require(originalTerminalHookCall || PAUSE_SCREEN.equals(context.screen())
                || priorHook==null || !priorHook.has("attempted") || !priorHook.get("attempted").getAsBoolean(),
                "pause_prior_terminal_attempt_no_retry");
        // All refusals above precede any mutation. After this boundary, exceptions are unknown.
        try {
        boolean already=PAUSE_SCREEN.equals(context.screen());
        if(!already) adapter.openPauseScreen();
        if(!adapter.pauseScreenInstalled()) throw new IllegalStateException("pause_screen_installation_unconfirmed");
        // Screen hooks can run reentrantly on this same thread. Never cancel a
        // newly installed owner merely because the earlier snapshot matched.
        Context latest=adapter.context(request.actionId());
        if(!latest.privateSingleplayer() || !request.session().equals(latest.session())
                || !request.world().equals(latest.world()) || !request.player().equals(latest.player())
                || latest.guardedOwner()) throw new IllegalStateException("pause_context_changed_during_screen_open");
        if("running".equals(string(latest.current(),"status"))) {
            if(!currentRunning || !request.actionId().equals(string(latest.current(),"action_id")))
                throw new IllegalStateException("pause_owner_changed_during_screen_open");
            adapter.cancelEncounter();
        }
        JsonObject action=expected==null?null:adapter.action(request.actionId());
        JsonObject answer=new JsonObject();
        answer.addProperty("ok",true);answer.addProperty("pause_schema_version",1);
        answer.addProperty("action","ensure_paused");answer.addProperty("pause_requested",true);
        answer.addProperty("pause_screen_installed",true);answer.addProperty("already_pause_screen",already);
        answer.addProperty("client_paused_observed",adapter.clientPaused());
        answer.addProperty("pause_effect_confirmed",false);answer.addProperty("server_confirmed",false);
        answer.addProperty("action_session",request.session());answer.addProperty("world_generation",request.world());
        answer.addProperty("player_uuid",request.player());answer.addProperty("expected_action_id",request.actionId());
        answer.addProperty("expected_action_present",expected!=null);answer.add("client_action",action);
        JsonObject result=object(action,"result");
        answer.add("input_release_confirmed",result==null?null:result.get("input_release_confirmed"));
        return answer;
        } catch(RuntimeException failure) {
            // In particular, do not let a late Rejected become a definite HTTP 4xx.
            throw new IllegalStateException("pause_outcome_unknown",failure);
        }
    }
}

package io.github.campione01.mineclientbridge;

import com.google.gson.JsonNull;
import com.google.gson.JsonObject;
import java.util.function.Function;

/** Same-callback post-terminal pause. Never changes the original terminal outcome. */
final class EncounterTerminalPause {
    static final String EVIDENCE="encounter_terminal_pause";

    static void afterTerminal(ActionRegistry.Entry entry,String session,
                              Function<EncounterPause.Request,JsonObject> pause) {
        if(!entry.request.action().equals("combat_entity")
                || !EncounterRequest.pauseRequested(entry.request.original()) || entry.result.has(EVIDENCE)) return;
        JsonObject evidence=new JsonObject();entry.result.add(EVIDENCE,evidence);
        evidence.addProperty("hook_schema_version",1);evidence.addProperty("requested",true);
        evidence.addProperty("attempted",true);evidence.addProperty("pause_call_attempted",false);
        evidence.addProperty("outcome","unconfirmed");
        evidence.add("pause_screen_installed",JsonNull.INSTANCE);
        evidence.add("already_pause_screen",JsonNull.INSTANCE);
        evidence.add("client_paused_observed",JsonNull.INSTANCE);
        evidence.addProperty("pause_effect_confirmed",false);evidence.addProperty("server_confirmed",false);
        evidence.add("input_release_confirmed",entry.result.get("input_release_confirmed"));
        try {
            if(entry.running() || !entry.result.has("input_release_confirmed"))
                throw new IllegalStateException("terminal_cleanup_not_recorded");
            JsonObject body=entry.request.original();
            var request=new EncounterPause.Request(session,
                    ClientActionRequest.string(body,"expected_world_generation"),
                    ClientActionRequest.string(body,"expected_player_uuid"),entry.request.id());
            evidence.addProperty("pause_call_attempted",true);
            JsonObject reply=pause.apply(request);
            if(reply==null || !reply.has("pause_screen_installed")
                    || !reply.get("pause_screen_installed").getAsBoolean()
                    || reply.get("pause_effect_confirmed").getAsBoolean()
                    || reply.get("server_confirmed").getAsBoolean())
                throw new IllegalStateException("pause_screen_acknowledgement_unconfirmed");
            for(String key:new String[]{"pause_screen_installed","already_pause_screen","client_paused_observed"})
                evidence.add(key,reply.get(key).deepCopy());
            evidence.addProperty("outcome","screen_installed");
        } catch(RuntimeException failure) {
            evidence.addProperty("outcome",failure instanceof ClientActionRequest.Rejected?"rejected":"unconfirmed");
            evidence.addProperty("error_type",failure.getClass().getSimpleName());
            String reason=failure.getMessage();
            evidence.addProperty("reason",reason!=null && reason.matches("[a-z0-9_]{1,100}")?reason:"pause_hook_failed");
        }
    }
}

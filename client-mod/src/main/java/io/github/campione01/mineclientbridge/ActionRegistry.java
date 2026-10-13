package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.util.LinkedHashMap;
import java.util.Map;

/** Client-thread-only action identity and outcomes. IDs survive world changes, so a lost response cannot replay an action. */
final class ActionRegistry {
    static final class Entry {
        final ClientActionRequest request;
        String status = "running", reason = "accepted";
        int ticks;
        final JsonObject result = new JsonObject();
        Entry(ClientActionRequest request) { this.request = request; }
        boolean running() { return status.equals("running"); }
        JsonObject json(boolean ownsInput) {
            JsonObject j = new JsonObject();
            j.addProperty("ok", true);
            j.addProperty("action_schema_version", 1);
            j.addProperty("action_id", request.id());
            j.addProperty("action", request.action());
            j.addProperty("status", status);
            j.addProperty("reason", reason);
            j.addProperty("ticks", ticks);
            j.addProperty("input_owner", ownsInput ? "action" : "direct");
            j.addProperty("server_confirmed", false);
            j.add("result", result.deepCopy());
            return j;
        }
    }
    final String session = java.util.UUID.randomUUID().toString();
    private final Map<String, Entry> entries = new LinkedHashMap<>();
    private Entry active, last;
    Entry existing(ClientActionRequest request) {
        Entry old = entries.get(request.id());
        if (old != null && !old.request.original().equals(request.original())) {
            throw new ClientActionRequest.Rejected(409, "action_id_payload_mismatch");
        }
        return old;
    }
    Entry begin(ClientActionRequest request) {
        Entry old = existing(request);
        if (old != null) return old;
        if (active != null) throw new ClientActionRequest.Rejected(409, "action_busy");
        active = last = new Entry(request);
        entries.put(request.id(), active);
        return active;
    }
    Entry active() { return active; }
    void finish(String status, String reason) {
        if (active == null) return;
        active.status = status;
        active.reason = reason;
        active = null;
    }
    void finishAfterCleanup(String status, String reason, boolean releaseConfirmed) {
        if (active == null) return;
        active.result.addProperty("input_release_confirmed", releaseConfirmed);
        if (!releaseConfirmed) {
            active.result.addProperty("requested_terminal_status", status);
            active.result.addProperty("requested_terminal_reason", reason);
        }
        finish(releaseConfirmed ? status : "failed", releaseConfirmed ? reason : "input_release_unconfirmed");
    }
    Entry get(String id) {
        if (id == null) return active != null ? active : last;
        Entry entry = entries.get(id);
        if (entry == null) throw new ClientActionRequest.Rejected(404, "action_not_found");
        return entry;
    }
    JsonObject status(String id) {
        Entry entry = get(id);
        if (entry != null) {
            JsonObject j = entry.json(active != null);
            j.addProperty("action_session", session);
            return j;
        }
        JsonObject j = new JsonObject();
        j.addProperty("ok", true);
        j.addProperty("action_schema_version", 1);
        j.addProperty("action_id", (String) null);
        j.addProperty("status", "idle");
        j.addProperty("action_session", session);
        j.addProperty("input_owner", "direct");
        return j;
    }
}

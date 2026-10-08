package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import net.minecraft.client.Minecraft;

/** Player-only ordinary yaw alignment; no target, translation, pitch change or input event. */
final class GuardedGameTurning {
    static final int SCHEMA = 1;
    static boolean enabled() { return Boolean.getBoolean("mineclientBridge.guardedTurning"); }

    static GuardedMovement.Ticket submit(GuardedMovement.Request request, double targetYaw,
                                        long receivedNanos, String entrySession) {
        Minecraft mc = Minecraft.getInstance();
        return GuardedGameMovement.LEASES.submitTurn(request, receivedNanos, entrySession, targetYaw, mc::execute,
                () -> {
                    GuardedAction.require(!ClientActions.ownsInput(), "action_input_owned");
                    GuardedAction.require(mc.player != null && enabled(), "guarded_turning_disabled");
                    return GuardedGameMovement.snapshot(mc, mc.player.input, false, enabled());
                }, yaw -> {
                    // The shared lease monitor spans the full fresh state check and these synchronous setters.
                    GuardedAction.require(mc.isSameThread() && mc.player != null && enabled() && BridgeServer.isRunning(),
                            "guarded_turning_disabled");
                    mc.player.setYRot((float) yaw);
                    mc.player.setYHeadRot((float) yaw);
                    mc.player.setYBodyRot((float) yaw);
                });
    }

    static JsonObject capabilities() {
        JsonObject json = new JsonObject();
        json.addProperty("schema_version", SCHEMA);
        json.addProperty("enabled", enabled());
        json.addProperty("max_ttl_ms", GuardedMovement.MAX_TURN_TTL_MS);
        json.addProperty("max_yaw_step", GuardedMovement.MAX_TURN_STEP);
        json.addProperty("held_input", false);
        json.addProperty("local_unpublished_survival_only", true);
        json.addProperty("shared_movement_observation", true);
        json.addProperty("pitch_supported", false);
        return json;
    }
    private GuardedGameTurning() { }
}

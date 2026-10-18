package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;

/** Java wire parser shared by the real HTTP route and offline contract tests. */
final class FallRescueControl {
    interface Adapter {
        JsonObject arm(FallRescuePolicy.Arm request);
        JsonObject renew(FallRescuePolicy.Renew request);
        JsonObject disarm(FallRescuePolicy.Stop request);
        JsonObject status();
    }
    static JsonObject apply(String operation,JsonObject body,Adapter adapter){
        return switch(operation){
            case "arm" -> adapter.arm(FallRescuePolicy.arm(body));
            case "renew" -> adapter.renew(FallRescuePolicy.renew(body));
            case "disarm" -> adapter.disarm(FallRescuePolicy.stop(body));
            case "status" -> adapter.status();
            default -> throw new ClientActionRequest.Rejected(404,"unknown_endpoint");
        };
    }
    private FallRescueControl() { }
}

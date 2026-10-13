package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;

/** Pure fail-closed walking-route binding. This is not a teleport or knockback detector. */
final class PositionDiscontinuityGuard {
    record Sample(double x, double y, double z, double vx, double vy, double vz,
            boolean grounded, boolean loaded, boolean supported, boolean riding) {
        boolean finite() { return Double.isFinite(x) && Double.isFinite(y) && Double.isFinite(z)
                && Double.isFinite(vx) && Double.isFinite(vy) && Double.isFinite(vz); }
        double speed() { return Math.sqrt(vx*vx + vy*vy + vz*vz); }
    }
    private Object world, player;
    private Sample last;
    private long epoch, lastStableTick = Long.MIN_VALUE;
    private int stableTicks;
    private boolean bindingRequired;
    private String reason = "initial";

    long epoch() { return epoch; }
    boolean ready() { return last != null && last.finite() && stableTicks >= 3; }
    void sample(Object world, Object player, Sample next, long tick) {
        if (world == null || player == null) {
            if (last != null) invalidate("world_unavailable");
            this.world = world; this.player = player; last = null; return;
        }
        if (this.world != world || this.player != player) {
            if (last != null || this.world != null) invalidate("identity_changed");
            this.world = world; this.player = player; last = null;
        }
        if (!next.finite()) {
            if (last == null || last.finite()) invalidate("invalid_position");
            last = next; stableTicks = 0; return;
        }
        if (last != null && last.finite()) {
            double dx=next.x-last.x, dy=next.y-last.y, dz=next.z-last.z;
            double displacement=Math.sqrt(dx*dx+dy*dy+dz*dz);
            // Walking, jumping and ordinary knockback are well below 16 blocks
            // per sample. Velocity-consistent falling is not called a teleport.
            double rx=dx-last.vx, ry=dy-last.vy, rz=dz-last.vz;
            double residual=Math.sqrt(rx*rx+ry*ry+rz*rz);
            if (displacement >= 16 && residual >= 8) invalidate("position_discontinuity");
        }
        last = next;
        boolean stable = next.grounded && next.loaded && next.supported && !next.riding && next.speed() <= .15;
        if (!stable) stableTicks=0;
        else if (tick != lastStableTick) stableTicks=Math.min(3,stableTicks+1);
        lastStableTick=tick;
    }
    private void invalidate(String why) {
        epoch++; bindingRequired=true; stableTicks=0; lastStableTick=Long.MIN_VALUE; reason=why;
    }
    void requireBinding(JsonObject request) {
        boolean supplied=request.has("expected_navigation_epoch");
        if (!bindingRequired && !supplied) return; // Existing ordinary walk contract.
        if (!supplied) throw new ClientActionRequest.Rejected(409,"navigation_rebind_required");
        long expected = integerEpoch(request);
        if (expected != epoch) throw new ClientActionRequest.Rejected(409,"navigation_epoch_changed");
        if (!ready()) throw new ClientActionRequest.Rejected(409,"navigation_not_settled");
        if (!request.has("expected_origin") || !request.get("expected_origin").isJsonObject())
            throw new ClientActionRequest.Rejected(400,"expected_origin_required");
        JsonObject origin=request.getAsJsonObject("expected_origin");
        double dx=number(origin,"x")-last.x, dy=number(origin,"y")-last.y, dz=number(origin,"z")-last.z;
        if (dx*dx+dy*dy+dz*dz > .25*.25)
            throw new ClientActionRequest.Rejected(409,"navigation_origin_changed");
    }
    private static long integerEpoch(JsonObject request) {
        double n=number(request,"expected_navigation_epoch");
        if (n < 0 || n > 9007199254740991L || n != Math.rint(n))
            throw new ClientActionRequest.Rejected(400,"invalid_navigation_epoch");
        return (long)n;
    }
    private static double number(JsonObject obj,String key) {
        var v=obj.get(key);
        if (v==null || !v.isJsonPrimitive() || !v.getAsJsonPrimitive().isNumber() || !Double.isFinite(v.getAsDouble()))
            throw new ClientActionRequest.Rejected(400,"invalid_"+key);
        return v.getAsDouble();
    }
    JsonObject snapshot() {
        JsonObject j=new JsonObject();
        j.addProperty("schema_version",1); j.addProperty("epoch",epoch);
        j.addProperty("fresh_binding_required",bindingRequired); j.addProperty("rebind_ready",ready());
        j.addProperty("stable_ticks",stableTicks); j.addProperty("reason",reason);
        j.addProperty("large_displacement_threshold",16);
        j.addProperty("detects_all_teleports",false);
        return j;
    }
}

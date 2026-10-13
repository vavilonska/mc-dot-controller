package io.github.campione01.mineclientbridge;

/** Pure bounded receipt logic. Dispatch is never inferred from a successful observation. */
final class BoatTransferProgress {
    private final boolean mounting;
    private long dispatchTick = -1, lastObservation = -1, lastInput = -1;
    private boolean dispatched, sneakStopped;
    private int stable, sneakTicks;
    BoatTransferProgress(boolean mounting) { this.mounting = mounting; }
    boolean dispatched() { return dispatched; }
    int sneakTicks() { return sneakTicks; }
    int stableTicks() { return stable; }
    long dispatchTick() { return dispatchTick; }
    void dispatch(long tick) {
        if (dispatched) throw new IllegalStateException("boat_transfer_already_dispatched");
        dispatched = true; dispatchTick = tick;
    }
    boolean sneak(long tick, boolean sameBoat) {
        if (mounting || sneakStopped) return false;
        if (!sameBoat || (lastInput >= 0 && tick < lastInput)) { sneakStopped = true; return false; }
        if (tick == lastInput) return true; // One game tick, not one callback.
        if (sneakTicks >= BoatTransferRequest.MAX_SNEAK_TICKS) { sneakStopped = true; return false; }
        if (!dispatched) dispatch(tick);
        lastInput = tick; sneakTicks++; return true;
    }
    String observe(long tick, boolean anyVehicle, boolean sameBoat, boolean driver, boolean exactPassengers, boolean boatEmpty) {
        // A pre-tick observation can see detachment before the next input callback.
        // Never restart that attempt if a later correction reattaches the player.
        if (!mounting && !sameBoat) sneakStopped = true;
        if (anyVehicle && !sameBoat) return "vehicle_changed";
        if (sameBoat && (!driver || !exactPassengers)) return "boat_driver_or_passengers_changed";
        if ((dispatched && tick < dispatchTick) || (lastObservation >= 0 && tick < lastObservation))
            return "boat_transfer_tick_regressed";
        if (!dispatched || tick <= dispatchTick) return null;
        boolean complete = mounting ? sameBoat && driver && exactPassengers : !anyVehicle && boatEmpty;
        if (tick == lastObservation) { if (!complete) stable = 0; return null; }
        lastObservation = tick;
        stable = complete ? stable + 1 : 0;
        return stable >= 2 ? (mounting ? "boat_mount_observed" : "boat_dismount_observed") : null;
    }
}

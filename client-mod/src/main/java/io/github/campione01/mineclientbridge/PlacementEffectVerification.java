package io.github.campione01.mineclientbridge;

/** Pure bounded post-call verifier. A return code never proves absence of effects. */
final class PlacementEffectVerification {
    static final int MAX_TICKS = 40, STABLE_TICKS = 5;
    enum Decision { WAIT, OBSERVED, UNKNOWN }
    private int stable;
    private int lastTick = -1;
    Decision observe(int elapsedTicks, boolean changedToExpectedBlock, boolean materialConsumed,
            boolean placementSettled) {
        if(elapsedTicks < 0 || elapsedTicks > MAX_TICKS || elapsedTicks < lastTick) return Decision.UNKNOWN;
        // Repeated observations inside one client tick cannot manufacture settlement.
        if(!changedToExpectedBlock || !materialConsumed || !placementSettled) stable=0;
        else if(elapsedTicks != lastTick) stable++;
        lastTick = elapsedTicks;
        if(stable >= STABLE_TICKS) return Decision.OBSERVED;
        return elapsedTicks >= MAX_TICKS ? Decision.UNKNOWN : Decision.WAIT;
    }
    int stableTicks(){return stable;}
}

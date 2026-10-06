package io.github.campione01.mineclientbridge;

/** Pure per-tick recovery decision. No game I/O, timers, or simulated physics. */
final class EnvironmentSteering {
    record State(boolean jump, boolean hazardous, int dryTicks, boolean recovered) { }
    static State update(boolean water, boolean eyeWater, boolean lava, boolean powder,
            boolean fire, boolean onGround, int previousDryTicks) {
        boolean hazardous = water || eyeWater || lava || powder || fire;
        int dryTicks = !hazardous && onGround ? previousDryTicks + 1 : 0;
        return new State(water || lava || powder, hazardous, dryTicks, dryTicks >= 5);
    }
    private EnvironmentSteering() { }
}

package io.github.campione01.mineclientbridge;

/** Small deterministic predicates; Minecraft supplies every live value. */
final class CombatRules {
    static boolean cooldownReady(double observed) {
        return Double.isFinite(observed) && observed >= .95 && observed <= 1;
    }
    static boolean rayInReach(boolean sameTarget, double eyeToHit, double observedReach) {
        return sameTarget && Double.isFinite(eyeToHit) && Double.isFinite(observedReach)
                && eyeToHit >= 0 && observedReach > 0 && eyeToHit <= Math.min(3,observedReach);
    }
    static boolean manualViewChanged(double yaw, double pitch, double expectedYaw, double expectedPitch) {
        return !Double.isFinite(yaw) || !Double.isFinite(pitch)
                || Math.abs(Math.IEEEremainder(yaw-expectedYaw,360)) > .05
                || Math.abs(pitch-expectedPitch) > .05;
    }
    private CombatRules() { }
}

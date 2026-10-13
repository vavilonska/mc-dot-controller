package io.github.campione01.mineclientbridge;

/** Pure conservative targeting math. Does not assert server damage or projectile hit. */
final class CapabilityTargetPolicy {
    static final double CRYSTAL_CLEARANCE = 12.0;
    static final double MAX_SHOT_DISTANCE = 32.0;
    static boolean crystalClear(double distance) {
        return Double.isFinite(distance) && distance >= CRYSTAL_CLEARANCE && distance <= MAX_SHOT_DISTANCE;
    }
    static boolean stationaryDragonPhase(int phase) { return phase == 6 || phase == 7; }
    static boolean meleeReach(double distance, double range) {
        return Double.isFinite(distance) && Double.isFinite(range) && distance >= 0 && range > 0
                && distance <= Math.min(3.0, range);
    }
    /** Lower-angle full-draw vanilla bow trajectory, gravity .05 blocks/tick^2.
     * Drag/target motion are not claimed exact: the caller must observe actual damage. */
    static double bowElevation(double horizontal, double vertical) {
        if (!Double.isFinite(horizontal) || !Double.isFinite(vertical) || horizontal <= 0
                || Math.hypot(horizontal,vertical) > MAX_SHOT_DISTANCE) return Double.NaN;
        double v2=9, g=.05, d=v2*v2-g*(g*horizontal*horizontal+2*vertical*v2);
        return d < 0 ? Double.NaN : Math.atan((v2-Math.sqrt(d))/(g*horizontal));
    }
    private CapabilityTargetPolicy() { }
}

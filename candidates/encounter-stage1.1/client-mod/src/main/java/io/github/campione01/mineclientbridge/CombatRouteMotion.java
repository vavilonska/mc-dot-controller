package io.github.campione01.mineclientbridge;

/** Bounded settle-before-turn admission for new detours and emergency withdrawal only. */
final class CombatRouteMotion {
    static final int MAX_SETTLE_TICKS = 10, MAX_TOTAL_SETTLE_TICKS = 40;
    static final double MAX_SPEED = .35, MAX_LATERAL = .03, ENVELOPE = .04;
    record Result(boolean ready, boolean failed, String reason, int settleTicks, int totalSettleTicks) { }
    private double lastX, lastZ;
    private boolean headingKnown;
    private int episodeWait, totalWait, lastTick = -1;

    Result sample(int tick, CombatRecovery.Motion motion, double dx, double dz, boolean urgent) {
        if (tick <= lastTick || motion == null || !motion.finite() || !Double.isFinite(dx)
                || !Double.isFinite(dz) || Math.hypot(dx,dz)<.001)
            return result(false,true,"invalid_route_motion");
        lastTick=tick;
        if (!motion.onGround() || motion.heightOffset()>.05)
            return result(false,true,"route_motion_not_grounded_flat");
        double length=Math.hypot(dx,dz),ux=dx/length,uz=dz/length;
        double speed=Math.hypot(motion.vx(),motion.vz());
        double parallel=motion.vx()*ux+motion.vz()*uz;
        double lateral=Math.abs(motion.vx()*uz-motion.vz()*ux);
        boolean turn=!headingKnown || lastX*ux+lastZ*uz<.98;
        boolean settled=speed<=CombatRecovery.MAX_HORIZONTAL_SPEED && Math.abs(motion.vy())<=CombatRecovery.MAX_VERTICAL_SPEED;
        boolean admitted=(!turn || settled) && speed<=MAX_SPEED && lateral<=MAX_LATERAL
                && parallel>=-.003 && Math.abs(motion.vy())<=CombatRecovery.MAX_VERTICAL_SPEED;
        if (!admitted) {
            if (urgent) return result(false,true,"retreat_motion_not_settled");
            episodeWait++;totalWait++;
            boolean exhausted=episodeWait>=MAX_SETTLE_TICKS || totalWait>=MAX_TOTAL_SETTLE_TICKS;
            return result(false,exhausted,exhausted?"route_settle_budget":"settling_route_turn");
        }
        headingKnown=true;lastX=ux;lastZ=uz;episodeWait=0;
        return result(true,false,"route_motion_admitted");
    }
    private Result result(boolean ready,boolean failed,String reason) {
        return new Result(ready,failed,reason,episodeWait,totalWait);
    }
}

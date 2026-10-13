package io.github.campione01.mineclientbridge;

import java.util.function.IntPredicate;

/** A bounded pause in native combat, never a movement or attack permission. */
final class CombatRecovery {
    static final int MAX_EPISODE_TICKS = 20;
    static final int REQUIRED_SETTLED_SAMPLES = 2;
    static final double MAX_HORIZONTAL_SPEED = .03;
    static final double MAX_VERTICAL_SPEED = .08;
    record Motion(double x, double y, double z, double vx, double vy, double vz, boolean onGround) {
        boolean finite() {
            return Double.isFinite(x) && Double.isFinite(y) && Double.isFinite(z)
                    && Double.isFinite(vx) && Double.isFinite(vy) && Double.isFinite(vz);
        }
        double heightOffset() { return Math.abs(y - Math.rint(y)); }
        boolean settled() {
            return onGround && heightOffset() <= .05 && Math.hypot(vx, vz) <= MAX_HORIZONTAL_SPEED
                    && Math.abs(vy) <= MAX_VERTICAL_SPEED;
        }
    }
    enum State { CONTINUE, WAIT, RECOVERED, FAILED }
    record Result(State state, String reason) { }

    private int startTick = -1, lastSampleTick = -1;
    private int episodes, episodeTicks, totalTicks, settledSamples, completed;
    private String reason = "not_recovering";

    Result sample(int tick, Motion motion, int direction, IntPredicate freshCorridorClear) {
        if (!motion.finite()) return result(State.FAILED, "invalid_combat_motion");
        if (!active() && motion.onGround()) return result(State.CONTINUE, "not_recovering");
        if (!active()) { startTick = tick; episodes++; settledSamples = 0; }
        // Airborne samples and interrupted settlement never renew this episode.
        episodeTicks = tick - startTick + 1;
        if (tick <= lastSampleTick || episodeTicks > MAX_EPISODE_TICKS)
            return result(State.FAILED, "airborne_recovery_timeout");
        boolean consecutive = lastSampleTick == tick - 1;
        lastSampleTick = tick;
        totalTicks++;
        if (motion.onGround() && motion.heightOffset() > .05)
            return result(State.FAILED, "unsupported_recovery_pose");
        settledSamples = motion.settled() ? (consecutive ? settledSamples + 1 : 1) : 0;
        if (settledSamples >= REQUIRED_SETTLED_SAMPLES) {
            // Caller reads the entire live corridor from the current landed pose.
            // A stationary continuation still checks its full occupied footprint.
            if (!freshCorridorClear.test(direction))
                return result(State.FAILED, "recovery_landing_corridor_blocked");
            startTick = -1;
            completed++;
            return result(State.RECOVERED, "airborne_recovery_complete");
        }
        if (episodeTicks >= MAX_EPISODE_TICKS)
            return result(State.FAILED, "airborne_recovery_timeout");
        return result(State.WAIT, motion.onGround() ? "waiting_landing_settle" : "waiting_airborne_recovery");
    }

    private Result result(State state, String value) { reason = value; return new Result(state, value); }
    boolean active() { return startTick >= 0; }
    int episodes() { return episodes; }
    int episodeTicks() { return episodeTicks; }
    int totalTicks() { return totalTicks; }
    int settledSamples() { return settledSamples; }
    int completed() { return completed; }
    String reason() { return reason; }
}

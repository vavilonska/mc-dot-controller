package io.github.campione01.mineclientbridge;

/** Deterministic local pursuit policy. It never owns inputs or the action deadline. */
final class CombatPursuit {
    static final long WINDOW_NANOS = 1_000_000_000L;
    static final long STALL_NANOS = 3_000_000_000L;
    static final long RETREAT_LIMIT_NANOS = 6_000_000_000L;
    static final int DEFEND_TICKS = 8, ADVANCE_TICKS = 12;
    private static final double CLOSING_EPSILON = .04, ADVANCE_EPSILON = .10;

    record Sample(double playerX, double playerZ, double targetX, double targetZ) {
        boolean finite() {
            return Double.isFinite(playerX) && Double.isFinite(playerZ)
                    && Double.isFinite(targetX) && Double.isFinite(targetZ);
        }
        double distance() { return Math.hypot(targetX-playerX, targetZ-playerZ); }
    }
    record Result(boolean failed, boolean defend, String reason, String progress,
                  double windowClosing, double windowPlayerAdvance, double windowTargetAdvance,
                  long noClosingNanos, long noAdvanceNanos, long totalNonClosingNanos, int cycleTick) { }

    private Sample anchor;
    private long windowStart, lastClosing, lastAdvance, lastSample, totalNonClosing;
    private int firstTick, lastTick;
    private boolean targetRetreating;
    private double windowClosing, windowPlayerAdvance, windowTargetAdvance;
    private String progress = "starting";

    /** Fresh target reach is progress, but cannot refund prior unproductive windows. */
    void reached() { anchor = null; }

    /** Recovery is not closing evidence; conservatively charge its unfinished window. */
    void rebaseAfterRecovery(long now) {
        if (anchor != null) totalNonClosing += Math.max(0, now-windowStart);
        anchor = null;
    }

    Result sample(int tick, long now, Sample current, boolean cadence) {
        if (current == null || !current.finite() || !Double.isFinite(current.distance()) || tick < 0)
            return failure("invalid_pursuit_sample");
        if (anchor == null) {
            anchor = current;
            windowStart = lastClosing = lastAdvance = lastSample = now;
            firstTick = lastTick = tick;
            windowClosing = windowPlayerAdvance = windowTargetAdvance = 0;
            targetRetreating = false;
            progress = "starting";
        } else {
            if (now < lastSample || tick < lastTick) return failure("invalid_pursuit_clock");
            lastSample = now; lastTick = tick;
            if (now-windowStart >= WINDOW_NANOS) {
                double distance = anchor.distance();
                double ux = distance > .01 ? (anchor.targetX-anchor.playerX)/distance : 0;
                double uz = distance > .01 ? (anchor.targetZ-anchor.playerZ)/distance : 0;
                windowClosing = distance-current.distance();
                windowPlayerAdvance = (current.playerX-anchor.playerX)*ux + (current.playerZ-anchor.playerZ)*uz;
                windowTargetAdvance = (current.targetX-anchor.targetX)*ux + (current.targetZ-anchor.targetZ)*uz;
                boolean closing = windowClosing >= CLOSING_EPSILON;
                boolean advancing = windowPlayerAdvance >= ADVANCE_EPSILON;
                targetRetreating = advancing && windowTargetAdvance >= ADVANCE_EPSILON;
                if (closing) lastClosing = now;
                else totalNonClosing += now-windowStart;
                if (advancing) lastAdvance = now;
                progress = closing ? "closing_locally" : targetRetreating ? "target_retreating"
                        : advancing ? "advancing_without_closure" : "no_forward_progress";
                // Each one-second observation window replaces its own reference. An
                // old all-time minimum cannot reject a genuine renewed approach.
                anchor = current; windowStart = now;
            }
        }
        long noClosing = now-lastClosing, noAdvance = now-lastAdvance;
        int cycle = (int)(((long)tick-firstTick) % (DEFEND_TICKS+ADVANCE_TICKS));
        String failure = null;
        if (noClosing >= STALL_NANOS) {
            if (noAdvance >= STALL_NANOS) failure = "approach_stalled";
            else if (!targetRetreating) failure = "no_closing_progress";
            else if (noClosing >= RETREAT_LIMIT_NANOS) failure = "target_retreat_no_closure";
        }
        if (failure == null && totalNonClosing >= RETREAT_LIMIT_NANOS)
            failure = "pursuit_no_closure_budget";
        boolean defend = cadence && cycle < DEFEND_TICKS;
        return new Result(failure != null, defend, failure != null ? failure
                : defend ? "approach_defending" : "approaching", progress,
                windowClosing, windowPlayerAdvance, windowTargetAdvance, noClosing, noAdvance, totalNonClosing, cycle);
    }

    private Result failure(String reason) {
        return new Result(true, false, reason, "invalid", 0, 0, 0, 0, 0, totalNonClosing, 0);
    }
}

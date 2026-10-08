package io.github.campione01.mineclientbridge;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/**
 * Pure, deliberately conservative client-observation safety policy. No inputs, world access,
 * server fuse inference, multikill claim, or guarantee of a safe escape belongs in this class.
 * The live adapter must supply a fresh snapshot before any aiming, movement, or attack.
 */
final class CombatThreats {
    static final int MAX_OBSERVED = 128;
    static final int MAX_EXAMINED = 1024;
    static final long MAX_SNAPSHOT_AGE_NANOS = 150_000_000L;
    static final double DANGER_RADIUS = 8.0;
    static final double OBSERVATION_RADIUS = 16.0;
    static final double ESCAPE_IMPROVEMENT = .1;
    private static final double EPSILON = 1e-7;
    // Wider than the ordinary sword-sweep expansion; allies and unknown collateral are excluded.
    private static final double SWEEP_HORIZONTAL_MARGIN = 1.5;
    private static final Set<String> ATTACK_TYPES = Set.of(
            "minecraft:zombie", "minecraft:husk", "minecraft:zombie_villager",
            "minecraft:skeleton", "minecraft:stray", "minecraft:bogged");
    private static final Set<String> KNOWN_DANGEROUS_TYPES = Set.of(
            "minecraft:creeper", "minecraft:spider", "minecraft:cave_spider", "minecraft:enderman",
            "minecraft:witch", "minecraft:drowned", "minecraft:phantom", "minecraft:slime",
            "minecraft:magma_cube", "minecraft:blaze", "minecraft:ghast", "minecraft:guardian",
            "minecraft:elder_guardian", "minecraft:silverfish", "minecraft:endermite",
            "minecraft:pillager", "minecraft:vindicator", "minecraft:evoker", "minecraft:vex",
            "minecraft:ravager", "minecraft:piglin", "minecraft:piglin_brute", "minecraft:zombified_piglin",
            "minecraft:hoglin", "minecraft:zoglin", "minecraft:wither_skeleton", "minecraft:breeze",
            "minecraft:warden", "minecraft:wither", "minecraft:ender_dragon");

    /** Position and radius are observed geometry; dangerous also includes adapter Enemy/NeutralMob. */
    record Observed(int entityId, String uuid, String type, double x, double y, double z,
                    double radius, boolean dangerous, boolean alive) {
        boolean valid() {
            return entityId >= 0 && uuid != null && !uuid.isBlank() && type != null && !type.isBlank()
                    && finite(x, y, z, radius) && radius >= 0 && radius <= 64;
        }
        boolean isDangerous() { return dangerous || observableThreat(type); }
    }

    /** Defensive bounded copy. Unknown, malformed, and oversized snapshots remain refusals. */
    record Snapshot(List<Observed> entities, long capturedNanos, int capturedTick,
                    boolean truncated, boolean known) {
        Snapshot {
            if (entities == null) {
                entities = List.of();
                known = false;
            } else {
                if (entities.size() > MAX_OBSERVED) truncated = true;
                var bounded = new ArrayList<Observed>(Math.min(entities.size(), MAX_OBSERVED));
                for (int i = 0; i < Math.min(entities.size(), MAX_OBSERVED); i++) bounded.add(entities.get(i));
                entities = Collections.unmodifiableList(bounded);
            }
        }
        int count() { return entities.size(); }
    }

    record Gate(boolean stop, String reason, int emergencyId, String emergencyUuid,
                int snapshotCount, boolean truncated, boolean fresh, boolean riskRemaining) { }

    /** minimumClearance measures the whole segment; endpointClearance is useful to rank candidates. */
    record Route(boolean safe, String reason, double minimumClearance, double endpointClearance,
                 int emergencyId) { }

    static boolean supportsAttack(String type) { return ATTACK_TYPES.contains(canonical(type)); }
    static boolean observableThreat(String type) {
        String name = canonical(type);
        return ATTACK_TYPES.contains(name) || KNOWN_DANGEROUS_TYPES.contains(name);
    }
    /** Empty collateral allowlist: even another supported attacker must never be swept incidentally. */
    static boolean allowsSweepCollateral(String type) { return false; }

    static Gate evaluate(Snapshot snapshot, long now, int tick, double playerX, double playerY,
                         double playerZ, int targetId, String targetUuid, HealthGuard.Result health) {
        String invalid = snapshotProblem(snapshot, now, tick);
        if (invalid != null) return gate(snapshot, now, tick, true, invalid, null, true);
        if (!finite(playerX, playerY, playerZ))
            return gate(snapshot, now, tick, true, "invalid_player_position", null, true);
        boolean risk = snapshot.entities.stream().anyMatch(e -> e.alive && e.isDangerous());
        if (health == null || !health.known())
            return gate(snapshot, now, tick, true, health == null ? "health_unknown" : health.reason(), null, true);
        if (health.interrupted()) return gate(snapshot, now, tick, true, health.reason(), null, true);

        Observed nearest = null, creeper = null, unsupported = null, enderman = null, nonTargetNear = null;
        int nearbyDangerCount = 0;
        for (Observed e : snapshot.entities) {
            if (!e.alive || !e.isDangerous()) continue;
            double clearance = clearance(playerX, playerZ, e);
            nearest = nearer(nearest, e, playerX, playerZ);
            // No gaze-aware planner exists: every observed Enderman blocks aiming, even beyond 8.
            if (canonical(e.type).equals("minecraft:enderman")) enderman = nearer(enderman, e, playerX, playerZ);
            if (clearance <= DANGER_RADIUS) {
                nearbyDangerCount++;
                if (targetId >= 0 && !sameIdentity(e, targetId, targetUuid))
                    nonTargetNear = nearer(nonTargetNear, e, playerX, playerZ);
                if (canonical(e.type).equals("minecraft:creeper")) creeper = nearer(creeper, e, playerX, playerZ);
                if (!supportsAttack(e.type)) unsupported = nearer(unsupported, e, playerX, playerZ);
            }
        }
        if (creeper != null) return gate(snapshot, now, tick, true, "critical_creeper_near", creeper, true);
        if (enderman != null) return gate(snapshot, now, tick, true, "enderman_gaze_unplanned", enderman, true);
        if (unsupported != null) return gate(snapshot, now, tick, true, "unsupported_threat_near", unsupported, true);
        if (nearbyDangerCount > 1) return gate(snapshot, now, tick, true, "multiple_threats_near", nearest, true);
        if (nonTargetNear != null) return gate(snapshot, now, tick, true, "non_target_threat_near", nonTargetNear, true);
        if (targetId >= 0) {
            Observed target = selected(snapshot, targetId, targetUuid);
            if (target == null || !target.alive)
                return gate(snapshot, now, tick, true, "target_missing_from_snapshot", null, risk);
            if (!supportsAttack(target.type))
                return gate(snapshot, now, tick, true, "unsupported_attack_target", target, true);
        }
        return gate(snapshot, now, tick, false, "single_target_policy_clear", null, risk);
    }

    /** Must be rechecked immediately before sword attack; no incidental living target is allowed. */
    static Gate sweep(Snapshot snapshot, long now, int tick, int targetId, String targetUuid) {
        String invalid = snapshotProblem(snapshot, now, tick);
        if (invalid != null) return gate(snapshot, now, tick, true, invalid, null, true);
        Observed target = selected(snapshot, targetId, targetUuid);
        if (target == null || !target.alive)
            return gate(snapshot, now, tick, true, "target_missing_from_snapshot", null, true);
        if (!supportsAttack(target.type))
            return gate(snapshot, now, tick, true, "unsupported_attack_target", target, true);
        Observed collateral = null;
        for (Observed e : snapshot.entities) {
            if (!e.alive || sameIdentity(e, targetId, targetUuid)) continue;
            // Sweep selection is box-shaped: a circle can miss diagonal collateral. Height is
            // intentionally not filtered because this bounded record does not certify full AABBs.
            double expanded = target.radius + e.radius + SWEEP_HORIZONTAL_MARGIN;
            if (Math.abs(e.x - target.x) <= expanded && Math.abs(e.z - target.z) <= expanded
                    && !allowsSweepCollateral(e.type)) {
                if (collateral == null || compareIdentity(e, collateral) < 0) collateral = e;
            }
        }
        return collateral == null ? gate(snapshot, now, tick, false, "sweep_collateral_clear", null, true)
                : gate(snapshot, now, tick, true, "sweep_collateral_forbidden", collateral, true);
    }

    /** A normal route must start outside 8 blocks and never reduce ANY non-target threat clearance. */
    static Route route(Snapshot snapshot, long now, int tick, double fromX, double fromZ,
                       double toX, double toZ, int targetId, String targetUuid) {
        return checkRoute(snapshot, now, tick, fromX, fromZ, toX, toZ, targetId, targetUuid, false);
    }

    /** A withdrawal may begin inside danger, but has no exemption for the selected target. */
    static Route escapeRoute(Snapshot snapshot, long now, int tick, double fromX, double fromZ,
                             double toX, double toZ) {
        return checkRoute(snapshot, now, tick, fromX, fromZ, toX, toZ, -1, "", true);
    }

    private static Route checkRoute(Snapshot snapshot, long now, int tick, double fromX, double fromZ,
                                    double toX, double toZ, int targetId, String targetUuid, boolean escape) {
        String invalid = snapshotProblem(snapshot, now, tick);
        if (invalid != null) return routeFailure(invalid, -1, Double.NaN, Double.NaN);
        if (!finite(fromX, fromZ, toX, toZ))
            return routeFailure("invalid_route_position", -1, Double.NaN, Double.NaN);
        if (!escape && targetId >= 0) {
            Observed target = selected(snapshot, targetId, targetUuid);
            if (target == null || !target.alive)
                return routeFailure("target_missing_from_snapshot", targetId, Double.NaN, Double.NaN);
            if (!supportsAttack(target.type))
                return routeFailure("unsupported_attack_target", targetId, Double.NaN, Double.NaN);
        }
        if (escape) for (Observed e : snapshot.entities)
            if (e.alive && canonical(e.type).equals("minecraft:enderman"))
                return routeFailure("enderman_gaze_unplanned", e.entityId, Double.NaN, Double.NaN);
        double minimum = Double.POSITIVE_INFINITY, endpoint = Double.POSITIVE_INFINITY;
        Observed nearest = null;
        for (Observed e : snapshot.entities) {
            if (!e.alive || !e.isDangerous() || (!escape && sameIdentity(e, targetId, targetUuid))) continue;
            double start = clearance(fromX, fromZ, e);
            double end = clearance(toX, toZ, e);
            double swept = segmentClearance(fromX, fromZ, toX, toZ, e);
            if (!finite(start, end, swept)) return routeFailure("invalid_route_geometry", e.entityId, Double.NaN, Double.NaN);
            minimum = Math.min(minimum, swept);
            endpoint = Math.min(endpoint, end);
            nearest = nearer(nearest, e, fromX, fromZ);
            if (!escape && start <= DANGER_RADIUS)
                return routeFailure("route_starts_near_nontarget_threat", e.entityId, minimum, endpoint);
            if (swept + EPSILON < start)
                return routeFailure("route_reduces_threat_clearance", e.entityId, minimum, endpoint);
        }
        if (escape && nearest != null
                && clearance(toX, toZ, nearest) + EPSILON < clearance(fromX, fromZ, nearest) + ESCAPE_IMPROVEMENT)
            return routeFailure("escape_no_clearance_progress", nearest.entityId, minimum, endpoint);
        return new Route(true, escape ? "escape_clearance_improves" : "route_threat_clearance_clear", minimum, endpoint, -1);
    }

    /** Exact closest point on a straight horizontal segment, not an endpoint-only approximation. */
    private static double segmentClearance(double ax, double az, double bx, double bz, Observed e) {
        double dx = bx - ax, dz = bz - az, denominator = dx * dx + dz * dz;
        double fraction = denominator == 0 ? 0 : Math.max(0, Math.min(1, ((e.x - ax) * dx + (e.z - az) * dz) / denominator));
        return Math.hypot(ax + fraction * dx - e.x, az + fraction * dz - e.z) - e.radius;
    }
    private static double clearance(double x, double z, Observed e) { return Math.hypot(x - e.x, z - e.z) - e.radius; }
    private static String canonical(String type) {
        return type == null ? "" : type.contains(":") ? type : "minecraft:" + type;
    }
    private static boolean finite(double... values) {
        for (double value : values) if (!Double.isFinite(value)) return false;
        return true;
    }
    private static boolean sameIdentity(Observed e, int entityId, String uuid) {
        return e.entityId == entityId && e.uuid.equals(uuid);
    }
    private static Observed selected(Snapshot snapshot, int id, String uuid) {
        for (Observed e : snapshot.entities) if (sameIdentity(e, id, uuid)) return e;
        return null;
    }
    private static Observed nearer(Observed a, Observed b, double x, double z) {
        if (a == null) return b;
        int distanceOrder = Double.compare(clearance(x, z, a), clearance(x, z, b));
        return distanceOrder > 0 || distanceOrder == 0 && compareIdentity(b, a) < 0 ? b : a;
    }
    private static int compareIdentity(Observed a, Observed b) {
        int id = Integer.compare(a.entityId, b.entityId);
        return id != 0 ? id : a.uuid.compareTo(b.uuid);
    }
    private static boolean fresh(Snapshot snapshot, long now, int tick) {
        if (snapshot == null || snapshot.capturedTick < 0 || tick != snapshot.capturedTick) return false;
        long age = now - snapshot.capturedNanos;
        return age >= 0 && age <= MAX_SNAPSHOT_AGE_NANOS;
    }
    static String snapshotProblem(Snapshot snapshot, long now, int tick) {
        if (snapshot == null || !snapshot.known) return "threat_snapshot_unknown";
        if (snapshot.truncated) return "threat_snapshot_truncated";
        if (!fresh(snapshot, now, tick)) return "threat_snapshot_stale";
        var ids = new HashSet<Integer>();
        var uuids = new HashSet<String>();
        for (Observed e : snapshot.entities) {
            if (e == null || !e.valid() || !ids.add(e.entityId) || !uuids.add(e.uuid))
                return "threat_snapshot_invalid";
        }
        return null;
    }
    private static Gate gate(Snapshot snapshot, long now, int tick, boolean stop, String reason,
                             Observed emergency, boolean risk) {
        return new Gate(stop, reason, emergency == null ? -1 : emergency.entityId,
                emergency == null ? "" : emergency.uuid, snapshot == null ? 0 : snapshot.count(),
                snapshot != null && snapshot.truncated, fresh(snapshot, now, tick), risk);
    }
    private static Route routeFailure(String reason, int id, double minimum, double endpoint) {
        return new Route(false, reason, minimum, endpoint, id);
    }

    /**
     * Tick-aware bounded rolling-loss monitor, retained for one action (including recovery).
     * 14 HP / 4 HP in one second are conservative, uncalibrated cutoffs, not survival guarantees.
     * Healing never refunds observed damage; a safety interruption is irrevocably latched here.
     */
    static final class HealthGuard {
        static final int CAPACITY = 24;
        static final long WINDOW_NANOS = 1_000_000_000L;
        static final long MAX_GAP_NANOS = 150_000_000L;
        static final int MAX_TICK_GAP = 3;
        static final double LOW_HEALTH = 14.0, MAX_ROLLING_LOSS = 4.0;
        static final double LOSS_EPSILON = EPSILON;
        record Result(boolean interrupted, String reason, double health, double damageInWindow,
                      int sampleCount, boolean known) { }

        /**
         * A read-only trace of this call, not a new safety decision. A valid diagnostic sample
         * has finite nonnegative health, a nonnegative tick, and monotonic observed clocks.
         * A gap still supplies a valid sample, but cannot certify continuity. In particular,
         * this trace keeps advancing after interruption without modifying the latched policy.
         * Null previous/delta fields mean that no previous valid diagnostic sample exists.
         */
        record SampleDiagnostic(int sampleTick, long sampleNanos, double observedHealth,
                                Integer previousValidSampleTick, Long previousValidSampleNanos,
                                Long sampleDeltaNanos, Long tickDelta, long sameTickElapsedNanos,
                                boolean dataValid, boolean clockValid, boolean wallGap,
                                boolean tickGap, boolean frozenTick, String detail) {
            boolean valid() { return dataValid && clockValid; }
            boolean continuous() {
                return previousValidSampleTick != null && valid() && !wallGap && !tickGap && !frozenTick;
            }
        }

        /** Trigger metrics are immutable; current describes the most recent sample call. */
        record Diagnostics(SampleDiagnostic current, SampleDiagnostic trigger,
                           Result triggerResult, boolean latchTriggeredNow) {
            boolean latched() { return triggerResult != null; }
        }

        private final long[] times = new long[CAPACITY];
        private final double[] losses = new double[CAPACITY];
        private int head, size, lastTick = -1;
        private long lastNanos, tickStartedNanos;
        private double lastHealth, damage;
        private Result latched;
        private SampleDiagnostic diagnosticPrevious, triggerDiagnostic;
        private long diagnosticTickStartedNanos;
        private Diagnostics diagnostics;

        Result sample(int tick, long now, double health) {
            SampleDiagnostic current = describe(tick, now, health);
            boolean alreadyLatched = latched != null;
            Result result = samplePolicy(tick, now, health);
            boolean triggeredNow = !alreadyLatched && result.interrupted();
            if (triggeredNow) triggerDiagnostic = current;
            diagnostics = new Diagnostics(current, triggerDiagnostic, latched, triggeredNow);
            if (current.valid()) {
                if (diagnosticPrevious == null || tick != diagnosticPrevious.sampleTick())
                    diagnosticTickStartedNanos = now;
                diagnosticPrevious = current;
            }
            return result;
        }

        Diagnostics diagnostics() { return diagnostics; }

        private SampleDiagnostic describe(int tick, long now, double health) {
            Integer previousTick = diagnosticPrevious == null ? null : diagnosticPrevious.sampleTick();
            Long previousNanos = diagnosticPrevious == null ? null : diagnosticPrevious.sampleNanos();
            Long sampleDelta = previousNanos == null ? null : now - previousNanos;
            Long tickDelta = previousTick == null ? null : (long) tick - previousTick;
            long sameTickElapsed = previousTick != null && tick == previousTick
                    ? now - diagnosticTickStartedNanos : 0;
            boolean dataValid = tick >= 0 && Double.isFinite(health) && health >= 0;
            boolean clockValid = previousTick == null || tickDelta >= 0 && sampleDelta >= 0;
            boolean wallGap = sampleDelta != null && sampleDelta > MAX_GAP_NANOS;
            boolean tickGap = tickDelta != null && tickDelta > MAX_TICK_GAP;
            boolean frozenTick = previousTick != null && tick == previousTick
                    && sameTickElapsed > MAX_GAP_NANOS;
            String detail;
            if (!dataValid) detail = tick < 0 ? "invalid_tick" : "invalid_health";
            else if (!clockValid) detail = tickDelta < 0 && sampleDelta < 0
                    ? "tick_and_wall_clock_regressed"
                    : tickDelta < 0 ? "tick_clock_regressed" : "wall_clock_regressed";
            else if (wallGap || tickGap || frozenTick) {
                var gaps = new ArrayList<String>(3);
                if (wallGap) gaps.add("wall_gap");
                if (tickGap) gaps.add("tick_gap");
                if (frozenTick) gaps.add("frozen_tick");
                detail = String.join("+", gaps);
            } else detail = previousTick == null ? "first_valid_sample" : "continuous_sample";
            return new SampleDiagnostic(tick, now, health, previousTick, previousNanos,
                    sampleDelta, tickDelta, sameTickElapsed, dataValid, clockValid,
                    wallGap, tickGap, frozenTick, detail);
        }

        private Result samplePolicy(int tick, long now, double health) {
            if (latched != null) return latched;
            if (tick < 0 || !Double.isFinite(health) || health < 0)
                return latch("health_data_unknown", health, false);
            if (lastTick >= 0 && (tick < lastTick || now - lastNanos < 0))
                return latch("health_clock_invalid", health, false);
            if (lastTick >= 0 && (now - lastNanos > MAX_GAP_NANOS
                    || tick == lastTick && now - tickStartedNanos > MAX_GAP_NANOS
                    || (long)tick - lastTick > MAX_TICK_GAP))
                return latch("health_observation_gap", health, false);
            if (health <= LOW_HEALTH) return latch("low_health", health, true);

            while (size > 0 && now - times[head] > WINDOW_NANOS) {
                damage -= losses[head];
                head = (head + 1) % CAPACITY;
                size--;
            }
            double loss = lastTick < 0 ? 0 : Math.max(0, lastHealth - health);
            if (tick == lastTick && size > 0) {
                // Several checks in one tick consume one ring slot and still retain every loss.
                int newest = (head + size - 1) % CAPACITY;
                times[newest] = now;
                losses[newest] += loss;
            } else {
                if (size == CAPACITY) return latch("health_history_overflow", health, false);
                int tail = (head + size) % CAPACITY;
                times[tail] = now;
                losses[tail] = loss;
                size++;
                tickStartedNanos = now;
            }
            damage = Math.max(0, damage + loss);
            lastTick = tick;
            lastNanos = now;
            lastHealth = health;
            if (damage + LOSS_EPSILON >= MAX_ROLLING_LOSS) return latch("rapid_health_loss", health, true);
            return new Result(false, "health_within_limits", health, damage, size, true);
        }
        private Result latch(String reason, double health, boolean known) {
            latched = new Result(true, reason, health, Math.max(0, damage), size, known);
            return latched;
        }
    }
}

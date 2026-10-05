package io.github.campione01.mineclientbridge;

import java.util.Objects;
import java.util.Set;
import java.util.UUID;

/** Pure fail-closed validation, not target selection or combat planning. */
final class GuardedAction {
    static final int SCHEMA = 1;
    static final int MAX_TTL_MS = 250;
    static final double MAX_RANGE = 2.75;
    static final double MAX_YAW_STEP = 30.0;
    static final double MAX_PITCH_STEP = 20.0;
    static final Set<String> HOSTILE_TYPES = Set.of(
            "minecraft:zombie", "minecraft:husk", "minecraft:drowned",
            "minecraft:skeleton", "minecraft:stray", "minecraft:bogged");
    static final Set<String> WEAPON_TYPES = Set.of("minecraft:wooden_axe", "minecraft:stone_axe",
            "minecraft:iron_axe", "minecraft:golden_axe", "minecraft:diamond_axe", "minecraft:netherite_axe");

    record Request(String action, String worldGeneration, String playerUuid,
                   String targetUuid, String crosshairUuid, int ttlMs, double yaw, double pitch) {
        Request {
            require(action != null && (action.equals("look") || action.equals("attack")), "invalid_action");
            require(uuid(worldGeneration) && uuid(playerUuid) && uuid(targetUuid)
                    && (crosshairUuid == null || uuid(crosshairUuid)), "invalid_identity");
            require(ttlMs >= 1 && ttlMs <= MAX_TTL_MS, "invalid_ttl_ms");
            require(Double.isFinite(yaw) && Double.isFinite(pitch), "invalid_angles");
            if (action.equals("look")) {
                require(yaw >= -180 && yaw < 180 && pitch >= -90 && pitch <= 90, "invalid_angles");
            } else {
                require(yaw == 0 && pitch == 0, "unexpected_angles");
                require(targetUuid.equals(crosshairUuid), "attack_requires_expected_crosshair");
            }
        }
    }

    record State(String worldGeneration, String playerUuid, boolean localSurvival,
                 boolean ready, boolean weaponAllowed, String targetUuid, String targetType, boolean targetAllowed,
                 String crosshairUuid, double targetDistance, double ordinaryReach,
                 boolean lineOfSight, double yaw, double pitch) { }

    static void validate(Request request, State live) {
        require(live.ready(), "player_not_ready");
        require(live.localSurvival(), "local_survival_required");
        require(live.weaponAllowed(), "unenchanted_vanilla_axe_required");
        require(request.worldGeneration().equals(live.worldGeneration()), "world_generation_changed");
        require(request.playerUuid().equals(live.playerUuid()), "player_changed");
        require(request.targetUuid().equals(live.targetUuid()), "target_changed");
        require(Objects.equals(request.crosshairUuid(), live.crosshairUuid()), "crosshair_changed");
        require(live.targetAllowed() && live.targetType() != null
                && HOSTILE_TYPES.contains(live.targetType()), "target_not_allowed");
        require(Double.isFinite(live.targetDistance()) && live.targetDistance() >= 0
                && Double.isFinite(live.ordinaryReach()) && live.ordinaryReach() > 0
                && live.targetDistance() <= Math.min(MAX_RANGE, live.ordinaryReach()), "target_out_of_range");
        require(live.lineOfSight(), "target_not_visible");
        if (request.action().equals("look")) {
            require(Double.isFinite(live.yaw()) && Double.isFinite(live.pitch()), "invalid_live_angles");
            require(Math.abs(wrap(request.yaw() - live.yaw())) <= MAX_YAW_STEP
                    && Math.abs(request.pitch() - live.pitch()) <= MAX_PITCH_STEP, "look_step_too_large");
        } else {
            require(request.targetUuid().equals(live.crosshairUuid()), "crosshair_changed");
        }
    }

    static boolean weaponAllowed(String type, boolean enchanted, boolean sweepCapable) {
        return type != null && WEAPON_TYPES.contains(type) && !enchanted && !sweepCapable;
    }

    static void require(boolean condition, String code) {
        if (!condition) throw new Rejected(code);
    }

    private static boolean uuid(String value) {
        if (value == null) return false;
        try { return UUID.fromString(value).toString().equals(value); }
        catch (IllegalArgumentException ignored) { return false; }
    }

    private static double wrap(double degrees) {
        double wrapped = degrees % 360.0;
        if (wrapped >= 180.0) wrapped -= 360.0;
        if (wrapped < -180.0) wrapped += 360.0;
        return wrapped;
    }

    static final class Rejected extends RuntimeException {
        Rejected(String code) { super(code); }
    }

    private GuardedAction() { }
}

package io.github.campione01.mineclientbridge;

/** Per-tick ordinary-input steering. No position, velocity or packet writes. */
final class PathSteering {
    record Step(float yaw, float forward, boolean jump, boolean reached, double distance) { }
    static Step toward(double x, double y, double z, float yaw, boolean onGround, boolean collision,
            ClientActionRequest.Point goal) {
        double dx = goal.x() - x, dz = goal.z() - z;
        double distance = Math.hypot(dx, dz);
        double dy = goal.y() - y;
        boolean reached = distance <= 0.23 && Math.abs(dy) <= 0.55;
        double targetYaw = distance < 0.025 ? yaw : Math.toDegrees(Math.atan2(-dx, dz));
        double error = Math.IEEEremainder(targetYaw - yaw, 360);
        // Smooth turning is execution timing, not a restriction on requested turns.
        float nextYaw = (float) (yaw + Math.max(-45, Math.min(45, error)));
        double residual = Math.IEEEremainder(targetYaw - nextYaw, 360);
        float forward = reached ? 0 : (float) (Math.max(0, Math.cos(Math.toRadians(residual)))
                * Math.min(1, distance / 0.45));
        boolean jump = !reached && onGround && (goal.jump() || dy > 0.5 || collision);
        return new Step(nextYaw, forward, jump, reached, Math.sqrt(dx * dx + dy * dy + dz * dz));
    }
    private PathSteering() { }
}

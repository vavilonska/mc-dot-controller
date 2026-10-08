package io.github.campione01.mineclientbridge;

import java.util.ArrayList;
import java.util.List;

/** Pure, bounded admission for a continuously translated, axis-aligned player footprint. */
final class FlatStepCorridor {
    static final double HALF_WIDTH = .31;
    static final double SAFETY_EPSILON = 1e-7;
    static final double MAX_STEP = .66;
    private static final double MAX_COORDINATE = Integer.MAX_VALUE - 2.0;

    record Pose(double x, double y, double z, boolean onGround, double yaw) { }
    record GridCell(int x, int z) { }
    enum Availability { LOADED, UNLOADED, OUT_OF_WORLD, UNKNOWN }
    record Cell(Availability availability, String id, boolean collisionKnown, boolean collisionEmpty,
                boolean fullTopSupport, String fluid, boolean hazardous) { }
    record CellRef(int x, int y, int z, String layer, String id) { }
    record Result(boolean clear, String reason, Pose pose, double dx, double dz, CellRef cell) { }
    @FunctionalInterface interface CellSource { Cell read(int x, int y, int z); }

    private FlatStepCorridor() { }

    static Result rejected(String reason, Pose pose, double dx, double dz) {
        return new Result(false, reason, pose, dx, dz, null);
    }

    static Result check(Pose pose, double dx, double dz, CellSource source) {
        if (pose == null) return rejected("not_in_world", null, dx, dz);
        if (!safeCoordinate(pose.x()) || !safeCoordinate(pose.y()) || !safeCoordinate(pose.z())
                || !Double.isFinite(pose.yaw())) return rejected("invalid_pose", pose, dx, dz);
        if (!pose.onGround()) return rejected("not_grounded", pose, dx, dz);
        if (!Double.isFinite(dx) || !Double.isFinite(dz)) return rejected("invalid_step", pose, dx, dz);
        if (Math.hypot(dx, dz) > MAX_STEP) return rejected("step_too_long", pose, dx, dz);
        if (!safeCoordinate(pose.x() + dx) || !safeCoordinate(pose.z() + dz))
            return rejected("invalid_step", pose, dx, dz);
        if (Math.abs(pose.y() - Math.rint(pose.y())) > .05)
            return rejected("unsupported_feet_height", pose, dx, dz);
        if (source == null) return rejected("missing_source", pose, dx, dz);
        int feetY = (int) Math.rint(pose.y());
        for (GridCell grid : sweptCells(pose.x(), pose.z(), dx, dz)) {
            for (int offset = -1; offset <= 1; offset++) {
                int by = feetY + offset;
                String layer = offset == -1 ? "support" : offset == 0 ? "feet" : "head";
                Cell cell;
                try { cell = source.read(grid.x(), by, grid.z()); }
                catch (RuntimeException exception) {
                    return denied("cell_read_failed", pose, dx, dz, grid, by, layer, null);
                }
                String reason;
                if (cell == null || cell.availability() == null || cell.availability() == Availability.UNKNOWN)
                    reason = "unknown_cell";
                else if (cell.availability() == Availability.UNLOADED) reason = "unloaded";
                else if (cell.availability() == Availability.OUT_OF_WORLD) reason = "out_of_world";
                else if (!cell.collisionKnown()) reason = "collision_unknown";
                else if (!"minecraft:empty".equals(cell.fluid())) reason = "fluid";
                else if (cell.hazardous()) reason = "hazard";
                else if (offset == -1 && !cell.fullTopSupport()) reason = "missing_support";
                else if (offset != -1 && !cell.collisionEmpty()) reason = layer + "_collision";
                else continue;
                return denied(reason, pose, dx, dz, grid, by, layer, cell == null ? null : cell.id());
            }
        }
        return new Result(true, "clear", pose, dx, dz, null);
    }

    private static Result denied(String reason, Pose pose, double dx, double dz, GridCell grid,
                                 int by, String layer, String id) {
        return new Result(false, reason, pose, dx, dz, new CellRef(grid.x(), by, grid.z(), layer, id));
    }

    private static boolean safeCoordinate(double value) {
        return Double.isFinite(value) && Math.abs(value) <= MAX_COORDINATE;
    }

    static List<GridCell> sweptCells(double x, double z, double dx, double dz) {
        if (!safeCoordinate(x) || !safeCoordinate(z) || !Double.isFinite(dx) || !Double.isFinite(dz)
                || Math.hypot(dx, dz) > MAX_STEP || !safeCoordinate(x + dx) || !safeCoordinate(z + dz))
            throw new IllegalArgumentException("invalid_swept_footprint");
        List<GridCell> cells = new ArrayList<>();
        double radius = HALF_WIDTH + SAFETY_EPSILON;
        // Broad phase only. Its two extra diagonal corners are not necessarily ever occupied.
        int minX = (int) Math.floor(Math.nextDown(Math.min(x, x + dx) - radius));
        int maxX = (int) Math.floor(Math.nextUp(Math.max(x, x + dx) + radius));
        int minZ = (int) Math.floor(Math.nextDown(Math.min(z, z + dz) - radius));
        int maxZ = (int) Math.floor(Math.nextUp(Math.max(z, z + dz) + radius));
        for (int bx = minX; bx <= maxX; bx++) {
            for (int bz = minZ; bz <= maxZ; bz++) {
                if (intersectsCell(x, z, dx, dz, bx, bz, radius)) cells.add(new GridCell(bx, bz));
            }
        }
        return List.copyOf(cells);
    }

    /**
     * A cell intersects the translated square iff the center segment intersects that cell
     * expanded by the square's half-width on BOTH axes (a Minkowski sum, not a circle).
     * Clipping both axes to the same time interval preserves the full continuous sweep,
     * including middle-only cells. Closed bounds plus a small OUTWARD epsilon conservatively
     * retain tangencies/roundoff; no endpoint sampling or inward footprint shrink is used.
     */
    private static boolean intersectsCell(double x, double z, double dx, double dz,
                                          int bx, int bz, double radius) {
        double[] interval = {0, 1};
        return clipAxis(x, dx, Math.nextDown(bx - radius), Math.nextUp(bx + 1.0 + radius), interval)
                && clipAxis(z, dz, Math.nextDown(bz - radius), Math.nextUp(bz + 1.0 + radius), interval);
    }

    private static boolean clipAxis(double start, double delta, double low, double high, double[] interval) {
        if (delta == 0) return start >= low && start <= high;
        double t0 = (low - start) / delta, t1 = (high - start) / delta;
        interval[0] = Math.max(interval[0], Math.min(t0, t1));
        interval[1] = Math.min(interval[1], Math.max(t0, t1));
        return interval[0] <= interval[1];
    }
}

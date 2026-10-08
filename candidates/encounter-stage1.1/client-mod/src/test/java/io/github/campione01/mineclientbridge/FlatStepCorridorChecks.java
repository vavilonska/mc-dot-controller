package io.github.campione01.mineclientbridge;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/** Pure geometry/synthetic terrain checks; sampled poses are not atomic live-game evidence. */
final class FlatStepCorridorChecks {
    private static final double[][] SAMPLES = {
            {14.5445888045, 21.7566958860, .153582657, .631595098},
            {14.5272867534, 21.8761731645, .166533214, .628304615}
    };
    private static final Set<FlatStepCorridor.GridCell> EXPECTED = Set.of(
            grid(14, 21), grid(14, 22), grid(15, 22));
    private static final FlatStepCorridor.Pose MID_POSE = new FlatStepCorridor.Pose(.6, 64, .1, true, -45);
    private static final double MID_STEP = .46;

    static void sampledDiagonalGeometry() {
        for (double[] p : SAMPLES) {
            equal(EXPECTED, cells(p[0], p[1], p[2], p[3]), "sampled diagonal must exclude unswept (15,21)");
        }
    }

    static void sampledOffCorridorGrassDoesNotBlock() {
        for (double[] p : SAMPLES) {
            var result = FlatStepCorridor.check(new FlatStepCorridor.Pose(p[0], 64, p[1], true, -14),
                    p[2], p[3], (x, y, z) -> x == 15 && y == 64 && z == 21
                            ? solid("minecraft:grass_block") : dryFlat(x, y, z));
            require(result.clear(), "unswept grass must not block: " + result);
        }
    }

    static void reflectedReversedAndSwappedSweeps() {
        for (double[] p : SAMPLES) {
            equal(EXPECTED, cells(p[0] + p[2], p[1] + p[3], -p[2], -p[3]), "reverse sweep");
            for (int sx : new int[]{-1, 1}) for (int sz : new int[]{-1, 1}) {
                Set<FlatStepCorridor.GridCell> reflected = new HashSet<>(), swapped = new HashSet<>();
                for (var cell : EXPECTED) {
                    int x = sx == 1 ? cell.x() : -cell.x() - 1;
                    int z = sz == 1 ? cell.z() : -cell.z() - 1;
                    reflected.add(grid(x, z)); swapped.add(grid(z, x));
                }
                equal(reflected, cells(p[0] * sx, p[1] * sz, p[2] * sx, p[3] * sz), "axis reflection");
                equal(swapped, cells(p[1] * sz, p[0] * sx, p[3] * sz, p[2] * sx), "axis swap");
            }
        }
    }

    static void forwardBackwardAxisAlignedAndStationary() {
        equal(Set.of(grid(0, 0), grid(1, 0)), cells(.5, .5, .65, 0), "forward x");
        equal(Set.of(grid(-1, 0), grid(0, 0)), cells(.5, .5, -.65, 0), "backward x");
        equal(Set.of(grid(0, 0), grid(0, 1)), cells(.5, .5, 0, .65), "forward z");
        equal(Set.of(grid(0, -1), grid(0, 0)), cells(.5, .5, 0, -.65), "backward z");
        equal(Set.of(grid(0, 0)), cells(.5, .5, 0, -0.0), "stationary full footprint");
        equal(Set.of(grid(-1, -1), grid(-1, 0), grid(0, -1), grid(0, 0)),
                cells(0, 0, 0, 0), "stationary grid vertex");
    }

    static void squareFootprintNotCircle() {
        require(Math.hypot(.25, .25) > FlatStepCorridor.HALF_WIDTH, "fixture outside circle");
        require(cells(.25, .25, 0, 0).contains(grid(-1, -1)), "square corner is occupied, despite outside circle");
        var result = FlatStepCorridor.check(new FlatStepCorridor.Pose(.25, 64, .25, true, 0), 0, 0,
                (x, y, z) -> x == -1 && z == -1 && y == 64 ? solid("minecraft:stone") : dryFlat(x, y, z));
        equal("feet_collision", result.reason(), "square-corner obstruction rejected");
    }

    static void tangenciesAndOutwardEpsilon() {
        double eps = FlatStepCorridor.SAFETY_EPSILON;
        require(cells(.69, .5, 0, 0).contains(grid(1, 0)), "positive exact edge tangency");
        require(cells(.69 - eps / 2, .5, 0, 0).contains(grid(1, 0)), "positive outward safety epsilon");
        require(!cells(.69 - 2 * eps, .5, 0, 0).contains(grid(1, 0)), "separated beyond epsilon");
        require(cells(.31, .5, 0, 0).contains(grid(-1, 0)), "negative exact edge tangency");
        require(cells(.31 + eps / 2, .5, 0, 0).contains(grid(-1, 0)), "negative outward safety epsilon");
        require(!cells(.31 + 2 * eps, .5, 0, 0).contains(grid(-1, 0)), "negative separated beyond epsilon");
        require(cells(.04, .5, .65, 0).contains(grid(1, 0)), "last instant tangency included");
        require(cells(.6, .22, .46, .46).contains(grid(1, -1)), "middle instant corner tangency");
        require(cells(.6, .22 + eps, .46, .46).contains(grid(1, -1)), "diagonal safety epsilon retained");
        require(!cells(.6, .22 + 4 * eps, .46, .46).contains(grid(1, -1)), "separated diagonal corner excluded");
    }

    static void middleOnlyCellsNeedSupport() {
        var middle = grid(1, -1);
        require(!cells(.6, .1, 0, 0).contains(middle), "not in start footprint");
        require(!cells(1.06, .56, 0, 0).contains(middle), "not in final footprint");
        require(cells(.6, .1, .46, .46).contains(middle), "continuously swept between endpoints");
        deniedMiddle(63, air(), "missing_support");
    }

    static void middleWaterRejectedAtEveryLayer() {
        for (int y = 63; y <= 65; y++)
            deniedMiddle(y, new FlatStepCorridor.Cell(FlatStepCorridor.Availability.LOADED,
                    "minecraft:water", true, true, true, "minecraft:water", true), "fluid");
    }

    static void middleLavaRejectedAtEveryLayer() {
        for (int y = 63; y <= 65; y++)
            deniedMiddle(y, new FlatStepCorridor.Cell(FlatStepCorridor.Availability.LOADED,
                    "minecraft:lava", true, true, true, "minecraft:lava", true), "fluid");
    }

    static void middleUnknownAndUnloadedRejected() {
        for (int y = 63; y <= 65; y++) {
            deniedMiddle(y, new FlatStepCorridor.Cell(FlatStepCorridor.Availability.UNLOADED,
                    null, false, false, false, null, false), "unloaded");
            deniedMiddle(y, new FlatStepCorridor.Cell(FlatStepCorridor.Availability.OUT_OF_WORLD,
                    null, false, false, false, null, false), "out_of_world");
            deniedMiddle(y, new FlatStepCorridor.Cell(FlatStepCorridor.Availability.UNKNOWN,
                    null, true, true, true, "minecraft:empty", false), "unknown_cell");
            deniedMiddle(y, new FlatStepCorridor.Cell(FlatStepCorridor.Availability.LOADED,
                    "mod:unknown_shape", false, true, true, "minecraft:empty", false), "collision_unknown");
            deniedMiddle(y, null, "unknown_cell");
        }
    }

    static void middleHazardsRejectedAtEveryLayer() {
        for (int y = 63; y <= 65; y++) {
            for (String id : List.of("minecraft:magma_block", "minecraft:fire", "minecraft:cactus",
                    "minecraft:powder_snow", "minecraft:cobweb", "minecraft:campfire"))
                deniedMiddle(y, new FlatStepCorridor.Cell(FlatStepCorridor.Availability.LOADED,
                        id, true, true, true, "minecraft:empty", true), "hazard");
        }
    }

    static void middleFeetAndHeadCollisionsRejected() {
        deniedMiddle(64, solid("minecraft:grass_block"), "feet_collision");
        deniedMiddle(65, solid("minecraft:stone"), "head_collision");
    }

    static void fractionalFeetRequireIntegerTolerance() {
        for (double y : new double[]{64, 64.05, 63.95}) {
            var result = FlatStepCorridor.check(new FlatStepCorridor.Pose(.5, y, .5, true, 0), 0, 0,
                    FlatStepCorridorChecks::dryFlat);
            require(result.clear(), "supported integer tolerance: " + result);
        }
        for (double y : new double[]{64.050001, 63.949999, 64.5, 64.9375}) {
            var result = FlatStepCorridor.check(new FlatStepCorridor.Pose(.5, y, .5, true, 0), 0, 0,
                    FlatStepCorridorChecks::mustNotRead);
            equal("unsupported_feet_height", result.reason(), "fractional/slab feet rejected");
        }
    }

    static void invalidPoseAndStepFailBeforeAnyRead() {
        for (double invalid : new double[]{Double.NaN, Double.POSITIVE_INFINITY, Double.NEGATIVE_INFINITY, 1e100, -1e100}) {
            for (var pose : List.of(new FlatStepCorridor.Pose(invalid, 64, .5, true, 0),
                    new FlatStepCorridor.Pose(.5, invalid, .5, true, 0),
                    new FlatStepCorridor.Pose(.5, 64, invalid, true, 0)))
                equal("invalid_pose", FlatStepCorridor.check(pose, 0, 0,
                        FlatStepCorridorChecks::mustNotRead).reason(), "invalid pose rejected");
            require(!FlatStepCorridor.check(MID_POSE, invalid, 0, FlatStepCorridorChecks::mustNotRead).clear(), "invalid dx");
            require(!FlatStepCorridor.check(MID_POSE, 0, invalid, FlatStepCorridorChecks::mustNotRead).clear(), "invalid dz");
        }
        equal("invalid_pose", FlatStepCorridor.check(new FlatStepCorridor.Pose(.5, 64, .5, true, Double.NaN),
                0, 0, FlatStepCorridorChecks::mustNotRead).reason(), "invalid yaw");
        equal("not_grounded", FlatStepCorridor.check(new FlatStepCorridor.Pose(.5, 64, .5, false, 0),
                0, 0, FlatStepCorridorChecks::mustNotRead).reason(), "airborne is not rounded into support");
        equal("not_in_world", FlatStepCorridor.check(null, 0, 0,
                FlatStepCorridorChecks::mustNotRead).reason(), "missing pose");
        equal("step_too_long", FlatStepCorridor.check(MID_POSE, .660001, 0,
                FlatStepCorridorChecks::mustNotRead).reason(), "step bound");
        equal("step_too_long", FlatStepCorridor.check(MID_POSE, .5, .5,
                FlatStepCorridorChecks::mustNotRead).reason(), "diagonal length bound");
        equal("missing_source", FlatStepCorridor.check(MID_POSE, 0, 0, null).reason(), "missing source");
        require(FlatStepCorridor.check(MID_POSE, .66, 0, FlatStepCorridorChecks::dryFlat).clear(), "maximum step admitted");
        for (double invalid : new double[]{Double.NaN, Double.POSITIVE_INFINITY, 1e100}) {
            try { FlatStepCorridor.sweptCells(invalid, .5, 0, 0); throw new AssertionError("invalid geometry accepted"); }
            catch (IllegalArgumentException expected) { /* bounded before integer conversion/enumeration */ }
        }
    }

    static void readFailuresAndIncompleteFactsFailClosed() {
        var result = FlatStepCorridor.check(MID_POSE, .46, .46, (x, y, z) -> { throw new IllegalStateException("shape failed"); });
        equal("cell_read_failed", result.reason(), "read failure is refusal");
        require(result.cell() != null, "failed read has exact coordinates");
        deniedMiddle(64, new FlatStepCorridor.Cell(null, null, true, true, true, "minecraft:empty", false), "unknown_cell");
        deniedMiddle(64, new FlatStepCorridor.Cell(FlatStepCorridor.Availability.LOADED,
                "mod:missing_fluid", true, true, true, null, false), "fluid");
    }

    static void preciseEvidenceAndAllThreeLayers() {
        List<String> reads = new ArrayList<>();
        var pose = new FlatStepCorridor.Pose(.5, 64, .5, true, 179.5);
        var result = FlatStepCorridor.check(pose, 0, 0, (x, y, z) -> { reads.add(x + "," + y + "," + z); return dryFlat(x, y, z); });
        require(result.clear() && result.cell() == null, "clear evidence");
        equal("clear", result.reason(), "clear reason"); equal(pose, result.pose(), "immediate immutable pose");
        equal(List.of("0,63,0", "0,64,0", "0,65,0"), reads, "support, feet and head inspected");
        deniedMiddle(64, solid("minecraft:grass_block"), "feet_collision");
    }

    static void deterministicSweepContainsDensePathReference() {
        // Independent reference: direct square occupancy at 401 times, never an oracle for admitting safety.
        java.util.Random random = new java.util.Random(0x5eedL);
        for (int sample = 0; sample < 400; sample++) {
            double x = random.nextDouble() * 4 - 2, z = random.nextDouble() * 4 - 2;
            double angle = random.nextDouble() * Math.PI * 2, length = random.nextDouble() * .66;
            double dx = Math.cos(angle) * length, dz = Math.sin(angle) * length;
            var sweep = cells(x, z, dx, dz);
            equal(sweep, cells(x + dx, z + dz, -dx, -dz), "seeded reverse symmetry");
            for (int t = 0; t <= 400; t++) {
                double px = x + dx * t / 400, pz = z + dz * t / 400;
                for (int bx = (int) Math.floor(px - .31); bx <= (int) Math.floor(px + .31); bx++)
                    for (int bz = (int) Math.floor(pz - .31); bz <= (int) Math.floor(pz + .31); bz++)
                        require(sweep.contains(grid(bx, bz)), "no occupied sampled square cell omitted");
            }
        }
    }

    private static void deniedMiddle(int y, FlatStepCorridor.Cell obstruction, String reason) {
        var result = FlatStepCorridor.check(MID_POSE, MID_STEP, MID_STEP,
                (x, by, z) -> x == 1 && by == y && z == -1 ? obstruction : dryFlat(x, by, z));
        require(!result.clear(), "middle-only unsafe cell must fail");
        equal(reason, result.reason(), "precise failure reason");
        equal(new FlatStepCorridor.CellRef(1, y, -1, y == 63 ? "support" : y == 64 ? "feet" : "head",
                obstruction == null ? null : obstruction.id()), result.cell(), "exact block/layer/id");
        equal(MID_POSE, result.pose(), "failed check pose");
        equal(MID_STEP, result.dx(), "action dx"); equal(MID_STEP, result.dz(), "action dz");
    }
    private static FlatStepCorridor.GridCell grid(int x, int z) { return new FlatStepCorridor.GridCell(x, z); }
    private static Set<FlatStepCorridor.GridCell> cells(double x, double z, double dx, double dz) {
        var cells = FlatStepCorridor.sweptCells(x, z, dx, dz);
        equal(cells.size(), Set.copyOf(cells).size(), "no duplicate cells");
        return Set.copyOf(cells);
    }
    private static FlatStepCorridor.Cell solid(String id) {
        return new FlatStepCorridor.Cell(FlatStepCorridor.Availability.LOADED, id, true, false,
                true, "minecraft:empty", false);
    }
    private static FlatStepCorridor.Cell air() {
        return new FlatStepCorridor.Cell(FlatStepCorridor.Availability.LOADED, "minecraft:air", true,
                true, false, "minecraft:empty", false);
    }
    private static FlatStepCorridor.Cell dryFlat(int x, int y, int z) { return y == 63 ? solid("minecraft:stone") : air(); }
    private static FlatStepCorridor.Cell mustNotRead(int x, int y, int z) { throw new AssertionError("invalid input read terrain"); }
    private static void equal(Object expected, Object actual, String message) {
        if (!expected.equals(actual)) throw new AssertionError(message + ": expected=" + expected + " actual=" + actual);
    }
    private static void require(boolean value, String message) { if (!value) throw new AssertionError(message); }
    public static void main(String[] args) {
        List<Runnable> tests = List.of(
                FlatStepCorridorChecks::sampledDiagonalGeometry,
                FlatStepCorridorChecks::sampledOffCorridorGrassDoesNotBlock,
                FlatStepCorridorChecks::reflectedReversedAndSwappedSweeps,
                FlatStepCorridorChecks::forwardBackwardAxisAlignedAndStationary,
                FlatStepCorridorChecks::squareFootprintNotCircle,
                FlatStepCorridorChecks::tangenciesAndOutwardEpsilon,
                FlatStepCorridorChecks::middleOnlyCellsNeedSupport,
                FlatStepCorridorChecks::middleWaterRejectedAtEveryLayer,
                FlatStepCorridorChecks::middleLavaRejectedAtEveryLayer,
                FlatStepCorridorChecks::middleUnknownAndUnloadedRejected,
                FlatStepCorridorChecks::middleHazardsRejectedAtEveryLayer,
                FlatStepCorridorChecks::middleFeetAndHeadCollisionsRejected,
                FlatStepCorridorChecks::fractionalFeetRequireIntegerTolerance,
                FlatStepCorridorChecks::invalidPoseAndStepFailBeforeAnyRead,
                FlatStepCorridorChecks::readFailuresAndIncompleteFactsFailClosed,
                FlatStepCorridorChecks::preciseEvidenceAndAllThreeLayers,
                FlatStepCorridorChecks::deterministicSweepContainsDensePathReference);
        int failures = 0;
        for (Runnable test : tests) {
            try { test.run(); }
            catch (AssertionError failure) { failures++; System.out.println("FAIL: " + failure.getMessage()); }
        }
        if (failures != 0) throw new AssertionError(failures + " deterministic corridor checks failed");
        System.out.println(tests.size() + " deterministic corridor checks passed");
    }
}

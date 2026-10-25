package io.github.campione01.mineclientbridge;

import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.function.BiPredicate;
import java.util.function.Predicate;
import java.util.function.ToDoubleFunction;

/** Pure production-planner checks. No Minecraft actions, terrain reads or game claims. */
public final class ReactiveLocalPlannerChecks {
    private static int checks;
    private static final ReactiveLocalPlanner.Cell START = cell(0, 0, 0);

    public static void main(String[] args) {
        var flat = terrain(c -> c.y() == 0, (from, to) -> true);
        var near = ReactiveLocalPlanner.path(START, toward(5, 0, 0), flat, 12, 384);
        check(near.size() == 5 && end(near).equals(cell(5, 0, 0)), "nearest target shortest approach");
        valid(START, near, flat, 12);
        var escape = ReactiveLocalPlanner.path(START, c -> -distance2(c, -2, 0, 0), flat, 5, 384);
        check(escape.size() == 5 && end(escape).equals(cell(5, 0, 0)), "escape increases distance from creeper");
        valid(START, escape, flat, 5);

        var wall = terrain(c -> c.y() == 0 && !(c.x() == 1 && Math.abs(c.z()) <= 1), (a, b) -> true);
        var detour = ReactiveLocalPlanner.path(START, toward(3, 0, 0), wall, 8, 384);
        check(end(detour).equals(cell(3, 0, 0)) && detour.size() == 7, "short wall detour reaches target");
        check(detour.stream().anyMatch(c -> Math.abs(c.z()) == 2), "detour permits temporarily worse score");
        valid(START, detour, wall, 8);

        Set<ReactiveLocalPlanner.Cell> stairs = Set.of(START, cell(1, 1, 0), cell(2, 2, 0), cell(3, 1, 0));
        var stepped = terrain(stairs::contains, (a, b) -> true);
        var stepPath = ReactiveLocalPlanner.path(START, toward(3, 1, 0), stepped, 4, 32);
        check(stepPath.equals(List.of(cell(1, 1, 0), cell(2, 2, 0), cell(3, 1, 0))), "one-up and one-down transitions");
        valid(START, stepPath, stepped, 4);
        check(ReactiveLocalPlanner.path(START, toward(1, 2, 0),
                terrain(c -> c.equals(cell(1, 2, 0)), (a, b) -> true), 12, 384).isEmpty(), "no two-block vertical jump");
        check(ReactiveLocalPlanner.path(START, toward(0, 1, 0),
                terrain(c -> c.equals(cell(0, 1, 0)), (a, b) -> true), 12, 384).isEmpty(), "no invented vertical-only move");

        var diagonalOnly = terrain(c -> c.equals(cell(1, 0, 1)), (a, b) -> true);
        check(ReactiveLocalPlanner.path(START, toward(1, 0, 1), diagonalOnly, 12, 384).isEmpty(), "cannot cut blocked diagonal corner");
        var noHeadroom = terrain(stairs::contains, (a, b) -> b.y() <= a.y());
        check(ReactiveLocalPlanner.path(START, toward(2, 2, 0), noHeadroom, 12, 384).isEmpty(), "adapter edge veto protects jump headroom");
        var unsupported = terrain(c -> c.y() == 0 && c.x() != 1, (a, b) -> true);
        var gap = ReactiveLocalPlanner.path(START, toward(2, 0, 0), unsupported, 4, 384);
        check(gap.stream().noneMatch(c -> c.x() > 0), "no unsupported gap crossing");
        check(ReactiveLocalPlanner.path(START, toward(5, 0, 0), terrain(c -> false, (a, b) -> true), 12, 384).isEmpty(), "unknown terrain not a path");

        var limited = ReactiveLocalPlanner.path(START, toward(9, 0, 0), flat, 3, 384);
        check(limited.size() == 3 && end(limited).equals(cell(3, 0, 0)), "depth radius bounds partial approach");
        check(ReactiveLocalPlanner.path(START, toward(9, 0, 0), flat, 12, 1).isEmpty(), "start consumes one admitted node");
        var tiny = ReactiveLocalPlanner.path(START, toward(-9, 0, 0), flat, 12, 2);
        check(tiny.equals(List.of(cell(-1, 0, 0))), "finite budget favors lower-scored neighbor");
        check(ReactiveLocalPlanner.path(START, toward(9, 0, 0), flat, 0, 384).isEmpty(), "zero radius remains in place");
        check(ReactiveLocalPlanner.path(START, toward(0, 0, 0), flat, 12, 384).isEmpty(), "no strictly better point returns empty");
        check(ReactiveLocalPlanner.path(START, c -> 7, flat, 12, 384).isEmpty(), "equal score cannot invent movement");

        var line = terrain(c -> c.y() == 0 && c.z() == 0 && c.x() >= 0 && c.x() <= 12, (a, b) -> true);
        var boundary = ReactiveLocalPlanner.path(START, toward(12, 0, 0), line, 12, 384);
        check(boundary.size() == 12, "documented maximum search depth supported");
        var signedEdge = terrain(c -> c.y() == 0 && c.z() == 0, (a, b) -> b.x() > a.x());
        check(ReactiveLocalPlanner.path(START, toward(-3, 0, 0), signedEdge, 12, 384).isEmpty(), "edge approval is directional");
        check(ReactiveLocalPlanner.path(START, toward(2, 0, 0),
                terrain(c -> !c.equals(START) && c.y() == 0, (a, b) -> true), 3, 384).size() == 2,
                "actual occupied start need not be a future standable destination");
        var viaInvalid = ReactiveLocalPlanner.path(START, c -> c.x() == 1 ? Double.NaN : distance2(c, 3, 0, 0), line, 12, 384);
        check(viaInvalid.isEmpty(), "nonfinite intermediate score is excluded");
        check(ReactiveLocalPlanner.path(START, c -> Double.POSITIVE_INFINITY, flat, 12, 384).isEmpty(), "nonfinite start yields no plan");
        var extreme = cell(Integer.MAX_VALUE, 0, 0);
        check(ReactiveLocalPlanner.path(extreme, c -> c.x(),
                terrain(c -> c.y() == 0 && c.z() == 0, (a, b) -> true), 1, 384)
                .equals(List.of(cell(Integer.MAX_VALUE - 1, 0, 0))), "coordinate addition cannot wrap across world");

        var cover = ReactiveLocalPlanner.path(START,
                c -> distance2(c, 0, 0, 0) + (c.z() >= 2 ? -100 : 0), flat, 4, 384);
        check(end(cover).equals(cell(0, 0, 2)), "caller score can prefer reachable cover over nearest approach");
        var tie = ReactiveLocalPlanner.path(START, c -> c.equals(START) ? 2 : 1, flat, 12, 384);
        check(tie.size() == 1, "equal best score prefers shorter route");
        check(tie.equals(ReactiveLocalPlanner.path(START, c -> c.equals(START) ? 2 : 1, flat, 12, 384)), "tie behavior is deterministic");
        rejects(() -> near.add(START), UnsupportedOperationException.class, "returned path immutable");
        rejects(() -> ReactiveLocalPlanner.path(START, toward(1, 0, 0), flat, 13, 384), IllegalArgumentException.class, "radius maximum enforced");
        rejects(() -> ReactiveLocalPlanner.path(START, toward(1, 0, 0), flat, -1, 384), IllegalArgumentException.class, "negative radius rejected");
        rejects(() -> ReactiveLocalPlanner.path(START, toward(1, 0, 0), flat, 12, 385), IllegalArgumentException.class, "node maximum enforced");
        rejects(() -> ReactiveLocalPlanner.path(START, toward(1, 0, 0), flat, 12, 0), IllegalArgumentException.class, "zero node budget rejected");
        rejects(() -> ReactiveLocalPlanner.path(START, toward(1, 0, 0), terrain(c -> {throw new IllegalStateException("stale");}, (a, b) -> true), 2, 16), IllegalStateException.class, "failed terrain observation is not converted into authorization");
        System.out.println("ReactiveLocalPlannerChecks: " + checks + " passed");
    }

    private static ReactiveLocalPlanner.Cell cell(int x, int y, int z) { return new ReactiveLocalPlanner.Cell(x, y, z); }
    private static ReactiveLocalPlanner.Cell end(List<ReactiveLocalPlanner.Cell> path) { return path.getLast(); }
    private static double distance2(ReactiveLocalPlanner.Cell c, int x, int y, int z) {
        double dx = (double)c.x() - x, dy = (double)c.y() - y, dz = (double)c.z() - z;
        return dx * dx + dy * dy + dz * dz;
    }
    private static ToDoubleFunction<ReactiveLocalPlanner.Cell> toward(int x, int y, int z) { return c -> distance2(c, x, y, z); }
    private static ReactiveLocalPlanner.Terrain terrain(Predicate<ReactiveLocalPlanner.Cell> standable,
            BiPredicate<ReactiveLocalPlanner.Cell, ReactiveLocalPlanner.Cell> edge) {
        return new ReactiveLocalPlanner.Terrain() {
            public boolean standable(ReactiveLocalPlanner.Cell cell) { return standable.test(cell); }
            public boolean edge(ReactiveLocalPlanner.Cell from, ReactiveLocalPlanner.Cell to) { return edge.test(from, to); }
        };
    }
    private static void valid(ReactiveLocalPlanner.Cell start, List<ReactiveLocalPlanner.Cell> path,
                              ReactiveLocalPlanner.Terrain terrain, int radius) {
        check(path.size() <= radius && !path.contains(start), "path bounded and excludes start");
        var seen = new HashSet<ReactiveLocalPlanner.Cell>(); seen.add(start);
        for (var next : path) {
            check(Math.abs(next.x() - start.x()) + Math.abs(next.z() - start.z()) == 1
                    && Math.abs(next.y() - start.y()) <= 1, "cardinal step and bounded height");
            check(terrain.standable(next) && terrain.edge(start, next) && seen.add(next), "all transitions approved without cycles");
            start = next;
        }
    }
    private static void check(boolean value, String reason) { checks++; if (!value) throw new AssertionError(reason); }
    private static void rejects(Runnable action, Class<? extends Throwable> type, String reason) {
        try { action.run(); } catch (Throwable failure) { check(type.isInstance(failure), reason); return; }
        throw new AssertionError(reason);
    }
}

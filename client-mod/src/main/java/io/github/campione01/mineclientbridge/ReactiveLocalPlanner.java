package io.github.campione01.mineclientbridge;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import java.util.Objects;
import java.util.function.ToDoubleFunction;

/** Small, observation-only ground planner; a returned path is not input authority. */
final class ReactiveLocalPlanner {
    static final int MAX_RADIUS = 12;
    static final int MAX_NODES = 384;

    record Cell(int x, int y, int z) { }

    interface Terrain {
        /** True only for a currently loaded, supported and clear destination cell. */
        boolean standable(Cell cell);

        /** Check the whole transition, including step/jump headroom, not just its endpoints. */
        boolean edge(Cell from, Cell to);
    }

    private record Node(Cell cell, Node parent, int depth, double score) { }
    private static final int[][] DIRECTIONS = {{1, 0}, {0, 1}, {-1, 0}, {0, -1}};
    private static final int[] HEIGHTS = {0, 1, -1};

    private ReactiveLocalPlanner() { }

    /**
     * Lower score is better. Explore at most {@code maxNodes} admitted cells and
     * {@code radius} cardinal moves from the actual start, then return a shortest
     * path to the best strictly improving score. Equal scores keep the shorter
     * path, then deterministic discovery order. Intermediate scores may worsen,
     * so a short detour around a wall is allowed. Non-finite scores are excluded.
     *
     * The actual occupied start is admitted without a standable test; every new
     * cell and edge still requires Terrain approval. This permits escape from a
     * just-changed start cell without treating it as proof of any onward route.
     * Re-check each returned edge against fresh terrain before moving in game.
     * Empty means no improving local path was found, not that the world is safe.
     */
    static List<Cell> path(Cell start, ToDoubleFunction<Cell> score, Terrain terrain,
                           int radius, int maxNodes) {
        Objects.requireNonNull(start, "start");
        Objects.requireNonNull(score, "score");
        Objects.requireNonNull(terrain, "terrain");
        if (radius < 0 || radius > MAX_RADIUS || maxNodes < 1 || maxNodes > MAX_NODES)
            throw new IllegalArgumentException("local_planner_bounds_radius_0_12_nodes_1_384");
        double startScore = score.applyAsDouble(start);
        if (!Double.isFinite(startScore)) return List.of();
        Node first = new Node(start, null, 0, startScore), best = first;
        var queue = new ArrayDeque<Node>();
        var visited = new HashSet<Cell>();
        queue.add(first);
        visited.add(start);
        while (!queue.isEmpty() && visited.size() < maxNodes) {
            Node current = queue.removeFirst();
            if (current.depth == radius) continue;
            var choices = new ArrayList<Node>(12);
            for (int[] direction : DIRECTIONS) for (int dy : HEIGHTS) {
                Cell next = offset(current.cell, direction[0], dy, direction[1]);
                if (next == null || visited.contains(next) || !terrain.standable(next)
                        || !terrain.edge(current.cell, next)) continue;
                double value = score.applyAsDouble(next);
                if (Double.isFinite(value))
                    choices.add(new Node(next, current, current.depth + 1, value));
            }
            // Prefer useful neighbors when the finite node budget cuts a layer short.
            choices.sort(Comparator.comparingDouble(Node::score));
            for (Node next : choices) {
                if (visited.size() == maxNodes) break;
                if (!visited.add(next.cell)) continue;
                queue.addLast(next);
                if (next.score < best.score) best = next;
            }
        }
        if (best == first) return List.of();
        var result = new ArrayList<Cell>(best.depth);
        for (Node node = best; node.parent != null; node = node.parent) result.add(node.cell);
        Collections.reverse(result);
        return List.copyOf(result);
    }

    private static Cell offset(Cell cell, int dx, int dy, int dz) {
        long x = (long) cell.x + dx, y = (long) cell.y + dy, z = (long) cell.z + dz;
        if (x < Integer.MIN_VALUE || x > Integer.MAX_VALUE || y < Integer.MIN_VALUE
                || y > Integer.MAX_VALUE || z < Integer.MIN_VALUE || z > Integer.MAX_VALUE)
            return null;
        return new Cell((int) x, (int) y, (int) z);
    }
}

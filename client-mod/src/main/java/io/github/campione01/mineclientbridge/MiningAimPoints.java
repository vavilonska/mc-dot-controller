package io.github.campione01.mineclientbridge;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

/** Bounded fallback proposals only. Minecraft's real pick must accept every actual hit. */
final class MiningAimPoints {
    record Point(double x, double y, double z) {
        double distanceSquared(double ex, double ey, double ez) {
            return (x - ex) * (x - ex) + (y - ey) * (y - ey) + (z - ez) * (z - ez);
        }
    }
    private record Face(int axis, double plane, Point center) { }
    static final int MAX_POINTS = 15; // At most three visible cube faces, five points each.
    private static final double[] INSET = {0.2, 0.8};

    static List<Point> facingFaces(int x, int y, int z, double eyeX, double eyeY, double eyeZ) {
        if (!Double.isFinite(eyeX) || !Double.isFinite(eyeY) || !Double.isFinite(eyeZ)) return List.of();
        double[] base = {x, y, z}, eye = {eyeX, eyeY, eyeZ};
        List<Face> faces = new ArrayList<>(3);
        for (int axis = 0; axis < 3; axis++) {
            double plane;
            if (eye[axis] <= base[axis]) plane = base[axis];
            else if (eye[axis] >= base[axis] + 1) plane = base[axis] + 1;
            else continue;
            double[] point = {x + 0.5, y + 0.5, z + 0.5};
            point[axis] = plane;
            faces.add(new Face(axis, plane, point(point)));
        }
        faces.sort(Comparator.comparingDouble(f -> f.center().distanceSquared(eyeX, eyeY, eyeZ)));
        List<Point> result = new ArrayList<>(MAX_POINTS);
        // Try every facing face center before spending rays on partially exposed corners.
        for (Face face : faces) result.add(face.center());
        for (Face face : faces) {
            int u = (face.axis() + 1) % 3, v = (face.axis() + 2) % 3;
            for (double a : INSET) for (double b : INSET) {
                double[] point = base.clone();
                point[face.axis()] = face.plane();
                point[u] += a;
                point[v] += b;
                result.add(point(point));
            }
        }
        return List.copyOf(result);
    }

    private static Point point(double[] value) { return new Point(value[0], value[1], value[2]); }
    private MiningAimPoints() { }
}

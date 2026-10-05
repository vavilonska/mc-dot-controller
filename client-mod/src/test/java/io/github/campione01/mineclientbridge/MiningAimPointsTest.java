package io.github.campione01.mineclientbridge;

import static org.junit.jupiter.api.Assertions.*;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashSet;
import java.util.List;
import org.junit.jupiter.api.Test;

/** Geometry fixtures only, not a Minecraft raycast or gameplay simulation. */
class MiningAimPointsTest {
    private record Box(String name, double x0, double y0, double z0, double x1, double y1, double z1) { }
    private static final Box TARGET = new Box("target", 0, 0, 0, 1, 1, 1);
    private static MiningAimPoints.Point point(double x, double y, double z) {
        return new MiningAimPoints.Point(x, y, z);
    }
    private static double entry(MiningAimPoints.Point eye, MiningAimPoints.Point toward, Box box, double range) {
        double[] e = {eye.x(), eye.y(), eye.z()};
        double[] d = {toward.x() - eye.x(), toward.y() - eye.y(), toward.z() - eye.z()};
        double length = Math.sqrt(d[0]*d[0] + d[1]*d[1] + d[2]*d[2]);
        if (length < 1e-12) return Double.POSITIVE_INFINITY;
        double[] low = {box.x0(), box.y0(), box.z0()}, high = {box.x1(), box.y1(), box.z1()};
        double near = 0, far = range;
        for (int i = 0; i < 3; i++) {
            d[i] /= length;
            if (Math.abs(d[i]) < 1e-12) {
                if (e[i] < low[i] || e[i] > high[i]) return Double.POSITIVE_INFINITY;
                continue;
            }
            double a = (low[i] - e[i]) / d[i], b = (high[i] - e[i]) / d[i];
            near = Math.max(near, Math.min(a, b));
            far = Math.min(far, Math.max(a, b));
            if (near > far + 1e-9) return Double.POSITIVE_INFINITY;
        }
        return near;
    }
    private static String firstBox(MiningAimPoints.Point eye, MiningAimPoints.Point toward,
            double range, Box... boxes) {
        String selected = null;
        double nearest = Double.POSITIVE_INFINITY;
        for (Box box : boxes) {
            double distance = entry(eye, toward, box, range);
            if (distance < nearest) { selected = box.name(); nearest = distance; }
        }
        return selected;
    }

    @Test void syntheticOverhangBlocksCenterButAFacingSurfaceWorks() {
        // Origin-relative synthetic fixture; no captured gameplay coordinates are retained.
        MiningAimPoints.Point eye = point(1.52, 1.62, 0.285);
        Box lower = new Box("target", 0, 0, 0, 1, 1, 1);
        Box upper = new Box("upper_block", 0, 1, 0, 1, 2, 1);
        assertEquals("upper_block", firstBox(eye, point(0.5, 0.5, 0.5), 4.5, lower, upper));
        List<MiningAimPoints.Point> points = MiningAimPoints.facingFaces(0, 0, 0, eye.x(), eye.y(), eye.z());
        assertTrue(points.stream().anyMatch(p -> "target".equals(firstBox(eye, p, 4.5, lower, upper))));
    }
    @Test void entirelyOccludedBlockHasNoAcceptedCandidate() {
        var eye = point(2.5, 0.5, 0.5);
        Box wall = new Box("wall", 1, 0, 0, 2, 1, 1);
        for (var p : MiningAimPoints.facingFaces(0, 0, 0, eye.x(), eye.y(), eye.z()))
            assertEquals("wall", firstBox(eye, p, 4.5, TARGET, wall));
    }
    @Test void PartialFaceOccluderAllowsInsetPointInsteadOfOccludedFaceCenter() {
        var eye = point(2.5, 0.5, 0.5);
        Box partial = new Box("partial_shape", 1.25, 0.35, 0.35, 1.35, 0.65, 0.65);
        var candidates = MiningAimPoints.facingFaces(0, 0, 0, eye.x(), eye.y(), eye.z());
        assertEquals("partial_shape", firstBox(eye, candidates.getFirst(), 4.5, TARGET, partial));
        assertTrue(candidates.stream().skip(1).anyMatch(p -> "target".equals(firstBox(eye, p, 4.5, TARGET, partial))));
    }
    @Test void OutOfReachIsNeverAcceptedByGeometryVerifier() {
        var eye = point(10, 0.5, 0.5);
        for (var p : MiningAimPoints.facingFaces(0, 0, 0, eye.x(), eye.y(), eye.z()))
            assertNull(firstBox(eye, p, 4.5, TARGET));
    }
    @Test void allSixViewDirectionsUseOnlyTheFacingPlane() {
        double[][] eyes = {{-2,.5,.5},{3,.5,.5},{.5,-2,.5},{.5,3,.5},{.5,.5,-2},{.5,.5,3}};
        for (int i=0; i<eyes.length; i++) {
            var e=eyes[i]; var points=MiningAimPoints.facingFaces(0,0,0,e[0],e[1],e[2]);
            assertEquals(5,points.size());
            int axis=i/2; double plane=i%2;
            for(var p:points) assertEquals(plane,new double[]{p.x(),p.y(),p.z()}[axis]);
        }
    }
    @Test void proposalsStayBoundedUniqueAndInsideTheirTargetFaces() {
        var points = MiningAimPoints.facingFaces(0,0,0,3,3,3);
        assertEquals(MiningAimPoints.MAX_POINTS,points.size());
        assertEquals(points.size(),new HashSet<>(points).size());
        for(var p:points) {
            double[] xyz={p.x(),p.y(),p.z()}; int faceCoordinates=0;
            for(double coordinate:xyz) {
                assertTrue(coordinate>=0 && coordinate<=1);
                if(coordinate==0 || coordinate==1) faceCoordinates++;
                else assertTrue(coordinate==.2 || coordinate==.5 || coordinate==.8);
            }
            assertEquals(1,faceCoordinates);
        }
    }
    @Test void faceCentersAreTriedBeforeInsetCorners() {
        var points=MiningAimPoints.facingFaces(0,0,0,2,3,4);
        for(var p:points.subList(0,3)) {
            int centerCoordinates=0;
            for(double c:new double[]{p.x(),p.y(),p.z()}) if(c==.5) centerCoordinates++;
            assertEquals(2,centerCoordinates);
        }
    }
    @Test void malformedEyeOrInsideTargetDoesNotGenerateUnboundedWork() {
        assertTrue(MiningAimPoints.facingFaces(0,0,0,Double.NaN,0,0).isEmpty());
        assertTrue(MiningAimPoints.facingFaces(0,0,0,0,Double.POSITIVE_INFINITY,0).isEmpty());
        assertTrue(MiningAimPoints.facingFaces(0,0,0,.5,.5,.5).isEmpty());
    }
    @Test void negativeWorldCoordinatesTranslateWithoutChangingCandidateOrder() {
        var base=MiningAimPoints.facingFaces(0,0,0,2,3,4);
        var moved=MiningAimPoints.facingFaces(-17,64,-23,-15,67,-19);
        assertEquals(base.size(),moved.size());
        for(int i=0;i<base.size();i++) {
            assertEquals(base.get(i).x()-17,moved.get(i).x());
            assertEquals(base.get(i).y()+64,moved.get(i).y());
            assertEquals(base.get(i).z()-23,moved.get(i).z());
        }
    }
    @Test void clientAdapterStillUsesRealTargetRayAndReachBeforeMining() throws Exception {
        Path project=Path.of(System.getProperty("mineclientBridge.projectDir"));
        String source=Files.readString(project.resolve("src/main/java/io/github/campione01/mineclientbridge/ClientActions.java"));
        String aim=source.substring(source.indexOf("private static BlockHitResult aimMiningTarget("),
                source.indexOf("private static void observeBreak("));
        assertTrue(aim.indexOf("if (hit != null) return hit;") < aim.indexOf("for (MiningAimPoints.Point"));
        assertEquals(3,aim.split("pick\\(mc, pos, null\\)",-1).length-1);
        assertTrue(aim.contains("return null;"));
        assertFalse(aim.contains("keyAttack"));
        assertFalse(aim.contains("startAttack"));
        String pick=source.substring(source.indexOf("private static BlockHitResult pick("),
                source.indexOf("private static double aEyeDistance("));
        assertTrue(pick.contains("mc.gameRenderer.pick(1.0F)"));
        assertTrue(pick.contains("!hit.getBlockPos().equals(expected)"));
        assertTrue(pick.contains("hit.getType() != HitResult.Type.BLOCK"));
        assertTrue(pick.contains("aEyeDistance(mc, hit) > mc.player.blockInteractionRange()"));
        String mine=source.substring(source.indexOf("private static void mine("),source.indexOf("private static BlockHitResult aimMiningTarget("));
        assertTrue(mine.indexOf("aimMiningTarget(mc, pos)") < mine.indexOf("mc.options.keyAttack.setDown(true)"));
        assertTrue(mine.contains("if (hit == null) { finish(\"failed\", \"target_not_in_reach_or_visible\"); return; }"));
    }
}

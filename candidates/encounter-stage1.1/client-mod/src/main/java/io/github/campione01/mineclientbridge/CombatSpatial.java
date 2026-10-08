package io.github.campione01.mineclientbridge;

import java.util.List;

/** Pure continuously swept entity collision check, independent of terrain admission. */
final class CombatSpatial {
    record Box(int entityId, double minX, double minY, double minZ, double maxX, double maxY, double maxZ) {
        boolean finite() {
            return Double.isFinite(minX) && Double.isFinite(minY) && Double.isFinite(minZ)
                    && Double.isFinite(maxX) && Double.isFinite(maxY) && Double.isFinite(maxZ)
                    && minX <= maxX && minY <= maxY && minZ <= maxZ;
        }
    }
    record Result(boolean clear, String reason, int entityId) { }
    static Result check(double x, double y, double z, double dx, double dz, List<Box> boxes) {
        if (!Double.isFinite(x) || !Double.isFinite(y) || !Double.isFinite(z)
                || !Double.isFinite(dx) || !Double.isFinite(dz) || Math.hypot(dx,dz)>2.001
                || boxes == null || boxes.size()>128) return new Result(false,"dynamic_obstacles_unknown",-1);
        double r=FlatStepCorridor.HALF_WIDTH+FlatStepCorridor.SAFETY_EPSILON;
        for (Box box:boxes) {
            if (box == null || !box.finite()) return new Result(false,"dynamic_obstacle_invalid",-1);
            if (y+1.81 < box.minY || y > box.maxY) continue;
            double[] time={0,1};
            if (clip(x,dx,box.minX-r,box.maxX+r,time) && clip(z,dz,box.minZ-r,box.maxZ+r,time))
                return new Result(false,"dynamic_entity_collision",box.entityId);
        }
        return new Result(true,"clear",-1);
    }
    static boolean withinCombatArea(double x,double y,double z,double originX,double originY,double originZ) {
        double distance=Math.hypot(Math.hypot(x-originX,z-originZ),y-originY);
        return Double.isFinite(distance) && distance<=12;
    }
    private static boolean clip(double p,double d,double low,double high,double[] time) {
        if (d==0) return p>=low && p<=high;
        double a=(low-p)/d,b=(high-p)/d;
        time[0]=Math.max(time[0],Math.min(a,b));time[1]=Math.min(time[1],Math.max(a,b));
        return time[0]<=time[1];
    }
    private CombatSpatial() { }
}

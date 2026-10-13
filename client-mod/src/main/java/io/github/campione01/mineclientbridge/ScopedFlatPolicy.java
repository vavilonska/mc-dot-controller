package io.github.campione01.mineclientbridge;

import java.util.List;

/** Pure finite geometry only. Does not establish Minecraft collision or hazard facts. */
final class ScopedFlatPolicy {
    static final int MAX_STEPS = 1, HALO = 2, MAX_CELLS = 150;
    static final double MAX_SPEED = .30, MAX_TICK_DISPLACEMENT = .35;
    static final long MAX_TIMEOUT_MS = 8000;
    record Point(double x, double y, double z) { }
    record Bounds(int minX, int minY, int minZ, int maxX, int maxY, int maxZ,
                  int startX, int feetY, int startZ, int endX, int endZ, int steps) {
        int cells() { return (maxX-minX+1)*(maxY-minY+1)*(maxZ-minZ+1); }
        boolean containsPose(double x, double y, double z) {
            if (!finite(x,y,z) || Math.abs(y-feetY)>1e-6) return false;
            double loX=Math.min(startX,endX)+.5, hiX=Math.max(startX,endX)+.5;
            double loZ=Math.min(startZ,endZ)+.5, hiZ=Math.max(startZ,endZ)+.5;
            return x>=loX-.25 && x<=hiX+.25 && z>=loZ-.25 && z<=hiZ+.25;
        }
    }
    static Bounds route(double x,double y,double z,List<Point> points) {
        require(finite(x,y,z) && Math.abs(x)<=29_999_990 && Math.abs(z)<=29_999_990
                && y>=-63 && y<=316, "scoped_movement_origin_bounds");
        int sx=(int)Math.floor(x), sy=(int)Math.rint(y), sz=(int)Math.floor(z);
        require(Math.abs(x-sx-.5)<=.10 && Math.abs(z-sz-.5)<=.10 && Math.abs(y-sy)<=1e-7,
                "scoped_movement_centered_integer_origin_required");
        require(points!=null && points.size()>=1 && points.size()<=MAX_STEPS,"scoped_movement_exactly_one_step");
        int dx=0,dz=0;
        for(int i=0;i<points.size();i++) {
            Point p=points.get(i);
            require(finite(p.x,p.y,p.z) && p.y==sy,"scoped_movement_flat_required");
            if(i==0) {
                dx=(int)Math.rint(p.x-(sx+.5)); dz=(int)Math.rint(p.z-(sz+.5));
                require(Math.abs(dx)+Math.abs(dz)==1,"scoped_movement_cardinal_required");
            }
            require(p.x==sx+.5+dx*(i+1) && p.z==sz+.5+dz*(i+1),"scoped_movement_straight_unit_steps_required");
        }
        int ex=sx+dx*points.size(),ez=sz+dz*points.size();
        Bounds b=new Bounds(Math.min(sx,ex)-HALO,sy-1,Math.min(sz,ez)-HALO,
                Math.max(sx,ex)+HALO,sy+3,Math.max(sz,ez)+HALO,sx,sy,sz,ex,ez,points.size());
        require(b.cells()<=MAX_CELLS,"scoped_movement_footprint_budget");return b;
    }
    static boolean finite(double... values) {for(double v:values)if(!Double.isFinite(v))return false;return true;}
    static void require(boolean condition,String reason) {if(!condition)throw new IllegalArgumentException(reason);}
    private ScopedFlatPolicy() { }
}

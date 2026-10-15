package io.github.campione01.mineclientbridge;

import java.util.List;

/** Finite candidate geometry for one isolated full-cube pedestal descent. No physics authority. */
final class ScopedStepDownPolicy {
    static final int HALO=2, MAX_CELLS=180, MAX_AIRBORNE_TICKS=20;
    static final double MAX_SPEED=.30, MAX_TICK_DISPLACEMENT=.35, MAX_DOWNWARD_SPEED=.5, MAX_FALL_DISTANCE=1.01;
    static final long MAX_TIMEOUT_MS=8000;
    record Point(double x,double y,double z) { }
    enum Phase { UPPER, DESCENDING, LANDED }
    record Bounds(int startX,int startY,int startZ,int endX,int endY,int endZ) {
        // Reuse only the immutable rectangular entity-prism carrier; never its flat route/pose policy.
        ScopedFlatPolicy.Bounds prism(){return new ScopedFlatPolicy.Bounds(Math.min(startX,endX)-HALO,startY-2,
            Math.min(startZ,endZ)-HALO,Math.max(startX,endX)+HALO,startY+3,Math.max(startZ,endZ)+HALO,
            startX,startY,startZ,endX,endZ,1);}
        boolean solid(int x,int y,int z){return y==startY-2 || x==startX && y==startY-1 && z==startZ;}
        boolean contains(double x,double y,double z){return finite(x,y,z) && y>=endY-1e-6 && y<=startY+1e-6
            && x>=Math.min(startX,endX)+.25 && x<=Math.max(startX,endX)+.75
            && z>=Math.min(startZ,endZ)+.25 && z<=Math.max(startZ,endZ)+.75
            && (y>=startY-1e-6 || x-.3>=startX+1-1e-6 || x+.3<=startX+1e-6
                || z-.3>=startZ+1-1e-6 || z+.3<=startZ+1e-6);}
    }
    static Bounds route(double x,double y,double z,List<Point> points){
        require(finite(x,y,z) && Math.abs(x)<=29_999_990 && Math.abs(z)<=29_999_990 && y>=-62 && y<=316,"step_down_origin_bounds");
        int sx=(int)Math.floor(x),sy=(int)Math.rint(y),sz=(int)Math.floor(z);
        require(Math.abs(x-sx-.5)<=.10 && Math.abs(z-sz-.5)<=.10 && Math.abs(y-sy)<=1e-7,"step_down_centered_integer_origin_required");
        require(points!=null && points.size()==1,"step_down_exactly_one_step");Point p=points.get(0);
        require(finite(p.x,p.y,p.z) && p.y==sy-1,"step_down_exactly_one_block_lower_required");
        double dx=p.x-sx-.5,dz=p.z-sz-.5;
        require((dx==1||dx==-1)&&dz==0 || (dz==1||dz==-1)&&dx==0,"step_down_cardinal_required");
        return new Bounds(sx,sy,sz,sx+(int)dx,sy-1,sz+(int)dz);
    }
    static Phase phase(Bounds b,Phase previous,double lastY,double y,double vy,float fall,boolean grounded){
        require(finite(y,vy,fall) && y>=b.endY-1e-6 && y<=b.startY+1e-6 && y<=lastY+1e-6
            && vy<=0 && vy>=-MAX_DOWNWARD_SPEED && fall>=0 && fall<=MAX_FALL_DISTANCE,"step_down_vertical_envelope_changed");
        if(grounded){
            require(fall==0 && vy>=-.09,"step_down_ground_motion_changed");
            if(Math.abs(y-b.endY)<=1e-6){require(previous!=Phase.UPPER,"step_down_descent_phase_missing");return Phase.LANDED;}
            require(previous==Phase.UPPER && Math.abs(y-b.startY)<=1e-6,"step_down_unexpected_ground_height");
            return Phase.UPPER;
        }
        require(previous!=Phase.LANDED,"step_down_second_ledge_departure");
        // First ordinary ledge frame can be airborne at unchanged starting Y.
        return Phase.DESCENDING;
    }
    static boolean finite(double...v){for(double n:v)if(!Double.isFinite(n))return false;return true;}
    static void require(boolean ok,String reason){if(!ok)throw new IllegalArgumentException(reason);}
    private ScopedStepDownPolicy() { }
}

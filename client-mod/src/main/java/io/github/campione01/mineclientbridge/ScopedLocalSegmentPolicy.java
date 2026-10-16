package io.github.campione01.mineclientbridge;

import java.util.List;

/** Finite cardinal segment geometry. Native collision reads remain the authority. */
final class ScopedLocalSegmentPolicy {
    static final int HALO=2, MAX_CELLS=180, MAX_AIRBORNE_TICKS=20;
    static final double MAX_SPEED=.30, MAX_TICK_DISPLACEMENT=.35, MAX_VERTICAL_SPEED=.5,
        MAX_RISE=1.26, MAX_FALL_DISTANCE=1.01, SOURCE_CENTER_TOLERANCE=.10, ARRIVAL_RADIUS=.08;
    static final long MAX_TIMEOUT_MS=8000;
    record Point(double x,double y,double z) { }
    enum Phase { GROUND, RISING, FALLING, LANDED }
    enum Role { SUPPORT, CLEAR, CONTEXT }
    record Bounds(int startX,int startY,int startZ,int endX,int endY,int endZ) {
        int dy(){return endY-startY;}
        ScopedFlatPolicy.Bounds prism(){return new ScopedFlatPolicy.Bounds(Math.min(startX,endX)-HALO,
            Math.min(startY,endY)-1,Math.min(startZ,endZ)-HALO,Math.max(startX,endX)+HALO,
            Math.max(startY,endY)+3,Math.max(startZ,endZ)+HALO,startX,startY,startZ,endX,endZ,1);}
        Role role(int x,int y,int z){
            boolean source=x==startX&&z==startZ,target=x==endX&&z==endZ;
            if(source&&y==startY-1 || target&&y==endY-1)return Role.SUPPORT;
            int ceiling=dy()>0?startY+3:dy()<0?startY+2:startY+1;
            if(source&&y>=startY&&y<=ceiling || target&&y>=endY&&y<=ceiling)return Role.CLEAR;
            return Role.CONTEXT;
        }
        boolean horizontalContains(double x,double z){
            if(!finite(x,z))return false;
            double along=(x-startX-.5)*(endX-startX)+(z-startZ-.5)*(endZ-startZ);
            double cross=(x-startX-.5)*(endZ-startZ)-(z-startZ-.5)*(endX-startX);
            return along>=-.100001&&along<=1.100001&&Math.abs(cross)<=.100001;
        }
        boolean contains(double x,double y,double z){
            if(!finite(x,y,z)||!horizontalContains(x,z)||y<Math.min(startY,endY)-1e-6||y>startY+(dy()>0?MAX_RISE:0)+1e-6)return false;
            double along=(x-startX-.5)*(endX-startX)+(z-startZ-.5)*(endZ-startZ);
            // The actual standing body must never penetrate a riser/pedestal side.
            if(dy()>0&&y<endY-1e-6&&along+.3>.5+1e-6)return false;
            return dy()>=0||y>=startY-1e-6||along-.3>=.5-1e-6;
        }
    }
    static Bounds route(double x,double y,double z,List<Point> points){
        require(finite(x,y,z)&&Math.abs(x)<=29_999_990&&Math.abs(z)<=29_999_990,"local_segment_origin_bounds");
        int sx=(int)Math.floor(x),sy=(int)Math.rint(y),sz=(int)Math.floor(z);
        require(Math.abs(x-sx-.5)<=SOURCE_CENTER_TOLERANCE&&Math.abs(z-sz-.5)<=SOURCE_CENTER_TOLERANCE
            &&Math.abs(y-sy)<=1e-7,"local_segment_centered_integer_origin_required");
        require(points!=null&&points.size()==1,"local_segment_exactly_one_step");Point p=points.get(0);
        require(finite(p.x,p.y,p.z)&&p.y==Math.rint(p.y)&&Math.abs(p.y-sy)<=1,"local_segment_unit_height_required");
        double dx=p.x-sx-.5,dz=p.z-sz-.5;
        require((dx==1||dx==-1)&&dz==0||(dz==1||dz==-1)&&dx==0,"local_segment_cardinal_required");
        require(sy>=-63&&sy<=316&&p.y>=-63&&p.y<=316,"local_segment_world_height_bounds");
        Bounds b=new Bounds(sx,sy,sz,sx+(int)dx,(int)p.y,sz+(int)dz);
        require(b.prism().cells()<=MAX_CELLS,"local_segment_footprint_budget");return b;
    }
    static Phase phase(Bounds b,Phase previous,double lastY,double y,double vy,float fall,boolean grounded,
            boolean jumped){
        require(finite(y,vy,fall)&&y>=Math.min(b.startY,b.endY)-1e-6
            &&y<=b.startY+(b.dy()>0?MAX_RISE:0)+1e-6&&Math.abs(vy)<=MAX_VERTICAL_SPEED
            &&fall>=0&&fall<=MAX_FALL_DISTANCE,"local_segment_vertical_envelope_changed");
        if(b.dy()==0){require(grounded&&Math.abs(y-b.startY)<=1e-6&&fall==0&&vy>=-.09&&vy<=0,
            "local_segment_flat_ground_required");return Phase.LANDED;}
        if(grounded){
            require(fall==0&&vy>=-.09&&vy<=0,"local_segment_ground_motion_changed");
            if(Math.abs(y-b.endY)<=1e-6){require(previous==Phase.FALLING||previous==Phase.LANDED,
                "local_segment_airborne_phase_missing");return Phase.LANDED;}
            require(previous==Phase.GROUND&&Math.abs(y-b.startY)<=1e-6,"local_segment_unexpected_ground_height");
            return Phase.GROUND;
        }
        require(previous!=Phase.LANDED,"local_segment_second_departure");
        if(b.dy()<0){require(y<=lastY+1e-6&&vy<=0,"local_segment_descent_reversed");return Phase.FALLING;}
        require(jumped,"local_segment_unowned_jump");
        if(vy>0){require(previous!=Phase.FALLING&&y>=lastY-1e-6,"local_segment_second_rise");return Phase.RISING;}
        require(previous==Phase.RISING||previous==Phase.FALLING,"local_segment_rise_missing");
        require(y<=lastY+(previous==Phase.FALLING?1e-6:MAX_VERTICAL_SPEED+1e-6),"local_segment_vertical_sample_gap");return Phase.FALLING;
    }
    record Steering(float yaw,float forward,double distance) { }
    static Steering toward(double x,double z,float yaw,double tx,double tz,double stopRadius,float cap){
        double dx=tx-x,dz=tz-z,distance=Math.hypot(dx,dz);
        double target=distance<1e-6?yaw:Math.toDegrees(Math.atan2(-dx,dz));
        double error=Math.IEEEremainder(target-yaw,360);
        float next=(float)(yaw+Math.max(-45,Math.min(45,error)));
        double residual=Math.abs(Math.IEEEremainder(target-next,360));
        // Align while neutral; this avoids cutting corners and spending the jump while turning.
        float forward=distance<=stopRadius||residual>1?0:(float)Math.min(cap,distance*.8);
        return new Steering(next,forward,distance);
    }
    static boolean finite(double...v){for(double n:v)if(!Double.isFinite(n))return false;return true;}
    static void require(boolean ok,String reason){if(!ok)throw new IllegalArgumentException(reason);}
    private ScopedLocalSegmentPolicy() { }
}

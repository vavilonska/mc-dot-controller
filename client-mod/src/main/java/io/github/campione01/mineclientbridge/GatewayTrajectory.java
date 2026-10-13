package io.github.campione01.mineclientbridge;

import java.util.ArrayList;
import java.util.List;

/** Vanilla 1.21.1 pearl air motion. Uncertainty encloses bounded triangle launch spread.
 * Coordinates are relative to pearl spawn (player eye minus .1Y), not player feet.
 * A plan is accepted only when an entire integer-tick envelope fits the aperture.
 */
final class GatewayTrajectory {
    static final double DRAG=(double).99F, GRAVITY=.03, SPEED=1.5;
    static final double LAUNCH_ERROR=.0172275*SPEED+.0005, POSITION_ERROR=.02, RADIUS=.125;
    record Point(double x,double y,double z,double uncertainty){}
    record Plan(double vx,double vy,double vz,int insideTick,List<Point> points) {
        float yaw(){return (float)Math.toDegrees(Math.atan2(-vx,vz));}
        float pitch(){return (float)-Math.toDegrees(Math.atan2(vy,Math.hypot(vx,vz)));}
    }
    static Plan plan(double dx,double dy,double dz,double inheritedX,double inheritedZ) {
        if(!Double.isFinite(dx)||!Double.isFinite(dy)||!Double.isFinite(dz)||!Double.isFinite(inheritedX)||!Double.isFinite(inheritedZ)
                || Math.sqrt(dx*dx+dy*dy+dz*dz)>4.6 || Math.hypot(inheritedX,inheritedZ)>.01)return null;
        for(int n=1;n<=4;n++) {
            double sum=0,power=1,gravityDrop=0,gvel=0;
            for(int i=0;i<n;i++){sum+=power;power*=DRAG;gravityDrop+=gvel;gvel=gvel*DRAG+GRAVITY;}
            double x=(dx/sum)-inheritedX,y=(dy+gravityDrop)/sum,z=(dz/sum)-inheritedZ;
            double length=Math.sqrt(x*x+y*y+z*z);if(length<.01)continue;
            x=x/length*SPEED;y=y/length*SPEED;z=z/length*SPEED;
            double px=0,py=0,pz=0,vx=x+inheritedX,vy=y,vz=z+inheritedZ,e=0,evel=LAUNCH_ERROR;
            List<Point> points=new ArrayList<>();points.add(new Point(0,0,0,POSITION_ERROR));
            for(int i=1;i<=n+1;i++) {
                px+=vx;py+=vy;pz+=vz;e+=evel;
                points.add(new Point(px,py,pz,e+POSITION_ERROR));
                vx*=DRAG;vy=vy*DRAG-GRAVITY;vz*=DRAG;evel*=DRAG;
            }
            Point end=points.get(n);double margin=end.uncertainty+RADIUS+.01;
            if(Math.abs(end.x-dx)+margin<.5 && Math.abs(end.y-dy)+margin<.5 && Math.abs(end.z-dz)+margin<.5)
                return new Plan(x,y,z,n,List.copyOf(points));
        }
        return null;
    }
    private GatewayTrajectory(){}
}

package io.github.campione01.mineclientbridge;

import java.util.List;

/** Pure control policy. Native boat physics remains authoritative; no pose/velocity writes. */
final class BoatSteering {
    static final double MAX_SPEED=.46, CRUISE_SPEED=.26, ARRIVAL_RADIUS=.65, SETTLED_SPEED=.025;
    record Point(double x,double z) { double distance(Point b) { return Math.hypot(x-b.x,z-b.z); } }
    record Pose(double x,double z,double yaw,double vx,double vz,double yawRate) {
        double speed() { return Math.hypot(vx,vz); }
    }
    record Step(int waypoint,boolean left,boolean right,boolean forward,boolean backward,
                boolean atEndpoint,boolean settled,String phase,double distance) { }
    record Decision(Step step,int turnLock) { }
    record Turn(double error,int lock) { }
    private BoatSteering() { }
    static double wrap(double degrees) { return ((degrees+180)%360+360)%360-180; }
    // On ordinary still water drag is .9/tick. This is a conservative coasting
    // allowance plus two command/observation ticks; not a calibrated hard guarantee.
    static double safetyDistance(double speed) { return speed*10+2; }
    static Step step(Pose pose,List<Point> points,int index) {return decide(pose,points,index,0).step();}
    static Turn turn(double error,double rate,int lock) {
        if (lock!=0 && Math.abs(error)<90) lock=0;
        if (lock==0 && Math.abs(error)>150)
            lock=(Math.abs(rate)>.05?rate:error)<0?-1:1;
        return new Turn(lock==0?error:Math.copySign(Math.abs(error),lock),lock);
    }
    static Decision decide(Pose pose,List<Point> points,int index,int turnLock) {
        if (points.isEmpty() || index<0 || index>=points.size() || !finite(pose))
            throw new IllegalArgumentException("invalid_boat_control_state");
        Point current=new Point(pose.x,pose.z); double speed=pose.speed();
        int previousWaypoint=index;
        while (index<points.size()-1 && current.distance(points.get(index))<=Math.max(.85,speed*3)) index++;
        if(index!=previousWaypoint)turnLock=0;
        Point goal=points.get(index); double distance=current.distance(goal);
        boolean last=index==points.size()-1;
        boolean at=last && distance<=ARRIVAL_RADIUS;
        double angle=Math.toDegrees(Math.atan2(-(goal.x-pose.x),goal.z-pose.z));
        // Latch a reverse turn (>150 degrees) until <90 degrees remains.
        // Stateless shortest-side selection chatters at +/-180 or a sector
        // boundary under vanilla's one-tick rideTick input pipeline.
        Turn turn=turn(wrap(angle-pose.yaw),pose.yawRate,turnLock);
        turnLock=turn.lock();double error=turn.error();
        double predicted=error-pose.yawRate*4;
        boolean left=predicted < -3, right=predicted > 3;
        double radians=Math.toRadians(pose.yaw);
        double along=-Math.sin(radians)*pose.vx+Math.cos(radians)*pose.vz;
        if (at) {
            // Do not spin toward a point already underneath the boat. Counter the
            // observed angular momentum only, while normal drag removes lateral drift.
            left=pose.yawRate>1.2; right=pose.yawRate< -1.2;
            return new Decision(new Step(index,left,right,along<-.025,along>.025,true,
                    speed<=SETTLED_SPEED && Math.abs(pose.yawRate)<=.25,"settling",distance),0);
        }
        double target=last?Math.min(CRUISE_SPEED,Math.max(.04,(distance-.45)/9)):CRUISE_SPEED;
        // Slow BEFORE an upcoming corner; no compulsory zero-input waypoint gap.
        if (!last) {
            Point next=points.get(index+1);
            double nextYaw=Math.toDegrees(Math.atan2(-(next.x-goal.x),next.z-goal.z));
            if (Math.abs(wrap(nextYaw-angle))>30 && distance<safetyDistance(speed)+1) target=Math.min(target,.07);
        }
        boolean turning=Math.abs(error)>28;
        boolean braking=speed>target+.02 || (turning && speed>.08);
        boolean up=!turning && !braking && speed<target;
        boolean down=braking && along>.025;
        return new Decision(new Step(index,left,right,up,down,false,false,
                braking?"braking":turning?"turning":"cruising",distance),turnLock);
    }
    static boolean finite(Pose p) {
        return Double.isFinite(p.x)&&Double.isFinite(p.z)&&Double.isFinite(p.yaw)
                &&Double.isFinite(p.vx)&&Double.isFinite(p.vz)&&Double.isFinite(p.yawRate);
    }
}

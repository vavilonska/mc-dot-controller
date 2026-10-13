package io.github.campione01.mineclientbridge;

/** Narrow finite bow-then-shield window. No policy permits replaying an aborted draw. */
final class BlazeShieldPolicy {
    static final int MIN_COVER_TICKS=20, MAX_COVER_TICKS=120, MAX_PRE_COVER_TICKS=240;
    // At most two pre-volley cycles + one post volley: nine ordinary five-damage fireballs,
    // six shield durability each, plus ten points margin. Other nearby hostiles are rejected.
    static final int SHIELD_RESERVE=64;
    static boolean reserve(int maximum,int damage){return maximum>0&&damage>=0&&damage<=maximum&&maximum-damage>=SHIELD_RESERVE;}
    static boolean range(double distance){return Double.isFinite(distance)&&distance>=16&&distance<=32;}
    static boolean initialReady(boolean sawCharge,int ticks,boolean charged,boolean fireballs){return sawCharge&&ticks>=MIN_COVER_TICKS&&ticks<=MAX_PRE_COVER_TICKS&&!charged&&!fireballs;}
    static boolean ready(int ticks,boolean charged,boolean fireballs){return ticks>=MIN_COVER_TICKS&&ticks<=MAX_COVER_TICKS&&!charged&&!fireballs;}
    static boolean frontal(double yaw,double dx,double dz) {
        if(!Double.isFinite(yaw)||!Double.isFinite(dx)||!Double.isFinite(dz)||Math.hypot(dx,dz)<.01)return false;
        double angle=Math.toDegrees(Math.atan2(-dx,dz));
        return Math.abs(Math.IEEEremainder(angle-yaw,360))<=55;
    }
    /** Only a known newly self-owned arrow still travelling outward along the released shot. */
    static boolean outgoingArrow(double dx,double dz,double vx,double vz,double shotX,double shotZ) {
        for(double value:new double[]{dx,dz,vx,vz,shotX,shotZ})if(!Double.isFinite(value))return false;
        double speed=Math.hypot(vx,vz),direction=Math.hypot(shotX,shotZ);
        return speed>.01 && direction>.01 && (vx*shotX+vz*shotZ)>=.9*speed*direction
                && dx*shotX+dz*shotZ>=0 && dx*vx+dz*vz>=0;
    }
    private BlazeShieldPolicy(){}
}

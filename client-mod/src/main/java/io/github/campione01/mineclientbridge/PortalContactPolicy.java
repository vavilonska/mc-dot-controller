package io.github.campione01.mineclientbridge;
/** Actual source-player contact only; records evidence and never grants an effect. */
final class PortalContactPolicy {
    static boolean permits(PortalTransitionPolicy.Bound b,PortalTransitionPolicy.Live v,boolean owned,boolean exactPlayer,boolean exactLevel,boolean exactServer,boolean exactPortal,boolean exactCell,boolean overlap,boolean attempted,boolean unknown){
        return b!=null&&v!=null&&owned&&exactPlayer&&exactLevel&&exactServer&&exactPortal&&exactCell&&overlap&&attempted&&!unknown
            &&b.action().equals(v.action())&&b.session().equals(v.session())&&b.player().equals(v.player())&&b.server().equals(v.server())
            &&b.sourceWorld().equals(v.world())&&b.sourceDimension().equals(v.dimension())&&b.revision()==v.revision()
            &&v.nano()>=b.sourceNano()&&v.nano()<b.deadline();
    }
    static boolean originalHealth(boolean dead,float current,float floor){
        return !dead&&Float.isFinite(current)&&Float.isFinite(floor)&&current>0&&floor>0&&current>=floor;
    }
    static boolean sourceLifecycle(boolean originalPlayer,boolean alive,boolean stableHealth,boolean overlap,long contactTick,long nowTick){
        return originalPlayer&&alive&&stableHealth&&overlap&&contactTick>=0&&nowTick>=contactTick&&nowTick-contactTick<=1;
    }
    static boolean overlaps(boolean end,int x,int y,int z,double minX,double minY,double minZ,double maxX,double maxY,double maxZ){
        return Double.isFinite(minX)&&Double.isFinite(minY)&&Double.isFinite(minZ)&&Double.isFinite(maxX)&&Double.isFinite(maxY)&&Double.isFinite(maxZ)
            &&minX<maxX&&minY<maxY&&minZ<maxZ&&maxX>x&&minX<x+1&&maxZ>z&&minZ<z+1
            &&maxY>y+(end?6.0/16:0)&&minY<y+(end?12.0/16:1);
    }
    private PortalContactPolicy(){}
}

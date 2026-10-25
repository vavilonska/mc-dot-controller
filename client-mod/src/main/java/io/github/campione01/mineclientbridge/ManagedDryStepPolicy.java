package io.github.campione01.mineclientbridge;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/** Pure, bounded proof of one dry ordinary step. The adapter owns all world and API reads. */
final class ManagedDryStepPolicy {
    enum Kind { TRAVERSE, ASCEND, DESCEND, DIAGONAL }
    record Point(int x,int y,int z) {}
    record Box(double minX,double minY,double minZ,double maxX,double maxY,double maxZ) {}
    /** Conservative post-impulse velocity; y includes at least .42 for a pending ordinary grounded jump. */
    record Motion(double x,double y,double z) {}
    record Step(Kind kind,Point source,Point destination) {}
    record Cell(int x,int y,int z) {}
    record CellState(boolean loaded,boolean fluidEmpty,boolean fullSupport,boolean bodyClear) {}
    record Decision(boolean allowed,String reason,int checkedCells) {}
    @FunctionalInterface interface CellReader { CellState read(Cell cell); }

    static final int MAX_HORIZONTAL_CELLS=81,MAX_CHECKED_CELLS=128;
    private static final int WORLD_XZ_LIMIT=29_999_980,MIN_Y=-2048,MAX_Y=2048;
    // Native proof: current speed <= .35 plus one yaw-bound ordinary impulse <= .101,
    // player speed <= .100001, exact dry friction .6, ordinary gravity/jump, no boosts/sprint.
    // The impulse bound rounds upward for vanilla's float .21600002 / (.6 * .6 * .6).
    private static final double MAX_HORIZONTAL_SPEED=.451,MAX_UP_SPEED=.75,MAX_DOWN_SPEED=1.5;
    // Includes airborne drag .91: 11.2 > 1/(1-.91), unlike a short ground-only coast.
    private static final double COAST_MULTIPLIER=11.2;
    private record Column(int x,int z) {}

    static Decision assess(Step step,Box box,Motion motion,CellReader reader) {
        return assess(step,box,motion,motion,reader);
    }

    static Decision assess(Step step,Box box,Motion maxImpulse,Motion noImpulse,CellReader reader) {
        if(step==null||step.kind()==null||!bounded(step.source())||!bounded(step.destination()))
            return deny("managed_navigation_step_unproven",0);
        Point src=step.source(),dst=step.destination();
        int dx=dst.x()-src.x(),dy=dst.y()-src.y(),dz=dst.z()-src.z();
        boolean cardinal=Math.abs(dx)+Math.abs(dz)==1;
        boolean shape=switch(step.kind()) {
            case TRAVERSE -> cardinal&&dy==0;
            case ASCEND -> cardinal&&dy==1;
            case DESCEND -> cardinal&&dy==-1;
            case DIAGONAL -> Math.abs(dx)==1&&Math.abs(dz)==1&&dy==0;
        };
        if(!shape)return deny("managed_navigation_step_geometry_unsupported",0);
        if(!valid(box)||!valid(maxImpulse)||!valid(noImpulse))return deny("managed_navigation_motion_unproven",0);
        double cx=(box.minX()+box.maxX())*.5,cz=(box.minZ()+box.maxZ())*.5;
        double tx=dst.x()+.5,tz=dst.z()+.5;
        int lowY=Math.min(src.y(),dst.y()),highY=Math.max(src.y(),dst.y());
        if(cx<Math.min(src.x()+.5,tx)-.8||cx>Math.max(src.x()+.5,tx)+.8
                ||cz<Math.min(src.z()+.5,tz)-.8||cz>Math.max(src.z()+.5,tz)+.8
                ||box.minY()<lowY-.1||box.minY()>highY+1.5)
            return deny("managed_navigation_step_position_unbound",0);
        return assessEnvelope(box,maxImpulse,noImpulse,reader,tx,tz,lowY-1,highY-1);
    }

    /** Admission or neutral calculation wait only; the native caller must separately prove grounded. */
    static Decision assessStation(Box box,Motion motion,CellReader reader) {
        return assessStation(box,motion,motion,reader);
    }

    static Decision assessStation(Box box,Motion maxImpulse,Motion noImpulse,CellReader reader) {
        if(!valid(box)||!valid(maxImpulse)||!valid(noImpulse))return deny("managed_navigation_motion_unproven",0);
        double cx=(box.minX()+box.maxX())*.5,cz=(box.minZ()+box.maxZ())*.5;
        double feet=Math.rint(box.minY());
        if(Math.abs(box.minY()-feet)>1e-5||!bounded(new Point(floor(cx),(int)feet,floor(cz))))
            return deny("managed_navigation_station_support_unbound",0);
        int support=(int)feet-1;
        return assessEnvelope(box,maxImpulse,noImpulse,reader,cx,cz,support,support);
    }

    private static Decision assessEnvelope(Box box,Motion maxImpulse,Motion noImpulse,CellReader reader,double tx,double tz,
            int supportLow,int supportHigh) {
        double halfX=(box.maxX()-box.minX())*.5+.10,halfZ=(box.maxZ()-box.minZ())*.5+.10;
        double cx=(box.minX()+box.maxX())*.5,cz=(box.minZ()+box.maxZ())*.5;
        double vx=cx+COAST_MULTIPLIER*maxImpulse.x(),vz=cz+COAST_MULTIPLIER*maxImpulse.z();
        double nx=cx+COAST_MULTIPLIER*noImpulse.x(),nz=cz+COAST_MULTIPLIER*noImpulse.z();
        // A collision may clip either horizontal component independently. The entire
        // current-to-coast rectangle, not only its diagonal, must therefore remain dry.
        // Include zero-to-maximum acceleration: weaker air input can leave an opposing
        // current velocity on the opposite side of zero from the maximum-impulse endpoint.
        double coastMinX=Math.min(cx,Math.min(vx,nx))-halfX,coastMaxX=Math.max(cx,Math.max(vx,nx))+halfX;
        double coastMinZ=Math.min(cz,Math.min(vz,nz))-halfZ,coastMaxZ=Math.max(cz,Math.max(vz,nz))+halfZ;

        int minX=floor(Math.min(tx-halfX,coastMinX));
        int maxX=floor(Math.nextDown(Math.max(tx+halfX,coastMaxX)));
        int minZ=floor(Math.min(tz-halfZ,coastMinZ));
        int maxZ=floor(Math.nextDown(Math.max(tz+halfZ,coastMaxZ)));
        long candidateCount=(long)(maxX-minX+1)*(maxZ-minZ+1);
        if(candidateCount<=0||candidateCount>MAX_HORIZONTAL_CELLS)
            return deny("managed_navigation_sweep_bound",0);
        List<Column> columns=new ArrayList<>();
        for(int x=minX;x<=maxX;x++)for(int z=minZ;z<=maxZ;z++) {
            boolean coastReachable=x+1>=coastMinX&&x<=coastMaxX&&z+1>=coastMinZ&&z<=coastMaxZ;
            if(coastReachable||touches(cx,cz,tx,tz,halfX,halfZ,x,z))
                columns.add(new Column(x,z));
        }
        // Include the complete neutral-input jump apex, not just the first upward tick.
        double rise=remainingRise(Math.max(maxImpulse.y(),noImpulse.y()));
        if(!Double.isFinite(rise))return deny("managed_navigation_motion_unproven",0);
        int scanTop=Math.max(supportHigh+2,floor(Math.nextDown(box.maxY()+rise)));
        long count=(long)columns.size()*(scanTop-supportLow+1);
        if(columns.isEmpty()||count<=0||count>MAX_CHECKED_CELLS||reader==null)
            return deny("managed_navigation_sweep_bound",0);
        Map<Cell,CellState> snapshot=new HashMap<>();int checked=0;
        try {
            for(Column column:columns) {
                // A proven full higher floor seals off the lower cell; water beneath it is irrelevant.
                for(int y=supportHigh;y<=scanTop;y++) {
                    Cell cell=new Cell(column.x(),y,column.z());
                    CellState state=reader.read(cell);checked++;
                    if(state==null||!state.loaded())return deny("managed_navigation_step_cell_unloaded",checked);
                    if(!state.fluidEmpty())return deny("managed_navigation_step_fluid_present",checked);
                    snapshot.put(cell,state);
                }
                if(supported(snapshot,column,supportHigh,scanTop))continue;
                if(supportHigh==supportLow)return deny("managed_navigation_step_support_or_clearance",checked);
                Cell cell=new Cell(column.x(),supportLow,column.z());
                CellState state=reader.read(cell);checked++;
                if(state==null||!state.loaded())return deny("managed_navigation_step_cell_unloaded",checked);
                if(!state.fluidEmpty())return deny("managed_navigation_step_fluid_present",checked);
                snapshot.put(cell,state);
                if(!supported(snapshot,column,supportLow,scanTop))return deny("managed_navigation_step_support_or_clearance",checked);
            }
        }catch(RuntimeException unavailable){return deny("managed_navigation_step_cell_unavailable",checked);}
        return new Decision(true,null,checked);
    }
    private static boolean supported(Map<Cell,CellState> cells,Column c,int y,int scanTop) {
        if(!cells.get(new Cell(c.x(),y,c.z())).fullSupport())return false;
        // The entire actual/upward head envelope must remain clear, including above two-block height.
        for(int bodyY=y+1;bodyY<=scanTop;bodyY++)
            if(!cells.get(new Cell(c.x(),bodyY,c.z())).bodyClear())return false;
        return true;
    }
    /** Native must prove ordinary gravity/drag and no jump/effect boost before using this recurrence. */
    private static double remainingRise(double velocityY) {
        double rise=0,vy=Math.max(0,velocityY);
        for(int tick=0;tick<32&&vy>0;tick++) {
            rise+=vy;
            vy=(vy-.08)*.98;
        }
        // One centimeter covers floating-point rounding in the standard bounded recurrence.
        return vy>0?Double.NaN:rise+.01;
    }
    /** Segment versus the cell expanded by the actual horizontal half-extents. */
    private static boolean touches(double ax,double az,double bx,double bz,double hx,double hz,int x,int z) {
        double[] interval={0,1};
        return clip(ax,bx-ax,x-hx,x+1+hx,interval)&&clip(az,bz-az,z-hz,z+1+hz,interval);
    }
    private static boolean clip(double origin,double delta,double lo,double hi,double[] interval) {
        if(delta==0)return origin>=lo&&origin<=hi;
        double t0=(lo-origin)/delta,t1=(hi-origin)/delta;
        interval[0]=Math.max(interval[0],Math.min(t0,t1));
        interval[1]=Math.min(interval[1],Math.max(t0,t1));
        return interval[0]<=interval[1];
    }
    private static boolean bounded(Point p) {
        return p!=null&&p.x()>=-WORLD_XZ_LIMIT&&p.x()<=WORLD_XZ_LIMIT
            &&p.z()>=-WORLD_XZ_LIMIT&&p.z()<=WORLD_XZ_LIMIT&&p.y()>=MIN_Y&&p.y()<=MAX_Y;
    }
    private static boolean valid(Box b) {
        if(b==null||!finite(b.minX(),b.minY(),b.minZ(),b.maxX(),b.maxY(),b.maxZ()))return false;
        double width=b.maxX()-b.minX(),depth=b.maxZ()-b.minZ(),height=b.maxY()-b.minY();
        return width>=.1&&width<=1.2&&depth>=.1&&depth<=1.2&&height>=.5&&height<=2.1
            &&Math.abs(b.minX())<=30_000_000&&Math.abs(b.maxX())<=30_000_000
            &&Math.abs(b.minZ())<=30_000_000&&Math.abs(b.maxZ())<=30_000_000
            &&b.minY()>=MIN_Y-2&&b.maxY()<=MAX_Y+5;
    }
    private static boolean valid(Motion m) {
        return m!=null&&finite(m.x(),m.y(),m.z())&&Math.hypot(m.x(),m.z())<=MAX_HORIZONTAL_SPEED
            &&m.y()>=-MAX_DOWN_SPEED&&m.y()<=MAX_UP_SPEED;
    }
    private static boolean finite(double... values){for(double v:values)if(!Double.isFinite(v))return false;return true;}
    private static int floor(double value){return (int)Math.floor(value);}
    private static Decision deny(String reason,int checked){return new Decision(false,reason,checked);}
    private ManagedDryStepPolicy() {}
}

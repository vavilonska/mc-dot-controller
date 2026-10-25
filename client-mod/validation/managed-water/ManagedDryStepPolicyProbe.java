package io.github.campione01.mineclientbridge;

import java.util.HashSet;
import java.util.Set;
import java.util.function.ToIntFunction;

/** Source-only standalone checks; needs no Minecraft, Baritone, reflection, or live world. */
public final class ManagedDryStepPolicyProbe {
    private static final ManagedDryStepPolicy.CellState SOLID=new ManagedDryStepPolicy.CellState(true,true,true,false);
    private static final ManagedDryStepPolicy.CellState AIR=new ManagedDryStepPolicy.CellState(true,true,false,true);
    private static final ManagedDryStepPolicy.CellState WATER=new ManagedDryStepPolicy.CellState(true,false,false,true);
    private static final ManagedDryStepPolicy.Motion STILL=new ManagedDryStepPolicy.Motion(0,0,0);
    private static int checks;
    private static void check(boolean value,String name){checks++;if(!value)throw new AssertionError(name);}
    private static ManagedDryStepPolicy.Point p(int x,int y,int z){return new ManagedDryStepPolicy.Point(x,y,z);}
    private static ManagedDryStepPolicy.Step step(ManagedDryStepPolicy.Kind kind,int x,int y,int z){
        return new ManagedDryStepPolicy.Step(kind,p(0,70,0),p(x,y,z));
    }
    private static ManagedDryStepPolicy.Box box(double x,double y,double z){
        return new ManagedDryStepPolicy.Box(x-.3,y,z-.3,x+.3,y+1.8,z+.3);
    }
    private static ManagedDryStepPolicy.CellReader floor(ToIntFunction<ManagedDryStepPolicy.Cell> height){
        return c->c.y()<=height.applyAsInt(c)?SOLID:AIR;
    }
    private static ManagedDryStepPolicy.Decision assess(ManagedDryStepPolicy.Step s,ManagedDryStepPolicy.CellReader r){
        return ManagedDryStepPolicy.assess(s,box(.5,70,.5),STILL,r);
    }
    private static void denied(ManagedDryStepPolicy.Decision d,String name){
        check(!d.allowed()&&d.reason()!=null,name);
        check(d.checkedCells()<=ManagedDryStepPolicy.MAX_CHECKED_CELLS,name+" bounded");
    }
    public static void main(String[] args){
        var flat=step(ManagedDryStepPolicy.Kind.TRAVERSE,1,70,0);
        var plane=floor(c->69);
        check(ManagedDryStepPolicy.assessStation(box(.5,70,.5),STILL,plane).allowed(),"dry station");
        var opposingNoImpulse=new ManagedDryStepPolicy.Motion(-.08,0,0);
        var opposingMaxImpulse=new ManagedDryStepPolicy.Motion(.021,0,0);
        check(ManagedDryStepPolicy.assess(flat,box(.5,70,.5),opposingMaxImpulse,opposingNoImpulse,plane).allowed(),
            "dry opposing velocity with weaker airborne acceleration");
        denied(ManagedDryStepPolicy.assess(flat,box(.5,70,.5),opposingMaxImpulse,opposingNoImpulse,
            c->c.x()==-1&&c.y()==70?WATER:plane.read(c)),"opposing coast water hidden by maximum input reversal");
        check(ManagedDryStepPolicy.assessStation(box(.5,70,.5),opposingMaxImpulse,opposingNoImpulse,plane).allowed(),
            "station accepts dry full impulse interval");
        denied(ManagedDryStepPolicy.assessStation(box(.5,70,.5),opposingMaxImpulse,opposingNoImpulse,
            c->c.x()==-1&&c.y()==70?WATER:plane.read(c)),"station covers opposing no-impulse coast");
        var pendingJump=new ManagedDryStepPolicy.Motion(0,.42,0);
        check(ManagedDryStepPolicy.assessStation(box(.5,70,.5),pendingJump,plane).allowed(),
            "dry station through complete ordinary jump apex");
        denied(ManagedDryStepPolicy.assessStation(box(.5,70,.5),pendingJump,
            c->c.y()==73?SOLID:plane.read(c)),"roof above one-tick envelope within full jump apex");
        check(ManagedDryStepPolicy.assessStation(box(.5,70,.5),STILL,
            c->c.y()==68?WATER:plane.read(c)).allowed(),"dry station over sealed water");
        denied(ManagedDryStepPolicy.assessStation(box(.5,70,.5),new ManagedDryStepPolicy.Motion(.3,0,0),
            c->c.x()==1&&c.y()==70?WATER:plane.read(c)),"station coast reaches adjacent water");
        denied(ManagedDryStepPolicy.assessStation(box(.5,70,.5),STILL,
            c->new ManagedDryStepPolicy.CellState(false,true,true,false)),"station unloaded footprint");
        denied(ManagedDryStepPolicy.assessStation(box(.5,70.5,.5),STILL,plane),"station cannot infer airborne full support");
        Set<ManagedDryStepPolicy.Cell> stationVisited=new HashSet<>();
        check(ManagedDryStepPolicy.assessStation(box(.5,70,.5),STILL,c->{stationVisited.add(c);return plane.read(c);}).allowed(),
            "station current footprint only");
        check(stationVisited.stream().allMatch(c->c.x()==0&&c.z()==0),"station invents no adjacent destination");
        for(int[] direction:new int[][]{{1,0},{-1,0},{0,1},{0,-1}}){
            int dx=direction[0],dz=direction[1];
            var walk=step(ManagedDryStepPolicy.Kind.TRAVERSE,dx,70,dz);
            check(assess(walk,plane).allowed(),"flat cardinal "+dx+","+dz);
            var up=step(ManagedDryStepPolicy.Kind.ASCEND,dx,71,dz);
            var upFloor=floor(c->c.x()*dx+c.z()*dz>=1?70:69);
            check(assess(up,upFloor).allowed(),"one-block ascent "+dx+","+dz);
            var down=step(ManagedDryStepPolicy.Kind.DESCEND,dx,69,dz);
            var downFloor=floor(c->c.x()*dx+c.z()*dz>=1?68:69);
            check(assess(down,downFloor).allowed(),"one-block descent "+dx+","+dz);
        }
        for(int dx:new int[]{-1,1})for(int dz:new int[]{-1,1})
            check(assess(step(ManagedDryStepPolicy.Kind.DIAGONAL,dx,70,dz),plane).allowed(),"flat diagonal "+dx+","+dz);

        var up=step(ManagedDryStepPolicy.Kind.ASCEND,1,71,0);
        var down=step(ManagedDryStepPolicy.Kind.DESCEND,1,69,0);
        check(ManagedDryStepPolicy.assess(up,box(.8,71.1,.5),new ManagedDryStepPolicy.Motion(.15,.2,0),
                floor(c->c.x()>=1?70:69)).allowed(),"ordinary dry airborne ascent remains admitted");
        var diagonalAscentMotion=new ManagedDryStepPolicy.Motion(.2,.2,.2);
        var diagonalAscentFloor=floor(c->c.x()>=1?70:69);
        check(ManagedDryStepPolicy.assess(up,box(.8,71.1,.5),diagonalAscentMotion,diagonalAscentFloor).allowed(),
            "dry independent-component ascent coast rectangle");
        denied(ManagedDryStepPolicy.assess(up,box(.8,71.1,.5),diagonalAscentMotion,
            c->c.x()==0&&c.z()==2&&c.y()==70?WATER:diagonalAscentFloor.read(c)),
            "clipped-component coast water off the straight segment");
        Set<ManagedDryStepPolicy.Cell> visited=new HashSet<>();
        var bridge=assess(flat,c->{check(visited.add(c),"each cell sampled once");return c.y()==68?WATER:plane.read(c);});
        check(bridge.allowed(),"full dry flat bridge over water");
        check(visited.stream().noneMatch(c->c.y()<69),"flat bridge never reads below sealed support");
        check(bridge.checkedCells()==visited.size(),"truthful sampled-cell count");
        Set<ManagedDryStepPolicy.Cell> upVisited=new HashSet<>();
        check(assess(up,c->{upVisited.add(c);if(c.x()>=1&&c.y()==69)return WATER;
            return c.y()<=(c.x()>=1?70:69)?SOLID:AIR;}).allowed(),"water beneath high ascent support is irrelevant");
        check(upVisited.stream().noneMatch(c->c.x()>=1&&c.y()==69),"higher ascent floor seals lower water");
        check(assess(down,c->{if(c.x()==0&&c.y()==68)return WATER;
            return c.y()<=(c.x()>=1?68:69)?SOLID:AIR;}).allowed(),"higher descent source floor seals lower water");
        check(assess(flat,c->c.z()==2?WATER:plane.read(c)).allowed(),"unrelated adjacent water outside swept corridor");

        denied(assess(down,floor(c->c.x()>=1?67:69)),"unsupported deep landing");
        denied(assess(down,c->c.x()>=1&&c.y()==69?WATER:(c.y()<=(c.x()>=1?68:69)?SOLID:AIR)),"wet one-block landing");
        denied(assess(flat,c->c.x()==1&&c.y()==69?new ManagedDryStepPolicy.CellState(true,false,true,false):plane.read(c)),"waterlogged full support");
        denied(assess(flat,c->c.x()==1&&c.y()==70?WATER:plane.read(c)),"shallow or flowing water at feet");
        denied(assess(flat,c->c.x()==1&&c.y()==71?WATER:plane.read(c)),"water at head");
        denied(assess(flat,c->c.x()==1&&c.y()==70?SOLID:plane.read(c)),"blocked body clearance");
        denied(assess(flat,c->c.x()==1&&c.y()==69?AIR:plane.read(c)),"missing destination support");
        denied(assess(step(ManagedDryStepPolicy.Kind.DIAGONAL,1,70,1),
            c->c.x()==1&&c.z()==0&&c.y()==70?WATER:plane.read(c)),"diagonal swept corner water");
        denied(ManagedDryStepPolicy.assess(flat,box(1.45,70,.5),new ManagedDryStepPolicy.Motion(.3,0,0),
            c->c.x()==2&&c.y()==70?WATER:plane.read(c)),"conservative coast reaches next column");
        var airborneDownBox=box(1.45,69.8,.5);
        var airborneDownMotion=new ManagedDryStepPolicy.Motion(.3,-.3,0);
        var dryDownFloor=floor(c->c.x()>=1?68:69);
        check(ManagedDryStepPolicy.assess(down,airborneDownBox,airborneDownMotion,dryDownFloor).allowed(),
            "ordinary airborne dry descent remains admitted");
        denied(ManagedDryStepPolicy.assess(down,airborneDownBox,airborneDownMotion,
            c->c.x()==4&&c.y()==69?WATER:dryDownFloor.read(c)),"airborne coast water beyond old three-times margin");
        denied(ManagedDryStepPolicy.assess(flat,box(.5,70,.7),STILL,
            c->c.z()==1&&c.y()==70?WATER:plane.read(c)),"ten-centimeter side margin protects swept edge");
        denied(ManagedDryStepPolicy.assess(flat,box(.5,70,.5),new ManagedDryStepPolicy.Motion(0,0,.3),
            c->c.z()==1&&c.y()==70?WATER:plane.read(c)),"sideways coast independently covered");
        denied(ManagedDryStepPolicy.assess(up,box(.8,71.1,.5),new ManagedDryStepPolicy.Motion(.1,.3,0),
            c->c.y()==73?WATER:(c.y()<=(c.x()>=1?70:69)?SOLID:AIR)),"ascending head and upward lookahead dry");
        denied(ManagedDryStepPolicy.assess(up,box(.8,71.1,.5),new ManagedDryStepPolicy.Motion(.1,.3,0),
            c->c.y()==73?SOLID:(c.y()<=(c.x()>=1?70:69)?SOLID:AIR)),"high solid roof in upward head envelope");
        var overBudget=ManagedDryStepPolicy.assess(up,box(.5,72.5,.5),new ManagedDryStepPolicy.Motion(.318,.75,.318),
            c->{throw new AssertionError("over-budget rectangle must not read cells");});
        denied(overBudget,"coast rectangle retains 128-cell fail-closed cap");
        check(overBudget.checkedCells()==0,"over-budget rectangle rejected before reading");

        for(var invalid:new ManagedDryStepPolicy.Step[]{
                step(ManagedDryStepPolicy.Kind.DESCEND,1,68,0),
                step(ManagedDryStepPolicy.Kind.DESCEND,0,69,0),
                step(ManagedDryStepPolicy.Kind.ASCEND,0,71,0),
                step(ManagedDryStepPolicy.Kind.TRAVERSE,2,70,0),
                step(ManagedDryStepPolicy.Kind.DIAGONAL,1,71,1),
                step(ManagedDryStepPolicy.Kind.TRAVERSE,1,71,0),
                step(ManagedDryStepPolicy.Kind.DIAGONAL,1,70,0),
                step(ManagedDryStepPolicy.Kind.TRAVERSE,0,70,0),
                new ManagedDryStepPolicy.Step(null,p(0,70,0),p(1,70,0)),
                new ManagedDryStepPolicy.Step(ManagedDryStepPolicy.Kind.TRAVERSE,p(Integer.MAX_VALUE,70,0),p(0,70,0)),
                new ManagedDryStepPolicy.Step(ManagedDryStepPolicy.Kind.TRAVERSE,p(0,4096,0),p(1,4096,0))}){
            var result=assess(invalid,c->{throw new AssertionError("invalid shape must not read cells");});
            denied(result,"unsupported step shape or coordinate bound");check(result.checkedCells()==0,"reject before reading");
        }
        denied(ManagedDryStepPolicy.assess(null,box(.5,70,.5),STILL,plane),"null step");
        denied(ManagedDryStepPolicy.assess(flat,null,STILL,plane),"null body");
        denied(ManagedDryStepPolicy.assess(flat,box(Double.NaN,70,.5),STILL,plane),"nonfinite body");
        denied(ManagedDryStepPolicy.assess(flat,box(.5,70,.5),new ManagedDryStepPolicy.Motion(Double.NaN,0,0),plane),"nonfinite velocity");
        denied(ManagedDryStepPolicy.assess(flat,box(.5,70,.5),STILL,new ManagedDryStepPolicy.Motion(Double.NaN,0,0),plane),"nonfinite no-impulse velocity");
        denied(ManagedDryStepPolicy.assessStation(box(.5,70,.5),STILL,new ManagedDryStepPolicy.Motion(.452,0,0),plane),"excessive no-impulse velocity");
        check(ManagedDryStepPolicy.assess(flat,box(.5,70,.5),new ManagedDryStepPolicy.Motion(.451,0,0),plane).allowed(),
            "upward-rounded post-impulse horizontal speed bound");
        denied(ManagedDryStepPolicy.assess(flat,box(.5,70,.5),new ManagedDryStepPolicy.Motion(.452,0,0),plane),"excessive post-impulse horizontal speed");
        denied(ManagedDryStepPolicy.assess(flat,box(.5,70,.5),new ManagedDryStepPolicy.Motion(.33,0,.33),plane),"combined post-impulse horizontal speed");
        denied(ManagedDryStepPolicy.assess(flat,box(.5,70,.5),new ManagedDryStepPolicy.Motion(0,.76,0),plane),"excessive upward speed");
        denied(ManagedDryStepPolicy.assess(flat,box(.5,70,.5),new ManagedDryStepPolicy.Motion(0,-1.51,0),plane),"excessive downward speed");
        denied(ManagedDryStepPolicy.assess(flat,box(4.5,70,.5),STILL,plane),"actual position outside source-destination bound");
        denied(ManagedDryStepPolicy.assess(flat,box(.5,68,.5),STILL,plane),"actual player below planned floor");
        denied(ManagedDryStepPolicy.assess(flat,box(.5,70,.5),STILL,null),"missing reader");
        denied(assess(flat,c->null),"unknown or stale cell snapshot");
        denied(assess(flat,c->new ManagedDryStepPolicy.CellState(false,true,true,false)),"unloaded cell");
        denied(assess(flat,c->{throw new IllegalStateException("expired snapshot");}),"reader failure");
        System.out.println("ManagedDryStepPolicyProbe "+checks+" checks passed");
    }
}

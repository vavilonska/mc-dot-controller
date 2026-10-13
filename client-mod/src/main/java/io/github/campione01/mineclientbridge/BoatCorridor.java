package io.github.campione01.mineclientbridge;

import java.util.ArrayList;
import java.util.List;

/** Exact continuous axis-aligned hull sweep; source must use the actual boat CollisionContext. */
final class BoatCorridor {
    record Column(int x,int z) { }
    record Cell(boolean loaded, boolean collisionKnown, boolean collisionEmpty, boolean sourceWater,
                boolean air, boolean hazardous) { }
    record Result(boolean clear,String reason,int x,int y,int z) { }
    @FunctionalInterface interface Source { Cell read(int x,int y,int z); }
    static Result check(double x,double z,double dx,double dz,double halfX,double halfZ,
                        int surfaceY,Source source) {
        for (var c:swept(x,z,dx,dz,halfX,halfZ)) {
            // Two full layers of still water, then three air layers for hull/passenger clearance.
            for (int y=surfaceY-2;y<=surfaceY+2;y++) {
                Cell cell;
                try { cell=source.read(c.x,y,c.z); }
                catch (RuntimeException e) { return new Result(false,"cell_read_failed",c.x,y,c.z); }
                String reason=null;
                if (cell==null) reason="unknown";
                else if (!cell.loaded) reason="unloaded";
                else if (!cell.collisionKnown) reason="collision_unknown";
                else if (cell.hazardous) reason="hazard";
                else if (!cell.collisionEmpty) reason="collision";
                else if (y<surfaceY && !cell.sourceWater) reason="requires_deep_still_water";
                else if (y>=surfaceY && !cell.air) reason="requires_open_air";
                if (reason!=null) return new Result(false,reason,c.x,y,c.z);
            }
        }
        return new Result(true,"clear",0,0,0);
    }
    static List<Column> swept(double x,double z,double dx,double dz,double halfX,double halfZ) {
        if (!Double.isFinite(x)||!Double.isFinite(z)||!Double.isFinite(dx)||!Double.isFinite(dz)
                ||!Double.isFinite(halfX)||!Double.isFinite(halfZ)||halfX<=0||halfZ<=0
                ||halfX>3||halfZ>3||Math.hypot(dx,dz)>32||Math.abs(x)+Math.abs(dx)>30000000
                ||Math.abs(z)+Math.abs(dz)>30000000) throw new IllegalArgumentException("invalid_boat_sweep");
        double hx=halfX+1e-7,hz=halfZ+1e-7;
        List<Column> cells=new ArrayList<>();
        for(int bx=(int)Math.floor(Math.min(x,x+dx)-hx);bx<=(int)Math.floor(Math.max(x,x+dx)+hx);bx++)
            for(int bz=(int)Math.floor(Math.min(z,z+dz)-hz);bz<=(int)Math.floor(Math.max(z,z+dz)+hz);bz++) {
                double[] interval={0,1};
                if(clip(x,dx,bx-hx,bx+1+hx,interval)&&clip(z,dz,bz-hz,bz+1+hz,interval)) cells.add(new Column(bx,bz));
            }
        return List.copyOf(cells);
    }
    private static boolean clip(double s,double d,double lo,double hi,double[] t) {
        if(d==0) return s>=lo&&s<=hi;
        double a=(lo-s)/d,b=(hi-s)/d;
        t[0]=Math.max(t[0],Math.min(a,b));t[1]=Math.min(t[1],Math.max(a,b));return t[0]<=t[1];
    }
}

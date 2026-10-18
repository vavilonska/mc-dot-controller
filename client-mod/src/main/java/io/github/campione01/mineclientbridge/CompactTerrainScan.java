package io.github.campione01.mineclientbridge;
import java.util.ArrayList;
import java.util.List;
import java.util.function.LongSupplier;
/** ID-only read scheduling. No collision/physics facts and no execution authority. */
final class CompactTerrainScan {
    static final long MAX_NANOS=8_000_000L;
    record Cell(int x,int y,int z,String status,String id) {}
    interface Source { Cell read(int x,int y,int z); }
    record Result(int radius,int x,int y,int z,List<Cell> cells,int total,long elapsedNanos,boolean budgetExhausted) {
        boolean complete(){return cells.size()==total;}
    }
    static Result read(int radius,int x,int y,int z,LongSupplier clock,Source source){
        if(radius<1||radius>2)throw new IllegalArgumentException("compact_radius");
        int width=2*radius+1,total=width*width*5;long started=clock.getAsLong();List<Cell> cells=new ArrayList<>(total);
        for(int offset=0;offset<total;offset++){
            long age=clock.getAsLong()-started;if(age<0)throw new IllegalStateException("compact_terrain_clock_reversed");
            if(age>=MAX_NANOS)return new Result(radius,x,y,z,List.copyOf(cells),total,age,true);
            int cx=x-radius+offset%width,cz=z-radius+(offset/width)%width,cy=y-2+offset/(width*width);
            Cell cell;
            try {cell=source.read(cx,cy,cz);
                if(cell==null||cell.x()!=cx||cell.y()!=cy||cell.z()!=cz
                    ||!List.of("loaded","unloaded","out_of_world","read_failed").contains(cell.status())
                    ||(cell.status().equals("loaded")&&(cell.id()==null||cell.id().isBlank()||cell.id().length()>160)))
                    throw new IllegalStateException("compact_cell_invalid");
            }catch(RuntimeException failure){cell=new Cell(cx,cy,cz,"read_failed",null);}
            cells.add(cell);
        }
        long elapsed=clock.getAsLong()-started;if(elapsed<0)throw new IllegalStateException("compact_terrain_clock_reversed");
        return new Result(radius,x,y,z,List.copyOf(cells),total,elapsed,elapsed>=MAX_NANOS);
    }
    private CompactTerrainScan(){}
}

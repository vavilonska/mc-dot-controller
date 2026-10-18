package io.github.campione01.mineclientbridge;
import java.util.HashSet;
public final class CompactTerrainScanTest {
    static int checks;static void ok(boolean v){checks++;if(!v)throw new AssertionError("check "+checks);}
    public static void main(String[]args){
        for(int radius:new int[]{1,2})for(int y:new int[]{-64,0,64,319}){
            long[] clock={100};int[] reads={0};
            var result=CompactTerrainScan.read(radius,-1,y,-16,()->clock[0],(x,yy,z)->{reads[0]++;clock[0]+=50_000;return new CompactTerrainScan.Cell(x,yy,z,"loaded","minecraft:stone");});
            ok(result.complete());ok(!result.budgetExhausted());ok(reads[0]==(2*radius+1)*(2*radius+1)*5);ok(result.elapsedNanos()==reads[0]*50_000L);
            var cells=new HashSet<String>();for(var cell:result.cells())ok(cells.add(cell.x()+":"+cell.y()+":"+cell.z()));
            ok(cells.size()==result.total());
        }
        // The old full-physics 2ms page would be partial; bounded ID-only 45 reads at 60us completes in 2.7ms.
        long[] clock={0};var cold=CompactTerrainScan.read(1,0,65,0,()->clock[0],(x,y,z)->{clock[0]+=60_000;return new CompactTerrainScan.Cell(x,y,z,"loaded","minecraft:air");});ok(cold.complete()&&cold.elapsedNanos()>TerrainScan.PAGE_BUDGET_NANOS&&cold.elapsedNanos()<CompactTerrainScan.MAX_NANOS);
        clock[0]=0;int[] reads={0};var slow=CompactTerrainScan.read(2,0,0,0,()->clock[0],(x,y,z)->{reads[0]++;clock[0]+=2_000_000;return new CompactTerrainScan.Cell(x,y,z,"loaded","minecraft:stone");});ok(!slow.complete()&&slow.budgetExhausted()&&reads[0]==4&&slow.cells().size()==4);
        var failed=CompactTerrainScan.read(1,0,0,0,()->0,(x,y,z)->{throw new IllegalStateException();});ok(failed.complete());ok(failed.cells().stream().allMatch(c->c.status().equals("read_failed")&&c.id()==null));
        var unknown=CompactTerrainScan.read(1,0,0,0,()->0,(x,y,z)->new CompactTerrainScan.Cell(x,y,z,"unloaded",null));ok(unknown.complete());ok(unknown.cells().stream().allMatch(c->c.status().equals("unloaded")));
        long[] reversed={10};boolean denied=false;try{CompactTerrainScan.read(1,0,0,0,()->reversed[0]--,(x,y,z)->null);}catch(IllegalStateException e){denied=true;}ok(denied);
        System.out.println("CompactTerrainScanTest: "+checks+" checks passed");
    }
}

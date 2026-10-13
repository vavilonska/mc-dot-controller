package io.github.campione01.mineclientbridge;

import java.util.HashMap;
import java.util.Map;

/** One instance per captured tick. Null/unknown entries remain cached; capacity never evicts. */
final class CombatCellCache implements FlatStepCorridor.CellSource {
    static final int MAX_CELLS=1024;
    private record Key(int x,int y,int z) {
        // Avoid record ObjectMethods bootstrap on the first timed cache access.
        // Keep the same coordinate equality and 31-based hash, including overflow.
        @Override public int hashCode() { return (31*x+y)*31+z; }
        @Override public boolean equals(Object other) {
            return other instanceof Key key && x==key.x && y==key.y && z==key.z;
        }
    }
    private final FlatStepCorridor.CellSource source;
    private final Map<Key,FlatStepCorridor.Cell> cells=new HashMap<>();
    long requests,hits,misses,capacityRejections,readFailures;
    CombatCellCache(FlatStepCorridor.CellSource source) { this.source=source; }
    @Override public FlatStepCorridor.Cell read(int x,int y,int z) {
        requests++;
        Key key=new Key(x,y,z);
        FlatStepCorridor.Cell cached=cells.get(key);
        if(cached!=null || cells.containsKey(key)) { hits++;return cached; }
        misses++;
        if(cells.size()>=MAX_CELLS) {
            capacityRejections++;
            return new FlatStepCorridor.Cell(FlatStepCorridor.Availability.UNKNOWN,null,false,false,false,null,false);
        }
        try {
            FlatStepCorridor.Cell cell=source.read(x,y,z);cells.put(key,cell);return cell;
        } catch(RuntimeException exception) { readFailures++;throw exception; }
    }
    int size() { return cells.size(); }
}

package io.github.campione01.mineclientbridge;

import java.util.HashMap;
import java.util.Map;

/** One instance per captured tick. Null/unknown entries remain cached; capacity never evicts. */
final class CombatCellCache implements FlatStepCorridor.CellSource {
    static final int MAX_CELLS=1024;
    private record Key(int x,int y,int z) { }
    private final FlatStepCorridor.CellSource source;
    private final Map<Key,FlatStepCorridor.Cell> cells=new HashMap<>();
    long requests,hits,misses,capacityRejections,readFailures;
    CombatCellCache(FlatStepCorridor.CellSource source) { this.source=source; }
    @Override public FlatStepCorridor.Cell read(int x,int y,int z) {
        requests++;
        Key key=new Key(x,y,z);
        if(cells.containsKey(key)) { hits++;return cells.get(key); }
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

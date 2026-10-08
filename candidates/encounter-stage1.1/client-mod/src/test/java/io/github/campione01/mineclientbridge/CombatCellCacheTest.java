package io.github.campione01.mineclientbridge;

import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class CombatCellCacheTest {
    @Test void hashCollisionDoesNotAliasLoadedAndNullCells() {
        AtomicInteger actual=new AtomicInteger();
        var loaded=new FlatStepCorridor.Cell(FlatStepCorridor.Availability.LOADED,"minecraft:air",true,true,false,"minecraft:empty",false);
        var cache=new CombatCellCache((x,y,z)->{actual.incrementAndGet();return y==1?loaded:null;});
        // Record keys (0,1,0) and (0,0,31) share a hash, but not an identity.
        assertSame(loaded,cache.read(0,1,0));assertNull(cache.read(0,0,31));
        assertSame(loaded,cache.read(0,1,0));assertNull(cache.read(0,0,31));
        assertEquals(2,actual.get());assertEquals(2,cache.hits);assertEquals(2,cache.misses);
    }
    @Test void nullAndUnknownEntriesAreStillHits() {
        AtomicInteger actual=new AtomicInteger();
        var cache=new CombatCellCache((x,y,z)->{actual.incrementAndGet();return null;});
        assertNull(cache.read(1,2,3));assertNull(cache.read(1,2,3));
        assertEquals(2,cache.requests);assertEquals(1,cache.hits);assertEquals(1,cache.misses);assertEquals(1,actual.get());
        assertEquals(cache.requests,cache.hits+cache.misses);assertEquals(1,cache.size());
    }
    @Test void limitStillRejectsWithoutEvictionOrSourceRead() {
        AtomicInteger actual=new AtomicInteger();var cache=new CombatCellCache((x,y,z)->{actual.incrementAndGet();return null;});
        for(int x=0;x<1024;x++) cache.read(x,0,0);
        assertEquals(FlatStepCorridor.Availability.UNKNOWN,cache.read(1024,0,0).availability());
        assertNull(cache.read(0,0,0));
        assertEquals(1024,actual.get());assertEquals(1026,cache.requests);assertEquals(1025,cache.misses);
        assertEquals(1,cache.hits);assertEquals(1,cache.capacityRejections);assertEquals(1024,cache.size());
    }
    @Test void exceptionsAreCountedAndNeverCachedAsSafe() {
        var cache=new CombatCellCache((x,y,z)->{throw new IllegalStateException();});
        assertThrows(IllegalStateException.class,()->cache.read(0,0,0));
        assertThrows(IllegalStateException.class,()->cache.read(0,0,0));
        assertEquals(2,cache.requests);assertEquals(2,cache.misses);assertEquals(0,cache.hits);assertEquals(2,cache.readFailures);
        assertEquals(0,cache.size());
    }
    @Test void newTickGetsIndependentCache() {
        AtomicInteger actual=new AtomicInteger();FlatStepCorridor.CellSource source=(x,y,z)->{actual.incrementAndGet();return null;};
        var first=new CombatCellCache(source);first.read(0,0,0);first.read(0,0,0);
        var next=new CombatCellCache(source);next.read(0,0,0);
        assertEquals(2,actual.get());assertEquals(1,next.misses);assertEquals(0,next.hits);
    }
}

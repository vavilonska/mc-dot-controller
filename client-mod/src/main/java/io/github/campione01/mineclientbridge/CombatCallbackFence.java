package io.github.campione01.mineclientbridge;
import java.util.function.BooleanSupplier;
import java.util.function.LongSupplier;
/** Production callback lifetime guard. A failed/closed scope never becomes reusable. */
final class CombatCallbackFence implements AutoCloseable {
    static final long MAX_NANOS=50_000_000L;
    private final BooleanSupplier owner;
    private final LongSupplier clock,tick;
    private final long started,sourceTick;
    private boolean closed,checking;
    CombatCallbackFence(BooleanSupplier owner,LongSupplier clock,LongSupplier tick){
        this.owner=owner;this.clock=clock;this.tick=tick;started=clock.getAsLong();sourceTick=tick.getAsLong();
    }
    void check(Runnable liveChecks){
        try {
            raw();if(checking)throw new IllegalStateException("combat_recursive_effect_check");
            checking=true;
            try {liveChecks.run();raw();} finally {checking=false;}
        } catch(RuntimeException failure){closed=true;throw failure;}
    }
    void raw(){
        try {
            if(closed || !owner.getAsBoolean())throw new IllegalStateException("combat_callback_owner_clock_or_tick_changed");
            long currentTick=tick.getAsLong();
            long elapsed=clock.getAsLong()-started;
            // Callback-backed reads finish before the pure exact-owner predicate.
            if(elapsed<0 || elapsed>MAX_NANOS || currentTick!=sourceTick || !owner.getAsBoolean())
                throw new IllegalStateException("combat_callback_owner_clock_or_tick_changed");
        } catch(RuntimeException failure){closed=true;throw failure;}
    }
    public void close(){closed=true;}
}

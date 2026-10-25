package io.github.campione01.mineclientbridge;
import java.util.function.BooleanSupplier;
import java.util.function.LongSupplier;
/** Production callback lifetime guard. A failed/closed scope never becomes reusable. */
final class CombatCallbackFence implements AutoCloseable {
    static final long MAX_NANOS=50_000_000L;
    private final BooleanSupplier owner;
    private final LongSupplier clock,tick;
    private final long started,sourceTick,actionDeadline;
    private final boolean actionBound;
    private boolean closed,checking;
    enum Failure { NONE, CLOSED, OWNER_BEFORE_READS, CLOCK_REGRESSED, LIFETIME_EXPIRED, TICK_CHANGED, OWNER_AFTER_READS, REENTRANT, CALLBACK_EXCEPTION, ACTION_DEADLINE_EXPIRED }
    private Failure failure=Failure.NONE;
    private long sampledElapsed=-1;
    Failure failure(){return failure;}
    long sampledElapsed(){return sampledElapsed;}
    private void note(Failure value){if(failure==Failure.NONE)failure=value;}
    CombatCallbackFence(BooleanSupplier owner,LongSupplier clock,LongSupplier tick){
        this(owner,clock,tick,false,0L);
    }
    /** Ordinary stationary target calls reuse the immutable original admission deadline. */
    static CombatCallbackFence forAction(BooleanSupplier owner,LongSupplier clock,LongSupplier tick,long originalDeadline){
        return new CombatCallbackFence(owner,clock,tick,true,originalDeadline);
    }
    private CombatCallbackFence(BooleanSupplier owner,LongSupplier clock,LongSupplier tick,boolean actionBound,long originalDeadline){
        this.owner=owner;this.clock=clock;this.tick=tick;this.actionBound=actionBound;actionDeadline=originalDeadline;
        started=clock.getAsLong();sourceTick=tick.getAsLong();
    }
    void check(Runnable liveChecks){
        try {
            raw();if(checking){note(Failure.REENTRANT);throw new IllegalStateException("combat_recursive_effect_check");}
            checking=true;
            try {liveChecks.run();raw();} finally {checking=false;}
        } catch(RuntimeException failure){note(Failure.CALLBACK_EXCEPTION);closed=true;throw failure;}
    }
    void raw(){
        try {
            if(closed){note(Failure.CLOSED);throw new IllegalStateException("combat_callback_owner_clock_or_tick_changed");}
            if(!owner.getAsBoolean()){note(Failure.OWNER_BEFORE_READS);throw new IllegalStateException("combat_callback_owner_clock_or_tick_changed");}
            long currentTick=tick.getAsLong();
            long now=clock.getAsLong();long elapsed=now-started;sampledElapsed=Math.max(-1L,Math.min(1_000_000_000L,elapsed));
            // Callback-backed reads finish before the pure exact-owner predicate.
            if(elapsed<0){note(Failure.CLOCK_REGRESSED);throw new IllegalStateException("combat_callback_owner_clock_or_tick_changed");}
            if(actionBound?now>=actionDeadline:elapsed>MAX_NANOS){note(actionBound?Failure.ACTION_DEADLINE_EXPIRED:Failure.LIFETIME_EXPIRED);throw new IllegalStateException("combat_callback_owner_clock_or_tick_changed");}
            if(currentTick!=sourceTick){note(Failure.TICK_CHANGED);throw new IllegalStateException("combat_callback_owner_clock_or_tick_changed");}
            if(!owner.getAsBoolean()){note(Failure.OWNER_AFTER_READS);throw new IllegalStateException("combat_callback_owner_clock_or_tick_changed");}
        } catch(RuntimeException failure){note(Failure.CALLBACK_EXCEPTION);closed=true;throw failure;}
    }
    public void close(){closed=true;}
}

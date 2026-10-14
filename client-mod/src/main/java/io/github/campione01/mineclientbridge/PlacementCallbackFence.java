package io.github.campione01.mineclientbridge;
import java.util.function.BooleanSupplier;
import java.util.function.LongSupplier;
/** Poison-on-failure, non-reentrant check scope shared by real placement callbacks and finite tests. */
final class PlacementCallbackFence {
    static final long MAX_NANOS=250_000_000L;
    private final BooleanSupplier owner;
    private final LongSupplier clock,tick;
    private boolean checking,poisoned;
    PlacementCallbackFence(BooleanSupplier owner,LongSupplier clock,LongSupplier tick){this.owner=owner;this.clock=clock;this.tick=tick;}
    void check(Runnable body){
        try {
            if(poisoned||checking||!owner.getAsBoolean())throw new IllegalStateException("placement_recursive_or_invalid_check");
            long start=clock.getAsLong(),sourceTick=tick.getAsLong();checking=true;
            try {
                body.run();long elapsed=clock.getAsLong()-start;
                if(poisoned||!owner.getAsBoolean()||elapsed<0||elapsed>MAX_NANOS||tick.getAsLong()!=sourceTick)
                    throw new IllegalStateException("placement_check_owner_clock_or_tick_changed");
            }finally{checking=false;}
        }catch(RuntimeException failure){poisoned=true;throw failure;}
    }
}

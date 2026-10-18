package io.github.campione01.mineclientbridge;
import java.util.function.Supplier;
import java.util.function.BooleanSupplier;
/** Callback-backed reads complete before a pure captured-owner fence. */
final class ExternalNavigationFence {
    static <T> T readThenCheck(Supplier<T> reads,BooleanSupplier exactOwner) {
        T result=reads.get();
        if(!exactOwner.getAsBoolean())throw new IllegalStateException("external_navigation_final_owner_changed");
        return result;
    }
    private ExternalNavigationFence(){}
}

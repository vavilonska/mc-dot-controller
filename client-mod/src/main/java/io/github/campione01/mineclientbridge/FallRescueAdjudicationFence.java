package io.github.campione01.mineclientbridge;

import java.util.function.BooleanSupplier;

/** Ordered read-only proof: callbacks first, fresh private context next, pure ownership last. */
final class FallRescueAdjudicationFence {
    static boolean prove(BooleanSupplier externalIdle,BooleanSupplier inputsNeutral,
                         BooleanSupplier freshPrivateContext,BooleanSupplier pureOwner) {
        return externalIdle.getAsBoolean() && inputsNeutral.getAsBoolean()
                && freshPrivateContext.getAsBoolean() && pureOwner.getAsBoolean();
    }
    private FallRescueAdjudicationFence() { }
}

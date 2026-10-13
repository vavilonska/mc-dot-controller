package io.github.campione01.mineclientbridge;

/** Reentrant side-effect fence. Cancellation inside use/release cannot prove cleanup.
 * Once uncertainty is observed, returning from the old call cannot erase it. */
final class CapabilityUseTransition {
    private boolean inFlight,uncertain;
    void run(Runnable effect) {
        if(inFlight||uncertain) {
            uncertain=true;
            throw new IllegalStateException("item_use_transition_uncertain");
        }
        inFlight=true;
        try { effect.run(); }
        catch(RuntimeException failure){uncertain=true;throw failure;}
        finally {inFlight=false;}
    }
    boolean cleanupMayConfirm() {
        if(inFlight)uncertain=true;
        return !inFlight&&!uncertain;
    }
}

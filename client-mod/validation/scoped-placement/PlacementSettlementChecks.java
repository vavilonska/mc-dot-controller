package io.github.campione01.mineclientbridge;

/**
 * Pure offline checks of the actual production settlement policy and callback fence.
 * Owners, callbacks, clocks and ticks below are synthetic. This does not run Minecraft,
 * apply mixins, exercise a live inventory, or establish live placement acceptance.
 */
public final class PlacementSettlementChecks {
    private static int checks;

    private static void require(boolean condition, String label) {
        checks++;
        if (!condition) throw new AssertionError(label + " (check " + checks + ")");
    }

    private static void denied(Runnable action, String label) {
        boolean rejected = false;
        try { action.run(); }
        catch (IllegalStateException expected) { rejected = true; }
        require(rejected, label);
    }

    private static void invalidSource(int revision) {
        boolean rejected = false;
        try { new PlacementSettlementPolicy(revision); }
        catch (IllegalArgumentException expected) { rejected = true; }
        require(rejected, "invalid source revision " + revision);
    }

    private static void strictBeforeUseReturned(int source) {
        PlacementSettlementPolicy policy = new PlacementSettlementPolicy(source);
        int next = PlacementSettlementPolicy.next(source);
        require(policy.accepted() == source, "initial revision");
        require(policy.permits(source, false, 0, 0, false), "original before use");
        require(policy.permits(source, false, 1, 0, false), "original during effect");
        require(policy.permits(source, false, 1, 1, true), "original after effect and packet but before return");
        require(!policy.permits(next, false, 0, 0, false), "next denied before use");
        require(!policy.permits(next, false, 1, 0, true), "next denied after effect before return");
        require(!policy.permits(next, false, 1, 1, true), "effect 1 packet 1 cannot open settlement before return");
        require(policy.accepted() == source, "permission queries do not commit");
    }

    private static void exactEvidenceRequired(int source) {
        PlacementSettlementPolicy policy = new PlacementSettlementPolicy(source);
        int[] counters = {-1, 0, 1, 2, Integer.MAX_VALUE};
        int[] revisions = {source, PlacementSettlementPolicy.next(source)};
        for (int revision : revisions) {
            for (int effects : counters) {
                for (int packets : counters) {
                    boolean exactCounters = effects == 1 && packets == 1;
                    require(policy.permits(revision, true, effects, packets, true) == exactCounters,
                            "settlement requires exactly one effect and one packet");
                    require(!policy.permits(revision, true, effects, packets, false),
                            "settlement requires exact selected-stack decrement, even at original revision");
                }
            }
        }
        require(policy.accepted() == source, "evidence queries cannot advance revision");
    }

    private static void boundedProgression(int source) {
        PlacementSettlementPolicy policy = new PlacementSettlementPolicy(source);
        int next = PlacementSettlementPolicy.next(source);
        int later = PlacementSettlementPolicy.next(next);
        int rollback = (source - 1) & PlacementSettlementPolicy.MASK;
        require(policy.permits(source, true, 1, 1, true), "original revision may settle");
        policy.commit(source);
        require(policy.accepted() == source, "committing original preserves next allowance");
        require(policy.permits(next, true, 1, 1, true), "single next revision permitted");
        require(policy.accepted() == source, "next permission remains uncommitted");
        require(!policy.permits(rollback, true, 1, 1, true), "rollback rejected before advance");
        require(!policy.permits(later, true, 1, 1, true), "jump rejected before advance");
        denied(() -> policy.commit(later), "out-of-bound commit rejected before advance");
        require(policy.accepted() == source, "rejected commit preserves original");
        policy.commit(next);
        require(policy.accepted() == next, "one next revision committed");
        require(policy.permits(next, true, 1, 1, true), "stable accepted revision remains permitted");
        policy.commit(next);
        require(policy.accepted() == next, "repeat accepted revision is idempotent");
        require(!policy.permits(source, true, 1, 1, true), "rollback to original rejected after advance");
        require(!policy.permits(later, true, 1, 1, true), "second progression rejected");
        require(!policy.permits(source, false, 1, 1, true), "cannot restore pre-return phase after advance");
        require(!policy.permits(next, false, 1, 1, true), "advanced revision cannot pass pre-return phase");
        require(!policy.permits(next, true, 0, 1, true), "accepted revision still requires effect");
        require(!policy.permits(next, true, 1, 0, true), "accepted revision still requires packet");
        require(!policy.permits(next, true, 1, 1, false), "accepted revision still requires exact decrement");
        denied(() -> policy.commit(source), "rollback commit rejected");
        denied(() -> policy.commit(later), "second progression commit rejected");
        require(policy.accepted() == next, "rejected post-advance commits preserve accepted revision");
        for (int invalid : new int[]{Integer.MIN_VALUE, -1, 32768, Integer.MAX_VALUE}) {
            require(!policy.permits(invalid, false, 1, 1, true), "invalid pre-return revision rejected");
            require(!policy.permits(invalid, true, 1, 1, true), "invalid settlement revision rejected");
            denied(() -> policy.commit(invalid), "invalid commit rejected");
            require(policy.accepted() == next, "invalid commit does not mutate accepted revision");
        }
    }

    /** Synthetic enclosing callback, using the real helpers and commit-after-success order. */
    private static final class SyntheticOwnerCallbacks {
        final Object expectedOwner = new Object();
        Object activeOwner = expectedOwner;
        boolean cancelled;
        long nano, tick;
        int bodies;
        final PlacementSettlementPolicy policy = new PlacementSettlementPolicy(41);
        final PlacementCallbackFence fence = new PlacementCallbackFence(
                () -> activeOwner == expectedOwner && !cancelled, () -> nano, () -> tick);

        void observeNext(Runnable callback) {
            int observedRevision = 42;
            fence.check(() -> {
                bodies++;
                require(policy.permits(observedRevision, true, 1, 1, true), "synthetic observation permits next");
                callback.run();
            });
            policy.commit(observedRevision);
        }

        void assertFailedAndPoisoned(String label) {
            require(policy.accepted() == 41, label + " cannot commit next");
            int oldBodies = bodies;
            activeOwner = expectedOwner;
            cancelled = false;
            denied(() -> observeNext(() -> {}), label + " poisons future checks even if owner restored");
            require(bodies == oldBodies, label + " poisoned callback body not entered");
            require(policy.accepted() == 41, label + " remains uncommitted");
        }
    }

    private static void callbackFailuresCannotCommit() {
        SyntheticOwnerCallbacks success = new SyntheticOwnerCallbacks();
        success.observeNext(() -> {});
        require(success.policy.accepted() == 42, "successful synthetic callback commits next");

        SyntheticOwnerCallbacks replacement = new SyntheticOwnerCallbacks();
        denied(() -> replacement.observeNext(() -> replacement.activeOwner = new Object()), "owner replaced in callback");
        replacement.assertFailedAndPoisoned("owner replacement");

        SyntheticOwnerCallbacks cancellation = new SyntheticOwnerCallbacks();
        denied(() -> cancellation.observeNext(() -> cancellation.cancelled = true), "owner cancelled in callback");
        cancellation.assertFailedAndPoisoned("cancellation");

        SyntheticOwnerCallbacks reentry = new SyntheticOwnerCallbacks();
        denied(() -> reentry.observeNext(() -> reentry.observeNext(() -> {})), "propagated callback reentry");
        require(reentry.bodies == 1, "recursive body never entered");
        reentry.assertFailedAndPoisoned("reentry");

        SyntheticOwnerCallbacks swallowed = new SyntheticOwnerCallbacks();
        denied(() -> swallowed.observeNext(() -> {
            try { swallowed.observeNext(() -> {}); }
            catch (IllegalStateException deliberatelySwallowed) { }
        }), "swallowed nested failure still rejects outer callback");
        require(swallowed.bodies == 1, "swallowed reentry body never entered");
        swallowed.assertFailedAndPoisoned("swallowed reentry");

        SyntheticOwnerCallbacks thrown = new SyntheticOwnerCallbacks();
        denied(() -> thrown.observeNext(() -> { throw new IllegalStateException("synthetic callback failure"); }),
                "callback exception rejected");
        thrown.assertFailedAndPoisoned("callback exception");

        SyntheticOwnerCallbacks changedTick = new SyntheticOwnerCallbacks();
        denied(() -> changedTick.observeNext(() -> changedTick.tick++), "tick changes inside callback");
        changedTick.assertFailedAndPoisoned("tick change");

        SyntheticOwnerCallbacks timeout = new SyntheticOwnerCallbacks();
        denied(() -> timeout.observeNext(() -> timeout.nano += PlacementCallbackFence.MAX_NANOS + 1),
                "callback exceeds clock budget");
        timeout.assertFailedAndPoisoned("clock timeout");

        SyntheticOwnerCallbacks regressedClock = new SyntheticOwnerCallbacks();
        denied(() -> regressedClock.observeNext(() -> regressedClock.nano--), "clock regresses inside callback");
        regressedClock.assertFailedAndPoisoned("clock regression");
    }

    public static void main(String[] args) {
        for (int invalid : new int[]{Integer.MIN_VALUE, -1, 32768, Integer.MAX_VALUE}) invalidSource(invalid);
        for (int source : new int[]{0, 1, 41, 32766, 32767}) {
            strictBeforeUseReturned(source);
            exactEvidenceRequired(source);
            boundedProgression(source);
        }
        require(PlacementSettlementPolicy.next(32767) == 0, "revision wraps 32767 to 0");
        callbackFailuresCannotCommit();
        System.out.println("PASS production settlement policy and callback fence: " + checks
                + " checks; synthetic owners/callbacks only; no game or live acceptance");
    }
}

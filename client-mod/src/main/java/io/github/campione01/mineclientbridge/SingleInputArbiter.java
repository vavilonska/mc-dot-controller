package io.github.campione01.mineclientbridge;

/** Game-thread ownership fence shared by the native emergency owner and existing action owners.
 * A lease is installed BEFORE releasing an old owner, so reentrant admissions cannot slip in.
 * An unknown effect stays quarantined; stopping never clears it. Only an explicit
 * exact-revision original-action adjudication may release authority, without changing old effects. */
final class SingleInputArbiter {
    record Lease(long revision, String owner) { }
    private long revision;
    private Lease lease;
    private String quarantine;
    private boolean cleaning;

    Lease claim(String owner) {
        requireFree();
        if (owner == null || owner.isBlank()) throw new IllegalArgumentException("invalid_input_owner");
        lease = new Lease(++revision, owner);
        return lease;
    }
    boolean owns(Lease candidate) { return candidate != null && candidate == lease && quarantine == null; }
    boolean blocked() { return lease != null || quarantine != null || cleaning; }
    String reason() { return quarantine == null ? "native_fall_rescue_input_owned" : quarantine; }
    void requireFree() { if (blocked()) throw new IllegalStateException(reason()); }
    void release(Lease candidate) { if (candidate == lease) { lease = null; revision++; } }
    void stop() { lease = null; revision++; }
    void quarantine(String reason) {
        quarantine = reason == null ? "native_fall_rescue_unknown_outcome_quarantined" : reason;
        stop();
    }
    boolean stopAndCleanup(String pendingQuarantine,Runnable cleanup) {
        stop();cleaning=true;
        if(pendingQuarantine!=null)quarantine(pendingQuarantine);
        try{cleanup.run();return true;}
        catch(RuntimeException failure){quarantine("native_fall_rescue_input_release_unconfirmed");return false;}
        finally{cleaning=false;}
    }
    void adjudicateOriginal(long expectedRevision) {
        if(revision!=expectedRevision||lease!=null||cleaning
                ||!"native_fall_rescue_original_action_quarantined".equals(quarantine))
            throw new IllegalStateException("fall_adjudication_exact_original_quarantine_required");
        quarantine=null;revision++;
    }
    boolean quarantined() { return quarantine != null; }
    long revision() { return revision; }
}

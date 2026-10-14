package io.github.campione01.mineclientbridge;

/** Expected vanilla selected-slot synchronization only; does not confer action ownership. */
final class PlacementSettlementPolicy {
    static final int MASK=32767;
    private final int sourceRevision;
    private int acceptedRevision;
    PlacementSettlementPolicy(int revision){
        if(revision<0||revision>MASK)throw new IllegalArgumentException("placement_invalid_source_revision");
        sourceRevision=acceptedRevision=revision;
    }
    static int next(int revision){return (revision+1)&MASK;}
    boolean permits(int revision,boolean useReturned,int effects,int packets,boolean exactSelectedDecrement){
        if(revision<0||revision>MASK)return false;
        if(!useReturned)return revision==sourceRevision&&acceptedRevision==sourceRevision;
        return effects==1&&packets==1&&exactSelectedDecrement
            &&(revision==acceptedRevision||acceptedRevision==sourceRevision&&revision==next(sourceRevision));
    }
    /** Commit only after the enclosing callback's owner/context/inventory fences have all returned successfully. */
    void commit(int revision){
        if(revision!=acceptedRevision){
            if(acceptedRevision!=sourceRevision||revision!=next(sourceRevision))
                throw new IllegalStateException("placement_revision_commit_outside_bound");
            acceptedRevision=revision;
        }
    }
    int accepted(){return acceptedRevision;}
}

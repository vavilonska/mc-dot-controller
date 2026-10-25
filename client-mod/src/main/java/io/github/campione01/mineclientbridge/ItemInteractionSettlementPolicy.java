package io.github.campione01.mineclientbridge;
/** One delayed server stack update. No deadline extension and no regression after observing it. */
final class ItemInteractionSettlementPolicy {
    private final int source;private int accepted;private boolean outcomeObserved;
    ItemInteractionSettlementPolicy(int revision){if(revision<0||revision>32767)throw new IllegalArgumentException("item_interaction_invalid_revision");source=accepted=revision;}
    boolean permits(int revision,boolean returned,int uses,int packets,boolean outcome){
        if(revision<0||revision>32767)return false;
        if(!returned)return revision==source&&!outcomeObserved;
        return uses==1&&packets==1&&(!outcomeObserved||outcome)
            &&(revision==accepted||accepted==source&&revision==((source+1)&32767)&&outcome);
    }
    void commit(int revision,boolean outcome){if(revision!=accepted){if(accepted!=source||revision!=((source+1)&32767)||!outcome)throw new IllegalStateException("item_interaction_revision_commit_changed");accepted=revision;}outcomeObserved|=outcome;}
}

package io.github.campione01.mineclientbridge;

/** A process-local one-shot UI claim, not an action journal or retry authority. */
final class RecoveryRespawnUiGate {
    enum Phase { IDLE, DISPATCHING, AWAITING_RESPAWN, UNKNOWN, COMPLETE }
    private Object consumedPlayer;
    private Phase phase=Phase.IDLE;
    synchronized boolean claim(Object player){
        if(player==null||consumedPlayer!=null)return false;
        consumedPlayer=player;phase=Phase.DISPATCHING;return true;
    }
    boolean claimIdle(RecoveryShortInputLedger ledger,Object player,boolean captureAbsent){
        synchronized(ledger){return ledger.owner()!=null&&!ledger.locked()&&!ledger.closed()&&ledger.active()==null&&captureAbsent&&claim(player);}
    }
    synchronized boolean blocksStarts(){return phase==Phase.DISPATCHING||phase==Phase.AWAITING_RESPAWN||phase==Phase.UNKNOWN;}
    synchronized boolean consumed(){return consumedPlayer!=null;}
    synchronized Phase phase(){return phase;}
    synchronized void returned(Object player){if(consumedPlayer==player&&phase==Phase.DISPATCHING)phase=Phase.AWAITING_RESPAWN;}
    synchronized void failed(Object player){if(consumedPlayer==player&&phase!=Phase.COMPLETE)phase=Phase.UNKNOWN;}
    synchronized boolean replacement(Object original,Object current,boolean validContext,boolean aliveAndScreenClosed){
        if(consumedPlayer!=original||phase!=Phase.AWAITING_RESPAWN)return false;
        if(!validContext){phase=Phase.UNKNOWN;return false;}
        if(current!=null&&current!=original&&aliveAndScreenClosed){phase=Phase.COMPLETE;return true;}return false;
    }
}

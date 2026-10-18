package io.github.campione01.mineclientbridge;

/** Pure one-shot episode accounting. Native-call entry is irreversible, including thrown/FAIL calls. */
final class FallRescueEpisode {
    final String id;
    final int startTick;
    private boolean attempted, packetSent, clientWater, serverWater, serverBucket, landedAlive, terminal;
    private String outcome="preparing";
    FallRescueEpisode(String id,int startTick){this.id=id;this.startTick=startTick;}
    void attempt(){if(terminal||attempted)throw new IllegalStateException("fall_rescue_duplicate_use_forbidden");attempted=true;outcome="dispatch_outcome_pending";}
    void packet(){if(!attempted||terminal||packetSent)throw new IllegalStateException("fall_rescue_packet_owner_changed");packetSent=true;}
    void predictedWater(boolean water){clientWater|=water;}
    void serverObservation(boolean water,boolean bucket,boolean landed){
        if(!attempted||terminal)return;
        // Landing must be observed after a prior placement + bucket observation.
        boolean placementPreviouslyObserved=serverWater&&serverBucket;
        serverWater|=water;serverBucket|=bucket;
        landedAlive|=placementPreviouslyObserved&&landed;
        if(serverWater&&serverBucket&&landedAlive){outcome="server_placement_and_landing_observed";terminal=true;}
    }
    void end(String reason){if(!terminal){outcome=reason;terminal=true;}}
    boolean timedOut(int tick){return tick-startTick>=FallRescuePolicy.MAX_EPISODE_TICKS;}
    boolean attempted(){return attempted;}boolean packetSent(){return packetSent;}
    boolean clientWater(){return clientWater;}boolean serverWater(){return serverWater;}
    boolean serverBucket(){return serverBucket;}boolean landedAlive(){return landedAlive;}
    boolean terminal(){return terminal;}String outcome(){return outcome;}
    boolean confirmed(){return serverWater&&serverBucket&&landedAlive;}
}

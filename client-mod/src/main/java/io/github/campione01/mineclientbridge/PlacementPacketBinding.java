package io.github.campione01.mineclientbridge;
/** Immutable primitive packet/hit identity used at the real final send fence. */
record PlacementPacketBinding(int sequence,String hand,int x,int y,int z,String face,
        double hitX,double hitY,double hitZ,boolean inside,String type) {
    PlacementPacketBinding {
        if(!Double.isFinite(hitX)||!Double.isFinite(hitY)||!Double.isFinite(hitZ))
            throw new IllegalArgumentException("placement_packet_nonfinite_hit");
    }
}

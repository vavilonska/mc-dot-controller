package io.github.campione01.mineclientbridge;

/** Explicit minimum species risk policy. No distance alone is a kill guarantee. */
final class CapabilitySpeciesPolicy {
    static boolean creeper(double distance,boolean powered,boolean ignited,int swell,int direction,int fuse,int radius) {
        return Double.isFinite(distance)&&distance>=(powered?16:12)&&distance<=32
            &&!ignited&&swell==0&&direction<=0&&fuse==30&&radius==3;
    }
    static boolean blaze(double distance,boolean resistance) {
        return Double.isFinite(distance)&&distance>=12&&distance<=32&&resistance;
    }
    static boolean caveSpider(double distance,boolean poisoned) {
        return Double.isFinite(distance)&&distance>=8&&distance<=32&&!poisoned;
    }
    private CapabilitySpeciesPolicy(){}
}

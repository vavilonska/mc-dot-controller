package io.github.campione01.mineclientbridge;
/** Adversarial checks of the exact production poison-on-reentry callback fence. */
public final class PlacementCallbackChecks {
    static int checks;
    static void require(boolean b){checks++;if(!b)throw new AssertionError("check "+checks);}
    static void denied(Runnable r){boolean no=false;try{r.run();}catch(IllegalStateException expected){no=true;}require(no);}
    public static void main(String[] args){
        boolean[] owner={true};long[] nano={0},tick={0};int[] effects={0};
        PlacementCallbackFence f=new PlacementCallbackFence(()->owner[0],()->nano[0],()->tick[0]);
        f.check(()->{});effects[0]++;f.check(()->{});require(effects[0]==1);
        var replaced=new PlacementCallbackFence(()->owner[0],()->nano[0],()->tick[0]);denied(()->replaced.check(()->owner[0]=false));owner[0]=true;denied(()->replaced.check(()->effects[0]++));
        var recursive=new PlacementCallbackFence(()->owner[0],()->nano[0],()->tick[0]);
        denied(()->recursive.check(()->{try{recursive.check(()->effects[0]++);}catch(IllegalStateException swallowed){};}));
        denied(()->recursive.check(()->effects[0]++));require(effects[0]==1);
        var expired=new PlacementCallbackFence(()->owner[0],()->nano[0],()->tick[0]);denied(()->expired.check(()->nano[0]+=PlacementCallbackFence.MAX_NANOS+1));
        var changedTick=new PlacementCallbackFence(()->owner[0],()->nano[0],()->tick[0]);denied(()->changedTick.check(()->tick[0]++));
        var regressed=new PlacementCallbackFence(()->owner[0],()->nano[0],()->tick[0]);denied(()->regressed.check(()->nano[0]--));
        var failure=new PlacementCallbackFence(()->owner[0],()->nano[0],()->tick[0]);denied(()->failure.check(()->{throw new IllegalStateException("hook");}));denied(()->failure.check(()->effects[0]++));
        var duplicate=new PlacementCallbackFence(()->owner[0],()->nano[0],()->tick[0]);
        denied(()->duplicate.check(()->duplicate.check(()->effects[0]++)));require(effects[0]==1);
        System.out.println("PASS production placement callback boundaries: "+checks);
    }
}

package io.github.campione01.mineclientbridge;
public final class CombatCallbackFenceChecks {
    static int checks;
    static void require(boolean value){checks++;if(!value)throw new AssertionError("check "+checks);}
    static void denied(Runnable r){boolean denied=false;try{r.run();}catch(IllegalStateException expected){denied=true;}require(denied);}
    public static void main(String[] args){
        boolean[] owner={true};long[] clock={0},tick={7};int[] effects={0};
        CombatCallbackFence f=new CombatCallbackFence(()->owner[0],()->clock[0],()->tick[0]);
        f.check(()->{});effects[0]++;f.raw();require(effects[0]==1);f.close();denied(f::raw);
        f=new CombatCallbackFence(()->owner[0],()->clock[0],()->tick[0]);var canceled=f;
        denied(()->canceled.check(()->owner[0]=false));require(effects[0]==1);owner[0]=true;denied(canceled::raw);
        f=new CombatCallbackFence(()->owner[0],()->clock[0],()->tick[0]);var timeout=f;
        denied(()->timeout.check(()->clock[0]+=CombatCallbackFence.MAX_NANOS+1));denied(timeout::raw);
        f=new CombatCallbackFence(()->owner[0],()->clock[0],()->tick[0]);var tickChanged=f;
        denied(()->tickChanged.check(()->tick[0]++));
        f=new CombatCallbackFence(()->owner[0],()->clock[0],()->tick[0]);var recursive=f;
        denied(()->recursive.check(()->recursive.check(()->effects[0]++)));require(effects[0]==1);
        f=new CombatCallbackFence(()->owner[0],()->clock[0],()->tick[0]);var regressed=f;
        denied(()->regressed.check(()->clock[0]--));
        f=new CombatCallbackFence(()->owner[0],()->clock[0],()->tick[0]);var late=f;
        late.check(()->{});effects[0]++;owner[0]=false;denied(late::raw);owner[0]=true;denied(late::raw);require(effects[0]==2);
        System.out.println("CombatCallbackFenceChecks passed: "+checks);
    }
}

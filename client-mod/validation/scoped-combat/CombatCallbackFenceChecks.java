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
        boolean[] replaceOnTick={false};owner[0]=true;
        f=new CombatCallbackFence(()->owner[0],()->clock[0],()->{if(replaceOnTick[0])owner[0]=false;return tick[0];});
        var lateGetter=f;replaceOnTick[0]=true;denied(lateGetter::raw);owner[0]=true;replaceOnTick[0]=false;denied(lateGetter::raw);require(effects[0]==2);
        boolean[] throwOnTick={false};owner[0]=true;int[] tickReads={0};
        f=new CombatCallbackFence(()->owner[0],()->clock[0],()->{tickReads[0]++;if(throwOnTick[0])throw new IllegalStateException("tick_read_fault");return tick[0];});
        var throwsLate=f;throwOnTick[0]=true;denied(throwsLate::raw);int reads=tickReads[0];throwOnTick[0]=false;denied(throwsLate::raw);require(tickReads[0]==reads);
        boolean[] slowTick={false};owner[0]=true;
        f=new CombatCallbackFence(()->owner[0],()->clock[0],()->{if(slowTick[0])clock[0]+=CombatCallbackFence.MAX_NANOS+1;return tick[0];});
        var slow=f;slowTick[0]=true;denied(slow::raw);
        System.out.println("CombatCallbackFenceChecks passed: "+checks);
    }
}

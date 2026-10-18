package io.github.campione01.mineclientbridge;
public final class ExternalNavigationLeaseProbe {
    private static int checks;
    private static void check(boolean value){checks++;if(!value)throw new AssertionError("check "+checks);}
    private static ExternalNavigationLease.Request req(String id){return new ExternalNavigationLease.Request(id,"owner",1,"job","session","world","player","dimension",0,100,1000);}
    public static void main(String[] args){
        var leases=new ExternalNavigationLease();var r=req("one");var e=leases.claim(r,100);
        check(leases.blocked());check(leases.existing(r)==e);leases.attempt(e);check(e.attempted);
        try{leases.attempt(e);throw new AssertionError();}catch(IllegalStateException expected){checks++;}
        try{leases.claim(req("two"),200);throw new AssertionError();}catch(IllegalStateException expected){checks++;}
        e.cancelAccepted=true;check(leases.blocked());check(e.phase==ExternalNavigationLease.Phase.STOPPING);
        leases.sample(e,true,true,8,200);check(leases.blocked());check(e.idleSamples==1);
        leases.sample(e,true,true,8,300);check(e.idleSamples==1);
        leases.sample(e,true,false,9,400);check(e.idleSamples==0);
        leases.sample(e,true,true,10,500);leases.sample(e,true,true,11,600);check(!leases.blocked());
        var next=leases.claim(req("two"),700);leases.unknown(e,"old_callback");check(leases.owns(next));
        leases.sample(next,false,true,12,800);check(next.phase==ExternalNavigationLease.Phase.UNKNOWN);
        leases.sample(next,true,true,13,900);leases.sample(next,true,true,14,1000);check(leases.blocked());
        check(leases.existing(r)==e);check(e.phase==ExternalNavigationLease.Phase.SETTLED);
        var deadline=new ExternalNavigationLease();var d=deadline.claim(req("deadline"),0);
        deadline.sample(d,true,true,1,1);deadline.sample(d,true,true,2,1_000_000_000L);check(deadline.blocked());check(d.phase==ExternalNavigationLease.Phase.UNKNOWN);
        var cap=new ExternalNavigationLease();for(int i=0;i<128;i++){var x=cap.claim(req("r"+i),0);cap.sample(x,true,true,1,1);cap.sample(x,true,true,2,2);}
        try{cap.claim(req("full"),0);throw new AssertionError();}catch(IllegalStateException expected){checks++;}
        try{leases.existing(new ExternalNavigationLease.Request("one","different",1,"job","session","world","player","dimension",0,100,1000));throw new AssertionError();}catch(IllegalStateException expected){checks++;}
        var admission=new ExternalNavigationLease();var ae=admission.claim(req("admission"),0,40);
        admission.sample(ae,true,true,40,1);check(ae.idleSamples==0);
        admission.sample(ae,true,true,41,2);check(ae.idleSamples==1);check(admission.blocked());
        admission.sample(ae,true,true,42,3);check(ae.phase==ExternalNavigationLease.Phase.SETTLED);
        leases.unknown(e,"late_failure_after_settlement");check(e.phase==ExternalNavigationLease.Phase.SETTLED);
        Object original=new Object();Object[] owner={original};int[] effects={0};
        try{ExternalNavigationFence.readThenCheck(() -> {owner[0]=new Object();return 1;},() -> owner[0]==original);
            effects[0]++;throw new AssertionError();}catch(IllegalStateException expected){checks++;}
        check(effects[0]==0);
        var late=new ExternalNavigationLease();var le=late.claim(req("late_getter"),0);late.sample(le,true,true,1,1);
        try{ExternalNavigationFence.readThenCheck(() -> {late.unknown(le,"replacement_at_last_getter");return 2;},() -> late.owns(le));
            late.sample(le,true,true,2,2);throw new AssertionError();}catch(IllegalStateException expected){checks++;}
        check(le.phase==ExternalNavigationLease.Phase.UNKNOWN);check(le.idleSamples==1);
        check(ExternalNavigationFence.readThenCheck(() -> 17,() -> true)==17);
        Object world=new Object();String generation=WorldGeneration.current(world);check(WorldGeneration.matches(world,generation));
        try{ExternalNavigationFence.readThenCheck(() -> {WorldGeneration.current(null);return 1;},() -> WorldGeneration.matches(world,generation));
            throw new AssertionError();}catch(IllegalStateException expected){checks++;}
        System.out.println("ExternalNavigationLeaseProbe "+checks+" checks passed");
    }
}

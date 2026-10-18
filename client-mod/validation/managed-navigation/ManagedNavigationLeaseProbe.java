package io.github.campione01.mineclientbridge;
public final class ManagedNavigationLeaseProbe {
    static int checks;static void check(boolean x){checks++;if(!x)throw new AssertionError("check "+checks);}
    static ManagedNavigationLease.Request request(String id){return new ManagedNavigationLease.Request(
        new ExternalNavigationLease.Request(id,"owner",1,"job","session","world","player","dimension",0,0,1000),100,64,100,200,8);}
    public static void main(String[] args){
        var s=new ManagedNavigationLease();var e=s.claim(request("one"),0,10);check(!s.permitsInput(e,1));s.startAttempt(e);
        check(s.permitsInput(e,1));check(!s.permitsInput(e,-1));check(!s.permitsInput(e,1_000_000_000L));
        try{s.startAttempt(e);throw new AssertionError();}catch(IllegalStateException expected){checks++;}
        s.sample(e,true,true,true,10,1);check(e.idleSamples==0);
        s.sample(e,true,true,true,11,2);s.sample(e,true,true,true,12,3);check(s.blocked());
        try{s.settle(e);throw new AssertionError();}catch(IllegalStateException expected){checks++;}
        e.settingsRestored=true;s.settle(e);check(!s.blocked());check(e.goalReached);
        s.unknown(e,"late_callback");check(e.phase==ManagedNavigationLease.Phase.SETTLED);
        var next=s.claim(request("two"),0,20);s.startAttempt(next);s.deadlines(next,1_000_000_000L);
        check(next.phase==ManagedNavigationLease.Phase.STOPPING);s.stopAttempt(next);next.cancelAccepted=true;check(s.blocked());
        try{s.stopAttempt(next);throw new AssertionError();}catch(IllegalStateException expected){checks++;}
        check(s.permitsInput(next,2_000_000_000L));check(!s.permitsInput(next,11_000_000_000L));
        long original=next.stopDeadline;s.requestStop(next,"again",2_000_000_000L);check(next.stopDeadline==original);
        s.deadlines(next,11_000_000_000L);check(next.phase==ManagedNavigationLease.Phase.UNKNOWN);check(!s.permitsInput(next,2_000_000_000L));
        s.sample(next,true,true,true,21,12_000_000_000L);check(s.blocked());check(next.idleSamples==0);
        s.unknown(e,"old_callback");check(next.phase==ManagedNavigationLease.Phase.UNKNOWN);
        check(s.existing(request("one"))==e);
        var bridge=new ManagedNavigationLease();var be=bridge.claim(request("bridge"),0,1);bridge.startAttempt(be);
        bridge.bridgeStopping(be,100);check(be.phase==ManagedNavigationLease.Phase.STOPPING);check(be.reason.equals("managed_navigation_bridge_stopping"));
        long bridgeDeadline=be.stopDeadline;bridge.bridgeStopping(be,200);check(be.stopDeadline==bridgeDeadline);bridge.stopAttempt(be);
        bridge.unknown(be,"original_unknown");bridge.bridgeStopping(be,300);check(be.phase==ManagedNavigationLease.Phase.UNKNOWN);
        check(be.reason.equals("original_unknown")&&be.stopAttempted&&be.stopDeadline==bridgeDeadline);
        try{bridge.stopAttempt(be);throw new AssertionError();}catch(IllegalStateException expected){checks++;}
        System.out.println("ManagedNavigationLeaseProbe "+checks+" checks passed");
    }
}

package io.github.campione01.mineclientbridge;
/** Production pure leases + production callback fence; no game initialization. */
public final class FallExternalOwnerProbe {
    static int checks;
    static void check(boolean value){checks++;if(!value)throw new AssertionError("check "+checks);}
    static ExternalNavigationLease.Request stop(String id){return new ExternalNavigationLease.Request(id,"owner",1,"job","session","world","player","dimension",0,0,1000);}
    static ManagedNavigationLease.Request route(String id){return new ManagedNavigationLease.Request(stop(id),2,64,2,10,12);}
    static boolean allowed(ExternalNavigationLease stop,ManagedNavigationLease route){return !stop.blocked()&&!route.blocked();}
    public static void main(String[] args){
        var stops=new ExternalNavigationLease();var routes=new ManagedNavigationLease();boolean[] owner={true};
        check(FallRescueFence.afterHook(()->true,()->owner[0]&&allowed(stops,routes)));
        var e=stops.claim(stop("stop"),0,0);check(!allowed(stops,routes));
        stops.sample(e,true,true,1,1);check(!allowed(stops,routes));
        stops.sample(e,true,true,2,2);check(allowed(stops,routes));
        check(!FallRescueFence.afterHook(()->{stops.claim(stop("callback"),3,3);return true;},()->owner[0]&&allowed(stops,routes)));
        var unknown=stops.active();stops.unknown(unknown,"lost_stop_response");
        stops.sample(unknown,true,true,4,4);stops.sample(unknown,true,true,5,5);check(!allowed(stops,routes));check(unknown.phase==ExternalNavigationLease.Phase.UNKNOWN);
        var idleStops=new ExternalNavigationLease();var r=routes.claim(route("route"),0,0);check(!allowed(idleStops,routes));
        routes.startAttempt(r);routes.requestStop(r,"cancel",1);check(!allowed(idleStops,routes));
        routes.sample(r,true,true,false,1,2);routes.sample(r,true,true,false,2,3);check(!allowed(idleStops,routes));
        r.settingsRestored=true;routes.settle(r);check(allowed(idleStops,routes));
        check(!FallRescueFence.afterHook(()->{routes.claim(route("late-route"),4,4);return true;},()->owner[0]&&allowed(idleStops,routes)));
        var ru=routes.active();routes.unknown(ru,"lost_route_response");routes.sample(ru,true,true,true,5,5);check(!allowed(idleStops,routes));
        var idleRoutes=new ManagedNavigationLease();
        check(!FallRescueFence.afterHook(()->{owner[0]=false;return true;},()->owner[0]&&allowed(idleStops,idleRoutes)));
        var revision=new FallRescueFence();long before=revision.stamp();
        check(!FallRescueFence.afterHook(()->{revision.changed();return true;},()->revision.stamp()==before&&allowed(idleStops,idleRoutes)));
        check(stops.blocked()&&routes.blocked()); // No closure clears another lease/quarantine.
        System.out.println("FallExternalOwnerProbe "+checks+" checks passed");
    }
}

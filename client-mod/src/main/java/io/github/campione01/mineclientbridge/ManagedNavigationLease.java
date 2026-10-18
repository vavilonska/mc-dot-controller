package io.github.campione01.mineclientbridge;

import java.util.LinkedHashMap;
import java.util.Map;

/** Exact bounded route ownership. The two effect attempts are never retried. */
final class ManagedNavigationLease {
    record Request(ExternalNavigationLease.Request identity,int x,int y,int z,int radius,float minHealth) {}
    enum Phase { ROUTING, STOPPING, SETTLED, UNKNOWN }
    static final class Entry {
        final Request request; final long admittedAt,deadline,admissionTick;
        long lastTick,stopDeadline; int idleSamples;
        Phase phase=Phase.ROUTING;String reason="route_reserved";
        boolean startAttempted,stopAttempted,goalReached,settingsRestored;
        Boolean cancelAccepted;
        Entry(Request r,long now,long tick){request=r;admittedAt=now;admissionTick=tick;lastTick=tick;
            deadline=now+r.identity().timeoutMs()*1_000_000L;}
    }
    private final Map<String,Entry> history=new LinkedHashMap<>();
    private Entry active;
    Entry existing(Request r){Entry old=history.get(r.identity().id());
        if(old!=null&&!old.request.equals(r))throw new IllegalStateException("managed_navigation_id_conflict");return old;}
    Entry active(){return active;}
    boolean owns(Entry e){return e!=null&&active==e&&(e.phase==Phase.ROUTING||e.phase==Phase.STOPPING);}
    boolean permitsInput(Entry e,long now){return owns(e)&&e.startAttempted&&now>=e.admittedAt
        &&now<(e.phase==Phase.ROUTING?e.deadline:e.stopDeadline);}
    boolean blocked(){return active!=null&&active.phase!=Phase.SETTLED;}
    Entry claim(Request r,long now,long tick){
        if(existing(r)!=null||blocked())throw new IllegalStateException("managed_navigation_original_owner_required");
        if(history.size()>=128)throw new IllegalStateException("managed_navigation_history_full");
        Entry e=new Entry(r,now,tick);history.put(r.identity().id(),e);active=e;return e;
    }
    void startAttempt(Entry e){if(!owns(e)||e.startAttempted)throw new IllegalStateException("managed_navigation_start_not_repeatable");
        e.startAttempted=true;e.reason="route_running";}
    void requestStop(Entry e,String reason,long now){if(!owns(e)||e.phase==Phase.STOPPING)return;
        e.phase=Phase.STOPPING;e.reason=reason;e.stopDeadline=now+10_000_000_000L;}
    void bridgeStopping(Entry e,long now){requestStop(e,"managed_navigation_bridge_stopping",now);}
    void stopAttempt(Entry e){if(!owns(e)||e.phase!=Phase.STOPPING||e.stopAttempted)
        throw new IllegalStateException("managed_navigation_stop_not_repeatable");e.stopAttempted=true;}
    void unknown(Entry e,String reason){if(owns(e)){e.phase=Phase.UNKNOWN;e.reason=reason;}}
    void deadlines(Entry e,long now){if(!owns(e))return;
        if(e.phase==Phase.ROUTING&&now>=e.deadline)requestStop(e,"managed_navigation_route_deadline",now);
        if(e.phase==Phase.STOPPING&&now>=e.stopDeadline)unknown(e,"managed_navigation_actual_idle_unconfirmed");}
    void sample(Entry e,boolean sameOwner,boolean idle,boolean atGoal,long tick,long now){
        if(!owns(e))return;
        if(!sameOwner){unknown(e,"managed_navigation_owner_changed");return;}
        deadlines(e,now);if(!owns(e)||tick<=e.lastTick)return;
        e.lastTick=tick;e.idleSamples=idle?e.idleSamples+1:0;
        if(e.idleSamples>=2){e.goalReached=atGoal;e.reason=e.phase==Phase.STOPPING?e.reason:
            atGoal?"managed_navigation_goal_observed":"managed_navigation_path_ended_before_goal";
            // Settings restoration is an exact-owner operation before settlement.
        }
    }
    void settle(Entry e){if(!owns(e)||e.idleSamples<2||!e.settingsRestored)
        throw new IllegalStateException("managed_navigation_release_unproven");e.phase=Phase.SETTLED;}
}

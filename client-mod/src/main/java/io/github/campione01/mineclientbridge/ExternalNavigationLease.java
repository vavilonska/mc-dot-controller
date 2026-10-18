package io.github.campione01.mineclientbridge;

import java.util.LinkedHashMap;
import java.util.Map;

/** Pure one-shot control lifecycle. UNKNOWN never clears from a later idle sample. */
final class ExternalNavigationLease {
    record Request(String id,String owner,long generation,String job,String session,String world,
                   String player,String dimension,long sourceTick,long sourceNano,int timeoutMs) {}
    enum Phase { STOPPING, SETTLED, UNKNOWN }
    static final class Entry {
        final Request request; final long deadline; final long admittedAt; final long admissionTick;
        Phase phase=Phase.STOPPING; String reason="awaiting_actual_idle";
        boolean attempted; Boolean cancelAccepted; int idleSamples; long lastTick=-1;
        Entry(Request request,long now,long tick){this.request=request;admittedAt=now;admissionTick=tick;lastTick=tick;deadline=now+request.timeoutMs()*1_000_000L;}
    }
    private final Map<String,Entry> history=new LinkedHashMap<>();
    private Entry active;
    Entry existing(Request request) {
        Entry old=history.get(request.id());
        if(old!=null && !old.request.equals(request))throw new IllegalStateException("external_navigation_id_conflict");
        return old;
    }
    Entry claim(Request request,long now) {return claim(request,now,request.sourceTick());}
    Entry claim(Request request,long now,long admissionTick) {
        if(existing(request)!=null)throw new IllegalStateException("external_navigation_original_id_read_only");
        if(blocked())throw new IllegalStateException("external_navigation_owner_unresolved");
        if(history.size()>=128)throw new IllegalStateException("external_navigation_history_full");
        Entry entry=new Entry(request,now,admissionTick);history.put(request.id(),entry);active=entry;return entry;
    }
    boolean owns(Entry entry){return active==entry && entry!=null && entry.phase==Phase.STOPPING;}
    boolean blocked(){return active!=null && active.phase!=Phase.SETTLED;}
    Entry active(){return active;}
    void attempt(Entry entry) {
        if(!owns(entry)||entry.attempted)throw new IllegalStateException("external_navigation_stop_not_repeatable");
        entry.attempted=true; // Install before any cancellation callback.
    }
    void unknown(Entry entry,String reason){if(owns(entry)){entry.phase=Phase.UNKNOWN;entry.reason=reason;}}
    void sample(Entry entry,boolean sameContext,boolean idle,long tick,long now) {
        if(!owns(entry))return;
        if(!sameContext){unknown(entry,"external_navigation_context_changed");return;}
        if(now>=entry.deadline){unknown(entry,"external_navigation_idle_deadline_expired");return;}
        if(tick<=entry.lastTick)return;
        entry.lastTick=tick;entry.idleSamples=idle?entry.idleSamples+1:0;
        if(entry.idleSamples>=2){entry.phase=Phase.SETTLED;entry.reason="external_navigation_actual_idle_observed";}
    }
}

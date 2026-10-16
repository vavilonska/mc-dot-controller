package io.github.campione01.mineclientbridge;

import java.util.List;
import com.google.gson.JsonObject;

/** Actual production pure policies with deterministic observations; no Minecraft lifecycle. */
public final class HealthRecoveryChecks {
    private static int assertions;
    private static void check(boolean value,String name) { assertions++;if(!value) throw new AssertionError(name); }
    private static void reason(CombatThreats.HealthGuard.Result value,String name) { check(value.reason().equals(name),"reason: "+value.reason()+" expected "+name); }
    private static CombatThreats.HealthGuard guard(double minimum) {
        var g=new CombatThreats.HealthGuard(minimum);g.enableObservationRecovery();return g;
    }
    private static CombatThreats.HealthGuard recovering() {
        var g=guard(18);g.sampleSource(3,3,288549500478426L,20);
        reason(g.sampleSource(4,4,288549661558199L,20),"health_observation_recovering");return g;
    }
    private static CombatThreats.Snapshot target(int tick,long now) {
        return new CombatThreats.Snapshot(List.of(new CombatThreats.Observed(15,"target","minecraft:zombie",2,64,0,.3,true,true)),now,tick,false,true);
    }
    public static void main(String[] args) {
        // Exact retained T44 sampling interval, not an attempt to simulate its scheduling cause.
        var legacy=new CombatThreats.HealthGuard(18);legacy.sampleSource(3,3,288549500478426L,20);
        var old=legacy.sampleSource(4,4,288549661558199L,20);
        reason(old,"health_observation_gap");check(!old.known(),"legacy unknown continuity");
        check(legacy.sampleSource(5,5,288549711558199L,20)==old,"legacy latch unchanged");
        var g=recovering();check(g.recovering(),"recovery active");
        check(!g.diagnostics().latched(),"gap is not adverse latch in opt-in mode");
        check(g.diagnostics().current().sampleDeltaNanos()==161079773L,"exact T44 delta");
        long now=288549661558199L;
        for(int i=1;i<20;i++) {
            var value=g.sampleSource(4+i,4+i,now+i*50000000L,20);
            check(value.interrupted() && !value.known(),"no offense before full window "+i);
        }
        // Multiple final effect checks in one tick cannot manufacture completion.
        check(g.sampleSource(23,23,now+999999999L,20).interrupted(),"under full window");
        check(g.sampleSource(23,23,now+1000000000L,20).interrupted(),"same tick cannot complete");
        var complete=g.sampleSource(24,24,now+1000000001L,20);
        check(!complete.interrupted() && complete.known(),"full continuous window recovers");
        check(g.recoveryCompleted()==1 && !g.recovering(),"one recovery completed");
        check(g.recoveryEpisodes()==1,"one recovery episode");
        JsonObject evidence=new JsonObject();CombatHealthEvidence.append(evidence,g);
        var diagnostic=evidence.getAsJsonObject("health_diagnostics");
        check(!diagnostic.get("latched").getAsBoolean(),"no fabricated latch");
        check(diagnostic.get("latch_trigger").isJsonNull(),"no fake trigger");
        var recovery=diagnostic.getAsJsonObject("observation_recovery");
        check(!recovery.get("unobserved_interval_proven").getAsBoolean(),"gap remains unproven");
        check(!recovery.get("loss_history_reset").getAsBoolean(),"no history reset");

        // The exact <=150ms boundary remains unchanged, with no raised freshness threshold.
        for(long elapsed:new long[]{149999999L,150000000L,150000001L}) {
            var b=guard(18);b.sampleSource(1,1,0,20);var v=b.sampleSource(2,2,elapsed,20);
            check(v.interrupted()==(elapsed>150000000L),"150ms boundary "+elapsed);
        }
        // Another observation gap restarts only the quiet window, not the action or loss history.
        g=guard(18);g.sampleSource(0,0,0,20);g.sampleSource(1,1,160000000L,20);
        for(int i=1;i<=8;i++) g.sampleSource(1+i,1+i,160000000L+i*50000000L,20);
        reason(g.sampleSource(10,10,760000000L,20),"health_observation_recovering");
        check(g.recoveryStarted()==760000000L && g.recoverySamples()==1,"new gap rebases quiet window only");
        check(g.recoveryEpisodes()==1 && g.recoveryCompleted()==0,"gap never refunds episode");
        for(int i=1;i<20;i++) check(g.sampleSource(10+i,10+i,760000000L+i*50000000L,20).interrupted(),"new quiet window "+i);
        check(!g.sampleSource(30,30,1760000000L,20).interrupted(),"second quiet interval eventually complete");
        g=guard(18);g.sampleSource(0,0,0,20);g.sampleSource(1,1,160000000L,20);
        g.sampleSource(1,1,309000000L,20); // Fresh call, but not a new action tick.
        reason(g.sampleSource(2,2,458000000L,20),"health_observation_recovering");
        check(g.recoveryStarted()==458000000L && g.recoverySamples()==1,
                "same-tick calls cannot bridge a missing advancing sample");

        // Any observed loss during the uncertain interval is hard, even below rapid-loss thresholds.
        for(double health:new double[]{19.999,19.0,18.0,14.0,Double.NaN,-1}) {
            g=recovering();var fail=g.sampleSource(5,5,now+50000000L,health);
            check(fail.interrupted() && g.diagnostics().latched(),"adverse recovery latch "+health);
            check(g.sampleSource(6,6,now+100000000L,20)==fail,"healing cannot clear adverse latch "+health);
            check(!g.recovering(),"adverse latch disables recovery "+health);
        }
        g=guard(18);g.sampleSource(1,1,0,20);
        reason(g.sampleSource(2,2,160000000L,19.999),"health_loss_during_observation_recovery");
        // Loss history from before the gap is preserved and healing never refunds it.
        g=guard(14);g.sampleSource(0,0,0,20);g.sampleSource(1,1,50000000L,19);g.sampleSource(2,2,100000000L,20);
        var gap=g.sampleSource(3,3,260000000L,20);check(gap.damageInWindow()==1,"pre-gap loss preserved");
        var loss=g.sampleSource(4,4,310000000L,17);reason(loss,"rapid_health_loss");check(loss.damageInWindow()==4,"new loss charged before latch");
        // Invalid clocks/data, omitted game ticks and frozen ticks are never soft recoveries.
        long[][] invalid={{0,50000000L},{1,-1},{1,150000001L},{5,50000000L}};
        for(long[] pair:invalid) {
            g=guard(18);g.sampleSource(1,1,0,20);var fail=g.sampleSource((int)pair[0],(int)pair[0],pair[1],20);
            check(fail.interrupted() && g.diagnostics().latched(),"invalid observation hard latch");
            check(!g.recovering(),"invalid observation never recovers");
        }
        g=guard(18);g.sampleSource(1,1,-1000000000L,20);g.sampleSource(2,2,-839000000L,20);
        for(int i=1;i<=20;i++) g.sampleSource(2+i,2+i,-839000000L+i*50000000L,20);
        check(!g.recovering(),"signed nanotime origin supported");
        boolean threw=false;try {g.enableObservationRecovery();} catch(IllegalStateException expected) {threw=true;}
        check(threw,"cannot enable recovery after observations");

        // The defensive topology observation never grants health or offensive authority.
        g=recovering();var uncertain=g.sampleSource(5,5,now+50000000L,20);var snapshot=target(5,now+50000000L);
        check(CombatThreats.evaluate(snapshot,now+50000000L,5,0,64,0,15,"target",uncertain).stop(),"uncertain health blocks ordinary gate");
        check(!CombatThreats.defensiveTarget(snapshot,now+50000000L,5,0,64,0,15,"target").stop(),"fresh single target allows defensive observation");
        check(CombatThreats.defensiveTarget(snapshot,now+200000001L,5,0,64,0,15,"target").stop(),"stale snapshot still refused");
        check(CombatThreats.defensiveTarget(snapshot,now+50000000L,6,0,64,0,15,"target").stop(),"new tick needs new snapshot");
        check(CombatThreats.defensiveTarget(snapshot,now+50000000L,5,0,64,0,15,"wrong").stop(),"UUID swap refused");
        for(String type:List.of("minecraft:creeper","minecraft:enderman","minecraft:spider","mod:unknown")) {
            var bad=new CombatThreats.Snapshot(List.of(snapshot.entities().getFirst(),new CombatThreats.Observed(16,"other",type,3,64,0,.3,true,true)),now+50000000L,5,false,true);
            check(CombatThreats.defensiveTarget(bad,now+50000000L,5,0,64,0,15,"target").stop(),"new danger refused "+type);
        }
        var truncated=new CombatThreats.Snapshot(snapshot.entities(),now+50000000L,5,true,true);
        check(CombatThreats.defensiveTarget(truncated,now+50000000L,5,0,64,0,15,"target").stop(),"truncated refuses");
        // An action callback is not the source world clock: /tick freeze keeps callbacks alive.
        var sourceFreeze=guard(18);sourceFreeze.sampleSource(1,77,0,20);
        sourceFreeze.sampleSource(2,78,160000000L,20);
        for(int i=1;i<=20;i++) {
            var frozen=sourceFreeze.sampleSource(2+i,78,160000000L+i*50000000L,20);
            check(frozen.interrupted(),"frozen source cannot recover through action callbacks "+i);
        }
        check(sourceFreeze.diagnostics().latched() && sourceFreeze.recoveryCompleted()==0,"source frozen hard latch");
        for(int i=1;i<=30;i++)check(sourceFreeze.sampleSource(22+i,78+i,1160000000L+i*50000000L,20).interrupted(),"unfreeze never revives old action "+i);
        for(long delta:new long[]{149999999L,150000000L,150000001L}) {
            var frozen=guard(18);frozen.sampleSource(1,500,0,20);
            var value=frozen.sampleSource(2,500,delta,20);
            check(value.interrupted()==(delta>150000000L),"exact source freeze boundary "+delta);
        }
        var repeated=guard(18);repeated.sampleSource(1,100,0,20);repeated.sampleSource(2,101,160000000L,20);
        repeated.sampleSource(3,101,210000000L,20);repeated.sampleSource(4,101,260000000L,20);
        check(repeated.recoverySamples()==1,"same source no quiet-window credit");
        repeated.sampleSource(5,102,310000000L,20);
        check(repeated.recoverySamples()==2,"both clocks advance within bound");
        reason(repeated.sampleSource(6,101,360000000L,20),"health_source_clock_invalid");
        check(repeated.sampleSource(7,103,410000000L,20).interrupted(),"source regression cannot heal");
        var skipped=guard(18);skipped.sampleSource(1,1000,0,20);
        reason(skipped.sampleSource(2,1004,50000000L,20),"health_source_tick_gap");
        var duplicateNano=guard(18);duplicateNano.sampleSource(1,100,0,20);duplicateNano.sampleSource(2,101,160000000L,20);
        duplicateNano.sampleSource(3,102,160000000L,20);
        check(duplicateNano.recoverySamples()==1,"source/action advance without monotonic-time advance earns no credit");
        duplicateNano.sampleSource(4,103,210000000L,20);
        check(duplicateNano.recoverySamples()==2,"strictly advancing source/time can credit next sample");
        var missing=guard(18);reason(missing.sample(1,0,20),"health_source_tick_missing");
        check(missing.sampleSource(2,1,50000000L,20).interrupted(),"missing clock cannot be repaired in action");
        for(long source:new long[]{77,76,81}) {
            var simultaneous=guard(18);simultaneous.sampleSource(0,77,0,20);
            var failure=simultaneous.sampleSource(1,source,160000000L,19);
            reason(failure,"health_loss_during_observation_recovery");
            check(failure.damageInWindow()==1,"observed loss retained on source refusal "+source);
            check(simultaneous.diagnostics().latched(),"source/loss hard latch "+source);
        }
        var simultaneousLow=guard(18);simultaneousLow.sampleSource(0,77,0,20);
        var lowAtFreeze=simultaneousLow.sampleSource(1,77,160000000L,18);
        reason(lowAtFreeze,"caller_min_health");check(lowAtFreeze.damageInWindow()==2,"low-health loss retained at freeze");
        var sourceLoss=guard(18);sourceLoss.sampleSource(1,10,0,20);sourceLoss.sampleSource(2,11,160000000L,20);
        reason(sourceLoss.sampleSource(3,11,210000000L,19.9),"health_loss_during_observation_recovery");
        // A short no-observation interval is not credited. A genuine advancing source
        // after a wall gap starts from zero credit; later fresh observations alone recover.
        var resumed=guard(18);resumed.sampleSource(1,100,0,20);
        reason(resumed.sampleSource(2,101,200000000L,20),"health_observation_recovering");
        check(resumed.recoverySamples()==1,"pause-like gap earns no recovery credit");
        for(int i=1;i<20;i++)check(resumed.sampleSource(2+i,101+i,200000000L+i*50000000L,20).interrupted(),"resumed interval below full window "+i);
        check(!resumed.sampleSource(22,121,1200000000L,20).interrupted(),"fresh source-bound full window recovers");
        var stillPaused=guard(18);stillPaused.sampleSource(1,100,0,20);
        reason(stillPaused.sampleSource(2,100,200000000L,20),"health_source_tick_frozen");
        check(stillPaused.sampleSource(3,101,250000000L,20).interrupted(),"frozen pause then resume cannot unlock");
        // Source game times are long values, never truncated to action counters.
        var wide=guard(18);wide.sampleSource(1,Long.MAX_VALUE-2,0,20);
        check(!wide.sampleSource(2,Long.MAX_VALUE-1,50000000L,20).interrupted(),"long source tick supported");
        System.out.println("{\"status\":\"passed\",\"assertions\":"+assertions+",\"scope\":\"production pure health recovery and threat gates; not game/controller lifecycle\"}");
    }
}

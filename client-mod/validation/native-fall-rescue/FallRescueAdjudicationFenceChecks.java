package io.github.campione01.mineclientbridge;

import java.util.ArrayList;
import java.util.List;

/** Actual production ordering helper, WorldGeneration and quarantine CAS; game facts are modeled. */
public final class FallRescueAdjudicationFenceChecks {
    static int checks;
    static void ok(boolean b){checks++;if(!b)throw new AssertionError("check "+checks);}
    static final class Facts {
        final Object originalServer=new Object(),originalPlayer=new Object(),originalLevel=new Object(),originalMode=new Object();
        Object server=originalServer,player=originalPlayer,level=originalLevel,mode=originalMode;
        final String world=WorldGeneration.current(originalLevel);
        long owner=1;boolean published,paused,external=true,neutral=true;String uuid="original";
        final List<String> order=new ArrayList<>();
        boolean proof(String phase,Runnable callback){
            return FallRescueAdjudicationFence.prove(
                ()->{order.add("external");if(phase.equals("external"))callback.run();return external;},
                ()->{order.add("neutral");if(phase.equals("neutral"))callback.run();return neutral;},
                ()->{order.add("private");if(phase.equals("private"))callback.run();
                    return !published&&!paused&&server==originalServer&&uuid.equals("original");},
                ()->{order.add("pure");return owner==1&&player==originalPlayer&&level==originalLevel&&mode==originalMode
                    &&WorldGeneration.matches(originalLevel,world);});
        }
    }
    public static void main(String[]args){
        Facts positive=new Facts();ok(positive.proof("none",()->{}));
        ok(positive.order.equals(List.of("external","neutral","private","pure")));
        for(String phase:List.of("external","neutral","private")){
            for(String fault:List.of("publication","server","world-invalidation","world-ABA","owner","player","level","mode","uuid","pause")){
                Facts f=new Facts();var arbiter=new SingleInputArbiter();arbiter.quarantine("native_fall_rescue_original_action_quarantined");long revision=arbiter.revision();
                Runnable callback=()->{switch(fault){
                    case "publication"->f.published=true;
                    case "server"->f.server=new Object();
                    case "world-invalidation"->WorldGeneration.current(null);
                    case "world-ABA"->{WorldGeneration.current(new Object());WorldGeneration.current(f.originalLevel);}
                    case "owner"->f.owner++;
                    case "player"->f.player=new Object();
                    case "level"->f.level=new Object();
                    case "mode"->f.mode=new Object();
                    case "uuid"->f.uuid="replacement";
                    case "pause"->f.paused=true;
                }};
                boolean proof=f.proof(phase,callback);if(proof)arbiter.adjudicateOriginal(revision);
                ok(!proof);ok(arbiter.quarantined()&&arbiter.revision()==revision);
            }
        }
        Facts stopped=new Facts();stopped.external=false;ok(!stopped.proof("none",()->{}));ok(stopped.order.equals(List.of("external")));
        Facts busy=new Facts();busy.neutral=false;ok(!busy.proof("none",()->{}));ok(busy.order.equals(List.of("external","neutral")));
        Facts throwing=new Facts();try{throwing.proof("neutral",()->{throw new IllegalStateException("hook");});throw new AssertionError("swallowed");}
        catch(IllegalStateException expected){ok(throwing.order.equals(List.of("external","neutral")));}
        Object world=new Object();String generation=WorldGeneration.current(world);ok(WorldGeneration.matches(world,generation));
        WorldGeneration.current(null);ok(!WorldGeneration.matches(world,generation));ok(!WorldGeneration.matches(null,generation));
        String replacement=WorldGeneration.current(world);ok(!replacement.equals(generation));ok(WorldGeneration.matches(world,replacement));
        System.out.println("PASS adjudication context/fence checks="+checks+" game_started=false");
    }
}

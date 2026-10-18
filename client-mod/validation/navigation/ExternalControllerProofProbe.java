package io.github.campione01.mineclientbridge;

import com.google.gson.JsonObject;
import java.net.URLClassLoader;
import java.nio.file.Path;

/** Small offline probe. Never loads Minecraft, initializes Baritone, or opens a game. */
public final class ExternalControllerProofProbe {
    private static int checks;
    static final ExternalControllerProof.Context CONTEXT=new ExternalControllerProof.Context(
            new Object(),new Object(),new Object(),"session","world","player",123);
    static ExternalControllerProof.Facts facts(boolean pathing,boolean current,boolean next,boolean planning,boolean goal,int active,int forced) {
        return new ExternalControllerProof.Facts("present",true,true,1,pathing,current,next,planning,goal,active,10,forced,"actual_sample");
    }
    static void check(boolean condition,String label) {if(!condition)throw new AssertionError(label);checks++;}
    static JsonObject sample(ExternalControllerProof.Facts facts) {return ExternalControllerProof.snapshot(CONTEXT,context->facts);}
    static final class UntrustedProcess {
        int calls;
        public boolean isActive(){calls++;throw new AssertionError("custom getter invoked");}
    }
    public static void main(String[] args) throws Exception {
        JsonObject idle=sample(facts(false,false,false,false,false,0,0));
        check(idle.get("idle_proven").getAsBoolean(),"actual idle");
        check(!idle.get("execution_authority").getAsBoolean(),"no authority");
        check(idle.get("source_tick").getAsLong()==123 && idle.get("player_uuid").getAsString().equals("player"),"exact context");
        check(!sample(facts(true,false,false,false,false,0,0)).get("idle_proven").getAsBoolean(),"pathing");
        check(!sample(facts(false,true,false,false,false,0,0)).get("idle_proven").getAsBoolean(),"paused path");
        check(!sample(facts(false,false,true,false,false,0,0)).get("idle_proven").getAsBoolean(),"queued path");
        check(!sample(facts(false,false,false,true,false,0,0)).get("idle_proven").getAsBoolean(),"planning");
        check(!sample(facts(false,false,false,false,true,0,0)).get("idle_proven").getAsBoolean(),"retained goal");
        check(!sample(facts(false,false,false,false,false,1,0)).get("idle_proven").getAsBoolean(),"active custom process");
        check(!sample(facts(false,false,false,false,false,0,1)).get("idle_proven").getAsBoolean(),"forced input");
        check(!sample(new ExternalControllerProof.Facts("present",false,true,1,false,false,false,false,false,0,10,0,"chat_ack"))
                .get("idle_proven").getAsBoolean(),"chat acknowledgement grants nothing");
        check(!sample(new ExternalControllerProof.Facts("present",true,false,1,false,false,false,false,false,0,10,0,"wrong_player"))
                .get("idle_proven").getAsBoolean(),"context mismatch");
        check(!sample(new ExternalControllerProof.Facts("present",true,true,2,false,false,false,false,false,0,10,0,"two_instances"))
                .get("idle_proven").getAsBoolean(),"two instances");
        check(!sample(new ExternalControllerProof.Facts("present",true,true,1,false,false,false,false,false,0,0,0,"no_registry"))
                .get("idle_proven").getAsBoolean(),"missing registry");
        JsonObject broken=ExternalControllerProof.snapshot(CONTEXT,context->{throw new LinkageError();});
        check(!broken.get("idle_proven").getAsBoolean() && broken.get("status").getAsString().equals("unknown"),"linkage failure");
        check(sample(new ExternalControllerProof.Facts("absent",true,true,0,false,false,false,false,false,0,0,0,"absent"))
                .get("idle_proven").getAsBoolean(),"verified absence");
        try(var loader=new URLClassLoader(new java.net.URL[]{Path.of(args[0]).toUri().toURL()},null)) {
            var access=new ExternalControllerProof.ReflectiveAccess(loader);
            check(access.fingerprintsSupported(),"official API class fingerprints");
            check(access.fingerprintsSupported(),"immutable fingerprints reusable");
        }
        try(var loader=new URLClassLoader(new java.net.URL[]{Path.of(args[1]).toUri().toURL()},null)) {
            var access=new ExternalControllerProof.ReflectiveAccess(loader);
            check(!access.fingerprintsSupported(),"standalone not mistaken for supported API");
            check(access.inspect(CONTEXT).reason().equals("baritone_api_variant_migration_required"),"standalone detected as present");
        }
        for (boolean cancel : new boolean[]{false,true}) {
            var clock=new java.util.concurrent.atomic.AtomicLong();
            var leases=new GuardedMovement(clock::get);leases.openAdmission();
            String world=java.util.UUID.randomUUID().toString(),player=java.util.UUID.randomUUID().toString();
            var state=new GuardedMovement.State(world,player,100,.5,64,.5,0,true,true,true,true,true);
            String observation=leases.observe(state);
            var request=new GuardedMovement.Request(leases.session(),java.util.UUID.randomUUID().toString(),observation,
                    world,player,100,.5,64,.5,0,250,100);
            var ticket=leases.submit(request,clock.get(),leases.session());
            var writes=new java.util.concurrent.atomic.AtomicInteger();
            leases.sample(()->state,()->{
                var permit=leases.effectPermit();
                if(cancel)leases.cancelAndRelease("external_hook_cancelled");
                else clock.addAndGet(java.util.concurrent.TimeUnit.MILLISECONDS.toNanos(101));
                permit.checkLive(); writes.incrementAndGet();
            },()->{});
            check(writes.get()==0 && ticket.result.isDone(),cancel?"external getter cancelled exact permit":"external getter consumed original TTL");
        }
        // Deterministic worker completion at the current-path getter. The old
        // order would observe current=false and then planning=false (false idle).
        var planning=new java.util.concurrent.atomic.AtomicBoolean(true);
        var pathFacts=ExternalControllerProof.readPath(planning::get,()->false,()->{
            planning.set(false);return false;
        },()->false,()->false);
        check(pathFacts.planning(),"planner completion cannot erase earlier busy witness");
        var published=new java.util.concurrent.atomic.AtomicBoolean();
        pathFacts=ExternalControllerProof.readPath(()->{published.set(true);return false;},
            ()->false,published::get,()->false,()->false);
        check(pathFacts.current(),"completed planner publication precedes current path read");
        var custom=new UntrustedProcess();
        var access=new ExternalControllerProof.ReflectiveAccess(ExternalControllerProofProbe.class.getClassLoader());
        try {access.processActive(custom,false);throw new AssertionError("custom process accepted");}
        catch(IllegalStateException expected){check(custom.calls==0,"unknown process rejected before callback");}
        check(!ExternalControllerProof.ReflectiveAccess.inventoryPausePending(false,false),"inventory pauser defer does not falsely block");
        check(ExternalControllerProof.ReflectiveAccess.inventoryPausePending(true,false),"inventory pause request blocks");
        check(ExternalControllerProof.ReflectiveAccess.inventoryPausePending(false,true),"previous controlling command blocks");
        System.out.println("PASS "+checks+" external-controller proof checks; no Minecraft or Baritone initialization");
    }
}

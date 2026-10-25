package io.github.campione01.mineclientbridge;

import com.google.gson.*;
import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import java.lang.reflect.*;

/** Offline production journal/codec checks. No Minecraft instance, world, bootstrap or networking. */
public final class RecoveryInteractionChecks {
    static int checks;
    static final String FP="a".repeat(64);
    static void check(boolean ok,String label){if(!ok)throw new AssertionError(label);checks++;}
    static void rejects(Runnable run,String label){try{run.run();throw new AssertionError(label);}catch(IllegalArgumentException|IllegalStateException expected){checks++;}}
    static RecoveryShortInputLedger.Request typed(RecoveryShortInputLedger l,String id,String kind,int calls){return typed(l,id,kind,calls,RecoveryShortInputChecks.OWNER);}
    static RecoveryShortInputLedger.Request typed(RecoveryShortInputLedger l,String id,String kind,int calls,String owner){
        var op=new RecoveryShortInputLedger.Operation(kind,kind.equals("look")?-180:0,kind.equals("look")?-30:0,kind.equals("select_hotbar")?2:0,kind.equals("break_block")||kind.equals("select_hotbar")?FP:"",kind.equals("break_block")?-636:0,kind.equals("break_block")?60:0,kind.equals("break_block")?33:0,kind.equals("break_block")?"SOUTH":"",kind.equals("break_block")?"minecraft:cobblestone":"");
        return new RecoveryShortInputLedger.Request(id,l.session,owner,l.nextGeneration(),RecoveryShortInputChecks.WORLD,RecoveryShortInputChecks.PLAYER,0,0,calls,false,2000,RecoveryShortInputChecks.OBS,op);
    }
    static void setLedger(RecoveryShortInputLedger l)throws Exception{Field f=NativeRecoveryShortInput.class.getDeclaredField("ledger");f.setAccessible(true);f.set(null,l);}
    public static void main(String[] args)throws Exception{
        if(args[0].equals("--both-flags")){rejects(NativeRecoveryShortInput::open,"startup_flags_mutually_exclusive");System.out.println("RecoveryInteractionChecks both-flags PASS assertions="+checks);return;}
        Path fixture=Path.of(args[0]),out=Path.of(args[1]);Files.createDirectories(out);
        typedBoundsAndStops();enteredStop();failureAndRestart();existingJournalRequired();typedFileRoundtrip();legacy57(fixture,out);wire(args.length>2&&args[2].equals("--preserve-fixtures")?Files.createTempDirectory("interaction-wire-check-"):out.resolve("wire-fixtures"));
        System.out.println("RecoveryInteractionChecks PASS assertions="+checks);
    }
    static void typedBoundsAndStops(){
        var now=new AtomicLong(100);var memory=new RecoveryShortInputChecks.Memory();var l=new RecoveryShortInputLedger(memory,now::get);
        rejects(()->typed(l,"bad_move","move",9),"move_bound");rejects(()->typed(l,"bad_look","look",2),"look_one");rejects(()->typed(l,"bad_break","break_block",33),"break_bound");
        var cancel=l.submit(typed(l,"cancel","break_block",32));l.stop(cancel,"explicit_stop");check(cancel.settled()&&!l.claimCall(cancel,1,true),"queued_cancel_no_claim");
        var exp=l.submit(typed(l,"expire","break_block",32));now.addAndGet(2_000_000_000L);check(!l.claimCall(exp,2,true)&&exp.settled()&&exp.applied==0,"queued_deadline_known_zero");
        var r=typed(l,"finite","break_block",32);var e=l.submit(r);int writes=memory.writes;check(l.submit(r)==e&&writes==memory.writes,"duplicate_no_write_or_dispatch");
        rejects(()->l.submit(new RecoveryShortInputLedger.Request(r.id(),r.session(),r.ownerId(),r.generation(),r.world(),r.player(),0,0,31,false,2000,r.observationId(),r.operation())),"same_id_changed_bound");
        for(int i=0;i<32;i++){check(l.claimCall(e,i,true),"bounded_call_claim");check(memory.saved.getLast().effectFenced,"durable_before_native_call");check(!l.claimCall(e,i,true),"no_reentrant_call");l.completeCall(e);check(!l.claimCall(e,i,true),"one_call_per_tick");}
        check(!l.claimCall(e,33,true)&&e.state.equals("STOPPING"),"32calls_cap");l.release(e,true,()->{},true,"finite_partial");check(e.settled()&&e.applied==32,"partial_known_not_unknown");
        var next=l.submit(typed(l,"next","look",1));l.stop(e,"stale_stop");l.release(e,true,()->{throw new AssertionError("old_cleanup_effect");},true,"old");check(l.active()==next&&l.live(next),"old_ticket_stop_cleanup_no_new_owner_effect");
        l.stop(next,"no_op");var future=typed(l,"wrongowner","look",1,"55555555-5555-4555-8555-555555555555");rejects(()->l.submit(future),"same_session_different_owner");
    }
    static void enteredStop()throws Exception{
        var memory=new RecoveryShortInputChecks.Memory();var l=new RecoveryShortInputLedger(memory,()->100);var e=l.submit(typed(l,"entered","break_block",32));
        CountDownLatch entered=new CountDownLatch(1),unwind=new CountDownLatch(1);AtomicInteger calls=new AtomicInteger();AtomicReference<Throwable> failure=new AtomicReference<>();
        Thread t=new Thread(()->{try{check(l.claimCall(e,1,true),"claim_entered");calls.incrementAndGet();entered.countDown();unwind.await();l.completeCall(e);}catch(Throwable x){failure.set(x);}});t.start();check(entered.await(1,TimeUnit.SECONDS),"entered_wait");
        long start=System.nanoTime();l.stop(e,"explicit_stop");check(System.nanoTime()-start<250_000_000L,"stop_not_blocked_by_native_stack");
        check(e.callRunning&&e.invalidated&&e.state.equals("STOPPING")&&!e.released,"stop_ack_not_terminal_while_entered");
        l.release(e,true,()->{throw new AssertionError("release_during_call");},true,"stop");check(!e.settled(),"no_early_release_proof");
        check(!l.claimCall(e,2,true),"stop_disallows_future_claim");unwind.countDown();t.join(1000);check(!t.isAlive()&&failure.get()==null,"original_stack_unwound");
        l.stop(e,"mining_bound_or_stop");l.release(e,true,()->{},true,"mining_attempt_finished");check(e.settled()&&e.applied==1&&calls.get()==1,"entered_call_accounted_then_released");check(e.reason.equals("explicit_stop"),"first_stop_reason_survives_unwind_cleanup");
    }
    static void failureAndRestart(){
        var memory=new RecoveryShortInputChecks.Memory();var l=new RecoveryShortInputLedger(memory,()->100);var e=l.submit(typed(l,"lost_receipt","look",1));
        var restarted=new RecoveryShortInputLedger(memory,()->200);check(restarted.locked(),"lost_receipt_restart_unknown");rejects(()->restarted.submit(typed(restarted,"newprofile","move",1)),"unknown_cross_kind_lock");
        var m2=new RecoveryShortInputChecks.Memory();var x=new RecoveryShortInputLedger(m2,()->1);var a=x.submit(typed(x,"io_before","break_block",32));m2.fail=true;rejects(()->x.claimCall(a,1,true),"io_before_claim");check(x.locked()&&!a.callRunning&&a.applied==0,"before_io_no_call");
        var m3=new RecoveryShortInputChecks.Memory();var z=new RecoveryShortInputLedger(m3,()->1);var b=z.submit(typed(z,"io_after","break_block",32));check(z.claimCall(b,1,true),"after_claim");m3.fail=true;rejects(()->z.completeCall(b),"io_after_call");check(z.locked()&&b.applied==1&&!b.callRunning,"after_io_unknown_accounted");m3.fail=false;z.release(b,true,()->{},true,"unknown_cleanup");check(z.locked()&&b.released&&!b.settled(),"unknown_release_not_unlock");
    }
    static void existingJournalRequired()throws Exception{
        var empty=new RecoveryShortInputChecks.Memory();var l=new RecoveryShortInputLedger(empty,()->1,true);
        check(l.locked()&&l.owner()==null&&empty.writes==0&&l.lockReason().equals("interaction_existing_journal_required"),"empty_existing_mode_no_new_identity");
        rejects(()->l.submit(typed(l,"no_new_ledger","look",1)),"empty_mode_cannot_start");
        Path missing=Files.createTempDirectory("recovery-interaction-missing-").resolve("journal");
        try(var store=new RecoveryShortInputLedger.FileStore(missing)){var x=new RecoveryShortInputLedger(store,()->1,true);check(x.locked()&&!Files.exists(missing),"missing_journal_not_created");}
        var old=new RecoveryShortInputLedger(empty,()->1);check(!old.locked(),"legacy_empty_init_unchanged");
        old.submit(typed(old,"unfinished_existing","break_block",32));var restarted=new RecoveryShortInputLedger(empty,()->2,true);check(restarted.locked()&&restarted.owner()!=null,"existing_unknown_retains_bound_owner_lock");
    }
    static void typedFileRoundtrip()throws Exception{
        var memory=new RecoveryShortInputChecks.Memory();var l=new RecoveryShortInputLedger(memory,()->100);
        for(String kind:List.of("move","look","select_hotbar","break_block")){
            var e=l.submit(typed(l,"persist_"+kind,kind,kind.equals("break_block")?32:1));
            if(kind.equals("break_block")){check(l.claimCall(e,1,true),"typed_file_claim");l.completeCall(e);e.gameplay="target_changed";}
            else check(l.sample(e,1,true,()->{}),"typed_file_sample");
            l.stop(e,"file_stop");l.release(e,true,()->{},true,"file_cleanup");
        }
        Path path=Files.createTempDirectory("recovery-interaction-typed-file-").resolve("journal");
        try(var store=new RecoveryShortInputLedger.FileStore(path)){
            store.write(memory.saved);var decoded=store.read();check(decoded.size()==4,"typed_file_all_kinds");
            for(int i=0;i<4;i++)check(decoded.get(i).request.equals(memory.saved.get(i).request)&&decoded.get(i).request.digest().equals(memory.saved.get(i).request.digest()),"typed_request_digest_roundtrip");
        }
    }
    static void legacy57(Path fixtures,Path out)throws Exception{
        Path temp=Files.createTempDirectory("recovery-interaction-migration-").resolve("journal");Files.copy(fixtures.resolve("native-57-entry-journal.bin"),temp);
        JsonObject publicActions=JsonParser.parseString(Files.readString(fixtures.resolve("public-ledger.json"))).getAsJsonObject().getAsJsonObject("actions");
        List<RecoveryShortInputLedger.Entry> originals;JsonArray snapshots=new JsonArray();
        try(var store=new RecoveryShortInputLedger.FileStore(temp)){
            originals=store.read();check(originals.size()==57,"actual_57_fixture");var l=new RecoveryShortInputLedger(store,()->100);setLedger(l);
            check(!l.locked()&&l.nextGeneration()==58&&l.owner().equals(originals.getFirst().request.ownerId()),"57_generation_owner_continuity");
            for(var old:originals){var r=old.request;var e=l.lookup(r.id(),r.session(),r.ownerId(),r.generation());JsonObject status=NativeRecoveryShortInput.describe(e);
                check(r.operation()==null&&r.profile().equals(RecoveryShortInputLedger.PROFILE),"legacy_kind_profile_retained");
                check(status.equals(publicActions.getAsJsonObject(r.id()).getAsJsonObject("terminal_native")),"every_old_terminal_exact_matches_actual_receipt");
                check(l.submit(r)==e,"old_duplicate_original");snapshots.add(status);
            }
            var entry=l.submit(typed(l,"migration-new","look",1,l.owner()));l.rejectQueued(entry,"offline_no_game");
            check(store.read().size()==58,"atomic_rsi2_write");
        }
        try(var store=new RecoveryShortInputLedger.FileStore(temp)){
            var l=new RecoveryShortInputLedger(store,()->200);setLedger(l);check(!l.locked()&&l.nextGeneration()==59,"rsi2_restart_continuity");
            for(int i=0;i<57;i++){var old=originals.get(i);var r=old.request;var e=l.lookup(r.id(),r.session(),r.ownerId(),r.generation());check(e.request.equals(r)&&e.request.digest().equals(r.digest())&&NativeRecoveryShortInput.describe(e).equals(snapshots.get(i)),"every_legacy_request_digest_terminal_after_upgrade");}
            JsonObject first=snapshots.get(0).getAsJsonObject();JsonObject q=new JsonObject();for(String k:new String[]{"id","session","owner_id","owner_generation"})q.add(k,first.get(k));check(NativeRecoveryShortInput.status(q,false).equals(first),"old_root_status_retained");
            JsonObject stop=q.deepCopy();stop.addProperty("schema_version",1);stop.addProperty("profile",RecoveryShortInputLedger.PROFILE);check(NativeRecoveryShortInput.stop(stop,false).equals(first),"old_root_exact_terminal_stop_retained");
            rejects(()->NativeRecoveryShortInput.status(q,true),"newroot_cannot_relabel_legacy");
        }
        Files.write(out.resolve("legacy57-preserved-statuses.json"),RecoveryShortInputCodec.encode(wrap(snapshots)));
        // A legacy unfinished record migrates to a global UNKNOWN, never a new empty typed namespace.
        Path pending=Files.createTempDirectory("recovery-interaction-pending-").resolve("journal");Files.copy(fixtures.resolve("native-57-entry-journal.bin"),pending);
        try(var store=new RecoveryShortInputLedger.FileStore(pending)){var entries=store.read();entries.getLast().state="ACTIVE";entries.getLast().invalidated=false;store.write(entries);var l=new RecoveryShortInputLedger(store,()->1);check(l.locked(),"legacy_pending_locks_typed");rejects(()->l.submit(typed(l,"no_bypass","look",1,l.owner())),"no_new_profile_reset");}
        try(var store=new RecoveryShortInputLedger.FileStore(pending)){check(new RecoveryShortInputLedger(store,()->2).locked(),"unknown_restart_persistent");}
    }
    static JsonObject wrap(JsonArray a){JsonObject j=new JsonObject();j.add("statuses",a);return j;}
    static JsonObject requestJson(RecoveryShortInputLedger.Request r){
        JsonObject j=new JsonObject();j.addProperty("schema_version",1);j.addProperty("profile",r.profile());j.addProperty("kind",r.kind());j.addProperty("id",r.id());j.addProperty("session",r.session());j.addProperty("owner_id",r.ownerId());j.addProperty("owner_generation",r.generation());j.addProperty("world_generation",r.world());j.addProperty("player_uuid",r.player());j.addProperty("ttl_ms",r.ttlMs());j.addProperty("observation_id",r.observationId());var o=r.operation();
        switch(r.kind()){case "move"->{j.addProperty("forward",r.forward());j.addProperty("strafe",r.strafe());j.addProperty("samples",r.samples());j.addProperty("jump_first",r.jumpFirst());}case "look"->{j.addProperty("yaw",o.yaw());j.addProperty("pitch",o.pitch());}case "select_hotbar"->{j.addProperty("slot",o.slot());j.addProperty("stack_fingerprint",o.fingerprint());}case "break_block"->{j.addProperty("x",o.x());j.addProperty("y",o.y());j.addProperty("z",o.z());j.addProperty("face",o.face());j.addProperty("block_id",o.blockId());j.addProperty("stack_fingerprint",o.fingerprint());j.addProperty("max_calls",r.samples());}}
        return j;
    }
    static void wire(Path out)throws Exception{
        Files.createDirectories(out);var l=new RecoveryShortInputLedger(new RecoveryShortInputChecks.Memory(),()->100);setLedger(l);int seq=0;
        for(String kind:List.of("move","look","select_hotbar","break_block")){
            var request=requestJson(typed(l,String.format("77777777-7777-4777-8777-%012d",++seq),kind,kind.equals("break_block")?32:1));byte[] bytes=RecoveryShortInputCodec.encode(request);var parsed=NativeRecoveryShortInput.parseInteractionStart(RecoveryShortInputCodec.parse(bytes));var e=l.submit(parsed);Files.write(out.resolve(kind+"-request.json"),bytes);Files.write(out.resolve(kind+"-queued.json"),RecoveryShortInputCodec.encode(NativeRecoveryShortInput.describe(e)));
            if(kind.equals("break_block")){check(l.claimCall(e,seq,true),"wire_call");l.completeCall(e);e.gameplay="target_unchanged";}else check(l.sample(e,seq,true,()->{}),"wire_one_shot");
            l.stop(e,"offline_fixture_stop");l.release(e,true,()->{},true,"offline_fixture_stop");Files.write(out.resolve(kind+"-settled.json"),RecoveryShortInputCodec.encode(NativeRecoveryShortInput.describe(e)));
            check(NativeRecoveryShortInput.describe(e).get("applied_calls").getAsInt()==1,"production_typed_count");
            if(kind.equals("look")){
                check(parsed.operation().yaw()==-180,"actual_codec_minus180_accepted");
                JsonObject plus=request.deepCopy();plus.addProperty("yaw",180);rejects(()->NativeRecoveryShortInput.parseInteractionStart(plus),"actual_codec_plus180_rejected");
            }
            JsonObject bad=request.deepCopy();bad.addProperty("unknown",1);rejects(()->NativeRecoveryShortInput.parseInteractionStart(bad),"closed_kind_schema");
        }
        Files.write(out.resolve("observe-no-world.json"),RecoveryShortInputCodec.encode(NativeRecoveryShortInput.describeNoWorld(false,true,true)));
        var zero=l.submit(typed(l,"77777777-7777-4777-8777-000000000005","look",1));l.rejectQueued(zero,"observation_stale_or_moved");Files.write(out.resolve("zero-request.json"),RecoveryShortInputCodec.encode(requestJson(zero.request)));Files.write(out.resolve("zero-settled.json"),RecoveryShortInputCodec.encode(NativeRecoveryShortInput.describe(zero)));
        var pending=l.submit(typed(l,"77777777-7777-4777-8777-000000000006","break_block",32));check(l.claimCall(pending,99,true),"wire_entered_claim");l.stop(pending,"explicit_stop");Files.write(out.resolve("entered-request.json"),RecoveryShortInputCodec.encode(requestJson(pending.request)));Files.write(out.resolve("entered-stop.json"),RecoveryShortInputCodec.encode(NativeRecoveryShortInput.describe(pending)));l.failedCall(pending);l.release(pending,true,()->{},true,"unknown_release");Files.write(out.resolve("unknown-released.json"),RecoveryShortInputCodec.encode(NativeRecoveryShortInput.describe(pending)));
    }
}

package io.github.campione01.mineclientbridge;

import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.atomic.*;

public final class RecoveryShortInputChecks {
    static int checks;
    static final String OWNER="11111111-1111-4111-8111-111111111111",WORLD="22222222-2222-4222-8222-222222222222",PLAYER="33333333-3333-4333-8333-333333333333",OBS="44444444-4444-4444-8444-444444444444";
    static class Memory implements RecoveryShortInputLedger.Store {
        List<RecoveryShortInputLedger.Entry> saved=new ArrayList<>();boolean fail;int writes;
        public List<RecoveryShortInputLedger.Entry> read(){return saved.stream().map(Memory::copy).toList();}
        public void write(Collection<RecoveryShortInputLedger.Entry> entries)throws IOException{
            writes++;if(fail)throw new IOException("injected_io_failure");saved=entries.stream().map(Memory::copy).toList();
        }
        static RecoveryShortInputLedger.Entry copy(RecoveryShortInputLedger.Entry e){
            var n=new RecoveryShortInputLedger.Entry(e.request,e.deadline);n.state=e.state;n.reason=e.reason;n.applied=e.applied;
            n.cancellationGeneration=e.cancellationGeneration;n.invalidated=e.invalidated;n.released=e.released;n.effectFenced=e.effectFenced;return n;
        }
    }
    static RecoveryShortInputLedger.Request request(RecoveryShortInputLedger l,String id,int samples){return new RecoveryShortInputLedger.Request(id,l.session,OWNER,l.nextGeneration(),WORLD,PLAYER,1,0,samples,true,500,OBS);}
    static void check(boolean condition,String label){if(!condition)throw new AssertionError(label);checks++;}
    static void rejects(Runnable action,String label){try{action.run();throw new AssertionError("accepted: "+label);}catch(IllegalArgumentException|IllegalStateException expected){checks++;}}
    public static void main(String[] args)throws Exception{
        finiteAndDuplicate();queuedCancelAndExpiry();oldOwner();restartUnknown();ioFailures();clockAndShutdown();fileStore();cleanupQueue();missingPost();
        System.out.println("RecoveryShortInputChecks PASS assertions="+checks);
    }
    static void finiteAndDuplicate(){
        Memory s=new Memory();AtomicLong now=new AtomicLong(100);var l=new RecoveryShortInputLedger(s,now::get);var r=request(l,"finite",8);var e=l.submit(r);
        check(s.saved.size()==1&&s.saved.getFirst().state.equals("QUEUED"),"durable_queue_before_receipt");
        check(l.submit(r)==e&&s.writes==1,"lost_receipt_duplicate_original_no_dispatch");
        rejects(()->l.submit(new RecoveryShortInputLedger.Request(r.id(),r.session(),r.ownerId(),r.generation(),r.world(),r.player(),0,1,8,true,500,OBS)),"same_id_changed_payload");
        AtomicInteger writes=new AtomicInteger();for(int tick=1;tick<=8;tick++){
            int savedCount=writes.get();
            check(l.sample(e,tick,true,()->{check(s.saved.getFirst().effectFenced,"effect_fence_durable_before_raw");writes.incrementAndGet();}),"sample");
            check(!l.sample(e,tick,true,writes::incrementAndGet),"same_tick_no_second_sample");
            l.release(e,true,()->{},false,"samples_complete");check(writes.get()==savedCount+1,"one_write_per_native_tick");
        }
        check(e.settled()&&e.invalidated&&e.released&&e.applied==8,"known_finite_terminal");
        check(!l.sample(e,9,true,writes::incrementAndGet)&&writes.get()==8,"at_most_sample_bound");
    }
    static void queuedCancelAndExpiry(){
        Memory s=new Memory();AtomicLong now=new AtomicLong(1);var l=new RecoveryShortInputLedger(s,now::get);var e=l.submit(request(l,"cancel",2));l.stop(e,"test_stop");
        check(e.settled()&&e.applied==0&&e.released&&!e.effectFenced,"queued_cancel_known_no_input");
        check(!l.sample(e,1,true,()->{throw new AssertionError();}),"stale_queued_callback_invalid");
        var expiry=l.submit(request(l,"expire",1));now.addAndGet(500_000_000L);l.expireQueued(expiry);
        check(expiry.settled()&&expiry.applied==0,"queued_expiry_known_no_input");
    }
    static void oldOwner(){
        Memory s=new Memory();var l=new RecoveryShortInputLedger(s,()->1);var old=l.submit(request(l,"old",1));l.sample(old,1,true,()->{});l.release(old,true,()->{},true,"done");
        var current=l.submit(request(l,"new",2));AtomicInteger untouched=new AtomicInteger();l.stop(old,"late_stop");l.release(old,true,untouched::incrementAndGet,true,"late_cleanup");
        check(l.owns(current)&&untouched.get()==0,"old_stop_cleanup_do_not_touch_replacement");
        l.stop(current,"cancel");var r=request(l,"different_owner",1);
        rejects(()->l.submit(new RecoveryShortInputLedger.Request(r.id(),r.session(),"55555555-5555-4555-8555-555555555555",r.generation(),r.world(),r.player(),1,0,1,false,500,OBS)),"same_session_different_owner");
    }
    static void restartUnknown(){
        Memory s=new Memory();var l=new RecoveryShortInputLedger(s,()->1);var r=request(l,"lost",2);var e=l.submit(r);l.sample(e,1,true,()->{});
        var restart=new RecoveryShortInputLedger(s,()->1);var unknown=restart.lookup(r.id(),r.session(),r.ownerId(),r.generation());
        check(restart.locked()&&unknown.state.equals("UNKNOWN")&&unknown.invalidated,"restart_unfinished_persistent_unknown");
        rejects(()->restart.submit(request(restart,"new_id",1)),"new_session_owner_cannot_clear_unknown");
        check(new RecoveryShortInputLedger(s,()->1).locked(),"unknown_persists_second_restart");
        l.unknown(e,"lost_release_proof");AtomicInteger release=new AtomicInteger();l.release(e,true,release::incrementAndGet,true,"stop");
        check(release.get()==1&&e.released&&e.state.equals("UNKNOWN")&&l.locked(),"unknown_exact_release_preserves_lock");
    }
    static void ioFailures(){
        Memory s=new Memory();var l=new RecoveryShortInputLedger(s,()->1);var e=l.submit(request(l,"pre_fence_io",1));s.fail=true;AtomicInteger effects=new AtomicInteger();
        rejects(()->l.sample(e,1,true,effects::incrementAndGet),"io_before_first_effect");check(effects.get()==0&&l.locked(),"failed_fence_no_effect");
        s.fail=false;check(new RecoveryShortInputLedger(s,()->1).locked(),"existing_durable_queue_survives_io_failure");
        Memory s2=new Memory();var l2=new RecoveryShortInputLedger(s2,()->1);var e2=l2.submit(request(l2,"post_effect_io",2));l2.sample(e2,1,true,effects::incrementAndGet);s2.fail=true;
        rejects(()->l2.release(e2,true,()->{},false,"release"),"post_effect_write_failure");
        AtomicInteger releases=new AtomicInteger();l2.release(e2,true,releases::incrementAndGet,true,"stop");
        check(releases.get()==1&&e2.released&&l2.locked(),"unknown_cleanup_even_with_broken_disk");s2.fail=false;
        check(new RecoveryShortInputLedger(s2,()->1).locked(),"post_effect_failure_restart_locked");
        Memory s3=new Memory();var l3=new RecoveryShortInputLedger(s3,()->1);s3.fail=true;
        rejects(()->l3.submit(request(l3,"first_journal_io",1)),"first_queue_write_failure_no_authority");check(l3.locked(),"initial_io_runtime_failclosed");
    }
    static void clockAndShutdown(){
        AtomicLong now=new AtomicLong(Long.MAX_VALUE-100);var l=new RecoveryShortInputLedger(new Memory(),now::get);var e=l.submit(request(l,"wrap",2));
        check(l.sample(e,1,true,()->{}),"nano_wrap_comparison_before_expiry");now.addAndGet(501_000_000L);check(!l.live(e),"nano_wrap_expiry");l.release(e,true,()->{},true,"expired");
        AtomicLong back=new AtomicLong(100);var lb=new RecoveryShortInputLedger(new Memory(),back::get);var eb=lb.submit(request(lb,"back",1));back.set(99);check(!lb.live(eb)&&eb.settled(),"clock_backwards_no_effect");
        var closed=new RecoveryShortInputLedger(new Memory(),()->1);var ec=closed.submit(request(closed,"close",1));closed.close();check(ec.settled()&&!closed.owns(ec),"bridge_close_invalidates_queue");
    }
    static void fileStore()throws Exception{
        Path directory=Files.createTempDirectory("recovery-short-input-ledger-");Path p=directory.resolve("native.ledger");
        try(var store=new RecoveryShortInputLedger.FileStore(p)){
            var l=new RecoveryShortInputLedger(store,()->1);l.submit(request(l,"file_restart",1));
            rejects(()->new RecoveryShortInputLedger.FileStore(p),"second_jvm_file_lock");
        }
        try(var store=new RecoveryShortInputLedger.FileStore(p)){
            var l=new RecoveryShortInputLedger(store,()->1);check(l.locked(),"real_file_restart_unknown");
        }
        Path alias=directory.resolve("alias.ledger");Files.createSymbolicLink(alias,p);
        rejects(()->new RecoveryShortInputLedger.FileStore(alias),"ledger_symlink_rejected");
        Files.write(p,new byte[]{1,2,3});try(var store=new RecoveryShortInputLedger.FileStore(p)){check(new RecoveryShortInputLedger(store,()->1).locked(),"corrupt_journal_locks");}
    }
    static void cleanupQueue(){
        var l=new RecoveryShortInputLedger(new Memory(),()->1);var e=l.submit(request(l,"cleanup_queue",2));l.sample(e,1,true,()->{});l.stop(e,"stalled_main_thread");
        int queued=0;for(int i=0;i<1000;i++)if(l.claimCleanup(e))queued++;
        check(queued==1,"watchdog_and_repeated_stop_coalesce_one_pending_cleanup");
        l.release(e,true,()->{},true,"stop");l.completeCleanup(e);var replacement=l.submit(request(l,"replacement",1));
        check(!l.claimCleanup(e)&&l.owns(replacement),"old_cleanup_cannot_queue_against_replacement");
        l.sample(replacement,2,true,()->{});l.unknown(replacement,"test_unknown");l.release(replacement,true,()->{},true,"release");
        check(!l.claimCleanup(replacement)&&l.locked(),"unknown_released_stops_queueing_without_unlock");
    }
    static void missingPost(){
        var l=new RecoveryShortInputLedger(new Memory(),()->1);var e=l.submit(request(l,"missing_post",2));
        AtomicInteger raw=new AtomicInteger();l.sample(e,1,true,()->raw.set(3));
        // The production preTick calls this exact predicate before context checks or another input sample.
        check(l.residualInput(e)&&raw.get()==3,"missing_post_detects_captured_residual_input");
        l.release(e,true,()->raw.set(0),false,"pre_tick_residual_release");
        check(raw.get()==0&&!l.residualInput(e)&&l.owns(e),"next_pre_releases_old_forward_and_jump");
        l.sample(e,2,true,()->raw.set(1));l.release(e,true,()->raw.set(0),false,"samples_complete");
        check(e.applied==2&&e.settled()&&raw.get()==0,"missing_post_does_not_extend_original_count");
    }
}

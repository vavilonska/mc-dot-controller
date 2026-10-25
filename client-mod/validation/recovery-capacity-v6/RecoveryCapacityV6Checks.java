package io.github.campione01.mineclientbridge;

import com.google.gson.*;
import java.io.*;
import java.nio.*;
import java.nio.file.*;
import java.security.*;
import java.util.*;
import java.util.concurrent.atomic.*;

/** Real production FileStore/codec on copied or synthetic TEMP data; never starts Minecraft. */
public final class RecoveryCapacityV6Checks {
 static final RecoveryShortInputLedger.CapacityMode V6=RecoveryShortInputLedger.CapacityMode.SURVIVAL_V6;
 static int checks;
 static void check(boolean ok,String why){if(!ok)throw new AssertionError(why);checks++;}
 interface IO {void run()throws Exception;}
 static void ioReject(IO r,String reason)throws Exception{try{r.run();throw new AssertionError("accepted "+reason);}catch(IOException e){check(e.getMessage().equals(reason),"IO reason "+e);}}
 static void reject(Runnable r,String reason){try{r.run();throw new AssertionError("accepted "+reason);}catch(IllegalArgumentException|IllegalStateException e){check(e.getMessage().equals(reason),"reason "+e);}}
 static String sha(byte[] b)throws Exception{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(b));}
 static RecoveryShortInputLedger.Request fresh(RecoveryShortInputLedger l,String id){
  var base=RecoverySurvivalV6Checks.request(l,"move");return new RecoveryShortInputLedger.Request(id,base.session(),base.ownerId(),base.generation(),base.world(),base.player(),1,0,8,true,2000,base.observationId(),base.operation());
 }
 static RecoveryShortInputLedger.Entry settled(int i,boolean maximum){
  var op=maximum?new RecoveryShortInputLedger.Operation("place_block",0,0,0,"a".repeat(64),0,0,0,"","",RecoveryShortInputLedger.MAINTENANCE_V5_PROFILE,3,"b".repeat(64),"s".repeat(64),new RecoveryShortInputLedger.Placement(0,1,0,0,0,0,"minecraft:chiseled_sandstone","UP",.5,1,.5,"minecraft:andesite")):
   new RecoveryShortInputLedger.Operation("move",0,0,0,"",0,0,0,"","",RecoveryShortInputLedger.SURVIVAL_V6_PROFILE,4,"b".repeat(64),"capacity-test");
  String id="synthetic-"+i;if(maximum)id=id+"x".repeat(128-id.length());
  var r=new RecoveryShortInputLedger.Request(id,maximum?"s".repeat(128):"synthetic-session",RecoveryShortInputChecks.OWNER,i+1,maximum?"w".repeat(128):RecoveryShortInputChecks.WORLD,maximum?"p".repeat(128):RecoveryShortInputChecks.PLAYER,maximum?0:1,0,1,false,2000,maximum?"o".repeat(128):RecoveryShortInputChecks.OBS,op);
  var e=new RecoveryShortInputLedger.Entry(r,0);e.state="SETTLED";e.invalidated=true;e.released=true;e.reason=maximum?"r".repeat(128):"synthetic_known_zero";e.gameplay=maximum?"g".repeat(128):"not_observed";
  if(maximum)e.observationRefusal=new RecoveryChallengeLease.Refusal("first_interaction_tick",2_000_000_000L,40L,127,true);
  return e;
 }
 static List<RecoveryShortInputLedger.Entry> rows(int n,boolean maximum){var out=new ArrayList<RecoveryShortInputLedger.Entry>();for(int i=0;i<n;i++)out.add(settled(i,maximum));return out;}
 public static void main(String[] args)throws Exception{
  Path original=Path.of(args[0]),out=Path.of(args[1]);Files.createDirectories(out);byte[] originalBytes=Files.readAllBytes(original);
  check(sha(originalBytes).equals("ff0a3b42b6485fd70d876c11348d144321b3e845a55e46efc58551b131ab998a"),"F481 immutable input pin");
  check(RecoverySurvivalV6.ENABLED,"explicit V6 runtime");
  modeLimits(out);byteBounds(out);actual481(originalBytes,out);unknown481(originalBytes,out);fullFence(out);benchmark(out);
  check(Arrays.equals(originalBytes,Files.readAllBytes(original)),"original F481 remains exact");
  System.out.println("RecoveryCapacityV6Checks PASS assertions="+checks+"; offline copied/synthetic files only");
 }
 static void modeLimits(Path out)throws Exception{
  for(var mode:RecoveryShortInputLedger.CapacityMode.values()){
   int limit=mode==V6?1024:mode==RecoveryShortInputLedger.CapacityMode.MAINTENANCE_V5?512:256;
   check(mode.historyLimit==limit&&mode.maxFileBytes==(mode==V6?2_097_152:1_048_576),"explicit mode limits");
   var memory=new RecoveryShortInputChecks.Memory();var l=new RecoveryShortInputLedger(memory,()->1,false,mode);
   for(int i=0;i<limit;i++){var e=l.submit(fresh(l,"limit-"+i));l.rejectQueued(e,"synthetic_known_zero");}
   var last=memory.saved.getLast().request;check(l.diagnosticEntryCount()==limit&&!l.locked(),"limit accepted");
   check(l.submit(last).request.equals(last),"same-id duplicate at capacity");reject(()->l.submit(fresh(l,"overflow")),"native_history_full");
   check(l.diagnosticEntryCount()==limit&&!l.locked(),"full rejection nonmutating");
   Path file=out.resolve(mode+"-count.bin");try(var store=new RecoveryShortInputLedger.FileStore(file,mode)){
    store.write(rows(limit,false));check(store.read().size()==limit,"FileStore count limit accepted");byte[] before=Files.readAllBytes(file);
    ioReject(()->store.write(rows(limit+1,false)),"ledger_count");check(Arrays.equals(before,Files.readAllBytes(file)),"count overflow keeps journal");check(!Files.exists(file.resolveSibling(file.getFileName()+".tmp")),"count overflow creates no tmp");
    byte[] malformed=before.clone();ByteBuffer.wrap(malformed).putInt(4,limit+1);Files.write(file,malformed);ioReject(store::read,"ledger_count");
    check(new RecoveryShortInputLedger(store,()->1,true,mode).locked(),"count overflow startup fails closed");
   }
  }
  for(boolean maintenance:new boolean[]{false,true}){
   int limit=maintenance?512:256;var m=new RecoveryShortInputChecks.Memory();m.saved=rows(limit,false);var old=new RecoveryShortInputLedger(m,()->1,true,maintenance);
   check(old.diagnosticEntryCount()==limit&&!old.locked(),"boolean ctor old capacity");reject(()->old.submit(fresh(old,"old-overflow")),"native_history_full");
   Path file=out.resolve("boolean-"+maintenance+".bin");try(var store=new RecoveryShortInputLedger.FileStore(file,maintenance)){store.write(rows(limit,false));ioReject(()->store.write(rows(limit+1,false)),"ledger_count");}
  }
 }
 static void byteBounds(Path out)throws Exception{
  for(var mode:RecoveryShortInputLedger.CapacityMode.values()){
   Path file=out.resolve(mode+"-bytes.bin");try(var store=new RecoveryShortInputLedger.FileStore(file,mode)){
    var entries=rows(64,false);for(var e:entries)e.reason="";store.write(entries);int remaining=mode.maxFileBytes-Math.toIntExact(Files.size(file));
    for(var e:entries){int n=Math.min(60_000,remaining);e.reason="r".repeat(n);remaining-=n;}
    check(remaining==0,"construct exact byte-bound fixture");store.write(entries);byte[] exact=Files.readAllBytes(file);
    check(exact.length==mode.maxFileBytes&&store.read().size()==64,"exact inclusive byte bound");
    entries.getLast().gameplay+="x";ioReject(()->store.write(entries),"ledger_too_large");
    check(Arrays.equals(exact,Files.readAllBytes(file))&&!Files.exists(file.resolveSibling(file.getFileName()+".tmp")),"byte overflow rejected before replacing/tmp");
    Files.write(file,Arrays.copyOf(exact,exact.length+1));ioReject(store::read,"ledger_too_large");
    check(new RecoveryShortInputLedger(store,()->1,true,mode).locked(),"oversize startup unknown lock");
   }
  }
 }
 static JsonObject body(RecoveryShortInputLedger.Request r){return RecoveryShortInputLedger.survivalProfile(r.profile())?RecoverySurvivalV6Checks.json(r):RecoverySurvivalV6Checks.legacyJson(r);}
 static void actual481(byte[] original,Path out)throws Exception{
  Path file=out.resolve("actual481-grow1024.bin");Files.write(file,original);
  try(var store=new RecoveryShortInputLedger.FileStore(file,V6)){
   var rows=store.read();check(rows.size()==481&&rows.stream().allMatch(RecoveryShortInputLedger.Entry::settled),"actual F481 known");store.write(rows);check(Arrays.equals(original,Files.readAllBytes(file)),"F481 full binary exactroundtrip");
   var l=new RecoveryShortInputLedger(store,()->1,true,V6);RecoveryInteractionChecks.setLedger(l);
   try(var receipts=Files.newOutputStream(out.resolve("actual481-receipts.jsonl"));var digests=Files.newBufferedWriter(out.resolve("actual481-digests.txt"))){
    for(var old:rows){
     var status=NativeRecoveryShortInput.status(RecoveryInteractionV2Checks.query(old.request),old.request.profile());check(status.equals(NativeRecoveryShortInput.describe(old)),"actual old status exact");
     check(NativeRecoveryShortInput.start(body(old.request),old.request.profile()).equals(status),"actual exact duplicate original receipt");
     var changed=body(old.request);changed.addProperty("ttl_ms",old.request.ttlMs()==100?101:100);reject(()->NativeRecoveryShortInput.start(changed,old.request.profile()),"id_payload_mismatch");
     receipts.write(RecoveryShortInputCodec.encode(status));receipts.write('\n');digests.write(old.request.id()+" "+old.request.digest()+"\n");
    }
   }
   for(int i=481;i<1024;i++){var e=l.submit(fresh(l,"append-"+i));l.rejectQueued(e,"offline_capacity_known_zero");}
   check(store.read().size()==1024&&!l.locked()&&l.active()==null,"F481 grows to finite1024 without eviction");
   reject(()->l.submit(fresh(l,"append-1025")),"native_history_full");
   Path prefix=out.resolve("actual481-retained-prefix.bin");try(var old=new RecoveryShortInputLedger.FileStore(prefix,true)){old.write(store.read().subList(0,481));}check(Arrays.equals(original,Files.readAllBytes(prefix)),"retained481 exact bytes after543 appends");
  }
  try(var store=new RecoveryShortInputLedger.FileStore(file,V6)){var l=new RecoveryShortInputLedger(store,()->1,true,V6);check(!l.locked()&&l.diagnosticEntryCount()==1024,"1024 reopen known");}
  for(boolean oldMode:new boolean[]{false,true})try(var store=new RecoveryShortInputLedger.FileStore(file,oldMode)){ioReject(store::read,"ledger_count");}
 }
 static void unknown481(byte[] original,Path out)throws Exception{
  Path file=out.resolve("synthetic-old-unknown481.bin");Files.write(file,original);RecoveryShortInputLedger.Request unfinished;
  try(var store=new RecoveryShortInputLedger.FileStore(file,V6)){
   var rows=store.read();var e=rows.stream().filter(x->!RecoveryShortInputLedger.survivalProfile(x.request.profile())).findFirst().orElseThrow();unfinished=e.request;String digest=e.request.digest();e.state="ACTIVE";e.invalidated=false;e.released=false;e.effectFenced=true;store.write(rows);
   var l=new RecoveryShortInputLedger(store,()->1,true,V6);RecoveryInteractionChecks.setLedger(l);var found=l.lookup(e.request.id(),e.request.session(),e.request.ownerId(),e.request.generation());
   check(l.locked()&&found.state.equals("UNKNOWN")&&found.request.digest().equals(digest),"old profile unfinished globally locks V6 with digest preserved");
   var dto=NativeRecoveryShortInput.status(RecoveryInteractionV2Checks.query(e.request),e.request.profile());check(dto.get("state").getAsString().equals("UNKNOWN"),"old UNKNOWN status retrievable");
   check(NativeRecoveryShortInput.start(body(e.request),e.request.profile()).equals(dto),"same-ID old UNKNOWN duplicate readable no replay");
   reject(()->l.submit(fresh(l,"unknown-new-v6")),"native_unknown_lock");
   reject(()->l.lookup(e.request.id(),"different",e.request.ownerId(),e.request.generation()),"ticket_mismatch");reject(()->l.lookup(e.request.id(),e.request.session(),e.request.ownerId(),e.request.generation()+1),"ticket_mismatch");
   check(l.active()==null&&l.diagnosticEntryCount()==481,"unknown no active replay and no new history");
  }
  try(var store=new RecoveryShortInputLedger.FileStore(file,V6)){var l=new RecoveryShortInputLedger(store,()->1,true,V6);check(l.locked()&&l.submit(unfinished).state.equals("UNKNOWN"),"old UNKNOWN stays locked next restart");}
 }
 static void fullFence(Path out)throws Exception{
  Path file=out.resolve("synthetic1024-durable-fence.bin");try(var store=new RecoveryShortInputLedger.FileStore(file,V6)){
   store.write(rows(1023,true));var clock=new AtomicLong(1);var l=new RecoveryShortInputLedger(store,clock::get,true,V6);var e=l.submit(fresh(l,"last-slot-samples"));AtomicInteger raw=new AtomicInteger();
   reject(()->l.submit(fresh(l,"second-active")),"one_in_flight");
   for(int tick=1;tick<=8;tick++){final int before=tick-1;check(l.sample(e,tick,true,()->{try{var durable=store.read().getLast();check(durable.effectFenced&&!durable.released&&durable.applied==before,"every sample durably fenced with1024 records");raw.incrementAndGet();}catch(IOException err){throw new AssertionError(err);}}),"bounded sample");check(!l.sample(e,tick,true,raw::incrementAndGet),"same tick once");l.release(e,true,()->{},false,"samples_complete");}
   check(raw.get()==8&&e.settled()&&store.read().size()==1024&&!l.locked(),"full history cleanup persists normally");
  }
  // Inject impossible production metadata at the file byte bound: failed fence never writes input,
  // and a post-effect persistence overflow still permits exact physical release while keeping UNKNOWN.
  Path overflow=out.resolve("synthetic-overflow-cleanup.bin");try(var store=new RecoveryShortInputLedger.FileStore(overflow,V6)){
   var l=new RecoveryShortInputLedger(store,()->1,false,V6);var history=new ArrayList<RecoveryShortInputLedger.Entry>();
   for(int i=0;i<40;i++){var e=l.submit(fresh(l,"overflow-history-"+i));l.rejectQueued(e,"offline");history.add(e);}
   var e=l.submit(fresh(l,"overflow-active"));check(l.sample(e,1,true,()->{}),"effect before synthetic overflow");for(var old:history)old.reason="x".repeat(60_000);
   reject(()->l.sample(e,2,true,()->{throw new AssertionError("unfenced effect");}),"native_ledger_write_failed");check(l.locked()&&e.state.equals("UNKNOWN"),"oversized write fails globally closed");
   AtomicInteger release=new AtomicInteger();l.release(e,true,release::incrementAndGet,true,"cleanup");check(release.get()==1&&e.released&&l.locked(),"physical cleanup survives overflow without unlocking");check(Files.size(overflow)<V6.maxFileBytes&&store.read().getLast().effectFenced,"last durable unfinished journal recoverable");
  }
  try(var store=new RecoveryShortInputLedger.FileStore(overflow,V6)){check(new RecoveryShortInputLedger(store,()->1,true,V6).locked(),"overflow recovery never silently clears unfinished ticket");}
  check(RecoveryChallengeLease.windowMask(2_000_000_000L,40,true)==15&&RecoveryChallengeLease.windowMask(2_000_000_001L,40,true)==1&&RecoveryChallengeLease.windowMask(1,41,true)==7,"2sec40tick lease unchanged");
 }
 static void benchmark(Path out)throws Exception{
  JsonObject result=new JsonObject();result.addProperty("scope","TEMP-only actual native complete codec+force(true)+atomic rename+directory force; no game latency claim");
  for(boolean maximum:new boolean[]{false,true}){
   Path file=out.resolve("synthetic1024-benchmark-"+maximum+".bin");var entries=rows(1024,maximum);try(var store=new RecoveryShortInputLedger.FileStore(file,V6)){
    for(int i=0;i<3;i++)store.write(entries);var nanos=new long[20];for(int i=0;i<nanos.length;i++){long start=System.nanoTime();store.write(entries);nanos[i]=System.nanoTime()-start;}
    Arrays.sort(nanos);JsonObject j=new JsonObject();j.addProperty("records",1024);j.addProperty("bytes",Files.size(file));j.addProperty("min_ms",nanos[0]/1e6);j.addProperty("median_ms",(nanos[9]+nanos[10])/2e6);j.addProperty("max_ms",nanos[19]/1e6);j.addProperty("reopened_records",store.read().size());result.add(maximum?"max_request_fields_plus128char_diagnostics_and_full_refusal":"short_v6_move",j);
    check(Files.size(file)<V6.maxFileBytes&&store.read().size()==1024,"complete native codec1024 fits2MiB");
   }
  }
  Files.writeString(out.resolve("native1024-temp-benchmark.json"),new GsonBuilder().setPrettyPrinting().create().toJson(result)+"\n");System.out.println(result);
 }
}

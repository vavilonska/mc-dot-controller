package io.github.campione01.mineclientbridge;

import com.google.gson.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicLong;

/** Offline actual journal/codec/lease checks, no game or native gameplay capture. */
public final class RecoveryInteractionV3Checks {
 static final String V3=RecoveryShortInputLedger.INTERACTION_V3_PROFILE;static int checks;
 static void check(boolean b,String label){if(!b)throw new AssertionError(label);checks++;}
 static void rejects(Runnable r){try{r.run();throw new AssertionError("accepted");}catch(IllegalArgumentException|IllegalStateException expected){checks++;}}
 static RecoveryShortInputLedger.Request request(RecoveryShortInputLedger l,String id,String kind,int ttl){
  var op=new RecoveryShortInputLedger.Operation(kind,0,0,0,kind.equals("break_block")||kind.equals("select_hotbar")?"b".repeat(64):"",0,kind.equals("break_block")?65:0,0,kind.equals("break_block")?"UP":"",kind.equals("break_block")?"minecraft:nether_wart_block":"",V3,1,"e".repeat(64));
  return new RecoveryShortInputLedger.Request(id,l.session,l.owner()==null?RecoveryShortInputChecks.OWNER:l.owner(),l.nextGeneration(),RecoveryShortInputChecks.WORLD,RecoveryShortInputChecks.PLAYER,0,0,kind.equals("break_block")?32:1,false,ttl,RecoveryShortInputChecks.OBS,op);
 }
 static JsonObject json(RecoveryShortInputLedger.Request r){var j=RecoveryInteractionChecks.requestJson(r);j.addProperty("plan_version",1);j.addProperty("plan_sha256",r.operation().planSha256());return j;}
 static void write(Path p,JsonObject j)throws Exception{Files.write(p,RecoveryShortInputCodec.encode(j));}
 public static void main(String[] a)throws Exception{
  Path fixtures=Path.of(a[0]),out=Path.of(a[1]);Files.createDirectories(out);boundaries();history(fixtures,out);wire(out.resolve("wire-fixtures"));
  System.out.println("RecoveryInteractionV3Checks PASS assertions="+checks+"; offline synthetic lease/codec, not live effect");
 }
 static void boundaries()throws Exception{
  check(RecoveryChallengeLease.windowMask(251_000_000L,5)==15,"v3 age251 passes");
  check(RecoveryChallengeLease.windowMask(1_000_000_000L,20)==15,"v3 inclusive1000/20");
  check(RecoveryChallengeLease.windowMask(1_000_000_001L,20)==1,"v3 age1000plus rejects");
  check(RecoveryChallengeLease.windowMask(100,21)==7,"v3 tick21 rejects");
  check(RecoveryChallengeLease.windowMask(-1,0)==0&&RecoveryChallengeLease.windowMask(0,-1)==3,"negative clocks reject");
  for(long age: new long[]{251_000_000L,725_000_000L,1_000_000_000L})check(RecoveryChallengeLease.windowMask(age,5)==15,"only lease budget replay, not native facts");
  rejects(()->new RecoveryChallengeLease.Refusal("admit",1L,1L,1));rejects(()->new RecoveryChallengeLease.Refusal("admit",null,null,0));rejects(()->new RecoveryChallengeLease.Refusal("first_input",null,null,-1));
  AtomicLong now=new AtomicLong(100);var l=new RecoveryShortInputLedger(new RecoveryShortInputChecks.Memory(),now::get);RecoveryInteractionChecks.setLedger(l);
  var e=l.submit(request(l,"ttl-look","look",1000));long original=e.deadline;now.addAndGet(1_000_000_000L);
  check(RecoveryChallengeLease.windowMask(10,1)==15&&!l.sample(e,1,true,()->{throw new AssertionError("expired write");}),"valid ticket but absoluteTTL refuses");
  check(e.deadline==original&&e.settled()&&e.applied==0&&!e.effectFenced,"ttl knownzero nofence no renewal");
  var expiredBreak=l.submit(request(l,"ttl-break","break_block",2000));long breakDeadline=expiredBreak.deadline;now.addAndGet(2_000_000_000L);check(RecoveryChallengeLease.windowMask(1,0)==15&&!l.claimCall(expiredBreak,2,true)&&expiredBreak.settled()&&!expiredBreak.effectFenced&&expiredBreak.applied==0&&expiredBreak.deadline==breakDeadline,"break absolute2000 no renewal or fence");
  var stopped=l.submit(request(l,"stopped","break_block",2000));l.stop(stopped,"explicit_stop");check(!l.claimCall(stopped,2,true)&&stopped.applied==0&&!stopped.effectFenced,"stop wins valid lease");
  var replacement=l.submit(request(l,"replacement","look",1000));l.recordObservationRefusal(stopped,new RecoveryChallengeLease.Refusal("admit",1_000_000_001L,1L,1));check(stopped.observationRefusal==null&&replacement.observationRefusal==null,"old owner metadata cannot touch either ticket");
  check(!l.sample(stopped,3,true,()->{throw new AssertionError("old write");}),"oldticket never writes");l.rejectQueued(replacement,"offline_known_zero");
  var fenced=l.submit(request(l,"unknown","break_block",2000));check(l.claimCall(fenced,4,true),"fence claimed");l.failedCall(fenced);check(l.locked()&&fenced.state.equals("UNKNOWN"),"unknown stays locked");rejects(()->l.submit(request(l,"bypass","look",1000)));
 }
 static void history(Path fixtures,Path out)throws Exception{
  byte[] old=Files.readAllBytes(fixtures.resolve("native-97-entry-journal.bin"));Path file=out.resolve("mixed-journal.bin");Files.write(file,old);
  var actions=JsonParser.parseString(Files.readString(fixtures.resolve("public-ledger-97.json"))).getAsJsonObject().getAsJsonObject("actions");
  JsonArray statuses=new JsonArray();List<RecoveryShortInputLedger.Request> requests=new ArrayList<>();
  try(var store=new RecoveryShortInputLedger.FileStore(file)){
   var entries=store.read();check(entries.size()==97,"real97 count");store.write(entries);check(Arrays.equals(old,Files.readAllBytes(file)),"all97 fullbinary unchanged rewrite");
   var l=new RecoveryShortInputLedger(store,()->100,true);RecoveryInteractionChecks.setLedger(l);check(!l.locked()&&l.nextGeneration()==98,"97 owner/generation retained");
   for(var row:entries){var r=row.request;requests.add(r);var e=l.lookup(r.id(),r.session(),r.ownerId(),r.generation());var status=NativeRecoveryShortInput.describe(e);check(status.equals(actions.getAsJsonObject(r.id()).getAsJsonObject("terminal_native")),"97 exact terminal");check(!status.has("observation_refusal"),"no oldwire newkey");check(l.submit(r)==e,"oldduplicate nondispatch");check(NativeRecoveryShortInput.status(RecoveryInteractionV2Checks.query(r),r.profile()).equals(status),"storedprofile status");var stop=RecoveryInteractionV2Checks.query(r);stop.addProperty("schema_version",1);stop.addProperty("profile",r.profile());check(NativeRecoveryShortInput.stop(stop,r.profile()).equals(status),"oldstoredprofile stop");statuses.add(status);}
   var add=l.submit(request(l,"offline-v3-98","look",1000));l.recordObservationRefusal(add,new RecoveryChallengeLease.Refusal("admit",1_000_000_001L,1L,1));l.rejectQueued(add,"observation_stale_or_moved");
  }
  try(var store=new RecoveryShortInputLedger.FileStore(file)){
   var all=store.read();check(all.size()==98&&all.getLast().observationRefusal.predicateMask()==1,"v3 conditionaltail survives restart");
   Path back=out.resolve("old97-reencoded.bin");try(var oldstore=new RecoveryShortInputLedger.FileStore(back)){oldstore.write(all.subList(0,97));}check(Arrays.equals(old,Files.readAllBytes(back)),"append did not change any old97 encoded bytes");
   for(int i=0;i<97;i++)check(all.get(i).request.equals(requests.get(i))&&all.get(i).request.digest().equals(requests.get(i).digest()),"old97 request and digest exact");
  }
  var j=new JsonObject();j.add("statuses",statuses);write(out.resolve("legacy97-preserved-statuses.json"),j);
 }
 static void wire(Path out)throws Exception{
  Files.createDirectories(out);Path file=out.resolve("synthetic-v3-journal.bin");List<JsonObject> expected=new ArrayList<>();List<RecoveryShortInputLedger.Request> requests=new ArrayList<>();
  try(var store=new RecoveryShortInputLedger.FileStore(file)){
   var l=new RecoveryShortInputLedger(store,()->100);RecoveryInteractionChecks.setLedger(l);int id=0;
   for(String kind:List.of("move","look","select_hotbar","break_block")){
    var r=request(l,String.format("99999999-9999-4999-8999-%012d",++id),kind,kind.equals("break_block")?2000:1000);var body=json(r);check(NativeRecoveryShortInput.parseInteractionStart(RecoveryShortInputCodec.parse(RecoveryShortInputCodec.encode(body)),V3).equals(r),"v3 actualparser roundtrip");
    var e=l.submit(r);write(out.resolve(kind+"-request.json"),body);write(out.resolve(kind+"-queued.json"),NativeRecoveryShortInput.describe(e));l.rejectQueued(e,"offline_known_zero");write(out.resolve(kind+"-settled.json"),NativeRecoveryShortInput.describe(e));requests.add(r);expected.add(NativeRecoveryShortInput.describe(e));
   }
   for(String stage:List.of("admit","first_input","first_interaction_tick"))for(int mask:new int[]{0,1,3,7,15,31,63,127}){
    long age=mask==0?-1:mask==1?1_000_000_001L:100,delta=mask==3?-1:mask==7?21:1;
    var e=l.submit(request(l,String.format("99999999-9999-4999-8999-%012d",++id),stage.equals("first_input")?"move":"look",1000));l.recordObservationRefusal(e,new RecoveryChallengeLease.Refusal(stage,age,delta,mask));l.rejectQueued(e,"observation_stale_or_moved");write(out.resolve(stage+"-"+mask+"-request.json"),json(e.request));write(out.resolve(stage+"-"+mask+"-settled.json"),NativeRecoveryShortInput.describe(e));requests.add(e.request);expected.add(NativeRecoveryShortInput.describe(e));
   }
   for(int mask:new int[]{-1,-2}){var e=l.submit(request(l,String.format("99999999-9999-4999-8999-%012d",++id),"look",1000));l.recordObservationRefusal(e,new RecoveryChallengeLease.Refusal("admit",null,null,mask));l.rejectQueued(e,"observation_stale_or_moved");write(out.resolve("missing"+mask+"-request.json"),json(e.request));write(out.resolve("missing"+mask+"-settled.json"),NativeRecoveryShortInput.describe(e));requests.add(e.request);expected.add(NativeRecoveryShortInput.describe(e));}
   write(out.resolve("observe-no-world.json"),NativeRecoveryShortInput.describeNoWorld(false,true,V3));
  }
  try(var store=new RecoveryShortInputLedger.FileStore(file)){
   var l=new RecoveryShortInputLedger(store,()->200,true);RecoveryInteractionChecks.setLedger(l);
   for(int i=0;i<requests.size();i++){var r=requests.get(i);check(NativeRecoveryShortInput.status(RecoveryInteractionV2Checks.query(r),V3).equals(expected.get(i)),"nullable diagnostic productionpersistent roundtrip");}
  }
  var summary=new JsonObject();summary.addProperty("scope","synthetic predicates through actual codec/FileStore; no live native facts");summary.addProperty("records",requests.size());write(out.resolve("manifest.json"),summary);
 }
}

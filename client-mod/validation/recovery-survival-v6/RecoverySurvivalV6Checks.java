package io.github.campione01.mineclientbridge;

import com.google.gson.*;
import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.atomic.*;

/** Synthetic branch tests use the real parser, journal, lease, use bound and serializer. No game construction. */
public final class RecoverySurvivalV6Checks {
 static final String V6=RecoveryShortInputLedger.SURVIVAL_V6_PROFILE,FP="a".repeat(64),TARGET="66666666-6666-4666-8666-666666666666";
 static int checks,serial;
 static void check(boolean ok,String msg){if(!ok)throw new AssertionError(msg);checks++;}
 static void reject(Runnable r){try{r.run();throw new AssertionError("unexpected accept");}catch(IllegalArgumentException|IllegalStateException good){checks++;}}
 static RecoveryShortInputLedger.Request request(RecoveryShortInputLedger l,String kind){
  var survival=kind.equals("attack_blaze")?new RecoveryShortInputLedger.Survival(17,TARGET,"minecraft:blaze",0):kind.equals("consume_bread")?new RecoveryShortInputLedger.Survival(0,"","",40):null;
  var op=new RecoveryShortInputLedger.Operation(kind,0,0,kind.equals("select_hotbar")?8:0,Set.of("select_hotbar","attack_blaze","consume_bread").contains(kind)?FP:"",0,0,0,"","",V6,4,"b".repeat(64),"survival-stage",null,survival);
  return new RecoveryShortInputLedger.Request(new UUID(0,++serial).toString(),l.session,l.owner()==null?RecoveryShortInputChecks.OWNER:l.owner(),l.nextGeneration(),RecoveryShortInputChecks.WORLD,RecoveryShortInputChecks.PLAYER,kind.equals("move")?1:0,0,kind.equals("move")?8:1,kind.equals("move"),kind.equals("consume_bread")?4000:2000,RecoveryShortInputChecks.OBS,op);
 }
 static JsonObject json(RecoveryShortInputLedger.Request r){
  JsonObject j=RecoveryInteractionChecks.requestJson(r);j.addProperty("plan_version",4);j.addProperty("plan_sha256",r.operation().planSha256());j.addProperty("stage_id",r.operation().stageId());var v=r.operation().survival();
  if(r.kind().equals("attack_blaze")){j.addProperty("target_entity_id",v.entityId());j.addProperty("target_uuid",v.uuid());j.addProperty("target_type",v.type());j.addProperty("stack_fingerprint",r.operation().fingerprint());}
  if(r.kind().equals("consume_bread")){j.addProperty("stack_fingerprint",r.operation().fingerprint());j.addProperty("max_use_ticks",v.maxUseTicks());}return j;
 }
 static void write(Path p,JsonObject j)throws Exception{byte[] b=RecoveryShortInputCodec.encode(j);RecoveryNavigationV4.checkResponseBudget(b);Files.write(p,b);}
 public static void main(String[] args)throws Exception{
  if(args.length==1&&args[0].equals("--both")){reject(NativeRecoveryShortInput::open);System.out.println("V6 exclusive PASS "+checks);return;}
  if(args.length==1&&args[0].equals("--disabled")){check(!RecoverySurvivalV6.ENABLED&&NativeRecoveryShortInput.activeProfile().equals(RecoveryShortInputLedger.MAINTENANCE_V5_PROFILE),"old startup unchanged");check(!RecoverySurvivalV6.suppressDefaultUse(),"no old use blocker");System.out.println("V6 disabled PASS "+checks);return;}
  Path fixture=Path.of(args[0]),out=Path.of(args[1]);Files.createDirectories(out);
  check(RecoverySurvivalV6.ENABLED&&NativeRecoveryShortInput.activeProfile().equals(V6),"explicit V6");check(!RecoverySurvivalV6.ready(),"missing real mixin not ready");RecoverySurvivalV6.installed();check(RecoverySurvivalV6.ready(),"installed gate");check(RecoverySurvivalV6.MIN_ATTACK_STRENGTH==1F,"full actual cooldown");
  schema();lifecycle();history(fixture,out);wire(out.resolve("wire"));System.out.println("RecoverySurvivalV6Checks PASS checks="+checks+"; synthetic lifecycle/actual codec, no live item consumption or combat");
 }
 static void schema()throws Exception{
  var l=new RecoveryShortInputLedger(new RecoveryShortInputChecks.Memory(),()->1,false,true);
  for(String kind:List.of("move","look","select_hotbar","attack_blaze","consume_bread")){
   var r=request(l,kind);var j=json(r);var parsed=NativeRecoveryShortInput.parseInteractionStart(RecoveryShortInputCodec.parse(RecoveryShortInputCodec.encode(j)),V6);check(parsed.equals(r),"roundtrip "+kind);
   var extra=j.deepCopy();extra.addProperty("hand","OFF_HAND");reject(()->NativeRecoveryShortInput.parseInteractionStart(extra,V6));
   var old=j.deepCopy();old.addProperty("profile",RecoveryShortInputLedger.MAINTENANCE_V5_PROFILE);reject(()->NativeRecoveryShortInput.parseInteractionStart(old,RecoveryShortInputLedger.MAINTENANCE_V5_PROFILE));
   for(String key:List.of("stage_id","plan_sha256","observation_id")){var changed=j.deepCopy();changed.addProperty(key,key.equals("plan_sha256")?"c".repeat(64):"different");check(!NativeRecoveryShortInput.parseInteractionStart(changed,V6).digest().equals(r.digest()),"bound "+key);}
   int max=kind.equals("consume_bread")?4000:2000;for(int ttl:new int[]{99,100,max,max+1}){var body=j.deepCopy();body.addProperty("ttl_ms",ttl);if(ttl>=100&&ttl<=max)check(NativeRecoveryShortInput.parseInteractionStart(body,V6).ttlMs()==ttl,"ttl boundary");else reject(()->NativeRecoveryShortInput.parseInteractionStart(body,V6));}
  }
  var consume=json(request(l,"consume_bread"));for(int ticks:new int[]{0,1,32,40,41}){var j=consume.deepCopy();j.addProperty("max_use_ticks",ticks);if(ticks>=1&&ticks<=40)check(NativeRecoveryShortInput.parseInteractionStart(j,V6).operation().survival().maxUseTicks()==ticks,"use bound");else reject(()->NativeRecoveryShortInput.parseInteractionStart(j,V6));}
  var attack=json(request(l,"attack_blaze"));for(String key:List.of("target_uuid","target_type","stack_fingerprint")){var j=attack.deepCopy();j.addProperty(key,"wrong");reject(()->NativeRecoveryShortInput.parseInteractionStart(j,V6));}
  for(int id:new int[]{Integer.MIN_VALUE,-1,0,Integer.MAX_VALUE}){var j=attack.deepCopy();j.addProperty("target_entity_id",id);check(NativeRecoveryShortInput.parseInteractionStart(j,V6).operation().survival().entityId()==id,"native signed Entity id");}
  var select=json(request(l,"select_hotbar"));for(int slot=0;slot<9;slot++){var j=select.deepCopy();j.addProperty("slot",slot);if(slot==1||slot==8)check(NativeRecoveryShortInput.parseInteractionStart(j,V6).operation().slot()==slot,"exact slot");else reject(()->NativeRecoveryShortInput.parseInteractionStart(j,V6));}
  var legacy=RecoveryMaintenanceV5Checks.json(RecoveryMaintenanceV5Checks.request(l,"break_block"));legacy.addProperty("profile",V6);legacy.addProperty("plan_version",4);reject(()->NativeRecoveryShortInput.parseInteractionStart(legacy,V6));
 }
 static void lifecycle(){
  check(RecoverySurvivalV6.withinHit(8.99,9,3),"strict native reachable unobstructed");for(double distance:new double[]{9,9.00001,Double.NaN,Double.POSITIVE_INFINITY,-1})check(!RecoverySurvivalV6.withinHit(distance,9,3),"tie/reach/nonfinite denied");check(!RecoverySurvivalV6.withinHit(4,4,3),"block wins equal distance");check(!RecoverySurvivalV6.withinHit(9,16,3),"exact reach filtered as native closerThan");
  for(int slot:new int[]{0,1,8})for(boolean bread:new boolean[]{false,true})for(boolean axe:new boolean[]{false,true})for(boolean using:new boolean[]{false,true})for(boolean mining:new boolean[]{false,true})check(RecoverySurvivalV6.selectAllowed(slot,bread,axe,using,mining)==(!using&&!mining&&(slot==1&&bread||slot==8&&axe)),"select cannot take external use/mining");
  for(int bound:new int[]{1,32,40}){var use=new RecoverySurvivalV6.UseBound(100,bound);check(!use.blocksRestart(),"not started");use.start();check(use.blocksRestart(),"repeat gate held");reject(use::start);for(int i=0;i<bound;i++)check(!use.expired(100+i)&&use.blocksRestart(),"bounded held tick");check(use.expired(100+bound)&&use.expired(99),"bound and backwards clock");use.release();check(!use.blocksRestart(),"only release ends suppression");reject(use::start);}
  for(String kind:List.of("attack_blaze","consume_bread")){
   AtomicLong now=new AtomicLong(1);var memory=new RecoveryShortInputChecks.Memory();var l=new RecoveryShortInputLedger(memory,now::get,false,true);var r=request(l,kind);var e=l.submit(r);
   check(l.submit(r)==e,"sameid returns original");check(l.claimCall(e,100,true)&&memory.saved.getLast().effectFenced,"durable before topcall");l.completeCall(e);check(e.applied==1&&!e.released&&!e.settled(),"return does not imply release/eating success");
   check(!l.claimCall(e,101,true),"no second topcall");AtomicInteger releases=new AtomicInteger();l.release(e,true,releases::incrementAndGet,true,"synthetic_finished");check(releases.get()==1&&e.settled()&&e.applied==1,"known normal released one attempt");
   var expired=l.submit(request(l,kind));now.addAndGet(expired.request.ttlMs()*1_000_000L);check(!l.claimCall(expired,200,true)&&!expired.effectFenced&&expired.applied==0&&expired.settled(),"submit absolute deadline no renewal");
   var stopped=l.submit(request(l,kind));l.stop(stopped,"explicit_stop");check(!l.claimCall(stopped,201,true)&&!stopped.effectFenced,"stop before call");
   var current=l.submit(request(l,kind));AtomicInteger touched=new AtomicInteger();l.release(stopped,true,touched::incrementAndGet,true,"old");check(touched.get()==0&&l.active()==current,"old cannot clear replacement");l.stop(current,"synthetic_clear");
   var entered=l.submit(request(l,kind));check(l.claimCall(entered,202,true),"entered");l.stop(entered,"explicit_stop");check(entered.callRunning&&!entered.settled(),"entered call unwinds after stop");l.completeCall(entered);l.release(entered,true,()->{},true,"unwound");check(entered.settled()&&entered.applied==1&&!l.locked(),"stop normal unwind known");
   var failed=l.submit(request(l,kind));l.claimCall(failed,203,true);l.failedCall(failed);check(l.locked()&&failed.state.equals("UNKNOWN"),"entered throw unknown");reject(()->l.submit(request(l,kind)));l.release(failed,true,()->{},true,"physical_release");check(l.locked()&&failed.state.equals("UNKNOWN"),"release cannot wash unknown");
  }
  for(boolean stop:new boolean[]{false,true}){
   AtomicLong clock=new AtomicLong(1);var owner=new RecoveryShortInputLedger(new RecoveryShortInputChecks.Memory(),clock::get,false,true);var entry=owner.submit(request(owner,"consume_bread"));var bound=new RecoverySurvivalV6.UseBound(10,40);boolean[] key={false};check(owner.claimCall(entry,10,true),"in-call expiration entry");bound.start();if(stop)owner.stop(entry,"explicit_stop");else clock.addAndGet(4_000_000_000L);key[0]=true;owner.completeCall(entry);
   if(!owner.live(entry)){key[0]=false;owner.release(entry,true,()->{},true,"returned_invalidated");bound.release();}
   check(!key[0]&&entry.settled()&&entry.applied==1&&!bound.blocksRestart()&&!owner.locked(),"samecallback stop/TTL unwind clears ownedhold");
  }
  AtomicLong now=new AtomicLong(1);var l=new RecoveryShortInputLedger(new RecoveryShortInputChecks.Memory(),now::get,false,true);var b=json(request(l,"consume_bread"));b.addProperty("ttl_ms",1000);var e=l.submit(NativeRecoveryShortInput.parseInteractionStart(b,V6));now.addAndGet(1_000_000_000L);check(RecoveryChallengeLease.windowMask(1_500_000_000L,30,true)==15&&!l.claimCall(e,30,true)&&!e.effectFenced,"ticket valid but actionTTL dead");
  var l2=new RecoveryShortInputLedger(new RecoveryShortInputChecks.Memory(),()->1,false,true);var replace=l2.submit(request(l2,"consume_bread"));l2.claimCall(replace,1,true);l2.completeCall(replace);AtomicInteger untouched=new AtomicInteger();l2.release(replace,false,untouched::incrementAndGet,true,"replacement");check(untouched.get()==0&&l2.locked(),"uncertain owner does not clear replacement");
 }
 static JsonObject legacyJson(RecoveryShortInputLedger.Request r){
  if(r.operation()==null){JsonObject j=new JsonObject();j.addProperty("schema_version",1);j.addProperty("profile",r.profile());j.addProperty("id",r.id());j.addProperty("session",r.session());j.addProperty("owner_id",r.ownerId());j.addProperty("owner_generation",r.generation());j.addProperty("world_generation",r.world());j.addProperty("player_uuid",r.player());j.addProperty("forward",r.forward());j.addProperty("strafe",r.strafe());j.addProperty("samples",r.samples());j.addProperty("jump_first",r.jumpFirst());j.addProperty("ttl_ms",r.ttlMs());j.addProperty("observation_id",r.observationId());return j;}
  JsonObject j=RecoveryInteractionChecks.requestJson(r);var o=r.operation();if(RecoveryShortInputLedger.planProfile(r.profile())){j.addProperty("plan_version",o.planVersion());j.addProperty("plan_sha256",o.planSha256());}if(RecoveryShortInputLedger.geometryProfile(r.profile()))j.addProperty("stage_id",o.stageId());if(o.placement()!=null){j=RecoveryMaintenanceV5Checks.json(r);}return j;
 }
 static void history(Path fixture,Path out)throws Exception{
  byte[] original=Files.readAllBytes(fixture);Path p=out.resolve("actual338-roundtrip.bin");Files.write(p,original);
  try(var store=new RecoveryShortInputLedger.FileStore(p,true)){var rows=store.read();check(rows.size()==338&&rows.stream().allMatch(RecoveryShortInputLedger.Entry::settled),"actual mixed338 allknown");store.write(rows);check(Arrays.equals(original,Files.readAllBytes(p)),"338 exact original bytes");var l=new RecoveryShortInputLedger(store,()->1,true,true);RecoveryInteractionChecks.setLedger(l);for(var old:rows){check(NativeRecoveryShortInput.status(RecoveryInteractionV2Checks.query(old.request),RecoveryShortInputLedger.geometryProfile(old.request.profile())?RecoveryShortInputLedger.INTERACTION_V3_PROFILE:old.request.profile()).get("id").getAsString().equals(old.request.id()),"stored oldprofile readable sharedroot");var body=legacyJson(old.request);check(NativeRecoveryShortInput.start(body,old.request.profile()).equals(NativeRecoveryShortInput.describe(old)),"old exact duplicate returns original no enqueue");var bad=body.deepCopy();bad.addProperty("ttl_ms",old.request.ttlMs()==100?101:100);reject(()->NativeRecoveryShortInput.start(bad,old.request.profile()));var fresh=body.deepCopy();fresh.addProperty("id",UUID.randomUUID().toString());reject(()->NativeRecoveryShortInput.start(fresh,old.request.profile()));}var e=l.submit(request(l,"consume_bread"));l.rejectQueued(e,"synthetic_known0");check(store.read().size()==339,"append survives338");Path prefix=out.resolve("old338-prefix.bin");try(var old=new RecoveryShortInputLedger.FileStore(prefix,true)){old.write(store.read().subList(0,338));}check(Arrays.equals(original,Files.readAllBytes(prefix)),"conditional v6 bytes preserve old338");}
 }
 static void wire(Path out)throws Exception{
  Files.createDirectories(out);var l=new RecoveryShortInputLedger(new RecoveryShortInputChecks.Memory(),()->1,false,true);RecoveryInteractionChecks.setLedger(l);JsonArray cases=new JsonArray();
  for(String kind:List.of("move","look","select_hotbar","attack_blaze","consume_bread")){var r=request(l,kind);var e=l.submit(r);write(out.resolve(kind+"-request.json"),json(r));write(out.resolve(kind+"-queued.json"),NativeRecoveryShortInput.describe(e));l.rejectQueued(e,"offline_known_zero");write(out.resolve(kind+"-settled.json"),NativeRecoveryShortInput.describe(e));cases.add(kind);}
  for(String result:List.of("success","success_no_item_used","consume","consume_partial","pass","fail","attack_returned_observe_outcome")){
   var r=request(l,result.startsWith("attack_")?"attack_blaze":"consume_bread");var e=l.submit(r);l.claimCall(e,serial,true);e.gameplay=result.startsWith("attack_")?result:"use_"+result;l.completeCall(e);write(out.resolve(result+"-request.json"),json(r));write(out.resolve(result+"-active.json"),NativeRecoveryShortInput.describe(e));l.stop(e,"offline_normal_return");l.release(e,true,()->{},true,"offline_release");write(out.resolve(result+"-settled.json"),NativeRecoveryShortInput.describe(e));cases.add(result);
  }
  for(String state:List.of("ACTIVE","STOPPING","UNKNOWN")){
   l=new RecoveryShortInputLedger(new RecoveryShortInputChecks.Memory(),()->1,false,true);RecoveryInteractionChecks.setLedger(l);var r=request(l,"consume_bread");var e=l.submit(r);l.claimCall(e,serial,true);e.gameplay="use_fail";if(state.equals("STOPPING"))l.stop(e,"explicit_stop");if(state.equals("UNKNOWN"))l.unknown(e,"offline_uncertain");String n="cross-lock-"+state;write(out.resolve(n+"-request.json"),json(r));write(out.resolve(n+"-status.json"),NativeRecoveryShortInput.describe(e));cases.add(n);
  }
  l=new RecoveryShortInputLedger(new RecoveryShortInputChecks.Memory(),()->1,false,true);RecoveryInteractionChecks.setLedger(l);write(out.resolve("observe-no-world.json"),NativeRecoveryShortInput.describeNoWorld(false,true,V6));var j=new JsonObject();j.addProperty("scope","synthetic inputs through production parser/ledger/codec; no live capture/consumption/attack");j.add("cases",cases);write(out.resolve("manifest.json"),j);
 }
}

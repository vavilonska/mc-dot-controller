package io.github.campione01.mineclientbridge;

import com.google.gson.*;
import java.nio.file.*;
import java.io.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicLong;
import net.minecraft.core.BlockPos;
import net.minecraft.world.phys.AABB;

/** Synthetic inputs through actual production parser, durable ledger, serializer and dynamic witness counter.
 * No game bootstrap, entities, worlds, packets, inputs, or live network. */
public final class RecoveryMaintenanceV5Checks {
 static final String V5=RecoveryShortInputLedger.MAINTENANCE_V5_PROFILE,V3=RecoveryShortInputLedger.INTERACTION_V3_PROFILE,FP="a".repeat(64);
 static int checks,serial;
 static void check(boolean b,String why){if(!b)throw new AssertionError(why);checks++;}
 static void reject(Runnable r){try{r.run();throw new AssertionError("unexpected accept");}catch(IllegalArgumentException|IllegalStateException good){checks++;}}
 static RecoveryShortInputLedger.Request request(RecoveryShortInputLedger l,String kind){
  var p=kind.equals("place_block")?new RecoveryShortInputLedger.Placement(-166,54,10,-166,53,10,"minecraft:andesite","UP",-165.5,54,10.5,"minecraft:andesite"):null;
  var o=new RecoveryShortInputLedger.Operation(kind,0,0,kind.equals("select_hotbar")?2:0,Set.of("break_block","select_hotbar","place_block").contains(kind)?FP:"",kind.equals("break_block")?-166:0,kind.equals("break_block")?53:0,kind.equals("break_block")?10:0,kind.equals("break_block")?"UP":"",kind.equals("break_block")?"minecraft:tnt":"",V5,3,"b".repeat(64),"south-cycle",p);
  return new RecoveryShortInputLedger.Request(new UUID(0,++serial).toString(),l.session,l.owner()==null?RecoveryShortInputChecks.OWNER:l.owner(),l.nextGeneration(),RecoveryShortInputChecks.WORLD,RecoveryShortInputChecks.PLAYER,kind.equals("move")?1:0,0,kind.equals("move")?8:1,kind.equals("move"),2000,RecoveryShortInputChecks.OBS,o);
 }
 static JsonObject json(RecoveryShortInputLedger.Request r){var j=RecoveryInteractionChecks.requestJson(r);var o=r.operation();j.addProperty("plan_version",3);j.addProperty("plan_sha256",o.planSha256());j.addProperty("stage_id",o.stageId());if(o.placement()!=null){var p=o.placement();j.addProperty("x",p.x());j.addProperty("y",p.y());j.addProperty("z",p.z());j.addProperty("anchor_x",p.anchorX());j.addProperty("anchor_y",p.anchorY());j.addProperty("anchor_z",p.anchorZ());j.addProperty("anchor_block_id",p.anchorBlock());j.addProperty("face",p.face());j.addProperty("hit_x",p.hitX());j.addProperty("hit_y",p.hitY());j.addProperty("hit_z",p.hitZ());j.addProperty("item_id",p.itemId());j.addProperty("stack_fingerprint",o.fingerprint());}return j;}
 static void write(Path path,JsonObject j)throws Exception{byte[] bytes=RecoveryShortInputCodec.encode(j);RecoveryNavigationV4.checkResponseBudget(bytes);Files.write(path,bytes);}
 public static void main(String[] args)throws Exception{
  if(args.length==1&&args[0].equals("--disabled")){check(!RecoveryMaintenanceV5.ENABLED&&NativeRecoveryShortInput.activeProfile().equals(V3),"v5startup off oldprofile retained");System.out.println("Maintenance disabled PASS checks="+checks);return;}
  if(args.length==1&&args[0].equals("--both-flags")){reject(NativeRecoveryShortInput::open);System.out.println("Maintenance exclusive flags PASS checks="+checks);return;}
  if(args.length==1&&args[0].equals("--ui-v5")){check(RecoveryDeathScreenUi.enabled(),"v5 explicit onceUI enabled");System.out.println("Maintenance UI flags PASS checks="+checks);return;}
  Path fixtures=Path.of(args[0]),out=Path.of(args[1]);Files.createDirectories(out);check(RecoveryMaintenanceV5.ENABLED&&NativeRecoveryShortInput.activeProfile().equals(V5),"explicit enabledv5");schema();lease();primed();witness();calls();limits(out);history(fixtures,out);wire(out.resolve("wire"));
  System.out.println("RecoveryMaintenanceV5Checks PASS checks="+checks+"; synthetic offline actual parser/ledger/codec, not live placement");
 }
 static void schema()throws Exception{
  var l=new RecoveryShortInputLedger(new RecoveryShortInputChecks.Memory(),()->1,false,true);
  for(String kind:List.of("move","look","select_hotbar","break_block","place_block")){
   var r=request(l,kind);var j=json(r);check(NativeRecoveryShortInput.parseInteractionStart(RecoveryShortInputCodec.parse(RecoveryShortInputCodec.encode(j)),V5).equals(r),"actualcodec "+kind);
   var bad=j.deepCopy();bad.addProperty("extra",1);reject(()->NativeRecoveryShortInput.parseInteractionStart(bad,V5));
   var old=j.deepCopy();old.addProperty("profile",RecoveryShortInputLedger.NAVIGATION_V4_PROFILE);reject(()->NativeRecoveryShortInput.parseInteractionStart(old,RecoveryShortInputLedger.NAVIGATION_V4_PROFILE));
   var stage=j.deepCopy();stage.addProperty("stage_id","different");check(!NativeRecoveryShortInput.parseInteractionStart(stage,V5).digest().equals(r.digest()),"stage bound");
  }
  var tnt=request(l,"break_block");var badTnt=json(tnt);badTnt.addProperty("max_calls",32);reject(()->NativeRecoveryShortInput.parseInteractionStart(badTnt,V5));
  byte[] damaged=RecoveryShortInputLedger.encodeRequest(tnt);java.nio.ByteBuffer.wrap(damaged,damaged.length-4,4).putInt(32);var decoder=RecoveryShortInputLedger.class.getDeclaredMethod("readInteractionRequest",DataInputStream.class);decoder.setAccessible(true);
  try{decoder.invoke(null,new DataInputStream(new ByteArrayInputStream(damaged)));throw new AssertionError("reopened multi-call TNT");}catch(java.lang.reflect.InvocationTargetException good){check(good.getCause() instanceof IllegalArgumentException,"actual persisted decoder rejects multi TNT");}
  var cut=badTnt.deepCopy();cut.addProperty("block_id","minecraft:cut_sandstone");check(NativeRecoveryShortInput.parseInteractionStart(cut,V5).samples()==32,"service block keeps32bound");
  var r=request(l,"place_block");var body=json(r);
  for(String key:List.of("item_id","anchor_block_id","face","stack_fingerprint")){var b=body.deepCopy();b.addProperty(key,"forbidden");reject(()->NativeRecoveryShortInput.parseInteractionStart(b,V5));}
  for(String key:List.of("x","anchor_y","hit_z")){var b=body.deepCopy();b.addProperty(key,Double.MAX_VALUE);reject(()->NativeRecoveryShortInput.parseInteractionStart(b,V5));}
  var hand=body.deepCopy();hand.addProperty("hand","OFF_HAND");reject(()->NativeRecoveryShortInput.parseInteractionStart(hand,V5));
  var b=body.deepCopy();b.addProperty("hit_x",-165.50005);check(!NativeRecoveryShortInput.parseInteractionStart(b,V5).digest().equals(r.digest()),"actualdouble digest not coldpoint rounding");
  try(var d=new DataInputStream(new ByteArrayInputStream(RecoveryShortInputLedger.encodeRequest(r)))){
   check(d.readUTF().equals(V5)&&d.readUTF().equals("place_block"),"binaryprofilekind");for(int i=0;i<3;i++)d.readUTF();d.readLong();d.readUTF();d.readUTF();d.readInt();d.readUTF();check(d.readInt()==3&&d.readUTF().equals(r.operation().planSha256())&&d.readUTF().equals("south-cycle"),"PLAN3 stage order");
   check(d.readInt()==-166&&d.readInt()==54&&d.readInt()==10&&d.readInt()==-166&&d.readInt()==53&&d.readInt()==10,"targetanchororder");check(d.readUTF().equals("minecraft:andesite")&&d.readUTF().equals("UP")&&d.readDouble()==-165.5&&d.readDouble()==54&&d.readDouble()==10.5&&d.readUTF().equals("minecraft:andesite")&&d.readUTF().equals(FP)&&d.available()==0,"placebodyorder");
  }
  check(RecoveryMaintenanceV5.eyeJson(new net.minecraft.world.phys.Vec3(1,2,3)).getAsJsonObject().keySet().equals(Set.of("x","y","z")),"pure eye DTO");for(double v:new double[]{Double.NaN,Double.POSITIVE_INFINITY,30_000_001})check(RecoveryMaintenanceV5.eyeJson(new net.minecraft.world.phys.Vec3(1,v,3)).isJsonNull(),"eye incomplete not invented");
  check(RecoveryMaintenanceV5.protectedCell(new AABB(Double.NaN,0,0,1,2,3),new BlockPos(0,0,0)),"malformed bbox denies break");
  var box=new AABB(-166.8,55,-166.2,-166.2,56.8,-165.6);check(RecoveryMaintenanceV5.protectedCell(box,new BlockPos(-167,53,-166)),"supportcolumn forbidden");check(RecoveryMaintenanceV5.protectedCell(box,new BlockPos(-167,56,-166)),"body forbidden");check(!RecoveryMaintenanceV5.protectedCell(box,new BlockPos(-166,54,-166)),"adjacentcolumn permitted");check(!RecoveryMaintenanceV5.protectedCell(box,new BlockPos(-167,57,-166)),"abovebody notsupport");
 }
 static void lease()throws Exception{
  for(long age:new long[]{-1,0,1_000_000_000L,1_000_000_001L,2_000_000_000L,2_000_000_001L})for(long tick:new long[]{-1,0,20,21,40,41}){
   int expected=age<0?0:age>2_000_000_000L?1:tick<0?3:tick>40?7:15;check(RecoveryChallengeLease.windowMask(age,tick,true)==expected,"v5 2s40 inclusive boundary");
   int legacy=age<0?0:age>1_000_000_000L?1:tick<0?3:tick>20?7:15;check(RecoveryChallengeLease.windowMask(age,tick)==legacy,"old1s20 unchanged");
  }
  var v5=new RecoveryChallengeLease.Refusal("admit",1_500_000_000L,30L,31,true);reject(()->new RecoveryChallengeLease.Refusal("admit",1_500_000_000L,30L,31));
  ByteArrayOutputStream a=new ByteArrayOutputStream();RecoveryChallengeLease.write(new DataOutputStream(a),v5);check(RecoveryChallengeLease.read(new DataInputStream(new ByteArrayInputStream(a.toByteArray())),true).equals(v5),"v5 diagnostic read uses storedprofile");
  try{RecoveryChallengeLease.read(new DataInputStream(new ByteArrayInputStream(a.toByteArray())));throw new AssertionError("oldprofile widened");}catch(IOException expected){checks++;}
  var old=new RecoveryChallengeLease.Refusal("admit",10L,1L,31);var same=new RecoveryChallengeLease.Refusal("admit",10L,1L,31,true);a.reset();var b=new ByteArrayOutputStream();RecoveryChallengeLease.write(new DataOutputStream(a),old);RecoveryChallengeLease.write(new DataOutputStream(b),same);check(Arrays.equals(a.toByteArray(),b.toByteArray()),"memoryonly flag never serialized");
  AtomicLong now=new AtomicLong(1);var l=new RecoveryShortInputLedger(new RecoveryShortInputChecks.Memory(),now::get,false,true);var base=request(l,"look");var shortTtl=new RecoveryShortInputLedger.Request(base.id(),base.session(),base.ownerId(),base.generation(),base.world(),base.player(),0,0,1,false,1000,base.observationId(),base.operation());var e=l.submit(shortTtl);now.addAndGet(1_000_000_000L);check(RecoveryChallengeLease.windowMask(1_500_000_000L,30,true)==15,"ticket can still be valid at ttl expiry");check(!l.sample(e,30,true,()->{throw new AssertionError("late look write");})&&e.applied==0&&!e.effectFenced&&e.settled(),"absolute submitTTL beats valid2s ticket");
 }
 static void primed(){
  Class<?> nativeClass=net.minecraft.world.entity.item.PrimedTnt.class;
  for(int n:List.of(0,1,32,33,1000)){var facts=RecoveryMaintenanceV5.classifyPrimed(Collections.nCopies(n,nativeClass));check(facts.count()==Math.min(n,32)&&facts.complete()==(n<=32)&&facts.overflow()==(n>32),"bounded primed count "+n);check(facts.clear()==(n==0),"clear only complete0");}
  var unknown=RecoveryMaintenanceV5.classifyPrimed(List.of(Object.class));check(unknown.count()==0&&!unknown.complete()&&!unknown.overflow()&&!unknown.clear(),"unknown class is not clean0");
  check(RecoveryMaintenanceV5.classifyPrimed(List.of(nativeClass,Object.class)).count()==1,"known count retained beside unknown");
 }
 static void witness(){
  for(int effects=0;effects<=1;effects++)for(int packets=0;packets<=1;packets++){
   var w=new RecoveryMaintenancePlacementDispatch.Witness();check(!w.returned(),"noentry false");w.enter();if(effects==1)w.effect();Object p=new Object();if(packets==1){w.packet(p);check(!w.returned(),"unsentpacket unknown");w.send(p);}check(w.returned()==(effects<=packets),"native branch combinations 00 01 11 known;10 missing prediction unknown");reject(w::enter);if(effects==1)reject(w::effect);if(packets==1){reject(()->w.packet(new Object()));reject(()->w.send(p));}
  }
  var w=new RecoveryMaintenancePlacementDispatch.Witness();reject(w::effect);var p=new RecoveryMaintenancePlacementDispatch.Witness();p.enter();Object o=new Object();p.packet(o);reject(()->p.send(new Object()));
 }
 static void calls(){
  AtomicLong now=new AtomicLong(1);var memory=new RecoveryShortInputChecks.Memory();var l=new RecoveryShortInputLedger(memory,now::get,false,true);
  var e=l.submit(request(l,"place_block"));check(l.claimCall(e,1,true)&&memory.saved.getLast().effectFenced,"durable BEFORE use");l.stop(e,"explicit_stop");check(e.callRunning&&!e.settled(),"stop permits entered unwind");l.completeCall(e);l.release(e,true,()->{},true,"returned");check(e.settled()&&e.applied==1&&!l.locked(),"known entered stop");
  var ttl=l.submit(request(l,"place_block"));now.addAndGet(2_000_000_000L);check(!l.claimCall(ttl,2,true)&&ttl.settled()&&!ttl.effectFenced,"absoluteTTL no use");
  var stop=l.submit(request(l,"place_block"));l.stop(stop,"stop");check(!l.claimCall(stop,3,true)&&!stop.effectFenced,"stop before claim");var replace=l.submit(request(l,"place_block"));check(!l.claimCall(stop,4,true)&&l.live(replace),"oldticket cannot affect replacement");
  check(l.claimCall(replace,5,true),"throw entry");l.failedCall(replace);check(l.locked()&&replace.state.equals("UNKNOWN"),"throw unknown retained");reject(()->l.submit(request(l,"look")));
 }
 static void limits(Path out)throws Exception{
  for(boolean v5:List.of(false,true)){
   var l=new RecoveryShortInputLedger(new RecoveryShortInputChecks.Memory(),()->1,false,v5);int max=v5?512:256;
   for(int i=0;i<max;i++){var e=l.submit(request(l,"look"));l.rejectQueued(e,"offline_zero");}
   check(l.diagnosticEntryCount()==max,"explicit history limit");reject(()->l.submit(request(l,"look")));
  }
  Path file=out.resolve("synthetic512.bin");try(var store=new RecoveryShortInputLedger.FileStore(file,true)){var l=new RecoveryShortInputLedger(store,()->1,false,true);for(int i=0;i<512;i++){var e=l.submit(request(l,"look"));l.rejectQueued(e,"offline_zero");}check(store.read().size()==512,"512 actualread");check(Files.size(file)<1_048_576,"native1MiB enough");}
  try(var old=new RecoveryShortInputLedger.FileStore(file)){try{old.read();throw new AssertionError("old mode read over256");}catch(IOException good){checks++;}}
 }
 static void history(Path fixtures,Path out)throws Exception{
  byte[] original=Files.readAllBytes(fixtures.resolve("native-101-entry-journal.bin"));Path file=out.resolve("history101.bin");Files.write(file,original);
  try(var store=new RecoveryShortInputLedger.FileStore(file,true)){var rows=store.read();check(rows.size()==101,"actual101");store.write(rows);check(Arrays.equals(original,Files.readAllBytes(file)),"actual101 exactbytes");var l=new RecoveryShortInputLedger(store,()->1,true,true);RecoveryInteractionChecks.setLedger(l);var e=l.submit(request(l,"place_block"));l.rejectQueued(e,"offline_zero");var dto=NativeRecoveryShortInput.describe(e);check(dto.get("stage_id").getAsString().equals("south-cycle"),"storedstage");check(NativeRecoveryShortInput.status(RecoveryInteractionV2Checks.query(e.request),V3).equals(dto),"sharedrootstatus");}
  try(var store=new RecoveryShortInputLedger.FileStore(file,true)){var rows=store.read();check(rows.size()==102&&rows.getLast().request.operation().placement()!=null,"place persisted");Path old=out.resolve("original101-reencoded.bin");try(var x=new RecoveryShortInputLedger.FileStore(old)){x.write(rows.subList(0,101));}check(Arrays.equals(original,Files.readAllBytes(old)),"conditionaltail preserves101");}
 }
 static void wire(Path out)throws Exception{
  Files.createDirectories(out);var l=new RecoveryShortInputLedger(new RecoveryShortInputChecks.Memory(),()->1,false,true);RecoveryInteractionChecks.setLedger(l);JsonArray cases=new JsonArray();
  for(String kind:List.of("move","look","select_hotbar","break_block","place_block")){
   var r=request(l,kind);var e=l.submit(r);write(out.resolve(kind+"-request.json"),json(r));write(out.resolve(kind+"-queued.json"),NativeRecoveryShortInput.describe(e));l.rejectQueued(e,"offline_known_zero");write(out.resolve(kind+"-settled.json"),NativeRecoveryShortInput.describe(e));cases.add(kind);
  }
  for(String result:List.of("success","success_no_item_used","consume","consume_partial","pass","fail"))for(String target:List.of("placed","unchanged","other")){
   var r=request(l,"place_block");var e=l.submit(r);l.claimCall(e,serial,true);l.completeCall(e);e.gameplay="place_"+result+"_target_"+target;l.stop(e,"offline_normal_return");l.release(e,true,()->{},true,"offline_normal_return");String n="place-"+result+"-"+target;write(out.resolve(n+"-request.json"),json(r));write(out.resolve(n+"-settled.json"),NativeRecoveryShortInput.describe(e));cases.add(n);
  }
  for(String state:List.of("ACTIVE","STOPPING","UNKNOWN")){
   var r=request(l,"place_block");var e=l.submit(r);l.claimCall(e,serial,true);e.gameplay="place_fail_target_unchanged";
   if(state.equals("STOPPING"))l.stop(e,"explicit_stop");if(state.equals("UNKNOWN"))l.unknown(e,"synthetic_cross_lock_unknown");
   String name="window-"+state.toLowerCase(Locale.ROOT);write(out.resolve(name+"-request.json"),json(r));write(out.resolve(name+"-status.json"),NativeRecoveryShortInput.describe(e));cases.add(name);
   // New independent synthetic journal; never clear an UNKNOWN ledger to manufacture another action.
   l=new RecoveryShortInputLedger(new RecoveryShortInputChecks.Memory(),()->1,false,true);RecoveryInteractionChecks.setLedger(l);
  }
  for(int mode=0;mode<3;mode++){
   var r=request(l,"look");var e=l.submit(r);var refusal=mode==0?new RecoveryChallengeLease.Refusal("admit",2_000_000_001L,1L,1,true):mode==1?new RecoveryChallengeLease.Refusal("first_interaction_tick",1_500_000_000L,41L,7,true):new RecoveryChallengeLease.Refusal("first_interaction_tick",1_500_000_000L,30L,31,true);
   l.recordObservationRefusal(e,refusal);l.rejectQueued(e,"observation_stale_or_moved");String name="v5-lease-"+mode;write(out.resolve(name+"-request.json"),json(r));write(out.resolve(name+"-settled.json"),NativeRecoveryShortInput.describe(e));cases.add(name);
   Path f=out.resolve(name+"-journal.bin");try(var store=new RecoveryShortInputLedger.FileStore(f,true)){store.write(List.of(e));check(store.read().getFirst().observationRefusal.equals(refusal),"actual v5 diagnostic file roundtrip");}
  }
  write(out.resolve("observe-no-world.json"),NativeRecoveryShortInput.describeNoWorld(false,true,V5));JsonObject manifest=new JsonObject();manifest.addProperty("scope","synthetic DTOs through actual production codec, not native game capture");manifest.add("cases",cases);write(out.resolve("manifest.json"),manifest);
 }
}

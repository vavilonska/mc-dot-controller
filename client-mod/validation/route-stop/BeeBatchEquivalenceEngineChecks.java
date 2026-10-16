package io.github.campione01.mineclientbridge;
import com.google.gson.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.world.entity.MoverType;
import net.minecraft.world.phys.Vec3;
import static io.github.campione01.mineclientbridge.BeeRouteEngineChecks.*;
import static io.github.campione01.mineclientbridge.LocalSegmentEngineChecks.sample;
import static io.github.campione01.mineclientbridge.LocalSegmentEngineChecks.writeFixture;
/** Production immutable Store/fence and controller; prescribed synthetic readers, no game or world execution. */
public final class BeeBatchEquivalenceEngineChecks {
 static int assertions;static JsonArray cases=new JsonArray();static Path out;
 static void check(boolean b,String why){assertions++;if(!b)throw new AssertionError(why);}
 static void scenario(String name,Runnable r){r.run();cases.add(name);System.out.println("PASS "+name);}
 static Minecraft env(){var mc=BeeRouteEngineChecks.env();WorldGeneration.value="00000000-0000-4000-8000-000000000001";return mc;}
 static B start(){var mc=env();var b=bee(mc);var source=server(b);publish(mc,source);return new B(admit(mc),b,source);}
 static ScopedLocalSegmentPolicy.Bounds route(){return ScopedLocalSegmentPolicy.route(.5,1,.5,List.of(new ScopedLocalSegmentPolicy.Point(1.5,1,.5)));}
 static NativeLivingSnapshot.Row timed(NativeLivingSnapshot.Row r,long tick,long nano){return new NativeLivingSnapshot.Row(r.uuid(),r.entityId(),r.type(),tick,nano,r.alive(),r.aggressive(),r.target(),r.bee(),r.rabbit(),r.beeRoute(),r.beeRouteReadStatus());}
 static NativeLivingSnapshot.Row changed(NativeLivingSnapshot.Row r,String kind){
  var bee=r.bee();var ext=r.beeRoute();
  return new NativeLivingSnapshot.Row(kind.equals("uuid")?UUID.randomUUID().toString():r.uuid(),kind.equals("id")?r.entityId()+1:r.entityId(),kind.equals("type")?"minecraft:sheep":r.type(),r.tick(),System.nanoTime(),
   !kind.equals("dead"),kind.equals("aggressive"),kind.equals("target")?new NativeLivingSnapshot.Target(UUID.randomUUID().toString(),999,"minecraft:player"):null,
   kind.equals("bee_missing")?null:new NativeLivingSnapshot.BeeState(kind.equals("angry"),kind.equals("anger")?1:0,kind.equals("persistent_target")?UUID.randomUUID().toString():null),
   kind.equals("rabbit")?new NativeLivingSnapshot.RabbitState(0,false,true):null,
   kind.equals("extension_missing")?null:new NativeLivingSnapshot.BeeRouteState(kind.equals("server_class")?"untrusted.Bee":ext.serverClass(),kind.equals("stung"),kind.equals("nectar"),kind.equals("hive")?new NativeLivingSnapshot.BeePosition(1,2,3):null,kind.equals("flower")?new NativeLivingSnapshot.BeePosition(4,5,6):null),
   kind.equals("read_status")?"not_recorded":r.beeRouteReadStatus());
 }
 static void publishBatch(NativeLivingObservation.Frame f,Map<String,NativeLivingSnapshot.Row> rows,boolean complete,int inspected,Object serverLevel,String dimension){
  check(NativeLivingObservation.STORE.publish(new NativeLivingSnapshot.Batch(f.context(),serverLevel,dimension,rows,complete,inspected,complete?"observed":"inspection_limit")),"publication accepted in expected context");
 }
 static void emitRefusal(String name,ClientActionRequest.Rejected e){
  check(e.routeEntityRejection!=null && e.routeEntityRejection.get("schema_version").getAsInt()==2 && e.routeEntityRejection.has("native_bee_diagnostic"),"actual optional Bee detail retained in canonical fixture context");
  try {String bytes=BridgeJson.toJson(e.response());Files.writeString(out.resolve("bee-diagnostics/bee-diagnostic-equivalent-publication-"+name+".json"),bytes,StandardOpenOption.CREATE_NEW);check(bytes.equals(BridgeJson.toJson(JsonParser.parseString(bytes).getAsJsonObject())),"original bounded refusal bytes stable");}
  catch(Exception failure){throw new AssertionError(failure);}
 }
 static void onOtherThread(Runnable task){
  AtomicReference<Throwable> failure=new AtomicReference<>();CountDownLatch finished=new CountDownLatch(1);
  Thread t=new Thread(()->{try{task.run();}catch(Throwable error){failure.set(error);}finally{finished.countDown();}},"synthetic-native-publication");t.setDaemon(true);t.start();
  try{check(finished.await(5,TimeUnit.SECONDS),"bounded independent publication completed");t.join(1000);check(!t.isAlive(),"publication thread joined");}catch(InterruptedException e){Thread.currentThread().interrupt();throw new AssertionError(e);}
  if(failure.get()!=null)throw new AssertionError(failure.get());
 }
 public static void main(String[] args)throws Exception{
  out=Path.of(args[0]);
  scenario("equivalent-publication-all-hooks-retains-original-witness",()->{
   for(String hook:List.of("friction","shape","state")){
    var b=start();var original=b.f().m().facts().deepCopy();var before=NativeLivingObservation.capture(b.f().mc());
    Hooks.once(hook,0,()->publish(b.f().mc(),b.server()));b.f().m().beforeEffect(b.f().mc());
    var after=NativeLivingObservation.capture(b.f().mc());check(after.batch()!=before.batch(),"different Batch object published");
    check(b.f().m().facts().equals(original),"old serialized witness unchanged");check(!NativeLivingObservation.currentBatch(before),"old pointer fence would refuse");clean(b.f());
   }
  });
  scenario("every-relevant-immutable-row-field-change-refuses",()->{
   for(String kind:List.of("uuid","id","type","dead","aggressive","target","angry","anger","persistent_target","bee_missing","rabbit","extension_missing","server_class","stung","nectar","hive","flower","read_status")){
    var b=start();var captured=ScopedRouteStopEntities.capture(b.f().mc(),route(),0,true);var frame=captured.serverFrame;var before=frame.batch().rows().get(b.bee().uuid.toString());var newer=changed(before,kind);
    publishBatch(frame,Map.of(before.uuid(),newer),true,2,frame.batch().serverLevel(),frame.batch().dimension());
    var rejected=refused(captured::finalFence);diagnostic(rejected,"route_bee_native_context_changed");
    if(kind.equals("anger"))emitRefusal("changed-anger",rejected);clean(b.f());
   }
  });
  scenario("latest-missing-partial-level-dimension-and-coverage-refuse",()->{
   for(String kind:List.of("missing","partial","level","dimension","inspected_zero","inspected_limit","row_limit","rows_exceed_inspected","complete_reason")){
    var b=start();var captured=ScopedRouteStopEntities.capture(b.f().mc(),route(),0,true);var f=captured.serverFrame;var rows=new HashMap<>(f.batch().rows());
    if(kind.equals("missing"))rows.clear();if(kind.equals("rows_exceed_inspected"))rows.put("unrelated",rows.values().iterator().next());if(kind.equals("row_limit"))for(int i=0;i<256;i++)rows.put("unrelated-"+i,rows.values().iterator().next());
    publishBatch(f,rows,!kind.equals("partial"),kind.equals("inspected_zero")?0:kind.equals("inspected_limit")?4097:kind.equals("row_limit")?4096:kind.equals("rows_exceed_inspected")?1:2,kind.equals("level")?new Object():f.batch().serverLevel(),kind.equals("dimension")?"minecraft:the_nether":f.batch().dimension());
    if(kind.equals("complete_reason"))check(NativeLivingObservation.STORE.publish(new NativeLivingSnapshot.Batch(f.context(),f.batch().serverLevel(),f.batch().dimension(),rows,true,2,"native_read_failed")),"invalid complete reason publication retained for test");
    var rejected=refused(captured::finalFence);diagnostic(rejected,"route_bee_native_context_changed");
    if(kind.equals("partial")||kind.equals("missing")||kind.equals("level"))emitRefusal(kind,rejected);clean(b.f());
   }
  });
  scenario("all-guarded-bees-checked-unrelated-complete-rows-may-change",()->{
   var m=env();var c1=bee(m);var c2=RouteStopEngineChecks.at(m,new net.minecraft.world.entity.animal.Bee(),30,20,20);var s1=server(c1);var s2=server(c2);
   var r1=NativeLivingObservation.read(s1,m.level.time,System.nanoTime());var r2=NativeLivingObservation.read(s2,m.level.time,System.nanoTime());NativeLivingObservation.publish(m,Map.of(r1.uuid(),r1,r2.uuid(),r2),true);
   var f=admit(m);var captured=ScopedRouteStopEntities.capture(m,route(),0,true);var base=captured.serverFrame;var rows=new HashMap<>(base.batch().rows());
   var unrelated=new NativeLivingSnapshot.Row("other",900,"minecraft:zombie",m.level.time,System.nanoTime(),true,true,null,null);rows.put("other",unrelated);
   publishBatch(base,rows,true,37,base.batch().serverLevel(),base.batch().dimension());captured.finalFence();check(true,"unrelated hostile server row does not widen client enumeration");
   var last=captured.entries.get(captured.entries.size()-1).row().uuid();rows.put(last,changed(base.batch().rows().get(last),"anger"));publishBatch(base,rows,true,37,base.batch().serverLevel(),base.batch().dimension());diagnostic(refused(captured::finalFence),"route_bee_native_context_changed");clean(f);
  });
  scenario("fresh-clock-rollover-monotonicity-expiry-and-future-fail-closed",()->{
   for(String kind:List.of("nano_regression","tick_regression","future_nano","tick_skew","negative_tick")){
    var b=start();var captured=ScopedRouteStopEntities.capture(b.f().mc(),route(),0,true);var f=captured.serverFrame;var r=f.batch().rows().get(b.bee().uuid.toString());
    long tick=kind.equals("tick_regression")?r.tick()-1:kind.equals("tick_skew")?r.tick()+6:kind.equals("negative_tick")?-1:r.tick();
    long nano=kind.equals("nano_regression")?r.nano()-1:kind.equals("future_nano")?System.nanoTime()+1_000_000_000L:System.nanoTime();
    var newer=timed(r,tick,nano);publishBatch(f,Map.of(r.uuid(),newer),true,2,f.batch().serverLevel(),f.batch().dimension());
    diagnostic(refused(captured::finalFence),kind.equals("future_nano")||kind.equals("tick_skew")?"route_bee_native_stale":"route_bee_native_context_changed");
   }
   var b=start();var captured=ScopedRouteStopEntities.capture(b.f().mc(),route(),0,true);try{Thread.sleep(260);}catch(InterruptedException e){throw new AssertionError(e);}publish(b.f().mc(),b.server());diagnostic(refused(captured::finalFence),"route_bee_native_stale");check(true,"new fresh publication cannot renew original expired witness");
   // Existing production rejection function is also used by the semantic fence at its atomic clock sample.
   var f=NativeLivingObservation.capture(b.f().mc());var r=f.batch().rows().get(b.bee().uuid.toString());var fixed=timed(r,100,1_000_000_000L);var batch=new NativeLivingSnapshot.Batch(f.context(),f.batch().serverLevel(),f.batch().dimension(),Map.of(r.uuid(),fixed),true,2,"observed");
   check(NativeLivingSnapshot.rejection(batch,f.context(),batch.dimension(),r.uuid(),r.entityId(),r.type(),105,1_250_000_000L)==null,"inclusive five ticks and 250ms");
   check(NativeLivingSnapshot.rejection(batch,f.context(),batch.dimension(),r.uuid(),r.entityId(),r.type(),106,1_250_000_000L).equals("source_tick_mismatch"),"six ticks refuses");
   check(NativeLivingSnapshot.rejection(batch,f.context(),batch.dimension(),r.uuid(),r.entityId(),r.type(),100,1_250_000_001L).equals("source_expired"),"250ms plus 1ns refuses");
  });
  scenario("independent-thread-equivalent-publication-and-unsafe-replacement",()->{
   for(String kind:List.of("equivalent","anger","partial","clear")){
    var b=start();var f=NativeLivingObservation.capture(b.f().mc());var r=f.batch().rows().get(b.bee().uuid.toString());
    Hooks.once("friction",0,()->onOtherThread(()->{if(kind.equals("clear")){NativeLivingObservation.STORE.clear();return;}var newer=kind.equals("anger")?changed(r,"anger"):timed(r,r.tick(),System.nanoTime());NativeLivingObservation.STORE.publish(new NativeLivingSnapshot.Batch(f.context(),f.batch().serverLevel(),f.batch().dimension(),Map.of(r.uuid(),newer),!kind.equals("partial"),2,kind.equals("partial")?"inspection_limit":"observed"));}));
    if(kind.equals("equivalent")){b.f().m().beforeEffect(b.f().mc());check(true,"independent equivalent publication accepted");}else refused(()->b.f().m().beforeEffect(b.f().mc()));clean(b.f());
   }
  });
  scenario("concurrent-equivalent-publication-stress-is-linearizable",()->{
   var b=start();var captured=ScopedRouteStopEntities.capture(b.f().mc(),route(),0,true);var f=captured.serverFrame;var r=f.batch().rows().get(b.bee().uuid.toString());AtomicReference<Throwable> failure=new AtomicReference<>();CountDownLatch go=new CountDownLatch(1);
   Thread t=new Thread(()->{try{if(!go.await(5,TimeUnit.SECONDS))throw new AssertionError("start timeout");for(int i=0;i<256;i++){var n=timed(r,r.tick(),System.nanoTime());if(!NativeLivingObservation.STORE.publish(new NativeLivingSnapshot.Batch(f.context(),f.batch().serverLevel(),f.batch().dimension(),Map.of(r.uuid(),n),true,2,"observed")))throw new AssertionError("publication failed");}}catch(Throwable e){failure.set(e);}},"synthetic-concurrent-publication");t.setDaemon(true);t.start();go.countDown();for(int i=0;i<256;i++)captured.finalFence();
   try{t.join(5000);}catch(InterruptedException e){throw new AssertionError(e);}check(!t.isAlive()&&failure.get()==null,"bounded publisher joined cleanly");captured.finalFence();
   check(java.lang.reflect.Modifier.isSynchronized(Arrays.stream(NativeLivingSnapshot.Store.class.getDeclaredMethods()).filter(m->m.getName().equals("equivalentBeeBatch")).findFirst().orElseThrow().getModifiers()),"current metadata, row comparisons and clocks share Store publication monitor");
   publishBatch(f,Map.of(r.uuid(),changed(r,"anger")),true,2,f.batch().serverLevel(),f.batch().dimension());diagnostic(refused(captured::finalFence),"route_bee_native_context_changed");check(true,"subsequent unsafe publication cannot reuse previous success");
  });
  scenario("equivalent-republication-never-bypasses-client-or-owner-change",()->{
   for(String kind:List.of("entity_object","position","velocity","lerp","client_sting","player","level","server","world","session_owner","tick")){
    var b=start();Hooks.once("friction",0,()->{publish(b.f().mc(),b.server());switch(kind){
     case "entity_object"->{b.f().mc().level.entities.remove(b.bee());var other=server(b.bee());RouteStopEngineChecks.at(b.f().mc(),other,20,20,20);}
     case "position"->b.bee().x+=.01;case "velocity"->b.bee().velocity=new Vec3(.001,0,0);case "lerp"->b.bee().tx+=.01;case "client_sting"->b.bee().stung=true;
     case "player"->b.f().mc().player=new LocalPlayer();case "level"->b.f().mc().level=new ClientLevel();case "server"->b.f().mc().server=new Object();case "world"->WorldGeneration.value="new-world";
     case "session_owner"->ClientActions.ownershipRevision++;case "tick"->b.f().mc().level.time++;
    }});refused(()->b.f().m().beforeEffect(b.f().mc()));clean(b.f());
   }
  });
  scenario("equivalent-motion-publication-passes-unsafe-stays-unknown",()->{
   var b=start();b.f().m().markAttempted();ScopedLocalSegmentDispatch.arm(b.f().m());Hooks.once("friction",0,()->publish(b.f().mc(),b.server()));check(ScopedLocalSegmentDispatch.beforeMove(b.f().mc().player,MoverType.SELF,b.f().mc().player.velocity),"equivalent publication alone is not unknown motion");check(!b.f().entry().result.has("unknown_outcome"),"no fabricated unknown");clean(b.f());
   var bad=start();bad.f().m().markAttempted();ScopedLocalSegmentDispatch.arm(bad.f().m());Hooks.once("friction",0,()->{bad.server().anger=1;publish(bad.f().mc(),bad.server());});check(!ScopedLocalSegmentDispatch.beforeMove(bad.f().mc().player,MoverType.SELF,bad.f().mc().player.velocity),"unsafe publication stops move");check(bad.f().entry().result.get("unknown_outcome").getAsBoolean(),"late unsafe retains unknown");check(bad.f().entry().result.get("effect_outcome").getAsString().equals("unknown"),"no retry success promotion");clean(bad.f());
  });
  // Genuine production serializers consume this controller-produced positive fixture without editing witness fields.
  var m=env();WorldGeneration.value="00000000-0000-4000-8000-000000000001";var client=bee(m);var source=server(client);publish(m,source);var original=NativeLivingObservation.capture(m);String uuid=client.uuid.toString();long originalNano=original.batch().rows().get(uuid).nano();long[] replacementNano={0};int[] publications={0};
  Hooks.once("friction",0,()->{publish(m,source);replacementNano[0]=NativeLivingObservation.capture(m).batch().rows().get(uuid).nano();publications[0]++;});var f=admit(m);
  check(replacementNano[0]>originalNano,"equivalent republish actually occurred during admission");var nativeWitness=f.m().facts().getAsJsonObject("entity_guard").getAsJsonArray("rows").get(0).getAsJsonObject().getAsJsonObject("native_living");check(Long.parseLong(nativeWitness.get("source_nano").getAsString())==originalNano,"original source retained after admission publication");
  for(int i=1;i<=4;i++){publish(m,source);Hooks.once("friction",0,()->{publish(m,source);publications[0]++;});sample(f,i,new double[]{0,.8,1.1,1.4,1.47}[i],1,true,-.0784,0);}f.m().markAttempted();Path fixture=out.resolve("route-bee-equivalent-publication-success");writeFixture(fixture,f);
  JsonObject evidence=new JsonObject();evidence.addProperty("original_source_nano",Long.toString(originalNano));evidence.addProperty("admission_replacement_source_nano",Long.toString(replacementNano[0]));evidence.addProperty("same_callback_equivalent_publications",publications[0]);evidence.addProperty("original_witness_retained",true);evidence.addProperty("scope","Production immutable Store/fence/controller with synthetic engine values; no live game or physics claim");Files.writeString(fixture.resolve("equivalent-publication-evidence.json"),evidence.toString(),StandardOpenOption.CREATE_NEW);
  JsonObject report=new JsonObject();report.addProperty("assertions",assertions);report.add("cases",cases);report.addProperty("status","passed");report.addProperty("scope","Production immutable snapshot/fence/controller, independent synthetic publisher thread, original witness and HTTP bytes; no game, loader, AI or world execution");Files.writeString(out.resolve("bee-batch-equivalence-result.json"),report.toString(),StandardOpenOption.CREATE_NEW);System.out.println("PASS bee batch equivalence assertions="+assertions);
 }
}

package io.github.campione01.mineclientbridge;

import com.google.gson.*;
import java.nio.file.*;
import java.io.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicLong;
import it.unimi.dsi.fastutil.doubles.DoubleList;
import it.unimi.dsi.fastutil.doubles.DoubleArrayList;
import net.minecraft.core.Direction;
import net.minecraft.world.phys.shapes.*;

/** Actual production parser/journal/shape DTO/route checks with synthetic facts. No Minecraft or GLFW instance. */
public final class RecoveryNavigationV4Checks {
 static final String V4=RecoveryShortInputLedger.NAVIGATION_V4_PROFILE,V3=RecoveryShortInputLedger.INTERACTION_V3_PROFILE;
 static int checks;
 static void check(boolean b,String label){if(!b)throw new AssertionError(label);checks++;}
 static void rejects(Runnable r){try{r.run();throw new AssertionError("accepted");}catch(IllegalArgumentException|IllegalStateException expected){checks++;}}
 static RecoveryShortInputLedger.Request request(RecoveryShortInputLedger l,String id,String kind,boolean jump){
  var op=new RecoveryShortInputLedger.Operation(kind,0,0,0,"",0,0,0,"","",V4,2,"e".repeat(64),"bed-to-table");
  return new RecoveryShortInputLedger.Request(id,l.session,l.owner()==null?RecoveryShortInputChecks.OWNER:l.owner(),l.nextGeneration(),RecoveryShortInputChecks.WORLD,RecoveryShortInputChecks.PLAYER,kind.equals("move")?1:0,0,kind.equals("move")?8:1,jump,1000,RecoveryShortInputChecks.OBS,op);
 }
 static JsonObject json(RecoveryShortInputLedger.Request r){var j=RecoveryInteractionChecks.requestJson(r);j.addProperty("plan_version",2);j.addProperty("plan_sha256",r.operation().planSha256());j.addProperty("stage_id",r.operation().stageId());return j;}
 static void write(Path p,JsonObject j)throws Exception{byte[] b=RecoveryShortInputCodec.encode(j);RecoveryNavigationV4.checkResponseBudget(b);Files.write(p,b);}
 public static void main(String[] args)throws Exception{
  if(args.length==1&&args[0].equals("--disabled")){check(!RecoveryNavigationV4.ENABLED,"flag off");check(RecoveryNavigationV4.observationProfile(V3).equals(V3),"old observation unchanged");System.out.println("V4 disabled PASS checks="+checks);return;}
  Path fixtures=Path.of(args[0]),out=Path.of(args[1]);Files.createDirectories(out);schema();geometry(out);history(fixtures,out);wire(out.resolve("wire-fixtures"));
  System.out.println("RecoveryNavigationV4Checks PASS checks="+checks+"; synthetic offline metadata/ledger, not live shape or effect");
 }
 static void schema()throws Exception{
  check(RecoveryNavigationV4.ENABLED&&NativeRecoveryShortInput.activeProfile().equals(V4),"exclusive startup v4");
  check(RecoveryNavigationV4.observationProfile(V3).equals(V4),"same root active observation");check(RecoveryNavigationV4.observationProfile(RecoveryShortInputLedger.INTERACTION_V2_PROFILE).equals(RecoveryShortInputLedger.INTERACTION_V2_PROFILE),"old root unchanged");
  for(int mask=0;mask<128;mask++){boolean[] b=new boolean[7];for(int i=0;i<7;i++)b[i]=(mask&(1<<i))!=0;check(RecoveryDeathScreenUi.flagsV4(b[0],b[1],b[2],b[3],b[4],b[5],b[6])==(b[0]&&(b[1]^b[2])&&!b[3]&&!b[4]&&!b[5]&&b[6]),"UI exclusiveflags");}
  AtomicLong now=new AtomicLong(100);var l=new RecoveryShortInputLedger(new RecoveryShortInputChecks.Memory(),now::get);RecoveryInteractionChecks.setLedger(l);
  var r=request(l,UUID.randomUUID().toString(),"move",true);var body=json(r);check(NativeRecoveryShortInput.parseInteractionStart(RecoveryShortInputCodec.parse(RecoveryShortInputCodec.encode(body)),V4).equals(r),"actual wire jump request");
  check(RecoveryNavigationV4.bodyProfile(V3,body).equals(V4),"explicit v4 shared route");check(RecoveryNavigationV4.bodyProfile(RecoveryShortInputLedger.INTERACTION_V2_PROFILE,body).equals(RecoveryShortInputLedger.INTERACTION_V2_PROFILE),"no v4 oldroot");
  for(String key:List.of("stage_id","plan_version","plan_sha256")){var b=body.deepCopy();b.remove(key);rejects(()->NativeRecoveryShortInput.parseInteractionStart(b,V4));}
  for(String stage:List.of("","a".repeat(65),"bed table","床","x/y")){var b=body.deepCopy();b.addProperty("stage_id",stage);rejects(()->NativeRecoveryShortInput.parseInteractionStart(b,V4));}
  for(String kind:List.of("select_hotbar","break_block")){var b=body.deepCopy();b.addProperty("kind",kind);rejects(()->NativeRecoveryShortInput.parseInteractionStart(b,V4));rejects(()->request(l,UUID.randomUUID().toString(),kind,false));}
  for(int n:new int[]{0,9}){var b=body.deepCopy();b.addProperty("samples",n);rejects(()->NativeRecoveryShortInput.parseInteractionStart(b,V4));}
  for(int n:new int[]{99,2001}){var b=body.deepCopy();b.addProperty("ttl_ms",n);rejects(()->NativeRecoveryShortInput.parseInteractionStart(b,V4));}
  var old=body.deepCopy();old.addProperty("profile",V3);old.addProperty("plan_version",1);old.remove("stage_id");rejects(()->NativeRecoveryShortInput.parseInteractionStart(old,V3));old.addProperty("jump_first",false);check(!NativeRecoveryShortInput.parseInteractionStart(old,V3).jumpFirst(),"old v3 nojump unchanged");
  var wrong=body.deepCopy();wrong.addProperty("plan_version",1);rejects(()->NativeRecoveryShortInput.parseInteractionStart(wrong,V4));
  var changed=body.deepCopy();changed.addProperty("stage_id","other");check(!NativeRecoveryShortInput.parseInteractionStart(changed,V4).digest().equals(r.digest()),"stage affects canonical digest");
  try(var d=new DataInputStream(new ByteArrayInputStream(RecoveryShortInputLedger.encodeRequest(r)))){check(d.readUTF().equals(V4)&&d.readUTF().equals("move"),"v4 binary prefix");for(int i=0;i<3;i++)d.readUTF();d.readLong();d.readUTF();d.readUTF();d.readInt();d.readUTF();check(d.readInt()==2&&d.readUTF().equals(r.operation().planSha256())&&d.readUTF().equals(r.operation().stageId()),"plan2 hash thenstage canonical order");check(d.readDouble()==1&&d.readDouble()==0&&d.readInt()==8&&d.readBoolean()&&d.available()==0,"existing move payload order");}
  var e=l.submit(r);now.addAndGet(1_000_000_000L);check(!l.sample(e,1,true,()->{throw new AssertionError("expired write");})&&e.settled()&&e.applied==0&&!e.effectFenced,"absoluteTTL wins validlease");
  var stop=l.submit(request(l,UUID.randomUUID().toString(),"move",true));l.stop(stop,"explicit_stop");check(!l.sample(stop,2,true,()->{throw new AssertionError("stop write");}),"stop wins");
  var next=l.submit(request(l,UUID.randomUUID().toString(),"move",true));check(!l.sample(stop,3,true,()->{throw new AssertionError("oldowner write");}),"oldowner no write");
  int[] writes={0},jumps={0};for(int i=0;i<8;i++){boolean jump=next.request.jumpFirst()&&next.applied==0;check(l.sample(next,10+i,true,()->{writes[0]++;if(jump)jumps[0]++;}),"one sample");check(!l.sample(next,10+i,true,()->{throw new AssertionError("duplicate sample");}),"no second sample same tick");l.release(next,true,()->{},false,"samples_complete");}check(writes[0]==8&&jumps[0]==1&&next.settled(),"8 samples exactly1 firstjump");
  var unknown=l.submit(request(l,UUID.randomUUID().toString(),"move",true));try{l.sample(unknown,99,true,()->{throw new IllegalStateException("synthetic write uncertain");});}catch(IllegalStateException expected){}check(l.locked()&&unknown.state.equals("UNKNOWN"),"unknown retains lock");rejects(()->l.submit(request(l,UUID.randomUUID().toString(),"look",false)));
 }
 static final class FakeShape extends VoxelShape {
  final int count;final double[] box;final boolean fail;int visits;
  FakeShape(int n,double[] b,boolean fail){super(new BitSetDiscreteVoxelShape(1,1,1));count=n;box=b;this.fail=fail;}
  public DoubleList getCoords(Direction.Axis a){return new DoubleArrayList(new double[]{0,1});}
  public boolean isEmpty(){return count==0;}
  public void forAllBoxes(Shapes.DoubleLineConsumer c){if(fail)throw new IllegalStateException("synthetic getter failure");for(int i=0;i<count;i++){visits++;c.consume(box[0],box[1],box[2],box[3],box[4],box[5]);}}
 }
 static void geometry(Path out)throws Exception{
  for(double d:new double[]{Double.NaN,Double.POSITIVE_INFINITY,-1,17})check(!RecoveryNavigationV4.validStepHeight(d),"invalid step");check(RecoveryNavigationV4.validStepHeight(.6F),"actualfloat step");
  var g=new RecoveryNavigationV4.Geometry(.6F);JsonObject bed=new JsonObject();g.shape(bed,Shapes.box(0,3.0/16,0,1,9.0/16,1));check(bed.getAsJsonArray("collision_boxes").get(0).getAsJsonArray().get(4).getAsDouble()==.5625,"bed exact sampledheight");
  JsonObject chest=new JsonObject();g.shape(chest,Shapes.box(1.0/16,0,1.0/16,15.0/16,14.0/16,15.0/16));check(chest.getAsJsonArray("collision_boxes").get(0).getAsJsonArray().get(4).getAsDouble()==.875,"chest exact sampledheight");
  JsonObject empty=new JsonObject();g.shape(empty,Shapes.empty());check(!empty.get("collision").getAsBoolean()&&empty.getAsJsonArray("collision_boxes").isEmpty(),"true empty shape");
  var sample=new JsonObject();sample.add("bed",bed);sample.add("chest",chest);sample.add("empty",empty);write(out.resolve("synthetic-actual-shape-serializer.json"),sample);
  double[] box={0,0,0,1,1,1};for(double[] b:new double[][]{{0,0,0,Double.NaN,1,1},{0,0,0,Double.POSITIVE_INFINITY,1,1},{0,0,0,17,1,1},{-17,0,0,1,1,1},{0,0,0,0,1,1},{1,0,0,0,1,1}}){var x=new RecoveryNavigationV4.Geometry(.6);JsonObject c=new JsonObject();x.shape(c,new FakeShape(1,b,false));var root=new JsonObject();x.describe(root,true);check(c.get("collision_boxes").isJsonNull()&&c.get("collision").isJsonNull()&&!root.get("collision_boxes_complete").getAsBoolean(),"invalidshape incomplete notair");}
  var overflow=new FakeShape(1000000,box,false);var x=new RecoveryNavigationV4.Geometry(.6);JsonObject c=new JsonObject();x.shape(c,overflow);check(overflow.visits==17&&c.get("collision_boxes").isJsonNull()&&x.totalBoxes()==0,"boundedcallback no unboundedlist");
  x=new RecoveryNavigationV4.Geometry(.6);for(int i=0;i<32;i++){c=new JsonObject();x.shape(c,new FakeShape(16,box,false));check(c.getAsJsonArray("collision_boxes").size()==16,"16 percell admitted");}check(x.totalBoxes()==512,"512 total exact");c=new JsonObject();x.shape(c,new FakeShape(1,box,false));check(c.get("collision_boxes").isJsonNull()&&x.totalBoxes()==512,"513 refused");var root=new JsonObject();x.describe(root,true);check(!root.get("collision_boxes_complete").getAsBoolean(),"overflow wholeincomplete");
  x=new RecoveryNavigationV4.Geometry(.6);c=new JsonObject();x.shape(c,new FakeShape(1,box,true));root=new JsonObject();x.describe(root,true);check(c.get("collision_boxes").isJsonNull()&&!root.get("collision_boxes_complete").getAsBoolean(),"shapeexception incomplete");
  x=new RecoveryNavigationV4.Geometry(.6);c=new JsonObject();x.unloaded(c);root=new JsonObject();x.describe(root,true);check(c.get("collision_boxes").isJsonNull()&&!root.get("collision_boxes_complete").getAsBoolean(),"unloaded incomplete");
  RecoveryNavigationV4.checkResponseBudget(new byte[65536]);rejects(()->RecoveryNavigationV4.checkResponseBudget(new byte[65537]));var huge=new JsonObject();huge.addProperty("x","x".repeat(65536));rejects(()->RecoveryNavigationV4.checkResponseBudget(huge));
 }
 static void history(Path fixtures,Path out)throws Exception{
  byte[] old=Files.readAllBytes(fixtures.resolve("native-101-entry-journal.bin"));Path file=out.resolve("mixed-journal.bin");Files.write(file,old);var actions=JsonParser.parseString(Files.readString(fixtures.resolve("public-ledger-101.json"))).getAsJsonObject().getAsJsonObject("actions");List<byte[]> oldRequests=new ArrayList<>();
  try(var store=new RecoveryShortInputLedger.FileStore(file)){var rows=store.read();check(rows.size()==101,"real101 count");store.write(rows);check(Arrays.equals(old,Files.readAllBytes(file)),"101 exactbinary roundtrip");var l=new RecoveryShortInputLedger(store,()->100,true);RecoveryInteractionChecks.setLedger(l);
   for(var row:rows){var r=row.request;oldRequests.add(RecoveryShortInputLedger.encodeRequest(r));var e=l.lookup(r.id(),r.session(),r.ownerId(),r.generation());var status=NativeRecoveryShortInput.describe(e);check(status.equals(actions.getAsJsonObject(r.id()).getAsJsonObject("terminal_native")),"101 originalterminal");check(!status.has("stage_id"),"old no v4 field");check(l.submit(r)==e,"duplicate originalid");check(NativeRecoveryShortInput.status(RecoveryInteractionV2Checks.query(r),r.profile()).equals(status),"old storedstatus");var stop=RecoveryInteractionV2Checks.query(r);stop.addProperty("schema_version",1);stop.addProperty("profile",r.profile());check(NativeRecoveryShortInput.stop(stop,r.profile()).equals(status),"old storedstop");}
   var e=l.submit(request(l,UUID.randomUUID().toString(),"move",true));l.recordObservationRefusal(e,new RecoveryChallengeLease.Refusal("first_input",1_000_000_001L,1L,1));l.rejectQueued(e,"observation_stale_or_moved");var q=RecoveryInteractionV2Checks.query(e.request);check(NativeRecoveryShortInput.status(q,V3).equals(NativeRecoveryShortInput.describe(e)),"v3root reads storedv4");rejects(()->NativeRecoveryShortInput.status(q,RecoveryShortInputLedger.INTERACTION_V2_PROFILE));var stop=q.deepCopy();stop.addProperty("schema_version",1);stop.addProperty("profile",V3);rejects(()->NativeRecoveryShortInput.stop(stop,V3));stop.addProperty("profile",V4);check(NativeRecoveryShortInput.stop(stop,V4).equals(NativeRecoveryShortInput.describe(e)),"explicit v4 stop");}
  try(var store=new RecoveryShortInputLedger.FileStore(file)){var rows=store.read();check(rows.size()==102&&rows.getLast().observationRefusal.predicateMask()==1&&rows.getLast().request.operation().stageId().equals("bed-to-table"),"v4 conditional persistence");for(int i=0;i<101;i++)check(Arrays.equals(oldRequests.get(i),RecoveryShortInputLedger.encodeRequest(rows.get(i).request)),"all original requests exact");Path subset=out.resolve("original101-reencoded.bin");try(var s=new RecoveryShortInputLedger.FileStore(subset)){s.write(rows.subList(0,101));}check(Arrays.equals(old,Files.readAllBytes(subset)),"v4append old101 bytes preserved");}
 }
 static void wire(Path out)throws Exception{
  Files.createDirectories(out);Path file=out.resolve("synthetic-v4-journal.bin");List<RecoveryShortInputLedger.Request> requests=new ArrayList<>();List<JsonObject> receipts=new ArrayList<>();
  try(var store=new RecoveryShortInputLedger.FileStore(file)){var l=new RecoveryShortInputLedger(store,()->100);RecoveryInteractionChecks.setLedger(l);int id=0;
   for(String kind:List.of("move","look")){var r=request(l,String.format("44444444-4444-4444-8444-%012d",++id),kind,kind.equals("move"));var e=l.submit(r);write(out.resolve(kind+"-request.json"),json(r));write(out.resolve(kind+"-queued.json"),NativeRecoveryShortInput.describe(e));l.rejectQueued(e,"offline_known_zero");write(out.resolve(kind+"-settled.json"),NativeRecoveryShortInput.describe(e));requests.add(r);receipts.add(NativeRecoveryShortInput.describe(e));}
   for(String stage:List.of("admit","first_input","first_interaction_tick")){var e=l.submit(request(l,String.format("44444444-4444-4444-8444-%012d",++id),stage.equals("first_input")?"move":"look",false));l.recordObservationRefusal(e,new RecoveryChallengeLease.Refusal(stage,1_000_000_001L,1L,1));l.rejectQueued(e,"observation_stale_or_moved");write(out.resolve(stage+"-request.json"),json(e.request));write(out.resolve(stage+"-settled.json"),NativeRecoveryShortInput.describe(e));requests.add(e.request);receipts.add(NativeRecoveryShortInput.describe(e));}
   write(out.resolve("observe-no-world.json"),NativeRecoveryShortInput.describeNoWorld(false,true,V4));}
  try(var store=new RecoveryShortInputLedger.FileStore(file)){var l=new RecoveryShortInputLedger(store,()->200,true);RecoveryInteractionChecks.setLedger(l);for(int i=0;i<requests.size();i++)check(NativeRecoveryShortInput.status(RecoveryInteractionV2Checks.query(requests.get(i)),V3).equals(receipts.get(i)),"actualcodec persistedreceipt");}
  var m=new JsonObject();m.addProperty("scope","synthetic DTO and requests through actual production codec; no live capture/gameplay");m.addProperty("records",requests.size());write(out.resolve("manifest.json"),m);
 }
}

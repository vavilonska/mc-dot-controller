package io.github.campione01.mineclientbridge;
import com.google.gson.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import org.objectweb.asm.*;

/** Actual pure UI gate/journal/codec and bytecode checks, no GLFW call or native entity creation. */
public final class RecoveryRespawnUiChecks {
 static int checks;static void check(boolean b,String s){if(!b)throw new AssertionError(s);checks++;}
 static void rejects(Runnable r){try{r.run();throw new AssertionError("unexpected acceptance");}catch(IllegalArgumentException|IllegalStateException expected){checks++;}}
 public static void main(String[] a)throws Exception{
  if(a.length==1&&a[0].equals("--flag-off")){check(!RecoveryDeathScreenUi.enabled(),"flag off");check(!RecoveryDeathScreenUi.blocksStarts(),"flag off no start block");System.out.println("flag-off PASS "+checks);return;}
  Path fixtures=Path.of(a[0]),out=Path.of(a[1]),classes=Path.of(a[2]);Files.createDirectories(out);
  policies();gates();history101(fixtures,out);bytecode(classes);globalBlock();
  System.out.println("RecoveryRespawnUiChecks PASS assertions="+checks+"; no game/GLFW/entity instantiated");
 }
 static void policies(){
  for(int bits=0;bits<64;bits++){boolean f=(bits&1)!=0,v3=(bits&2)!=0,v2=(bits&4)!=0,v1=(bits&8)!=0,old=(bits&16)!=0,iso=(bits&32)!=0;check(RecoveryDeathScreenUi.flags(f,v3,v2,v1,old,iso)==(bits==35),"startup combination");}
  check(RecoveryDeathScreenUi.exactActorClasses(net.minecraft.client.player.LocalPlayer.class,net.minecraft.client.gui.screens.DeathScreen.class),"exact actor class literals");
  check(!RecoveryDeathScreenUi.exactActorClasses(Object.class,net.minecraft.client.gui.screens.DeathScreen.class),"wrong player");check(!RecoveryDeathScreenUi.exactActorClasses(net.minecraft.client.player.LocalPlayer.class,Object.class),"wrong screen");check(!RecoveryDeathScreenUi.exactButtonClass(Object.class),"wrong button");
  check(RecoveryDeathScreenUi.acceptPress(true,0,1,0),"leftPRESS only");for(int button:new int[]{1,2,-1})check(!RecoveryDeathScreenUi.acceptPress(true,button,1,0),"other buttons blocked");check(!RecoveryDeathScreenUi.acceptPress(true,0,0,0),"release swallowed");check(!RecoveryDeathScreenUi.acceptPress(true,0,1,2),"modifier refused");check(!RecoveryDeathScreenUi.acceptPress(false,0,1,0),"disabled");
  check(RecoveryDeathScreenUi.hitBounds(10,20,10,20,200,20),"inclusive lowbound");check(!RecoveryDeathScreenUi.hitBounds(210,20,10,20,200,20),"exclusive right");check(!RecoveryDeathScreenUi.hitBounds(10,40,10,20,200,20),"exclusive bottom");check(!RecoveryDeathScreenUi.hitBounds(Double.NaN,20,10,20,200,20),"nan");check(!RecoveryDeathScreenUi.hitBounds(10,Double.POSITIVE_INFINITY,10,20,200,20),"infinity");
 }
 static RecoveryShortInputLedger bound(){var l=new RecoveryShortInputLedger(new RecoveryShortInputChecks.Memory(),()->100);var seed=l.submit(RecoveryShortInputChecks.request(l,"seed",1));l.rejectQueued(seed,"seed_settled");return l;}
 static void gates()throws Exception{
  Object old=new Object(),replacement=new Object();var g=new RecoveryRespawnUiGate();var l=new RecoveryShortInputLedger(new RecoveryShortInputChecks.Memory(),()->100);
  check(!g.claimIdle(l,old,true)&&!g.consumed(),"unbound empty ledger refused");check(!g.claimIdle(l,old,false)&&!g.consumed(),"capture blocks without consuming");var queued=l.submit(RecoveryShortInputChecks.request(l,"queued",1));check(!g.claimIdle(l,old,true),"queued blocks");l.rejectQueued(queued,"test");
  check(g.claimIdle(l,old,true)&&g.blocksStarts(),"idle atomic claim");check(!g.claim(old)&&!g.claim(replacement),"duplicates/resize/new screen no rearm");g.returned(old);check(g.blocksStarts(),"return alone not success");check(!g.replacement(old,old,true,true)&&g.blocksStarts(),"sameplayer cannot complete");check(!g.replacement(old,replacement,true,false)&&g.blocksStarts(),"new dead player cannot complete");check(g.replacement(old,replacement,true,true)&&!g.blocksStarts()&&g.consumed(),"newalive context completes without rearm");check(!g.claim(old),"oldidentity stays consumed");
  var thrown=new RecoveryRespawnUiGate();thrown.claim(old);thrown.failed(old);thrown.returned(old);check(thrown.blocksStarts()&&thrown.phase()==RecoveryRespawnUiGate.Phase.UNKNOWN&&!thrown.replacement(old,replacement,true,true),"throw unknown never autoreleases");
  var changed=new RecoveryRespawnUiGate();changed.claim(old);changed.returned(old);changed.replacement(old,replacement,false,true);check(changed.phase()==RecoveryRespawnUiGate.Phase.UNKNOWN,"different connection context unknown");
  var locked=new RecoveryShortInputLedger(new RecoveryShortInputChecks.Memory(),()->100);locked.unknown(null,"test");check(!new RecoveryRespawnUiGate().claimIdle(locked,old,true),"UNKNOWN prevents UI");var closed=new RecoveryShortInputLedger(new RecoveryShortInputChecks.Memory(),()->100);closed.close();check(!new RecoveryRespawnUiGate().claimIdle(closed,old,true),"closed prevents UI");
  var concurrent=new RecoveryRespawnUiGate();var bus=bound();AtomicBoolean submitted=new AtomicBoolean();CountDownLatch ready=new CountDownLatch(1);Thread t;
  synchronized(bus){t=new Thread(()->{ready.countDown();synchronized(bus){if(!concurrent.blocksStarts()){bus.submit(RecoveryShortInputChecks.request(bus,"racing",1));submitted.set(true);}}});t.start();ready.await();check(concurrent.claimIdle(bus,old,true),"claim linearizes under existing bus");}t.join();check(!submitted.get()&&bus.active()==null,"concurrentstart sees busy");
  var queuedFirst=new RecoveryShortInputLedger(new RecoveryShortInputChecks.Memory(),()->100);queuedFirst.submit(RecoveryShortInputChecks.request(queuedFirst,"first",1));check(!new RecoveryRespawnUiGate().claimIdle(queuedFirst,old,true),"start linearizes first UI denied");
 }
 static void history101(Path fixtures,Path out)throws Exception{
  byte[] bytes=Files.readAllBytes(fixtures.resolve("native-101-entry-journal.bin"));Path copy=out.resolve("roundtrip101.bin");Files.write(copy,bytes);var actions=JsonParser.parseString(Files.readString(fixtures.resolve("public-ledger-101.json"))).getAsJsonObject().getAsJsonObject("actions");
  try(var store=new RecoveryShortInputLedger.FileStore(copy)){
   var entries=store.read();check(entries.size()==101,"actual101 count");store.write(entries);check(Arrays.equals(bytes,Files.readAllBytes(copy)),"actual101 wholebinary exact");var l=new RecoveryShortInputLedger(store,()->100,true);RecoveryInteractionChecks.setLedger(l);check(!l.locked()&&l.nextGeneration()==102,"owner and generation retained");
   for(var e:entries){var r=e.request;var current=l.lookup(r.id(),r.session(),r.ownerId(),r.generation());var j=NativeRecoveryShortInput.describe(current);check(j.equals(actions.getAsJsonObject(r.id()).getAsJsonObject("terminal_native")),"actual101 exact terminal and digest");check(NativeRecoveryShortInput.status(RecoveryInteractionV2Checks.query(r),r.profile()).equals(j),"oldprofile status");var stop=RecoveryInteractionV2Checks.query(r);stop.addProperty("schema_version",1);stop.addProperty("profile",r.profile());check(NativeRecoveryShortInput.stop(stop,r.profile()).equals(j),"oldprofile stop");check(l.submit(r)==current,"idempotent oldentry no dispatch");}
   check(Arrays.equals(bytes,Files.readAllBytes(copy)),"all readbacks leave bytes exact");
  }
 }
 static void bytecode(Path classes)throws Exception{
  Set<String> calls=new HashSet<>();Set<String> methods=new HashSet<>();new ClassReader(Files.readAllBytes(classes.resolve("io/github/campione01/mineclientbridge/RecoveryDeathScreenUi.class"))).accept(new ClassVisitor(Opcodes.ASM9){public MethodVisitor visitMethod(int access,String name,String descriptor,String signature,String[] exceptions){methods.add(name);return new MethodVisitor(Opcodes.ASM9){public void visitMethodInsn(int opcode,String owner,String name,String descriptor,boolean iface){calls.add(owner+"."+name+descriptor);}};}},0);
  check(calls.stream().anyMatch(x->x.startsWith("net/minecraft/client/gui/components/Button.onPress")),"real Button.onPress route");check(calls.stream().anyMatch(x->x.contains("GLFW.glfwSetMouseButtonCallback")),"buttononly registration");check(calls.stream().anyMatch(x->x.contains("GLFW.glfwGetCursorPos")),"cursor read only");
  for(String forbidden:List.of("MouseHandler","KeyMapping","syntheticDispatch",".execute(",".mouseClicked(",".respawn(",".setHealth(",".setPos(","glfwSetCursorPosCallback","glfwSetKeyCallback","glfwSetScrollCallback","glfwSetDropCallback"))check(calls.stream().noneMatch(x->x.contains(forbidden)),"no bypass/fallthrough "+forbidden);
  check(methods.contains("sameBinding")&&methods.contains("observeLifecycle"),"native context and completion gates");
 }
 static void globalBlock()throws Exception{
  var l=new RecoveryShortInputLedger(new RecoveryShortInputChecks.Memory(),()->100);RecoveryInteractionChecks.setLedger(l);var seedRequest=RecoveryInteractionV3Checks.request(l,"seed-v3","look",1000);var seed=l.submit(seedRequest);l.rejectQueued(seed,"seed_settled");Object old=new Object();check(RecoveryDeathScreenUi.enabled(),"actual flags enabled");check(RecoveryDeathScreenUi.claimIdle(l,old,true),"actual native shared gate claim");var body=RecoveryInteractionV3Checks.json(RecoveryInteractionV3Checks.request(l,"pending-reject","look",1000));rejects(()->NativeRecoveryShortInput.start(body,RecoveryShortInputLedger.INTERACTION_V3_PROFILE));check(l.active()==null&&l.diagnosticEntryCount()==1,"actual start rejects before submit/journal/game enqueue");check(NativeRecoveryShortInput.start(RecoveryInteractionV3Checks.json(seedRequest),RecoveryShortInputLedger.INTERACTION_V3_PROFILE).equals(NativeRecoveryShortInput.describe(seed)),"old exactduplicate remains read-only while UI busy");var bad=RecoveryInteractionV3Checks.json(seedRequest);bad.addProperty("yaw",1);rejects(()->NativeRecoveryShortInput.start(bad,RecoveryShortInputLedger.INTERACTION_V3_PROFILE));
 }
}

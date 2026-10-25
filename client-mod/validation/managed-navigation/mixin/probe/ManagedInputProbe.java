package probe;
import java.io.*;
import java.lang.reflect.*;
import java.nio.file.*;
import java.security.*;
import java.util.*;
import org.objectweb.asm.*;
import org.objectweb.asm.commons.ClassRemapper;
import org.objectweb.asm.commons.SimpleRemapper;
import org.objectweb.asm.tree.*;
import org.objectweb.asm.util.*;
import org.spongepowered.asm.launch.*;
import org.spongepowered.asm.mixin.*;
import org.spongepowered.asm.mixin.transformer.*;
import org.spongepowered.asm.service.*;

/** Real pinned target transformation + executable extracted real setter/getter bodies.
 * Extraction removes Minecraft-dependent construction/lifecycle only. Actual setter,
 * getter, clear method and injected handler instructions execute unchanged except the
 * carrier class name. The real API Input enum and interface are retained.
 */
public final class ManagedInputProbe {
 static int checks;static void check(boolean b,String reason){checks++;if(!b)throw new AssertionError(reason);}
 static String sha(byte[] b)throws Exception{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(b));}
 static byte[] resource(String name)throws Exception{try(InputStream in=ManagedInputProbe.class.getClassLoader().getResourceAsStream(name)){return in.readAllBytes();}}
 static MethodNode method(ClassNode n,String name){return n.methods.stream().filter(m->m.name.equals(name)).findFirst().orElseThrow();}
 static List<String> ops(MethodNode m){List<String> out=new ArrayList<>();for(AbstractInsnNode i:m.instructions){if(i.getOpcode()<0)continue;
  out.add(i.getOpcode()+":"+(i instanceof MethodInsnNode x?x.owner+"."+x.name+x.desc:i instanceof FieldInsnNode x?x.owner+"."+x.name+x.desc:i instanceof VarInsnNode x?x.var:i instanceof TypeInsnNode x?x.desc:""));}return out;}
 static void lifecycleWiring()throws Exception{
  ClassNode bridge=new ClassNode();new ClassReader(resource("io/github/campione01/mineclientbridge/BridgeServer.class")).accept(bridge,0);
  List<String> stop=ops(method(bridge,"stop"));int close=-1,cleanup=-1;
  for(int i=0;i<stop.size();i++){if(stop.get(i).contains("ManagedNavigationInputPolicy.closeAdmission"))close=i;if(stop.get(i).contains("BridgeServer.releaseAllOnMinecraftThread"))cleanup=i;}
  check(close>=0&&cleanup>close,"actual bridge stop closes policy before blocking client-thread cleanup");
  int callbacks=0;for(MethodNode m:bridge.methods)if(m.name.startsWith("lambda$releaseAllOnMinecraftThread$")){
   List<String> calls=ops(m);int own=-1,release=-1;for(int i=0;i<calls.size();i++){if(calls.get(i).contains("NativeManagedNavigation.bridgeStopping"))own=i;if(calls.get(i).contains("BridgeServer.releaseAllInputs"))release=i;}
   check(own>=0&&release>own,"actual bridge shutdown callback notifies exact managed owner before legacy release");callbacks++;
  }
  check(callbacks==2,"both direct and queued shutdown callbacks covered");
  ClassNode nativeRoute=new ClassNode();new ClassReader(resource("io/github/campione01/mineclientbridge/NativeManagedNavigation.class")).accept(nativeRoute,0);
  check(ops(nativeRoute.methods.stream().filter(m->m.name.equals("inputAllowed")&&m.desc.equals("(Lio/github/campione01/mineclientbridge/NativeManagedNavigation$Data;Lnet/minecraft/world/phys/Vec3;ZD)Z")).findFirst().orElseThrow()).stream().filter(x->x.contains("BridgeServer.isRunning")).count()==2,"setter checks bridge availability before and after callbacks");
  check(ops(method(nativeRoute,"bridgeStopping")).stream().anyMatch(x->x.contains("ManagedNavigationInputPolicy.shutdownOwns")),"actual shutdown callback checks original captured token");
  check(ops(method(nativeRoute,"tick")).stream().anyMatch(x->x.contains("ManagedNavigationInputPolicy.bridgeClosed")),"tick retains original closure across reopen even without callback");
  check(ops(method(nativeRoute,"start")).stream().filter(x->x.contains("BridgeServer.isRunning")).count()==3,"start checks bridge availability at initial and both final fences");
 }
 static void executable(ClassNode transformed)throws Exception{
  ClassNode carrier=new ClassNode();carrier.version=Opcodes.V21;carrier.access=Opcodes.ACC_PUBLIC;carrier.name="baritone/fj";carrier.superName="java/lang/Object";
  carrier.interfaces.add("baritone/api/utils/IInputOverrideHandler");carrier.interfaces.add("io/github/campione01/mineclientbridge/ManagedNavigationInputFence");
  carrier.fields.add(new FieldNode(Opcodes.ACC_PRIVATE|Opcodes.ACC_FINAL,"a","Ljava/util/Map;",null,null));
  for(MethodNode m:transformed.methods)if(Set.of("setInputForceState","isInputForcedDown","clearAllKeys").contains(m.name)||m.name.contains("mdc$walkingInput"))carrier.methods.add(m);
  check(carrier.methods.size()==4,"exact three actual methods plus injected handler");
  MethodNode init=new MethodNode(Opcodes.ACC_PUBLIC,"<init>","()V",null,null);init.visitCode();init.visitVarInsn(Opcodes.ALOAD,0);init.visitMethodInsn(Opcodes.INVOKESPECIAL,"java/lang/Object","<init>","()V",false);
  init.visitVarInsn(Opcodes.ALOAD,0);init.visitTypeInsn(Opcodes.NEW,"java/util/HashMap");init.visitInsn(Opcodes.DUP);init.visitMethodInsn(Opcodes.INVOKESPECIAL,"java/util/HashMap","<init>","()V",false);init.visitFieldInsn(Opcodes.PUTFIELD,"baritone/fj","a","Ljava/util/Map;");init.visitInsn(Opcodes.RETURN);init.visitMaxs(3,1);init.visitEnd();carrier.methods.add(init);
  ClassWriter writer=new ClassWriter(ClassWriter.COMPUTE_MAXS);carrier.accept(new ClassRemapper(writer,new SimpleRemapper("baritone/fj","probe/InputCarrier")));
  class Loader extends ClassLoader {Loader(){super(ManagedInputProbe.class.getClassLoader());}Class<?> define(byte[] b){return defineClass("probe.InputCarrier",b,0,b.length);}}
  Class<?> type=new Loader().define(writer.toByteArray());Object target=type.getConstructor().newInstance();
  Class<?> input=Class.forName("baritone.api.utils.input.Input");Class<?> api=Class.forName("baritone.api.utils.IInputOverrideHandler");
  Method setter=type.getMethod("setInputForceState",input,boolean.class),apiSetter=api.getMethod("setInputForceState",input,boolean.class),getter=type.getMethod("isInputForcedDown",input),clear=type.getMethod("clearAllKeys");
  Class<?> policy=Class.forName("io.github.campione01.mineclientbridge.ManagedNavigationInputPolicy"),tokenType=Class.forName("io.github.campione01.mineclientbridge.ManagedNavigationInputPolicy$Token");
  Method claim=policy.getDeclaredMethod("claim",Object.class,java.util.function.BooleanSupplier.class),settled=policy.getDeclaredMethod("settled",tokenType),quarantine=policy.getDeclaredMethod("quarantine",tokenType),reason=policy.getDeclaredMethod("blockedReason");claim.setAccessible(true);settled.setAccessible(true);quarantine.setAccessible(true);reason.setAccessible(true);
  Method open=policy.getDeclaredMethod("openAdmission"),close=policy.getDeclaredMethod("closeAdmission");open.setAccessible(true);close.setAccessible(true);
  Method shutdownOwns=policy.getDeclaredMethod("shutdownOwns",tokenType,tokenType),bridgeClosed=policy.getDeclaredMethod("bridgeClosed",tokenType);shutdownOwns.setAccessible(true);bridgeClosed.setAccessible(true);
  check(Modifier.isSynchronized(claim.getModifiers())&&Modifier.isSynchronized(open.getModifiers())&&Modifier.isSynchronized(close.getModifiers()),"claim and bridge close/reopen use one monitor");
  try{claim.invoke(null,target,(java.util.function.BooleanSupplier)()->true);throw new AssertionError("closed bridge admitted token");}catch(InvocationTargetException expected){check(expected.getCause() instanceof IllegalStateException,"closed bridge refuses claim");}
  open.invoke(null);
  java.util.concurrent.atomic.AtomicBoolean permit=new java.util.concurrent.atomic.AtomicBoolean(true),customActive=new java.util.concurrent.atomic.AtomicBoolean(true);
  Method movementOwner=policy.getDeclaredMethod("movementOwner",boolean.class,boolean.class,Object.class,Object.class);movementOwner.setAccessible(true);
  java.util.function.BooleanSupplier originalMovement=()->{try{return (Boolean)movementOwner.invoke(null,permit.get(),customActive.get(),target,target);}catch(Exception e){throw new RuntimeException(e);}};
  Object left=input.getField("CLICK_LEFT").get(null),right=input.getField("CLICK_RIGHT").get(null);
  setter.invoke(target,left,true);Object token=claim.invoke(null,target,originalMovement);check((Boolean)getter.invoke(target,left),"existing click remains visible; getter must never hide forced input");setter.invoke(target,left,false);check(!(Boolean)getter.invoke(target,left),"release false always permitted");
  for(Method variant:List.of(setter,apiSetter))for(Object key:input.getEnumConstants()){
   clear.invoke(target);variant.invoke(target,key,true);boolean click=((Enum<?>)key).name().startsWith("CLICK_");
   check((Boolean)getter.invoke(target,key)==!click,"actual direct/API user-forced variant "+key);
   variant.invoke(target,key,false);check(!(Boolean)getter.invoke(target,key),"actual false release "+key);
  }
  check(reason.invoke(null).equals("managed_navigation_door_or_nonwalking_input_blocked"),"blocked interaction explicit reason");
  Object forward=input.getField("MOVE_FORWARD").get(null),foreign=type.getConstructor().newInstance();
  apiSetter.invoke(foreign,forward,true);check(!(Boolean)getter.invoke(foreign,forward),"foreign handler has no walking authority");
  permit.set(false);apiSetter.invoke(target,forward,true);check(!(Boolean)getter.invoke(target,forward),"foreign goal/owner proof blocks movement");permit.set(true);
  customActive.set(false);apiSetter.invoke(target,forward,true);check(!(Boolean)getter.invoke(target,forward),"original handler plus inactive original process/null goal cannot authorize new movement");customActive.set(true);
  apiSetter.invoke(target,forward,true);check((Boolean)getter.invoke(target,forward),"original movement present before bridge stop");
  Thread shutdown=new Thread(()->{try{close.invoke(null);}catch(Exception e){throw new RuntimeException(e);}});shutdown.start();shutdown.join();
  check((Boolean)getter.invoke(target,forward),"bridge stop never hides existing forced input");
  apiSetter.invoke(target,forward,false);check(!(Boolean)getter.invoke(target,forward),"bridge stop permits original release");
  apiSetter.invoke(target,forward,true);check(!(Boolean)getter.invoke(target,forward),"bridge stop blocks new original movement");
  open.invoke(null);apiSetter.invoke(target,forward,true);check(!(Boolean)getter.invoke(target,forward),"bridge restart cannot resume old token");
  check((Boolean)bridgeClosed.invoke(null,token)&&(Boolean)shutdownOwns.invoke(null,token,token),"closed original token remains visible to tick after reopen");
  try{claim.invoke(null,target,originalMovement);throw new AssertionError("restart admitted second owner");}catch(InvocationTargetException expected){check(expected.getCause() instanceof IllegalStateException,"restart retains original token until settlement");}
  quarantine.invoke(null,token);apiSetter.invoke(target,forward,true);check(!(Boolean)getter.invoke(target,forward),"UNKNOWN blocks new movement");
  apiSetter.invoke(target,right,true);check(!(Boolean)getter.invoke(target,right),"UNKNOWN blocks use");
  settled.invoke(null,token);apiSetter.invoke(target,right,true);check((Boolean)getter.invoke(target,right),"settled owner releases filter");clear.invoke(target);
  Object[] replacement=new Object[2];java.util.function.BooleanSupplier replacing=()->{try{settled.invoke(null,replacement[0]);replacement[1]=claim.invoke(null,target,(java.util.function.BooleanSupplier)()->true);return true;}catch(Exception e){throw new RuntimeException(e);}};
  replacement[0]=claim.invoke(null,target,replacing);check(!(Boolean)shutdownOwns.invoke(null,token,replacement[0]),"delayed old shutdown cannot stop replacement route");apiSetter.invoke(target,forward,true);check(!(Boolean)getter.invoke(target,forward),"replacement during proof cannot authorize stale setter");
  quarantine.invoke(null,replacement[0]);apiSetter.invoke(target,forward,true);check((Boolean)getter.invoke(target,forward),"old callback cannot quarantine replacement owner");
  apiSetter.invoke(target,forward,false);settled.invoke(null,replacement[1]);
  java.util.function.BooleanSupplier stopInProof=()->{try{close.invoke(null);open.invoke(null);return true;}catch(Exception e){throw new RuntimeException(e);}};
  Object closingToken=claim.invoke(null,target,stopInProof);apiSetter.invoke(target,forward,true);
  check(!(Boolean)getter.invoke(target,forward),"bridge close/reopen inside last proof cannot authorize old write");settled.invoke(null,closingToken);
  System.out.println("ACTUAL_SETTER_EXECUTED direct and public API/user-forced variants; movement allowed; attack/use blocked; getter unchanged; false releases allowed");
 }
 public static void main(String[] args)throws Exception{
  lifecycleWiring();
  byte[] before=resource("baritone/fj.class");check(sha(before).equals("98e6529f3c0d15278aedd9818c6ec9c811c118bfe33c1618ade6620e1c013a7f"),"official actual target pin");
  check(sha(resource("baritone/api/utils/input/Input.class")).equals("372f3447d0039931898e924f912873aeec34999e5fe00341462e0d3095c54480"),"actual Input enum pin");
  ClassNode original=new ClassNode();new ClassReader(before).accept(original,0);
  if(args.length>1){original.methods.removeIf(m->m.name.equals("setInputForceState"));ClassWriter w=new ClassWriter(0);original.accept(w);before=w.toByteArray();}
  MixinBootstrap.init();OfflineMixinService service=(OfflineMixinService)MixinService.getService();service.enterDefaultPhase();
  MixinEnvironment env=MixinEnvironment.getDefaultEnvironment().setSide(MixinEnvironment.Side.CLIENT);Mixins.addConfiguration("mineclient_bridge.baritone.mixins.json");
  byte[] after=service.createTransformer().transformClass(env,"baritone.fj",before);check(!Arrays.equals(before,after),"real target transformed");
  ClassNode node=new ClassNode();new ClassReader(after).accept(new CheckClassAdapter(node,true),0);
  check(ops(method(original,"isInputForcedDown")).equals(ops(method(node,"isInputForcedDown"))),"actual getter instructions unchanged");
  MethodNode setter=method(node,"setInputForceState");List<String> instructions=ops(setter);int gate=-1,put=-1,query=-1,exit=-1;
  for(int i=0;i<instructions.size();i++){String op=instructions.get(i);if(op.contains("mdc$walkingInput"))gate=i;if(op.contains("isCancelled"))query=i;if(op.equals(Opcodes.RETURN+":"))exit=i;if(op.contains("java/util/Map.put"))put=i;}
  check(gate>=0&&query>gate&&put>query,"gate and cancellation query precede actual map write");
  boolean earlyReturn=false;for(int i=query+1;i<put;i++)if(instructions.get(i).equals(Opcodes.RETURN+":"))earlyReturn=true;
  check(earlyReturn,"cancelled branch returns before original effect");
  Path out=Path.of(args[0]);Files.createDirectories(out);Files.write(out.resolve("InputOverrideHandler-transformed.class"),after);Files.write(out.resolve("applied-mixins.txt"),OfflineMixinService.applied);
  check(OfflineMixinService.applied.size()==1,"one actual optional mixin applied");executable(node);
  Class<?> plugin=Class.forName("io.github.campione01.mineclientbridge.mixin.OptionalBaritoneMixinPlugin");Method supported=plugin.getDeclaredMethod("supported",ClassLoader.class);supported.setAccessible(true);
  check(!(Boolean)supported.invoke(null,new ClassLoader(null){public InputStream getResourceAsStream(String name){return null;}}),"missing API fails closed");
  check(!(Boolean)supported.invoke(null,new ClassLoader(null){public InputStream getResourceAsStream(String name){return new ByteArrayInputStream(new byte[]{1,2,3});}}),"wrong official bytes fail closed");
  check(OfflineMixinService.attemptedLoads.isEmpty(),"no game class load attempted by bytecode service");
  System.out.println("ManagedInputProbe "+checks+" checks passed; transformed sha="+sha(after));
 }
}

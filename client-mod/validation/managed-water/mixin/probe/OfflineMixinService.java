package probe;
import java.io.*;
import java.net.*;
import java.util.*;
import org.objectweb.asm.*;
import org.objectweb.asm.tree.*;
import org.spongepowered.asm.service.*;
import org.spongepowered.asm.mixin.*;
import org.spongepowered.asm.mixin.transformer.*;
import org.spongepowered.asm.launch.platform.container.*;
import org.spongepowered.asm.logging.*;

/** Bytecode-only Mixin SPI. Never defines or initializes game or production classes. */
public final class OfflineMixinService extends MixinServiceAbstract implements IClassProvider, IClassBytecodeProvider, ITransformerProvider, IClassTracker, IMixinAuditTrail {
 public static final List<String> applied = new ArrayList<>();
 public static final List<String> attemptedLoads = new ArrayList<>();
 private org.spongepowered.asm.util.IConsumer<MixinEnvironment.Phase> phaseConsumer;
 public void wire(MixinEnvironment.Phase phase,org.spongepowered.asm.util.IConsumer<MixinEnvironment.Phase> consumer){this.phaseConsumer=consumer;super.wire(phase,consumer);}
 public void enterDefaultPhase(){if(phaseConsumer==null)throw new IllegalStateException("No Mixin phase callback");phaseConsumer.accept(MixinEnvironment.Phase.DEFAULT);}
 public String getName(){return "MDC-offline-bytecode-probe";}
 public boolean isValid(){return true;}
 public MixinEnvironment.Phase getInitialPhase(){return MixinEnvironment.Phase.PREINIT;}
 public IClassProvider getClassProvider(){return this;}
 public IClassBytecodeProvider getBytecodeProvider(){return this;}
 public ITransformerProvider getTransformerProvider(){return this;}
 public IClassTracker getClassTracker(){return this;}
 public IMixinAuditTrail getAuditTrail(){return this;}
 public Collection<String> getPlatformAgents(){return Collections.emptyList();}
 public IContainerHandle getPrimaryContainer(){return new ContainerHandleVirtual("MDC-offline-bytecode-probe");}
 public InputStream getResourceAsStream(String name){return getClass().getClassLoader().getResourceAsStream(name);}
 public URL[] getClassPath(){return new URL[0];}
 public Class<?> findClass(String name)throws ClassNotFoundException{return findClass(name,false);}
 public Class<?> findClass(String name,boolean initialize)throws ClassNotFoundException{
  if(name.startsWith("net.minecraft.")||name.startsWith("io.github.campione01.")&&!name.endsWith(".OptionalBaritoneMixinPlugin")){
   attemptedLoads.add(name+" initialize="+initialize);throw new ClassNotFoundException("Game/production loading prohibited by offline probe: "+name);
  }
  return Class.forName(name,initialize,getClass().getClassLoader());
 }
 public Class<?> findAgentClass(String name,boolean initialize)throws ClassNotFoundException{return findClass(name,initialize);}
 public ClassNode getClassNode(String name)throws ClassNotFoundException,IOException{return getClassNode(name,false,0);}
 public ClassNode getClassNode(String name,boolean transform)throws ClassNotFoundException,IOException{return getClassNode(name,transform,0);}
 public ClassNode getClassNode(String name,boolean transform,int flags)throws ClassNotFoundException,IOException{
  String resource=name.replace('.','/')+".class";
  try(InputStream in=getResourceAsStream(resource)){
   if(in==null)throw new ClassNotFoundException(name);
   ClassNode node=new ClassNode();new ClassReader(in).accept(node,flags);return node;
  }
 }
 public Collection<ITransformer> getTransformers(){return Collections.emptyList();}
 public Collection<ITransformer> getDelegatedTransformers(){return Collections.emptyList();}
 public void addTransformerExclusion(String name){}
 public void registerInvalidClass(String name){}
 public boolean isClassLoaded(String name){return false;}
 public String getClassRestrictions(String name){return "";}
 public void onApply(String target,String mixin){String row=target+" <- "+mixin;applied.add(row);System.out.println("APPLIED "+row);}
 public void onPostProcess(String name){System.out.println("POST_PROCESS "+name);}
 public void onGenerate(String name,String generator){System.out.println("GENERATED "+name+" by "+generator);}
 protected ILogger createLogger(String name){return new LoggerAdapterConsole(name).setDebugStream(System.err);}
 public IMixinTransformer createTransformer(){return getInternal(IMixinTransformerFactory.class).createTransformer();}
}

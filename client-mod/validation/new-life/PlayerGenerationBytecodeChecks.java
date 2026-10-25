package probe;
import java.nio.file.*;
import java.util.*;
import org.objectweb.asm.*;
import org.objectweb.asm.tree.*;

/** Reads actual compiled exporter bytecode without initializing Minecraft. */
public final class PlayerGenerationBytecodeChecks {
 private static int checks;
 private static void check(boolean value,String reason){checks++;if(!value)throw new AssertionError(reason);}
 private static final String OWNER="io/github/campione01/mineclientbridge/PlayerGeneration";
 private static void validate(MethodNode method){
  List<AbstractInsnNode> insns=Arrays.asList(method.instructions.toArray());
  int current=-1,frame=-1,matches=-1,generation=-1,health=-1,alive=-1,reader=-1;
  for(int i=0;i<insns.size();i++){
   AbstractInsnNode in=insns.get(i);
   if(in instanceof MethodInsnNode call){
    if(call.owner.equals(OWNER)&&call.name.equals("current"))current=i;
    if(call.owner.equals(OWNER)&&call.name.equals("frameCurrent"))frame=i;
    if(call.owner.equals(OWNER)&&call.name.equals("matches"))matches=i;
    if(call.name.equals("getHealth"))health=i;
    if(call.name.equals("isAlive"))alive=i;
   }
   if(in instanceof LdcInsnNode value){
    if("generation_schema_version".equals(value.cst))generation=i;
    if(value.cst instanceof Type type&&type.getInternalName().equals("net/minecraft/network/syncher/SynchedEntityData"))reader=i;
   }
  }
  check(current>=0&&reader>current,"missing generation/original-reader admission");
  check(health>reader&&alive>health,"health getters precede reader admission");
  check(frame>alive&&matches>frame&&generation>matches,"missing or reordered final identity fence");
  int uuidReads=0,levelReads=0;boolean returnBranch=false;
  for(int i=alive+1;i<generation;i++){
   AbstractInsnNode in=insns.get(i);
   if(in instanceof MethodInsnNode call){if(call.name.equals("getUUID"))uuidReads++;if(call.name.equals("level"))levelReads++;}
   if(i>frame&&in instanceof JumpInsnNode jump&&jump.getOpcode()==Opcodes.IFEQ)returnBranch=true;
  }
  check(uuidReads==1&&levelReads==1&&returnBranch,"final player UUID/level or failure branch missing");
 }
 public static void main(String[] args)throws Exception{
  ClassNode c=new ClassNode();new ClassReader(Files.readAllBytes(Path.of(args[0]))).accept(c,0);
  MethodNode target=c.methods.stream().filter(m->m.name.equals("createStateSnapshot")&&m.desc.contains("CompactObservation$Diagnostic")).findFirst().orElseThrow();
  validate(target);
  MethodInsnNode removed=null;
  for(AbstractInsnNode in:target.instructions.toArray())if(in instanceof MethodInsnNode call&&call.owner.equals(OWNER)&&call.name.equals("frameCurrent")){removed=call;break;}
  check(removed!=null,"no frame call for negative");target.instructions.remove(removed);
  boolean refused=false;try{validate(target);}catch(AssertionError expected){refused=true;}
  check(refused,"missing-final-frame negative accepted");
  System.out.println("Actual exporter bytecode checks="+checks+"; Minecraft initialized=false; missing-frame negative refused=true");
 }
}

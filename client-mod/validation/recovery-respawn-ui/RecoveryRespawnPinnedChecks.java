package io.github.campione01.mineclientbridge;
import java.nio.file.*;
import java.util.*;
import java.util.jar.*;
import org.objectweb.asm.*;
import org.objectweb.asm.tree.*;
/** Independent pinned bytecode checks; never loads or initializes Minecraft classes. */
public final class RecoveryRespawnPinnedChecks {
 static int n;static void check(boolean b,String s){if(!b)throw new AssertionError(s);n++;}
 static ClassNode read(JarFile jar,String name)throws Exception{var node=new ClassNode();new ClassReader(jar.getInputStream(jar.getJarEntry(name+".class"))).accept(node,0);return node;}
 static MethodNode method(ClassNode c,String name,String desc){return c.methods.stream().filter(m->m.name.equals(name)&&m.desc.equals(desc)).findFirst().orElseThrow();}
 static List<String> calls(MethodNode m){var a=new ArrayList<String>();for(var i:m.instructions)if(i instanceof MethodInsnNode x)a.add(x.owner+"."+x.name+x.desc);return a;}
 public static void main(String[] a)throws Exception{
  try(var j=new JarFile(a[0])){
   var button=read(j,"net/minecraft/client/gui/components/Button");var onPress=method(button,"onPress","()V");check(calls(onPress).equals(List.of("net/minecraft/client/gui/components/Button$OnPress.onPress(Lnet/minecraft/client/gui/components/Button;)V")),"exact Button.onPress only original callback");
   var death=read(j,"net/minecraft/client/gui/screens/DeathScreen");var lambda=method(death,"lambda$init$0","(Lnet/minecraft/client/gui/components/Button;)V");check(calls(lambda).equals(List.of("net/minecraft/client/player/LocalPlayer.respawn()V")),"respawn lambda only vanilla lifecycle call");boolean disables=false;for(var i:lambda.instructions)if(i instanceof FieldInsnNode f&&f.getOpcode()==Opcodes.PUTFIELD&&f.owner.equals("net/minecraft/client/gui/components/Button")&&f.name.equals("active"))disables=true;check(disables,"lambda disables originalbutton");
   var init=method(death,"init","()V");List<String> strings=new ArrayList<>();for(var i:init.instructions)if(i instanceof LdcInsnNode l&&l.cst instanceof String s)strings.add(s);check(strings.indexOf("deathScreen.respawn")>=0&&strings.indexOf("deathScreen.respawn")<strings.indexOf("deathScreen.titleScreen"),"respawn first native button");check(calls(init).stream().filter(s->s.contains("Button.builder")).count()==2,"two native buttons");
   var player=read(j,"net/minecraft/client/player/LocalPlayer");var respawn=method(player,"respawn","()V");var rc=calls(respawn);check(rc.stream().anyMatch(s->s.contains("ClientPacketListener.send")),"vanilla respawn packet send");check(rc.stream().anyMatch(s->s.contains("KeyMapping.resetToggleKeys")),"vanilla reset toggles");boolean action=false;for(var i:respawn.instructions)if(i instanceof FieldInsnNode f&&f.name.equals("PERFORM_RESPAWN"))action=true;check(action,"vanilla PERFORM_RESPAWN action");check(rc.stream().noneMatch(s->s.contains("setHealth")||s.contains("setPos")),"no local state cheat in lifecycle entry");
   var listener=read(j,"net/minecraft/client/multiplayer/ClientPacketListener");var received=method(listener,"handleRespawn","(Lnet/minecraft/network/protocol/game/ClientboundRespawnPacket;)V");var calls=calls(received);check(calls.getFirst().contains("PacketUtils.ensureRunningOnSameThread"),"respawn reply on game thread");check(calls.stream().anyMatch(s->s.contains("MultiPlayerGameMode.createPlayer")),"reply creates new player");int playerIndex=-1,screenIndex=-1,index=0;for(var i:received.instructions){if(i instanceof FieldInsnNode f&&f.getOpcode()==Opcodes.PUTFIELD&&f.owner.equals("net/minecraft/client/Minecraft")&&f.name.equals("player"))playerIndex=index;if(i instanceof MethodInsnNode m&&m.owner.equals("net/minecraft/client/Minecraft")&&m.name.equals("setScreen"))screenIndex=index;index++;}check(playerIndex>=0&&screenIndex>playerIndex,"newplayer assignment precedes DeathScreen close");
  }
  System.out.println("RecoveryRespawnPinnedChecks PASS assertions="+n+"; bytecode only, no native initialization");
 }
}

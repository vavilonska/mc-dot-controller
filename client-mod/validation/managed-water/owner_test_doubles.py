"""Controlled source-only dependency doubles for ManagedWaterOwnerProbe.

These deliberately do not certify world snapshots, movement geometry, settings
restoration internals, or real Baritone bytecode. The native owner control itself
is compiled from the actual production source, never copied into this module.
"""

SOURCES = {
'net/minecraft/world/phys/Vec3.java': '''package net.minecraft.world.phys;
public class Vec3 { public final double x,y,z; public static final Vec3 ZERO=new Vec3(0,0,0);
 public Vec3(double x,double y,double z){this.x=x;this.y=y;this.z=z;} }
''',
'net/minecraft/world/level/GameType.java': '''package net.minecraft.world.level;
public enum GameType { SURVIVAL, CREATIVE }
''',
'net/minecraft/client/multiplayer/MultiPlayerGameMode.java': '''package net.minecraft.client.multiplayer;
public class MultiPlayerGameMode { public net.minecraft.world.level.GameType mode=net.minecraft.world.level.GameType.SURVIVAL;
 public net.minecraft.world.level.GameType getPlayerMode(){return mode;} }
''',
'net/minecraft/client/multiplayer/ClientLevel.java': '''package net.minecraft.client.multiplayer;
public class ClientLevel { public long tick=10; public String world="world-1"; public long getGameTime(){return tick;}
 public Dimension dimension(){return new Dimension();}
 public static final class Dimension {public String location(){return "minecraft:overworld";}} }
''',
'net/minecraft/client/player/LocalPlayer.java': '''package net.minecraft.client.player;
import io.github.campione01.mineclientbridge.*;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.world.phys.Vec3;
public class LocalPlayer implements ManagedDryInputFence,ManagedDryTravelFence,ManagedDryAccelerationFence {
 public java.util.UUID uuid=java.util.UUID.fromString("12345678-1234-1234-1234-123456789abc");
 public ClientLevel world; public double x=.5,y=70,z=.5; public float health=20,fallDistance,xxa,zza;
 public boolean ground=true,alive=true,passenger,fallFlying,water,lava,fire;
 public int air=300; public Vec3 delta=Vec3.ZERO; public Input input=new Input(); public Abilities abilities=new Abilities();
 public LocalPlayer(ClientLevel level){world=level;} public java.util.UUID getUUID(){return uuid;}
 public ClientLevel level(){return world;} public double getX(){return x;} public double getY(){return y;} public double getZ(){return z;}
 public float getHealth(){return health;} public boolean onGround(){return ground;} public boolean isAlive(){return alive;}
 public boolean isPassenger(){return passenger;} public boolean isFallFlying(){return fallFlying;}
 public boolean isInWater(){return water;} public boolean isInLava(){return lava;} public boolean isOnFire(){return fire;}
 public int getAirSupply(){return air;} public Abilities getAbilities(){return abilities;}
 public Vec3 getDeltaMovement(){OwnerHarnessState.motionReads++;OwnerHarnessState.onMotionRead.run();return delta;}
 public static final class Input {public float forwardImpulse,leftImpulse; public boolean jumping,shiftKeyDown;}
 public static final class Abilities {public boolean flying;}
}
''',
'net/minecraft/client/Minecraft.java': '''package net.minecraft.client;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.client.multiplayer.*;
public class Minecraft { private static Minecraft instance;
 public LocalPlayer player; public ClientLevel level; public MultiPlayerGameMode gameMode; public Object screen;
 public boolean sameThread=true,window=true,paused;
 public static Minecraft getInstance(){return instance;} public static void install(Minecraft value){instance=value;}
 public boolean isSameThread(){return sameThread;} public boolean isWindowActive(){return window;} public boolean isPaused(){return paused;}
}
''',
'baritone/api/pathing/goals/Goal.java': '''package baritone.api.pathing.goals; public interface Goal {}''',
'baritone/api/pathing/goals/GoalBlock.java': '''package baritone.api.pathing.goals;
public final class GoalBlock implements Goal {public final int x,y,z;public GoalBlock(int x,int y,int z){this.x=x;this.y=y;this.z=z;}}
''',
'baritone/api/process/ICustomGoalProcess.java': '''package baritone.api.process;
public interface ICustomGoalProcess {void setGoalAndPath(baritone.api.pathing.goals.Goal goal);}
''',
'baritone/api/behavior/IPathingBehavior.java': '''package baritone.api.behavior;
public interface IPathingBehavior {boolean cancelEverything();}
''',
'baritone/api/IBaritone.java': '''package baritone.api;
public interface IBaritone {baritone.api.process.ICustomGoalProcess getCustomGoalProcess();
 baritone.api.behavior.IPathingBehavior getPathingBehavior(); Object getInputOverrideHandler();}
''',
'baritone/api/IBaritoneProvider.java': '''package baritone.api;
public interface IBaritoneProvider {IBaritone getPrimaryBaritone();}
''',
'baritone/api/BaritoneAPI.java': '''package baritone.api;
public final class BaritoneAPI {public static baritone.BaritoneProvider provider=new baritone.BaritoneProvider();
 public static IBaritoneProvider getProvider(){return provider;}}
''',
'baritone/BaritoneProvider.java': '''package baritone;
public final class BaritoneProvider implements baritone.api.IBaritoneProvider {
 public final a primary=new a();public baritone.api.IBaritone getPrimaryBaritone(){return primary;}}
''',
'baritone/a.java': '''package baritone;
public final class a implements baritone.api.IBaritone {public final ea process=new ea();public final i path=new i();public final fj input=new fj();
 public baritone.api.process.ICustomGoalProcess getCustomGoalProcess(){return process;}
 public baritone.api.behavior.IPathingBehavior getPathingBehavior(){return path;}public Object getInputOverrideHandler(){return input;}}
''',
'baritone/ea.java': '''package baritone;
import io.github.campione01.mineclientbridge.OwnerHarnessState;
public final class ea implements baritone.api.process.ICustomGoalProcess {
 public void setGoalAndPath(baritone.api.pathing.goals.Goal goal){OwnerHarnessState.startCalls++;
  OwnerHarnessState.customActive=true;OwnerHarnessState.idle=false;OwnerHarnessState.onStart.run();
  if(OwnerHarnessState.throwStart)throw new IllegalStateException("start effect result unavailable");}}
''',
'baritone/i.java': '''package baritone;
import io.github.campione01.mineclientbridge.OwnerHarnessState;
public final class i implements baritone.api.behavior.IPathingBehavior {public boolean cancelEverything(){
 OwnerHarnessState.cancelCalls++;OwnerHarnessState.onCancel.run();
 if(OwnerHarnessState.throwCancel)throw new IllegalStateException("cancel effect result unavailable");
 return OwnerHarnessState.cancelAccepted;}}
''',
'baritone/fj.java': '''package baritone;
public final class fj implements io.github.campione01.mineclientbridge.ManagedNavigationInputFence {}
''',
'io/github/campione01/mineclientbridge/OwnerHarnessState.java': '''package io.github.campione01.mineclientbridge;
public final class OwnerHarnessState {
 public static final Runnable NOTHING=()->{};
 public static Runnable onStart=NOTHING,onCancel=NOTHING,onProof=NOTHING,onSettings=NOTHING,onDryUnchanged=NOTHING,onMotionRead=NOTHING;
 public static int startCalls,cancelCalls,dryCaptures,dryUnchanged,settingsRestores,motionReads;
 public static double pendingJump;public static boolean requiredStep;public static net.minecraft.world.phys.Vec3 pendingMotion;
 public static boolean throwStart,throwCancel,cancelAccepted,customActive,idle=true,exactOwner=true,
  settingsOkay=true,staleDry,bridge=true,externalBlocked,runtimeAction,fallBlocked,heldInputs,privateWorld=true;
 public static Object observedInput; public static long revision; public static String session="session-1",movementOwner;
 public static void reset(){onStart=onCancel=onProof=onSettings=onDryUnchanged=onMotionRead=NOTHING;
  startCalls=cancelCalls=dryCaptures=dryUnchanged=settingsRestores=motionReads=0;pendingJump=0;requiredStep=false;pendingMotion=null;
  throwStart=throwCancel=cancelAccepted=customActive=staleDry=externalBlocked=runtimeAction=fallBlocked=heldInputs=false;
  idle=exactOwner=settingsOkay=bridge=privateWorld=true;observedInput=null;revision=0;session="session-1";movementOwner=null;}
}
''',
'io/github/campione01/mineclientbridge/NativeDependencies.java': '''package io.github.campione01.mineclientbridge;
import com.google.gson.JsonObject;
import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.player.LocalPlayer;
final class ClientActions {static long externalOwnerRevision(){return OwnerHarnessState.revision;}
 static String session(){return OwnerHarnessState.session;}static boolean hasRuntimeAction(){return OwnerHarnessState.runtimeAction;}}
final class WorldGeneration {static String current(ClientLevel level){return level.world;}
 static boolean matches(ClientLevel level,String world){return level.world.equals(world);}}
final class BridgeServer {static boolean isRunning(){return OwnerHarnessState.bridge;}
 static boolean hasHeldInputs(){return OwnerHarnessState.heldInputs;}
 static JsonObject heldInputsSnapshot(Minecraft mc){JsonObject j=new JsonObject();j.addProperty("neutral",!OwnerHarnessState.heldInputs);return j;}}
final class NativeExternalNavigation {static boolean blocksInput(){return OwnerHarnessState.externalBlocked;}}
final class NativeFallRescue {static boolean armedOrBlocked(){return OwnerHarnessState.fallBlocked;}}
final class CapabilityGuard {static boolean privateSingleplayer(Minecraft mc){return OwnerHarnessState.privateWorld;}}
final class GuardedGameMovement {static final Leases LEASES=new Leases();static final class Leases{Status status(){return new Status(OwnerHarnessState.movementOwner);}}
 record Status(String ownerRequestId){}}
final class ExternalControllerGuard {static boolean idle(Minecraft mc){return OwnerHarnessState.idle;}}
final class ClientActionRequest {static final class Rejected extends RuntimeException {final int code;Rejected(int code,String why){super(why);this.code=code;}}}
final class ManagedNavigationSettings {ManagedNavigationSettings(ClassLoader loader){} void install(){}
 boolean unchanged(){OwnerHarnessState.onSettings.run();return OwnerHarnessState.settingsOkay;}
 void restore(){OwnerHarnessState.settingsRestores++;}}
final class ManagedDryRoute {static void verify(){}}
final class ManagedDryWorld {
 record Decision(int checkedCells){}
 static final class Frame {final Decision decision=new Decision(3);
  void unchanged(Minecraft mc){OwnerHarnessState.dryUnchanged++;OwnerHarnessState.onDryUnchanged.run();
   if(OwnerHarnessState.staleDry)throw new IllegalStateException("managed_navigation_dry_snapshot_stale");}}
 static Frame capture(Minecraft mc,Object path,net.minecraft.world.phys.Vec3 pending,boolean requireStep){return capture(mc,path,pending,requireStep,0);}
 static Frame capture(Minecraft mc,Object path,net.minecraft.world.phys.Vec3 pending,boolean requireStep,double pendingJump){
  OwnerHarnessState.dryCaptures++;OwnerHarnessState.pendingJump=pendingJump;OwnerHarnessState.pendingMotion=pending;
  OwnerHarnessState.requiredStep=requireStep;return new Frame();}
}
final class ExternalControllerProof {
 record Context(Minecraft mc,LocalPlayer player,ClientLevel level,String session,String world,String uuid,long tick){}
 record ManagedProof(boolean exactOwner,boolean customActive,Object input,JsonObject external){}
 static ManagedProof managed(Context context,Object process,Object goal){JsonObject j=new JsonObject();boolean busy=!OwnerHarnessState.idle;
  j.addProperty("schema_version",1);j.addProperty("controller","baritone");j.addProperty("adapter","baritone-api-neoforge/1.11.3");
  j.addProperty("source_tick",context.tick());j.addProperty("source_nano",Long.toString(System.nanoTime()));
  j.addProperty("action_session",context.session());j.addProperty("world_generation",context.world());j.addProperty("player_uuid",context.uuid());
  j.addProperty("execution_authority",false);j.addProperty("status",busy?"busy":"idle");j.addProperty("supported",true);
  j.addProperty("idle_proven",!busy);j.addProperty("reason","modeled_external_proof_for_control_test");
  JsonObject facts=new JsonObject();facts.addProperty("instances",1);facts.addProperty("context_matches",true);
  facts.addProperty("is_pathing",busy);facts.addProperty("current_path",busy);facts.addProperty("next_path",false);facts.addProperty("planning",false);
  facts.addProperty("goal_present",busy);facts.addProperty("active_process_count",busy?1:0);facts.addProperty("registered_process_count",12);facts.addProperty("forced_input_count",busy?1:0);j.add("facts",facts);
  Object input=OwnerHarnessState.observedInput==null?baritone.api.BaritoneAPI.provider.primary.input:OwnerHarnessState.observedInput;
  var result=new ManagedProof(OwnerHarnessState.exactOwner,OwnerHarnessState.customActive,input,j);
  OwnerHarnessState.onProof.run();return result;}
}
''',
}

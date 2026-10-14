"""AUTHORING ONLY: materialize explicitly synthetic engine sources. No compilation or execution."""
from pathlib import Path
import sys
OUT=Path(sys.argv[1]).resolve()
P='io.github.campione01.mineclientbridge'
def put(name,body):
 p=OUT/Path(*name.split('.')).with_suffix('.java');p.parent.mkdir(parents=True,exist_ok=True);p.write_text('package '+name.rsplit('.',1)[0]+';\n'+body+'\n')
put(P+'.Hooks','''import java.util.*;
public final class Hooks {
 static final Map<String,Runnable> actions=new HashMap<>();static final Map<String,Integer> waits=new HashMap<>();
 public static final Map<String,Integer> calls=new HashMap<>();
 public static void reset(){actions.clear();waits.clear();calls.clear();}
 public static void once(String key,int skip,Runnable action){actions.put(key,action);waits.put(key,skip);}
 public static void fire(String key){calls.merge(key,1,Integer::sum);if(actions.containsKey(key)){int n=waits.get(key);if(n==0){Runnable a=actions.remove(key);waits.remove(key);a.run();}else waits.put(key,n-1);}}
}''')
put('net.minecraft.world.phys.Vec3','''public class Vec3 {public final double x,y,z;public Vec3(double x,double y,double z){this.x=x;this.y=y;this.z=z;}public double horizontalDistance(){return Math.hypot(x,z);}}''')
put('net.minecraft.world.phys.AABB','''public class AABB {public final double minX,minY,minZ,maxX,maxY,maxZ;public AABB(double a,double b,double c,double d,double e,double f){minX=a;minY=b;minZ=c;maxX=d;maxY=e;maxZ=f;}public double getXsize(){return maxX-minX;}public double getYsize(){return maxY-minY;}public double getZsize(){return maxZ-minZ;}}''')
put('net.minecraft.core.BlockPos','''public record BlockPos(int x,int y,int z) {}''')
put('net.minecraft.world.entity.EntityType','''public final class EntityType<T> {public final String id;private EntityType(String n){id="minecraft:"+n;}
 public static final EntityType<?> SHEEP=new EntityType<>("sheep"),COW=new EntityType<>("cow"),CHICKEN=new EntityType<>("chicken"),PIG=new EntityType<>("pig"),RABBIT=new EntityType<>("rabbit"),FROG=new EntityType<>("frog"),BOAT=new EntityType<>("boat"),CHEST_MINECART=new EntityType<>("chest_minecart"),ITEM=new EntityType<>("item");}''')
put('net.minecraft.world.entity.Entity','''import java.util.*;import net.minecraft.world.phys.*;
public class Entity {
 public int id=2,fireTicks;public UUID uuid=UUID.randomUUID();public EntityType<?> type=EntityType.ITEM;
 public double x=100,y=64,z=100,tx=100,ty=64,tz=100;public Vec3 velocity=new Vec3(0,0,0);
 public boolean removed,noPhysics,alive=true,onFire;public Entity vehicle;public List<Entity> passengers=new ArrayList<>();
 public int getId(){return id;}public UUID getUUID(){return uuid;}public EntityType<?> getType(){return type;}
 public boolean isRemoved(){return removed;}public boolean isAlive(){return alive;}public double getX(){return x;}public double getY(){return y;}public double getZ(){return z;}
 public AABB getBoundingBox(){return new AABB(x-.3,y,z-.3,x+.3,y+1.8,z+.3);}public Vec3 getDeltaMovement(){return velocity;}
 public double lerpTargetX(){return tx;}public double lerpTargetY(){return ty;}public double lerpTargetZ(){return tz;}
 public Entity getVehicle(){return vehicle;}public List<Entity> getPassengers(){return passengers;}public int getRemainingFireTicks(){return fireTicks;}
 public boolean getSharedFlag(int i){return onFire;}public boolean isOnFire(){return onFire;}
}''')
put('net.minecraft.world.entity.Leashable','''public interface Leashable {Object getLeashData();}''')
put('net.minecraft.world.entity.LivingEntity','''import java.util.*;public class LivingEntity extends Entity {public float health=20;public int hurtTime;public boolean dying;public List<Object> effects=new ArrayList<>();public float getHealth(){return health;}public boolean isDeadOrDying(){return dying;}public List<Object> getActiveEffects(){return effects;}}''')
put('net.minecraft.world.entity.Mob','''public class Mob extends LivingEntity {public Entity target;public Entity getTarget(){return target;}}''')
for cls,key in [('Sheep','SHEEP'),('Cow','COW'),('Chicken','CHICKEN'),('Pig','PIG'),('Rabbit','RABBIT')]:
 put('net.minecraft.world.entity.animal.'+cls,f'public class {cls} extends net.minecraft.world.entity.Mob {{public {cls}(){{type=net.minecraft.world.entity.EntityType.{key};}}}}')
put('net.minecraft.world.entity.animal.frog.Frog','''public class Frog extends net.minecraft.world.entity.Mob {public Frog(){type=net.minecraft.world.entity.EntityType.FROG;}}''')
for pkg,cls,key in [('vehicle','Boat','BOAT'),('vehicle','MinecartChest','CHEST_MINECART'),('item','ItemEntity','ITEM')]:
 put('net.minecraft.world.entity.'+pkg+'.'+cls,f'public class {cls} extends net.minecraft.world.entity.Entity {{public {cls}(){{type=net.minecraft.world.entity.EntityType.{key};}}}}')
put('net.minecraft.client.player.Input','''public class Input {public float forwardImpulse,leftImpulse;public boolean up,down,left,right,jumping,shiftKeyDown;}''')
put('net.minecraft.world.inventory.InventoryMenu','''public class InventoryMenu {public boolean carried;public Stack getCarried(){return new Stack(carried);}public record Stack(boolean occupied){public boolean isEmpty(){return !occupied;}}}''')
put('net.minecraft.world.entity.ai.attributes.Attributes','''public final class Attributes {public static final Object MOVEMENT_SPEED=new Object();}''')
put('net.minecraft.client.player.LocalPlayer','''import net.minecraft.world.entity.*;import net.minecraft.world.inventory.InventoryMenu;import io.github.campione01.mineclientbridge.Hooks;
public class LocalPlayer extends LivingEntity {
 public InventoryMenu inventoryMenu=new InventoryMenu(),containerMenu=inventoryMenu;public Input input=new Input();
 public boolean using,spectator,passenger,sprinting,ground=true,water,lava,isInPowderSnow,climbing,horizontalCollision;public float fallDistance,yaw,pitch,speed=.1f;public double attribute=.1;
 public final Abilities abilities=new Abilities();public static final class Abilities{public boolean flying;}
 public LocalPlayer(){id=1;x=.5;y=64;z=.5;tx=x;ty=y;tz=z;}
 public boolean isUsingItem(){return using;}public boolean isSpectator(){return spectator;}public boolean isPassenger(){return passenger;}public boolean isSprinting(){return sprinting;}public Abilities getAbilities(){return abilities;}
 public boolean onGround(){return ground;}public boolean isInWater(){return water;}public boolean isInLava(){return lava;}public boolean onClimbable(){return climbing;}
 public double getAttributeValue(Object ignored){Hooks.fire("attribute");return attribute;}public float getSpeed(){return speed;}public float getYRot(){return yaw;}public float getXRot(){return pitch;}
}''')
put('net.minecraft.world.level.GameType','''public enum GameType {SURVIVAL,CREATIVE}''')
put('net.minecraft.world.level.block.Block','''public class Block {public final String id;public Block(String id){this.id=id;}}''')
put('net.minecraft.world.level.block.GrassBlock','''public class GrassBlock extends Block {public GrassBlock(){super("minecraft:grass_block");}}''')
put('net.minecraft.core.registries.BuiltInRegistries','''import net.minecraft.world.level.block.Block;import net.minecraft.world.entity.EntityType;
public final class BuiltInRegistries {public static final Blocks BLOCK=new Blocks();public static final Entities ENTITY_TYPE=new Entities();public static class Blocks {public String getKey(Block b){return b.id;}}public static class Entities {public String getKey(EntityType<?> e){return e.id;}}}''')
put('net.minecraft.client.multiplayer.ClientLevel','''import java.util.*;import net.minecraft.core.BlockPos;import net.minecraft.world.entity.Entity;import net.minecraft.world.level.block.Block;import io.github.campione01.mineclientbridge.Hooks;
public class ClientLevel {
 public long time=195867;public boolean loaded=true,fluid,solid=true,air=true;public float friction=.6f;public String dimension="minecraft:overworld",floorId="minecraft:stone",airId="minecraft:air";public List<Entity> entities=new ArrayList<>();
 public long getGameTime(){Hooks.fire("gameTime");return time;}public Iterable<Entity> entitiesForRendering(){Hooks.fire("entities");return new ArrayList<>(entities);}
 public Dimension dimension(){return new Dimension(dimension);}public record Dimension(String name){public String location(){return name;}}
 public boolean hasChunkAt(BlockPos p){Hooks.fire("loaded");return loaded;}public State getBlockState(BlockPos p){Hooks.fire("state");return new State(p.y()==63);}
 public Fluid getFluidState(BlockPos p){return new Fluid(fluid);}public record Fluid(boolean filled){public boolean isEmpty(){return !filled;}}
 public final class State {final boolean floor;State(boolean f){floor=f;}public Block getBlock(){return new Block(floor?floorId:airId);}public boolean isCollisionShapeFullBlock(ClientLevel l,BlockPos p){Hooks.fire("shape");return solid;}public float getFriction(ClientLevel l,BlockPos p,Object player){Hooks.fire("friction");return friction;}public boolean isAir(){return air;}public Shape getCollisionShape(ClientLevel l,BlockPos p){Hooks.fire("shape");return new Shape(air);}public Fluid getFluidState(){return new Fluid(fluid);}public String toString(){return floor?floorId:airId;}}
 public record Shape(boolean empty){public boolean isEmpty(){return empty;}}
}''')
put('net.minecraft.client.Minecraft','''import net.minecraft.client.player.LocalPlayer;import net.minecraft.client.multiplayer.ClientLevel;import net.minecraft.world.level.GameType;
public class Minecraft {
 public LocalPlayer player=new LocalPlayer();public ClientLevel level=new ClientLevel();public Mode gameMode=new Mode();public Object server=new Object(),screen;public boolean sameThread=true,focused=true,paused,privateWorld=true;public Options options=new Options();
 public Minecraft(){level.entities.add(player);}public Object getSingleplayerServer(){return server;}public boolean isSameThread(){return sameThread;}public boolean isWindowActive(){return focused;}public boolean isPaused(){return paused;}
 public static class Mode {public GameType type=GameType.SURVIVAL;public GameType getPlayerMode(){return type;}}
 public static class Key {public boolean down;public boolean isDown(){return down;}}
 public static class Options {public Key keyUp=new Key(),keyDown=new Key(),keyLeft=new Key(),keyRight=new Key(),keyJump=new Key(),keySprint=new Key(),keyShift=new Key(),keyAttack=new Key(),keyUse=new Key();}
}''')
put(P+'.FixtureDependencies','''import net.minecraft.client.Minecraft;import com.google.gson.JsonObject;
final class CapabilityGuard {static boolean privateSingleplayer(Minecraft mc){return mc.privateWorld;}static void validate(ClientActionRequest r){}}
final class IntegratedServerIdentity {static String value="server";static String current(Object s,boolean p){return value;}}
final class WorldGeneration {static String value="world";static String current(Object l){return value;}}
final class NavigationPositionGuard {static long value;static long epoch(){return value;}}
final class BridgeServer {static boolean held;static boolean hasHeldInputs(){return held;}}
// Deliberately unavailable branches: T13 dynamics cover ordinary movement only.
// Actual collect/mining sources are separately compiled and checked natively.
final class ScopedCollectTarget {
 static final String PROFILE="collect-local-observed-v1";final String uuid=null;
 ScopedCollectTarget(Minecraft mc,ClientActionRequest request){throw new AssertionError("Collect engine branch is outside synthetic T13 coverage");}
 void assertCurrent(net.minecraft.client.multiplayer.ClientLevel level){throw new AssertionError("Collect engine branch is outside synthetic T13 coverage");}
 JsonObject facts(){throw new AssertionError("Collect engine branch is outside synthetic T13 coverage");}
}
final class ScopedMining {static final String PROFILE="mining-local-observed-v2";}
final class ScopedNativePreflight {static final long MAX_NANOS=250_000_000L;}
final class EncounterRequest {static final String PAUSE_ON_TERMINAL="encounter_pause_on_terminal";}
final class MovementBudget {static boolean budgetAction(String s){return false;}static void validate(ClientActionRequest r){}}
final class CapabilityGateway {static void validate(JsonObject o){}}
final class CapabilityTargetAction {static void validate(JsonObject o){}}
final class BoatTransferRequest {static void parse(JsonObject o){}}
final class BoatDriveRequest {static void parse(JsonObject o){}}
final class BoundedCombatRequest {static void parse(JsonObject o){}}
final class CoordinationStepGuard {static void validate(ClientActionRequest r){}}
''')
print('Authored synthetic fixture files only:',len(list(OUT.rglob('*.java'))))

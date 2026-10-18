"""Reader doubles only. No real engine physics execution is claimed."""
from pathlib import Path
import argparse,subprocess,sys
p=argparse.ArgumentParser();p.add_argument('output',type=Path);p.add_argument('--repo',type=Path,default=Path(__file__).resolve().parents[3]);a=p.parse_args()
root=a.repo.resolve();out=a.output.resolve()
subprocess.run([sys.executable,'-B',str(root/'client-mod/validation/step-down/prepare_engine.py'),str(out),'--repo',str(root)],check=True)
def edit(name,old,new):
 p=out/Path(*name.split('.')).with_suffix('.java');s=p.read_text();assert old in s,(name,old);p.write_text(s.replace(old,new))
edit('net.minecraft.world.entity.ai.attributes.Attributes','GRAVITY=new Object();','GRAVITY=new Object(),JUMP_STRENGTH=new Object();')
edit('net.minecraft.client.player.LocalPlayer','public double gravity=.08;','public double gravity=.08,jumpStrength=(double).42F;')
edit('net.minecraft.client.player.LocalPlayer','?gravity:attribute;','?gravity:ignored==net.minecraft.world.entity.ai.attributes.Attributes.JUMP_STRENGTH?jumpStrength:attribute;')
edit('net.minecraft.client.player.LocalPlayer','ma=new net.minecraft.world.entity.ai.attributes.AttributeInstance(()->this.attribute);','ma=new net.minecraft.world.entity.ai.attributes.AttributeInstance(()->this.attribute),ja=new net.minecraft.world.entity.ai.attributes.AttributeInstance(()->this.jumpStrength);')
edit('net.minecraft.client.player.LocalPlayer','?ga:ma;','?ga:k==net.minecraft.world.entity.ai.attributes.Attributes.JUMP_STRENGTH?ja:ma;')
edit('net.minecraft.client.multiplayer.ClientLevel','public class ClientLevel {','public class ClientLevel { public int dy;public boolean contextWall;')
edit('net.minecraft.client.multiplayer.ClientLevel','return new State(p.y()==-1 || p.x()==0 && p.y()==0 && p.z()==0);','return new State(p.y()==(dy<0?-1:0) || dy<0&&p.x()==0&&p.y()==0&&p.z()==0 || dy>0&&p.x()==1&&p.y()==1&&p.z()==0 || contextWall&&p.z()==1&&p.y()==1);')
edit('net.minecraft.client.multiplayer.ClientLevel','public boolean isAir(){return air;}','public boolean isAir(){return !floor&&air;}')
edit('net.minecraft.client.multiplayer.ClientLevel','return new Shape(air);','return new Shape(!floor&&air);')

p=out/"io/github/campione01/mineclientbridge/FixtureDependencies.java";p.write_text(p.read_text()+'\nfinal class ScopedStepDownMovement {static final String PROFILE="movement-step-down-observed-v1";}\n')

edit('net.minecraft.client.Minecraft','public class Minecraft {','public class Minecraft {static Minecraft instance;public static Minecraft getInstance(){return instance;}')
edit('net.minecraft.client.Minecraft','public Minecraft(){','public Minecraft(){instance=this;')
p=out/'net/minecraft/world/entity/MoverType.java';p.write_text('package net.minecraft.world.entity; public enum MoverType {SELF,PISTON,PLAYER;}')

for name in ('Barrel','Furnace'):
 p=out/('net/minecraft/world/level/block/'+name+'Block.java');p.write_text('package net.minecraft.world.level.block;public class '+name+'Block extends Block {public '+name+'Block(){super("minecraft:'+name.lower()+'");}}')

p=out/'net/minecraft/world/level/block/CraftingTableBlock.java';p.write_text('package net.minecraft.world.level.block;public class CraftingTableBlock extends Block {public CraftingTableBlock(){super("minecraft:crafting_table");}}')
p=out/'net/minecraft/world/level/block/RotatedPillarBlock.java';p.write_text('package net.minecraft.world.level.block;public class RotatedPillarBlock extends Block {public static final Object AXIS=new Object();public RotatedPillarBlock(String id){super(id);}}')

# A separately addressable context cell exercises real controller role/friction/state guards.
p=out/'net/minecraft/world/level/block/LeavesBlock.java';p.write_text('package net.minecraft.world.level.block;public class LeavesBlock extends Block {public LeavesBlock(String id){super(id);}}')
edit('net.minecraft.client.multiplayer.ClientLevel','public boolean contextWall;','public boolean contextWall;public String contextId="",contextState="";public boolean contextSolid=true,contextFluid;public float contextFriction=.6f;')
edit('net.minecraft.client.multiplayer.ClientLevel','contextWall&&p.z()==1&&p.y()==1);','contextWall&&p.z()==1&&p.y()==1,contextWall&&p.z()==1&&p.y()==1);')
edit('net.minecraft.client.multiplayer.ClientLevel','return new Fluid(fluid);','return new Fluid(fluid||contextFluid&&p.z()==1&&p.y()==1);')
edit('net.minecraft.client.multiplayer.ClientLevel','final boolean floor;State(boolean f){floor=f;}','final boolean floor,context;State(boolean f,boolean c){floor=f;context=c;}')
edit('net.minecraft.client.multiplayer.ClientLevel','return new Block(floor?floorId:airId);','return context&&!contextId.isEmpty()?new net.minecraft.world.level.block.LeavesBlock(contextId):new Block(floor?floorId:airId);')
edit('net.minecraft.client.multiplayer.ClientLevel','return solid;','return solid&&(!context||contextSolid);')
edit('net.minecraft.client.multiplayer.ClientLevel','return friction;','return context?contextFriction:friction;')
# Correct the state-local fluid reader after the global method replacement above.
edit('net.minecraft.client.multiplayer.ClientLevel','public Fluid getFluidState(){return new Fluid(fluid||contextFluid&&p.z()==1&&p.y()==1);}','public Fluid getFluidState(){return new Fluid(fluid||context&&contextFluid);}')
edit('net.minecraft.client.multiplayer.ClientLevel','return floor?floorId:airId;','return context&&!contextId.isEmpty()?contextId+contextState:floor?floorId:airId;')

# Interned immutable state doubles model the native BlockState identity fence. These are
# reader fixtures only, never a substitute for game collision or future leaf decay.
p=out/'net/minecraft/world/level/block/LeavesBlock.java';p.write_text('package net.minecraft.world.level.block;public class LeavesBlock extends Block {public static final Object DISTANCE=new Object(),PERSISTENT=new Object(),WATERLOGGED=new Object();public LeavesBlock(String id){super(id);}}')
p=out/'net/minecraft/client/multiplayer/ClientLevel.java';s=p.read_text()
s=s.replace('public boolean contextWall;','public boolean contextWall;public String contextBlockKind="";public int stateVersion;')
start=s.index('public State getBlockState(');end=s.index('\n public Fluid getFluidState',start)
s=s[:start]+'''public State getBlockState(BlockPos p){Hooks.fire("state");boolean c=contextWall&&p.z()==1&&p.y()==1;boolean f=p.y()==(dy<0?-1:0)||dy<0&&p.x()==0&&p.y()==0&&p.z()==0||dy>0&&p.x()==1&&p.y()==1&&p.z()==0||c;
 String id=c&&!contextId.isEmpty()?contextId:f?floorId:airId;String text=id+(c?contextState:"");boolean dry=!(fluid||c&&contextFluid),full=solid&&(!c||contextSolid),isair=!f&&air;float slip=c?contextFriction:friction;
 String key=text+"|"+f+"|"+c+"|"+dry+"|"+full+"|"+isair+"|"+slip+"|"+contextBlockKind+"|"+stateVersion;
 return states.computeIfAbsent(key,k->new State(f,c,id,text,dry,full,isair,slip));}
 private final Map<String,State> states=new HashMap<>();private final Map<String,Block> blocks=new HashMap<>();
''' +s[end:]
start=s.index(' public final class State');end=s.index('\n public record Shape',start)
s=s[:start]+''' public final class State {
 final boolean floor,context,dry,full,isair;final String id,text;final float slip;final Block block;final Map<Object,Object> values;
 State(boolean f,boolean c,String id,String text,boolean dry,boolean full,boolean isair,float slip){this.floor=f;this.context=c;this.id=id;this.text=text;this.dry=dry;this.full=full;this.isair=isair;this.slip=slip;
 block=blocks.computeIfAbsent(id+"|"+contextBlockKind,k->contextBlockKind.equals("plain")?new Block(id):id.endsWith("_leaves")?new net.minecraft.world.level.block.LeavesBlock(id):id.equals("minecraft:grass_block")?new net.minecraft.world.level.block.GrassBlock():id.equals("minecraft:barrel")?new net.minecraft.world.level.block.BarrelBlock():id.equals("minecraft:furnace")?new net.minecraft.world.level.block.FurnaceBlock():id.equals("minecraft:crafting_table")?new net.minecraft.world.level.block.CraftingTableBlock():id.endsWith("_log")?new net.minecraft.world.level.block.RotatedPillarBlock(id):new Block(id));
 var v=new HashMap<Object,Object>();if(id.endsWith("_log"))v.put(net.minecraft.world.level.block.RotatedPillarBlock.AXIS,"y");if(id.endsWith("_leaves")){v.put(net.minecraft.world.level.block.LeavesBlock.DISTANCE,1);v.put(net.minecraft.world.level.block.LeavesBlock.PERSISTENT,false);v.put(net.minecraft.world.level.block.LeavesBlock.WATERLOGGED,false);}
 if(id.equals("minecraft:grass_block"))v.put(net.minecraft.world.level.block.SnowyDirtBlock.SNOWY,false);
 int open=text.indexOf('[');if(open>=0&&text.endsWith("]"))for(String item:text.substring(open+1,text.length()-1).split(",")){String[] pair=item.split("=",2);if(pair.length==2){Object prop=switch(pair[0]){case "axis"->net.minecraft.world.level.block.RotatedPillarBlock.AXIS;case "distance"->net.minecraft.world.level.block.LeavesBlock.DISTANCE;case "persistent"->net.minecraft.world.level.block.LeavesBlock.PERSISTENT;case "waterlogged"->net.minecraft.world.level.block.LeavesBlock.WATERLOGGED;case "snowy"->net.minecraft.world.level.block.SnowyDirtBlock.SNOWY;default->pair[0].intern();};Object value=pair[1].equals("true")?Boolean.TRUE:pair[1].equals("false")?Boolean.FALSE:pair[0].equals("distance")?Integer.valueOf(pair[1]):pair[1];v.put(prop,value);}}
 values=Map.copyOf(v);}
 public Block getBlock(){return block;}public Map<Object,Object> getValues(){return values;}
 public boolean isCollisionShapeFullBlock(ClientLevel l,BlockPos p){Hooks.fire("shape");return full;}
 public float getFriction(ClientLevel l,BlockPos p,Object player){Hooks.fire("friction");return slip;}
 public boolean isAir(){return isair;}public Shape getCollisionShape(ClientLevel l,BlockPos p){Hooks.fire("shape");return new Shape(isair);}
 public Fluid getFluidState(){return new Fluid(!dry);}public String toString(){return text;}}
''' +s[end:]
p.write_text(s)

p=out/"net/minecraft/world/level/block/SnowyDirtBlock.java";p.write_text('package net.minecraft.world.level.block;public class SnowyDirtBlock extends Block {public static final Object SNOWY=new Object();public SnowyDirtBlock(){super("minecraft:grass_block");}}')

"""Explicit synthetic engine readers; production descent policy/controller/owner queries stay unchanged."""
from pathlib import Path
import argparse,subprocess,sys
p=argparse.ArgumentParser();p.add_argument('output',type=Path);p.add_argument('--repo',type=Path,default=Path(__file__).resolve().parents[3]);a=p.parse_args()
out=a.output.resolve();repo=a.repo.resolve()
if out==repo or repo in out.parents or out.exists():raise ValueError('Synthetic output must be a new directory outside the checkout')
base=repo/'client-mod/validation/movement-t13/prepare_engine_fixtures.py' 
subprocess.run([sys.executable,str(base),str(out)],check=True)
def edit(name,a,b):
 p=out/Path(*name.split('.')).with_suffix('.java');s=p.read_text();assert a in s,(name,a);p.write_text(s.replace(a,b))
edit('net.minecraft.world.entity.ai.attributes.Attributes','MOVEMENT_SPEED=new Object();','MOVEMENT_SPEED=new Object(),GRAVITY=new Object();')
edit('net.minecraft.client.player.LocalPlayer','public boolean using,','public boolean noGravity,autoJump,fallFlying,swimming,crouching;public int autoJumpTime;public double gravity=.08;public Food food=new Food();public static class Food{public int level=20;public int getFoodLevel(){return level;}}public Food getFoodData(){return food;}public boolean isNoGravity(){return noGravity;}public boolean isAutoJumpEnabled(){return autoJump;}public boolean isFallFlying(){return fallFlying;}public boolean isSwimming(){return swimming;}public boolean isCrouching(){return crouching;}\n public boolean using,')
edit('net.minecraft.client.player.LocalPlayer','public boolean flying;','public boolean flying,mayfly;')
edit('net.minecraft.client.player.LocalPlayer','Hooks.fire("attribute");return attribute;','Hooks.fire("attribute");return ignored==net.minecraft.world.entity.ai.attributes.Attributes.GRAVITY?gravity:attribute;')
edit('net.minecraft.client.player.LocalPlayer','x=.5;y=64;z=.5;','x=.5;y=1;z=.5;')
edit('net.minecraft.client.multiplayer.ClientLevel','return new State(p.y()==63);','return new State(p.y()==-1 || p.x()==0 && p.y()==0 && p.z()==0);')
edit('net.minecraft.client.Minecraft','public static class Options {','public static class Options {public boolean autoJump;public Value autoJump(){return new Value(autoJump);}public record Value(boolean value){public boolean get(){return value;}}')
edit('io.github.campione01.mineclientbridge.FixtureDependencies','final class MovementBudget {','final class MovementBudget {static boolean active;static JsonObject snapshot(){JsonObject j=new JsonObject();j.addProperty("schema_version",1);j.addProperty("status",active?"observing":"unarmed");return j;}')
def put(name,body):
 p=out/Path(*name.split('.')).with_suffix('.java');p.parent.mkdir(parents=True,exist_ok=True);p.write_text('package '+name.rsplit('.',1)[0]+';\n'+body+'\n')
put('net.minecraft.world.entity.ai.attributes.AttributeInstance','public class AttributeInstance {public java.util.function.DoubleSupplier source;public AttributeInstance(java.util.function.DoubleSupplier s){source=s;}public double getBaseValue(){return source.getAsDouble();}public java.util.Set<Object> getModifiers(){return java.util.Set.of();}}')
put('net.minecraft.world.entity.ai.attributes.AttributeMap','public class AttributeMap {}')
edit('net.minecraft.client.player.LocalPlayer','public boolean noGravity,','public net.minecraft.world.entity.ai.attributes.AttributeMap attrs=new net.minecraft.world.entity.ai.attributes.AttributeMap();public net.minecraft.world.entity.ai.attributes.AttributeInstance ga=new net.minecraft.world.entity.ai.attributes.AttributeInstance(()->this.gravity),ma=new net.minecraft.world.entity.ai.attributes.AttributeInstance(()->this.attribute);public net.minecraft.world.entity.ai.attributes.AttributeMap getAttributes(){return attrs;}public net.minecraft.world.entity.ai.attributes.AttributeInstance getAttribute(Object k){return k==net.minecraft.world.entity.ai.attributes.Attributes.GRAVITY?ga:ma;}public boolean noGravity,')

put("io.github.campione01.mineclientbridge.ScopedFlatMovement",'final class ScopedFlatMovement {static final String PROFILE="movement-flat-observed-v2";}')

# Deterministic generated metadata, not an installed-world clock or observed identity.
p=out/'net/minecraft/client/multiplayer/ClientLevel.java'
s=p.read_text();import re
s,count=re.subn(r'public long time=\d+;', 'public long time=100;', s);assert count==1
p.write_text(s)
p=out/'net/minecraft/world/entity/Entity.java'
s=p.read_text().replace('UUID.randomUUID()', 'UUID.fromString("00000000-0000-0000-0000-00000000fff1")')
p.write_text(s)

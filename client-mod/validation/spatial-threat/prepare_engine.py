"""Explicit synthetic client/server readers. Production spatial readers/policy/controller are unchanged."""
from pathlib import Path
import subprocess,sys,argparse
p=argparse.ArgumentParser();p.add_argument('output',type=Path);p.add_argument('--repo',type=Path,default=Path(__file__).resolve().parents[3]);a=p.parse_args()
out=a.output.resolve();repo=a.repo.resolve()
subprocess.run([sys.executable,'-B',str(repo/'client-mod/validation/local-segment/prepare_engine.py'),str(out),'--repo',str(repo)],check=True)
def edit(name,old,new):
 p=out/Path(*name.split('.')).with_suffix('.java');s=p.read_text();assert old in s,(name,old);p.write_text(s.replace(old,new))
def put(name,text):
 p=out/Path(*name.split('.')).with_suffix('.java');p.parent.mkdir(parents=True,exist_ok=True);p.write_text('package '+name.rsplit('.',1)[0]+';\n'+text+'\n')
edit('net.minecraft.world.entity.EntityType','ITEM=new EntityType<>("item")','ITEM=new EntityType<>("item"),ZOMBIE=new EntityType<>("zombie")')
put('net.minecraft.world.entity.monster.Zombie','public class Zombie extends net.minecraft.world.entity.Mob {public Zombie(){type=net.minecraft.world.entity.EntityType.ZOMBIE;}}')
put('io.github.campione01.mineclientbridge.NativeLivingObservation','''
import com.google.gson.*;import java.util.*;import net.minecraft.client.Minecraft;import net.minecraft.world.entity.Entity;
/** Server thread acquisition is synthetic; immutable store, expiry and JSON are production NativeLivingSnapshot. */
final class NativeLivingObservation {
 static final NativeLivingSnapshot.Store STORE=new NativeLivingSnapshot.Store();static Object context;
 record Frame(Object context,NativeLivingSnapshot.Batch batch){}
 static void reset(){context=new Object();STORE.replace(context);}
 static Frame capture(Minecraft mc){return new Frame(context,STORE.snapshot());}
 static NativeLivingSnapshot.BeeFence equivalentBeeBatch(Frame f,List<String> uuids,long tick){return f==null?NativeLivingSnapshot.BeeFence.CONTEXT_CHANGED:STORE.equivalentBeeBatch(f.context(),f.batch(),uuids,tick);}
 static boolean currentBatch(Frame f){return f!=null&&STORE.current(f.context(),f.batch());}
 static boolean current(Frame f){return f.context()!=null&&f.context()==STORE.context();}
 static void publish(Minecraft mc,Map<String,NativeLivingSnapshot.Row> rows,boolean complete){STORE.publish(new NativeLivingSnapshot.Batch(context,mc.level,mc.level.dimension,rows,complete,rows.size()+1,"observed"));}
 static void appendRouteBee(Minecraft mc,Entity e,JsonObject out,Frame f){append(mc,e,out,f);var n=out.getAsJsonObject("native_living");if(n.get("known").getAsBoolean()){var value=f.batch().rows().get(e.getUUID().toString());if(value.beeRoute()!=null)n.add("bee_route",NativeBeeRouteObservation.json(value.beeRoute()));}}
 static void append(Minecraft mc,Entity entity,JsonObject row,Frame frame){row.add("native_living",NativeLivingSnapshot.json(frame.batch(),current(frame)?frame.context():null,mc.level.dimension,WorldGeneration.current(mc.level),mc.player.getUUID().toString(),entity.getUUID().toString(),entity.getId(),entity.getType().id,mc.level.time,System.nanoTime()));}
}''')

# New profile symbols are linked by the shared controller; old-profile behavior remains unchanged.
subprocess.run([sys.executable,'-B',str(repo/'client-mod/validation/route-stop/prepare_far_readers.py'),str(out)],check=True)

# Route-v2 links exact Bee readers without changing v1/controller behavior.
edit('net.minecraft.world.entity.EntityType','ZOMBIE=new EntityType<>("zombie")','ZOMBIE=new EntityType<>("zombie"),BEE=new EntityType<>("bee")')
put('net.minecraft.world.entity.animal.Bee','''public class Bee extends net.minecraft.world.entity.Mob {
 public boolean stung,nectar;public int anger;public java.util.UUID angerTarget;public net.minecraft.core.BlockPos hive,flower;
 public Bee(){type=net.minecraft.world.entity.EntityType.BEE;}
 public boolean isAngry(){return anger>0;}public int getRemainingPersistentAngerTime(){return anger;}
 public java.util.UUID getPersistentAngerTarget(){return angerTarget;}public boolean hasStung(){return stung;}public boolean hasNectar(){return nectar;}
 public net.minecraft.core.BlockPos getHivePos(){return hive;}public net.minecraft.core.BlockPos getSavedFlowerPos(){return flower;}
}''')
put('net.minecraft.core.BlockPos','''public class BlockPos {
 protected int x,y,z;public BlockPos(int x,int y,int z){this.x=x;this.y=y;this.z=z;}
 public int x(){return x;}public int y(){return y;}public int z(){return z;}
 public int getX(){return x;}public int getY(){return y;}public int getZ(){return z;}
 public boolean equals(Object v){return v instanceof BlockPos b&&x==b.x&&y==b.y&&z==b.z;}public int hashCode(){return java.util.Objects.hash(x,y,z);}
 public static class MutableBlockPos extends BlockPos {public MutableBlockPos(int x,int y,int z){super(x,y,z);}public MutableBlockPos set(int a,int b,int c){x=a;y=b;z=c;return this;}}
}''')

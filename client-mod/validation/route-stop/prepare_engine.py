"""Explicit synthetic entity readers; production classes and policies are compiled unchanged."""
from pathlib import Path
import subprocess,sys,argparse
p=argparse.ArgumentParser();p.add_argument('output',type=Path);p.add_argument('--repo',type=Path,default=Path(__file__).resolve().parents[3]);a=p.parse_args()
out=a.output.resolve();repo=a.repo.resolve()
subprocess.run([sys.executable,'-B',str(repo/'client-mod/validation/spatial-threat/prepare_engine.py'),str(out),'--repo',str(repo)],check=True)

p=out/'io/github/campione01/mineclientbridge/FixtureDependencies.java';s=p.read_text();s=s.replace('final class ScopedPlacement {','final class ScopedPlacement {void recordFailure(RuntimeException failure){}');p.write_text(s)

# The server thread/event loop is synthetic. Compile the production exact-row reader
# unchanged, so Bee state extraction itself is exercised rather than reconstructed.
def extract(text,signature):
 start=text.index(signature);brace=text.index('{',start);depth=1;end=brace+1
 while depth:
  depth+=(text[end]=='{')-(text[end]=='}');end+=1
 return text[start:end]
source=(repo/'client-mod/src/main/java/io/github/campione01/mineclientbridge/NativeLivingObservation.java').read_text()
p=out/'io/github/campione01/mineclientbridge/NativeLivingObservation.java';s=p.read_text()
s=s.replace('import com.google.gson.*;', 'import net.minecraft.world.entity.Mob;import net.minecraft.world.entity.LivingEntity;import net.minecraft.world.entity.animal.Bee;import net.minecraft.core.registries.BuiltInRegistries;import com.google.gson.*;')
s=s[:s.rfind('}')]+extract(source,'static NativeLivingSnapshot.Row read(')+'\n'+s[s.rfind('}'):];p.write_text(s)
p=out/'io/github/campione01/mineclientbridge/NativeRabbitObservation.java';p.write_text('package io.github.campione01.mineclientbridge;final class NativeRabbitObservation {static NativeLivingSnapshot.RabbitState read(net.minecraft.world.entity.Mob m){return null;}}')
p=out/'net/minecraft/world/entity/Mob.java';s=p.read_text().replace('public Entity target;public Entity getTarget()', 'public boolean aggressive;public boolean isAggressive(){return aggressive;}public LivingEntity target;public LivingEntity getTarget()');p.write_text(s)

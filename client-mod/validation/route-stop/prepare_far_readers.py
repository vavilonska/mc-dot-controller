"""Add explicit synthetic exact-type reader doubles to an existing isolated engine harness."""
from pathlib import Path
import sys
out=Path(sys.argv[1]).resolve()
far={'bat': 'ambient.Bat', 'cod': 'animal.Cod', 'salmon': 'animal.Salmon', 'tropical_fish': 'animal.TropicalFish', 'squid': 'animal.Squid', 'glow_squid': 'GlowSquid', 'turtle': 'animal.Turtle', 'cat': 'animal.Cat', 'ocelot': 'animal.Ocelot', 'parrot': 'animal.Parrot', 'horse': 'animal.horse.Horse', 'donkey': 'animal.horse.Donkey', 'mule': 'animal.horse.Mule', 'villager': 'npc.Villager', 'wandering_trader': 'npc.WanderingTrader'}
p=out/'net/minecraft/world/entity/EntityType.java';s=p.read_text();s=s.replace('ZOMBIE=new EntityType<>("zombie")','ZOMBIE=new EntityType<>("zombie"),'+','.join(k.upper()+'=new EntityType<>("'+k+'")' for k in far));p.write_text(s.replace('private EntityType(', 'public EntityType('))
for key,name in far.items():
 full='net.minecraft.world.entity.'+name;p=out/Path(*full.split('.')).with_suffix('.java');p.parent.mkdir(parents=True,exist_ok=True);package,cls=full.rsplit('.',1)
 p.write_text('package '+package+';public class '+cls+' extends net.minecraft.world.entity.Mob {public '+cls+'(){type=net.minecraft.world.entity.EntityType.'+key.upper()+';}}')

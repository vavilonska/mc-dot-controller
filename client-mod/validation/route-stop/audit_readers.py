"""Read only pinned Java class bytes with javap. No classes are initialized or game code executed."""
from pathlib import Path
import argparse,hashlib,json,re,subprocess,zipfile
p=argparse.ArgumentParser();p.add_argument('--jar',type=Path,required=True);p.add_argument('--javap',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(exist_ok=False)
far={'bat':'ambient.Bat','cod':'animal.Cod','salmon':'animal.Salmon','tropical_fish':'animal.TropicalFish','squid':'animal.Squid','glow_squid':'GlowSquid','turtle':'animal.Turtle','cat':'animal.Cat','ocelot':'animal.Ocelot','parrot':'animal.Parrot','horse':'animal.horse.Horse','donkey':'animal.horse.Donkey','mule':'animal.horse.Mule','villager':'npc.Villager','wandering_trader':'npc.WanderingTrader'}
reader_names={'getId','getUUID','getType','isRemoved','getX','getY','getZ','getBoundingBox','getDeltaMovement','lerpTargetX','lerpTargetY','lerpTargetZ','getHealth','getTarget','isAlive','isDeadOrDying','getVehicle','getPassengers','getLeashData','getRemainingFireTicks','getSharedFlag','getActiveEffects'}
readers={name+('(int)' if name=='getSharedFlag' else '()') for name in reader_names}
cache={};jar=zipfile.ZipFile(a.jar)
def sha(b):return hashlib.sha256(b).hexdigest()
def load(cls):
 if cls in cache:return cache[cls]
 r=subprocess.run([str(a.javap),'-p','-c','-classpath',str(a.jar),cls],text=True,capture_output=True,timeout=30);assert r.returncode==0,r.stderr
 (a.output/(cls+'.javap.txt')).write_text(r.stdout)
 header=next(l for l in r.stdout.splitlines() if ' class ' in l or ' interface ' in l);m=re.search(r'\bextends ([a-zA-Z0-9_.$]+)',header);parent=m.group(1) if m else None
 methods={};current=None
 for line in r.stdout.splitlines():
  if re.match(r'^  \S.*\);$',line):
   match=re.search(r'([\w$]+\([^)]*\))',line);current=match.group(1) if match else None
   if current:methods[current]={'signature':line.strip(),'body':[]}
  elif current:methods[current]['body'].append(line)
 data={'class':cls,'header':header,'parent':parent,'class_sha256':sha(jar.read(cls.replace('.','/')+'.class')),'methods':methods};cache[cls]=data
 return data
report={}
for key,suffix in far.items():
 cls='net.minecraft.world.entity.'+suffix;chain=[];cur=cls
 while cur and cur!='java.lang.Object':
  d=load(cur);chain.append(d);cur=d['parent']
 resolved={}
 for name in sorted(readers):
  found=next((d for d in chain if name in d['methods']),None)
  if found:
   method=found['methods'][name];body='\n'.join(method['body']);resolved[name]={'owner':found['class'],'signature':method['signature'],'body_sha256':sha(body.encode()),'body':body}
  else:resolved[name]={'owner':None,'reason':'interface-default-or-not-applicable'}
 goals=sorted(set(re.findall(r'(?:class|Method) (net/minecraft/world/entity/ai/(?:goal|behavior)/[\w$/]+)',chain[0]['methods'].get('registerGoals()',{}).get('body',[]) and '\n'.join(chain[0]['methods']['registerGoals()']['body']) or '')))
 report['minecraft:'+key]={'class':cls,'hierarchy':[d['class'] for d in chain],'getter_resolution':resolved,'direct_goal_classes':goals}
 # Exact concrete newcomers must not override this reader surface.
 assert not readers.intersection(chain[0]['methods']), (cls,readers.intersection(chain[0]['methods']))
 # Safe type diagnostic invokes only Entity's exact field getter.
 assert resolved['getType()']['owner']=='net.minecraft.world.entity.Entity'
(a.output/'reader-audit.json').write_text(json.dumps({'schema_version':1,'jar':str(a.jar),'jar_sha256':sha(a.jar.read_bytes()),'javap_sha256':sha(a.javap.read_bytes()),'scope':'Static pinned class/getter resolution and bytecode inventory; no loader/physics/AI-future certification','types':report,'class_inventory':{k:v['class_sha256'] for k,v in cache.items()}},indent=2))
print('AUDIT',len(report),'concrete classes,',len(cache),'hierarchy classes')
print(json.dumps({k:{n:d['owner'] for n,d in v['getter_resolution'].items()} for k,v in report.items()},indent=2))

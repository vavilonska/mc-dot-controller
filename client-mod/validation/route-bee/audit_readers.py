"""Static pinned Bee reader/mechanics inventory. Never loads a game class or inspects a world."""
from pathlib import Path
import argparse, hashlib, json, re, subprocess, zipfile
p=argparse.ArgumentParser();p.add_argument('--jar',type=Path,required=True);p.add_argument('--javap',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(exist_ok=False)
sha=lambda b:hashlib.sha256(b).hexdigest()
assert sha(a.jar.read_bytes())=='1c47e83623a9a2634db3f3b2b93ebf69f0bfe5d975cc038248135d289d772b6f','Unreviewed game compiler JAR'
jar=zipfile.ZipFile(a.jar);cache={}
def read(cls):
 if cls in cache:return cache[cls]
 run=subprocess.run([str(a.javap),'-p','-c','-classpath',str(a.jar),cls],capture_output=True,text=True,check=True,timeout=30)
 (a.output/(cls+'.javap.txt')).write_text(run.stdout)
 header=next(line for line in run.stdout.splitlines() if ' class ' in line or ' interface ' in line or line.startswith(('class ','interface ')));match=re.search(r'\bextends ([a-zA-Z0-9_.$]+)',header);parent=match.group(1) if match else None
 methods={};current=None
 for line in run.stdout.splitlines():
  if re.match(r'^  \S.*\);$',line):
   match=re.search(r'([\w$]+\([^)]*\))',line);current=match.group(1) if match else None
   if current:methods[current]={'signature':line.strip(),'body':[]}
  elif current:methods[current]['body'].append(line)
 result={'class':cls,'header':header,'parent':parent,'class_sha256':sha(jar.read(cls.replace('.','/')+'.class')),'methods':methods};cache[cls]=result;return result
cls='net.minecraft.world.entity.animal.Bee';chain=[];cur=cls
while cur and cur!='java.lang.Object':
 info=read(cur);chain.append(info);cur=info['parent']
neutral=read('net.minecraft.world.entity.NeutralMob')
client=['getId()','getUUID()','getType()','isRemoved()','getX()','getY()','getZ()','getBoundingBox()','getDeltaMovement()','lerpTargetX()','lerpTargetY()','lerpTargetZ()','getHealth()','getTarget()','isAlive()','isDeadOrDying()','getVehicle()','getPassengers()','getLeashData()','getRemainingFireTicks()','getSharedFlag(int)','getActiveEffects()','isAngry()','getRemainingPersistentAngerTime()','hasStung()']
server=['isAggressive()','getPersistentAngerTarget()','hasNectar()','getHivePos()','getSavedFlowerPos()']
resolved={}
for name in client+server:
 owner=next((c for c in chain+[neutral] if name in c['methods']),None)
 assert owner is not None,name
 body='\n'.join(owner['methods'][name]['body']);resolved[name]={'owner':owner['class'],'signature':owner['methods'][name]['signature'],'body':body,'body_sha256':sha(body.encode())}
# The added Bee-specific surface consists only of field/synchronized data readers and the NeutralMob default.
assert resolved['isAngry()']['owner']=='net.minecraft.world.entity.NeutralMob'
assert resolved['getType()']['owner']=='net.minecraft.world.entity.Entity'
assert not set(client[:22]).intersection(chain[0]['methods'])
for name in ['getRemainingPersistentAngerTime()','getPersistentAngerTarget()','hasStung()','hasNectar()','getHivePos()','getSavedFlowerPos()']:
 assert resolved[name]['owner']==cls
for suffix in ['Bee$BeeAttackGoal','Bee$BeeHurtByOtherGoal','Bee$BeeBecomeAngryTargetGoal','Bee$BeeEnterHiveGoal','Bee$BeeGoToHiveGoal','Bee$BaseBeeGoal','Bee$BeePollinateGoal','Bee$BeeGoToKnownFlowerGoal','Bee$BeeGrowCropGoal']:
 read('net.minecraft.world.entity.animal.'+suffix)
for name in ['net.minecraft.world.entity.ai.goal.MeleeAttackGoal','net.minecraft.world.entity.ai.goal.target.HurtByTargetGoal','net.minecraft.world.entity.ai.goal.target.ResetUniversalAngerTargetGoal','net.minecraft.world.level.block.BeehiveBlock','net.minecraft.world.level.block.entity.BeehiveBlockEntity','net.minecraft.core.BlockPos','net.minecraft.core.BlockPos$MutableBlockPos','net.minecraft.core.Vec3i']:
 read(name)
# Ordinary pollination stores the exact mutable object, so rejecting every subclass rejects vanilla state.
mutable=cache['net.minecraft.core.BlockPos$MutableBlockPos'];block=cache['net.minecraft.core.BlockPos'];vec=cache['net.minecraft.core.Vec3i']
assert mutable['parent']=='net.minecraft.core.BlockPos' and block['parent']=='net.minecraft.core.Vec3i'
for name in ['getX()','getY()','getZ()']:
 assert name not in mutable['methods'] and name not in block['methods']
 body='\n'.join(vec['methods'][name]['body']);assert 'getfield' in body and not any(x in body for x in ['invoke','putfield','monitor'])
pollinate=cache['net.minecraft.world.entity.animal.Bee$BeePollinateGoal']['methods']
find='\n'.join(pollinate['findNearestBlock(java.util.function.Predicate<net.minecraft.world.level.block.state.BlockState>, double)']['body'])
use='\n'.join(pollinate['canBeeUse()']['body'])
assert re.search(r'9: new\s+#[0-9]+\s+// class net/minecraft/core/BlockPos\$MutableBlockPos',find)
assert re.search(r'128: aload\s+5\s+130: invokestatic[^\n]*java/util/Optional.of:[^\n]*\s+133: areturn',find)
assert 'immutable' not in find and 'immutable' not in use
assert re.search(r'56: invokevirtual[^\n]*java/util/Optional.get:[^\n]*\s+59: checkcast[^\n]*BlockPos\s+62: putfield[^\n]*Bee.savedFlowerPos',use)
coordinate={}
for name in ['getX()','getY()','getZ()']:
 owner=next(c for c in [cache['net.minecraft.core.BlockPos'],cache['net.minecraft.core.Vec3i']] if name in c['methods'])
 coordinate[name]={'owner':owner['class'],**owner['methods'][name]}
report={'schema_version':1,'status':'passed','jar_sha256':sha(a.jar.read_bytes()),'javap_sha256':sha(a.javap.read_bytes()),'hierarchy':[c['class'] for c in chain],'readers':resolved,'coordinate_readers':coordinate,'vanilla_pollination_mutable_reference':{'verified':True,'find_nearest_block_offsets':[9,128,130,133],'can_bee_use_offsets':[56,59,62],'mutable_getter_owner':'net.minecraft.core.Vec3i','scope':'Exact pinned MutableBlockPos inherits only field getters; unknown subclasses remain excluded'},'class_inventory':{k:v['class_sha256'] for k,v in cache.items()},'scope':'Static exact pinned bytecode inventory and reader resolution only; no runtime, world, future AI, mod attestation or physics guarantee'}
(a.output/'reader-audit.json').write_text(json.dumps(report,indent=2));print('PASS',len(resolved),'readers',len(cache),'classes')

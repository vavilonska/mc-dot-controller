#!/usr/bin/env python3
"""Frozen diagnostic-only gate: full native compile, production hook doubles and retained actual Mixin order."""
from pathlib import Path
import hashlib,json,os,sys,subprocess,time,runpy,zipfile
V=Path(__file__).resolve().parent;S=V.parents[2];W=S.parent.parent;P='io/github/campione01/mineclientbridge'
manifest=Path(sys.argv[1]).resolve();out=Path(sys.argv[2]).resolve()
def h(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def inv(p):return {str(f.relative_to(p)):h(f) for f in sorted(p.rglob('*')) if f.is_file()}
def write(p,v):p.write_text(json.dumps(v,indent=2,sort_keys=True)+'\n')
expected=json.loads(manifest.read_text())['files'];assert inv(S)==expected
base=W/'mdc-survival-test2_11-candidate/source';base_manifest=W/'mdc-survival-test2_11-results/SOURCE-FINAL.json';base_pin={k:v['sha256'] for k,v in json.loads(base_manifest.read_text())['files'].items()};assert inv(base)==base_pin
jar=W/'mdc-survival-test2_11-results/delivery/mineclient-bridge-1.1.8-recovery-test.2.11.jar'
cpfile=W/'minecraft-runtime/compile-classpath-at.txt';cp=cpfile.read_text().strip();deps=[Path(x) for x in cp.split(':')];java=Path('/usr/bin/java').resolve();jdk=java.parent.parent;python=Path(sys.executable).resolve()
transformed=W/'mdc-survival-test2_11-results/native-r1/transformed-none';actual_classes=[transformed/(n+'.class') for n in ['net_minecraft_client_multiplayer_MultiPlayerGameMode','net_minecraft_world_entity_player_Player','net_minecraft_client_multiplayer_ClientCommonPacketListenerImpl']]
native_result=transformed.parent/'RESULT.json';native_inventory=transformed.parent/'ALL-OUTPUT-CLASS-HASHES.json';accepted_review=W/'mdc-survival-test2_11-results/UNION-AND-BUILD-REVIEW.json'
assert h(base_manifest)=='a5ca41a65a9ddd1cef31f8c49d0373eeaff5bc7683597404bc685f0530709ddc','unaccepted baseline source'
assert h(jar)=='ccfdd7ca576dd1a47ae7671fd741954f2dccd09e3c586f21f9cd193899e22960','unaccepted baseline JAR'
assert h(accepted_review)=='df5f3ab1542f4a66c9c56eb7accc8bc80f6d0a469cef9c8517fb8afe150a419f','unaccepted baseline review'
assert h(native_result)=='67964ed88ae10d4dc7199f32559f510af335e59868d5ec86e7370cd6f2bd17f1','unaccepted native result'
assert h(native_inventory)=='181c45fc213c47ae54bacec95126dcf79353e52020817a14e27ca3fefcad81a9','unaccepted native outputs'
accepted=json.loads(native_inventory.read_text());assert all(h(p)==accepted[str(p.relative_to(transformed.parent))] for p in actual_classes),'changed retained transformed class'
extras=[jar,base_manifest,native_result,native_inventory,accepted_review,base/'client-mod/src/main/java'/P/'CombatCallbackFence.java',*actual_classes]
# Reject any output overlapping frozen source, production/dependency/tool or manifest inputs before mkdir.
for root in [S,base,transformed,jdk]:
 assert out!=root and not out.is_relative_to(root) and not root.is_relative_to(out),'output overlaps protected tree'
for protected in [manifest,*extras,*deps,java,python,cpfile]:
 assert out!=protected.resolve() and not protected.resolve().is_relative_to(out),'output overlaps protected input'
assert not out.exists();out.mkdir()
def inputs():return {'source_manifest_sha256':h(manifest),'source':inv(S),'base_source':inv(base),'ordered_dependencies':[{'path':str(p),'sha256':h(p)} for p in deps],'extra':{str(p):h(p) for p in extras},'tools':{str(p):h(p) for p in [java,jdk/'release',jdk/'lib/modules',jdk/'lib/server/libjvm.so',python,cpfile]}}
before=inputs();write(out/'INPUTS-BEFORE.json',before);steps=[];env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'}
def run(name,argv):
 write(out/(name+'-command.json'),{'argv':argv,'cwd':str(out),'timeout_seconds':45});start=time.monotonic()
 with (out/(name+'.log')).open('w') as log:done=subprocess.run(argv,cwd=out,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=45)
 row={'name':name,'exit_code':done.returncode,'seconds':time.monotonic()-start,'log_sha256':h(out/(name+'.log'))};steps.append(row);write(out/'PROGRESS.json',steps);print(json.dumps(row),flush=True);assert done.returncode==0,row
compiler=[str(java),'-Xmx384m','-XX:ActiveProcessorCount=1','-m','jdk.compiler/com.sun.tools.javac.Main'];(out/'empty').mkdir();closed=['-proc:none','-implicit:none','-sourcepath',str(out/'empty'),'-source','21','-target','21']
classes=out/'classes';classes.mkdir();testsrc=out/'test-src';testclasses=out/'test-classes';testclasses.mkdir();sources=sorted((S/'client-mod/src/main/java').rglob('*.java'));(out/'sources.txt').write_text('\n'.join(map(str,sources))+'\n')
try:
 run('compile',[*compiler,*closed,'-cp',cp,'-d',str(classes),'@'+str(out/'sources.txt')])
 legacy=runpy.run_path(str(S/'client-mod/validation/scoped-target/run_dispatch_hook_checks.py'));stubs=legacy['STUBS'].copy()
 stubs[P+'/BridgeLog.java']='''package io.github.campione01.mineclientbridge;import java.util.*;final class BridgeLog {static final Log LOGGER=new Log();static final class Log {boolean fail;Runnable onWarn=()->{};final List<Object[]> records=new ArrayList<>();void warn(String format,Object... values){onWarn.run();if(fail)throw new IllegalStateException("logger failure");records.add(values.clone());}}}'''
 stubs['net/minecraft/world/entity/Entity.java']=stubs['net/minecraft/world/entity/Entity.java'].replace('public int id=9;','public int id=9;public net.minecraft.world.phys.Vec3 getDeltaMovement(){return new net.minecraft.world.phys.Vec3();}')
 stubs['net/minecraft/world/entity/monster/Shulker.java']='package net.minecraft.world.entity.monster;public class Shulker extends net.minecraft.world.entity.Entity {public net.minecraft.world.phys.Vec3 getDeltaMovement(){return new net.minecraft.world.phys.Vec3();}}'
 for rel,text in stubs.items():p=testsrc/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
 for n in ['ScopedTargetDispatch.java','TargetActionEffectBudget.java','TargetActionReaderPolicy.java','CombatCallbackFence.java']:(testsrc/P/n).write_bytes((S/'client-mod/src/main/java'/P/n).read_bytes())
 for n in ['TargetDiagnosticChecks.java','FenceParityChecks.java']:(testsrc/P/n).write_bytes((V/n).read_bytes())
 (testsrc/P/'LegacyCombatCallbackFence.java').write_text((base/'client-mod/src/main/java'/P/'CombatCallbackFence.java').read_text().replace('CombatCallbackFence','LegacyCombatCallbackFence'))
 (testsrc/P/'ScopedTargetHookChecks.java').write_text(legacy['CHECKS'])
 (testsrc/P/'CombatCallbackFenceChecks.java').write_bytes((S/'client-mod/validation/scoped-combat/CombatCallbackFenceChecks.java').read_bytes())
 run('test-compile',[*compiler,*closed,'-d',str(testclasses),*map(str,sorted(testsrc.rglob('*.java')))])
 for name in ['TargetDiagnosticChecks','FenceParityChecks','ScopedTargetHookChecks','CombatCallbackFenceChecks']:
  run(name,[str(java),'-Xmx192m','-XX:ActiveProcessorCount=1','-cp',str(testclasses),'io.github.campione01.mineclientbridge.'+name])
 run('actual-transformed-order',[str(python),'-B',str(V/'verify_order.py'),str(transformed),str(out/'ACTUAL-ORDER.json')])
finally:
 write(out/'PRODUCTION-CLASS-HASHES.json',inv(classes));write(out/'TEST-CLASS-HASHES.json',inv(testclasses));write(out/'GENERATED-TEST-INPUTS.json',inv(testsrc));after=inputs();write(out/'INPUTS-AFTER.json',after);assert before==after,'input changed'
def norm(raw):
 b=bytearray(raw);p=8;cp={}
 def u(n):
  nonlocal p
  v=int.from_bytes(b[p:p+n],'big');p+=n;return v
 count=u(2);k=1
 while k<count:
  tag=u(1)
  if tag==1:
   n=u(2);cp[k]=bytes(b[p:p+n]).decode('utf8',errors='replace');p+=n
  elif tag in (7,8,16,19,20):p+=2
  elif tag in (3,4,9,10,11,12,17,18):p+=4
  elif tag in (5,6):p+=8;k+=1
  elif tag==15:p+=3
  else:raise ValueError(tag)
  k+=1
 p+=6;ninterfaces=u(2);p+=2*ninterfaces
 changes=[]
 def attrs():
  nonlocal p
  for _ in range(u(2)):
   name=cp[u(2)];n=u(4);start=p
   if name=='Code':
    p+=4;ncode=u(4);p+=ncode;nexceptions=u(2);p+=8*nexceptions;attrs()
   elif name=='LineNumberTable':
    changes.append({'offset':p,'length':n});count=int.from_bytes(b[p:p+2],'big');assert n==2+4*count
    for index in range(count):b[p+4+4*index:p+6+4*index]=b'\x00\x00'
    p+=n
   else:p+=n
   assert p==start+n,(name,p,start,n)
 for _ in range(2):
  for i in range(u(2)):p+=6;attrs()
 attrs();assert p==len(b)
 return bytes(b),changes

with zipfile.ZipFile(jar) as z:old={n:hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist() if n.endswith('.class')}
new=inv(classes);changed=sorted(k for k in old if new.get(k)!=old[k]);added=sorted(set(new)-set(old));missing=sorted(set(old)-set(new));write(out/'CLASS-COMPARISON.json',{'baseline_classes':len(old),'fresh_classes':len(new),'changed':changed,'added':added,'missing':missing})
allowed={P+'/'+n+'.class' for n in ['CombatCallbackFence','ScopedTargetDispatch','ScopedTargetDispatch$Call','ScopedTargetDispatch$AttackPacketReader']};assert set(changed)<=allowed and {P+'/CombatCallbackFence.class',P+'/ScopedTargetDispatch.class'}<=set(changed) and not missing
with zipfile.ZipFile(jar) as z:
 key=P+'/ScopedTargetDispatch$AttackPacketReader.class';a,al=norm(z.read(key));b,bl=norm((classes/key).read_bytes());assert a==b and al==bl,'unexpected packet-reader semantic change'
 write(out/'PACKET-READER-LINE-ONLY.json',{'class':key,'normalized_sha256':hashlib.sha256(a).hexdigest(),'line_tables':al})
assert set(added)=={P+'/'+n+'.class' for n in ['CombatCallbackFence$Failure','ScopedTargetDispatch$Phase','ScopedTargetDispatch$Stage']}
write(out/'RESULT.json',{'status':'passed','source_manifest_sha256':h(manifest),'native_sources':len(sources),'fresh_classes':len(new),'input_manifest_sha256':h(out/'INPUTS-BEFORE.json'),'production_class_manifest_sha256':h(out/'PRODUCTION-CLASS-HASHES.json'),'steps':steps,'limits':'Diagnostic-only; unchanged checks/deadlines/outcomes. Actual hook methods use test-double engine with controlled clock; retained transformed bytecode proves real call order. Does not establish original live cause or packet transmission.'})

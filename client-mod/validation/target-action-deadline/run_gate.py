#!/usr/bin/env python3
"""Frozen stationary-target action-deadline gate: exact source compile, production hooks and legacy parity."""
from pathlib import Path
import hashlib,json,os,sys,subprocess,time,runpy,zipfile
V=Path(__file__).resolve().parent;S=V.parents[2];W=S.parent.parent;P='io/github/campione01/mineclientbridge'
manifest=Path(sys.argv[1]).resolve();out=Path(sys.argv[2]).resolve()
def h(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def inv(p):return {str(f.relative_to(p)):h(f) for f in sorted(p.rglob('*')) if f.is_file()}
def write(p,v):p.write_text(json.dumps(v,indent=2,sort_keys=True)+'\n')
expected=json.loads(manifest.read_text())['files'];assert inv(S)==expected
base=W/'mdc-survival-test2_12-candidate/source';base_manifest=W/'mdc-survival-test2_12-results/SOURCE-FINAL.json';base_pin={k:v['sha256'] for k,v in json.loads(base_manifest.read_text())['files'].items()};assert inv(base)==base_pin
jar=W/'mdc-survival-test2_12-results/delivery/mineclient-bridge-1.1.8-recovery-test.2.12.jar'
cpfile=W/'minecraft-runtime/compile-classpath-at.txt';cp=cpfile.read_text().strip();deps=[Path(x) for x in cp.split(':')];java=Path('/usr/bin/java').resolve();jdk=java.parent.parent;python=Path(sys.executable).resolve()
transformed=W/'mdc-survival-test2_11-results/native-r1/transformed-none';actual_classes=[transformed/(n+'.class') for n in ['net_minecraft_client_multiplayer_MultiPlayerGameMode','net_minecraft_world_entity_player_Player','net_minecraft_client_multiplayer_ClientCommonPacketListenerImpl']]
native_result=transformed.parent/'RESULT.json';native_inventory=transformed.parent/'ALL-OUTPUT-CLASS-HASHES.json';accepted_review=W/'mdc-survival-test2_11-results/UNION-AND-BUILD-REVIEW.json'
assert h(base_manifest)=='ccfe7659abef6460db6ba8bbdfe39c5cbd4f5c5ae3b474c1512fd6d04e49a87d','unaccepted baseline source'
assert h(jar)=='bb12d915231648dfeb3370a7a008b3a64b7b5cbb00b72c4684022e666577398b','unaccepted baseline JAR'
assert h(accepted_review)=='df5f3ab1542f4a66c9c56eb7accc8bc80f6d0a469cef9c8517fb8afe150a419f','unaccepted baseline review'
assert h(native_result)=='67964ed88ae10d4dc7199f32559f510af335e59868d5ec86e7370cd6f2bd17f1','unaccepted native result'
assert h(native_inventory)=='181c45fc213c47ae54bacec95126dcf79353e52020817a14e27ca3fefcad81a9','unaccepted native outputs'
accepted=json.loads(native_inventory.read_text());assert all(h(p)==accepted[str(p.relative_to(transformed.parent))] for p in actual_classes),'changed retained transformed class'
pair_review=W/'mdc-survival-test2_12-results/PAIR-REVIEW.json';reuse=W/'mdc-survival-test2_12-results/NATIVE-REUSE.json'
assert h(pair_review)=='bb6d3e334ea23ae264282a2c1044e2d91a8a5745529efd881b484e55d54bd192'
assert h(reuse)=='f1acf4b5a80d540a9939ecd8cccc7819a362549e04b497b79e60d46dfa95ccdc'
extras=[jar,base_manifest,native_result,native_inventory,accepted_review,pair_review,reuse,base/'client-mod/src/main/java'/P/'CombatCallbackFence.java',*actual_classes]
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
 for n in ['TargetDiagnosticChecks.java','FenceParityChecks.java']:(testsrc/P/n).write_bytes((S/'client-mod/validation/target-diagnostic'/n).read_bytes())
 (testsrc/P/'TargetActionDeadlineChecks.java').write_bytes((V/'TargetActionDeadlineChecks.java').read_bytes())
 (testsrc/P/'LegacyCombatCallbackFence.java').write_text((base/'client-mod/src/main/java'/P/'CombatCallbackFence.java').read_text().replace('CombatCallbackFence','LegacyCombatCallbackFence'))
 (testsrc/P/'ScopedTargetHookChecks.java').write_text(legacy['CHECKS'])
 (testsrc/P/'CombatCallbackFenceChecks.java').write_bytes((S/'client-mod/validation/scoped-combat/CombatCallbackFenceChecks.java').read_bytes())
 run('test-compile',[*compiler,*closed,'-d',str(testclasses),*map(str,sorted(testsrc.rglob('*.java')))])
 for name in ['TargetActionDeadlineChecks','TargetDiagnosticChecks','FenceParityChecks','ScopedTargetHookChecks','CombatCallbackFenceChecks']:
  run(name,[str(java),'-Xmx192m','-XX:ActiveProcessorCount=1','-cp',str(testclasses),'io.github.campione01.mineclientbridge.'+name])
 run('compiled-deadline-binding',[str(python),'-B',str(V/'verify_binding.py'),str(classes),str(out/'COMPILED-DEADLINE-BINDING.json')])
 run('actual-transformed-order',[str(python),'-B',str(S/'client-mod/validation/target-diagnostic/verify_order.py'),str(transformed),str(out/'ACTUAL-ORDER.json')])
finally:
 write(out/'PRODUCTION-CLASS-HASHES.json',inv(classes));write(out/'TEST-CLASS-HASHES.json',inv(testclasses));write(out/'GENERATED-TEST-INPUTS.json',inv(testsrc));after=inputs();write(out/'INPUTS-AFTER.json',after);assert before==after,'input changed'
with zipfile.ZipFile(jar) as z:old={n:hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist() if n.endswith('.class')}
new=inv(classes);changed=sorted(k for k in old if new.get(k)!=old[k]);added=sorted(set(new)-set(old));missing=sorted(set(old)-set(new));write(out/'CLASS-COMPARISON.json',{'baseline_classes':len(old),'fresh_classes':len(new),'changed':changed,'added':added,'missing':missing})
allowed={P+'/'+n+'.class' for n in ['CombatCallbackFence','CombatCallbackFence$Failure','ScopedTargetDispatch$Call']};assert set(changed)==allowed and not missing and not added,'unexpected class change'
write(out/'RESULT.json',{'status':'passed','source_manifest_sha256':h(manifest),'native_sources':len(sources),'fresh_classes':len(new),'input_manifest_sha256':h(out/'INPUTS-BEFORE.json'),'production_class_manifest_sha256':h(out/'PRODUCTION-CLASS-HASHES.json'),'steps':steps,'limits':'Ordinary stationary target calls bind the original immutable action deadline, with same tick/owner/final facts; default legacy and cleanup 50ms behavior retained. Production hooks use explicit engine doubles. Actual compiled binding and retained transformed call order verified. No live success or historical outcome claim.'})

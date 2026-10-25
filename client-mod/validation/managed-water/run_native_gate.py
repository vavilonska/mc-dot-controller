#!/usr/bin/env python3
"""Serialized official gate: run_native_gate.py FRESH_OUTPUT FROZEN_DELTA_JSON."""
from pathlib import Path
import os,subprocess,sys,time
from input_provenance import capture,digest,inventory,write

V=Path(__file__).resolve().parent;S=V.parents[2];W=S.parent.parent
out=Path(sys.argv[1]).resolve();delta=Path(sys.argv[2]).resolve()
assert out!=S and S not in out.parents, 'results must be outside source'
out.mkdir(parents=True,exist_ok=False)
jdk=W/'minecraft-runtime/jdk/jdk-21.0.12.1+1/bin';cpfile=W/'minecraft-runtime/compile-classpath-at.txt';cp=cpfile.read_text().strip()
deps=[Path(p) for p in cp.split(os.pathsep)]
before=capture(S,delta,jdk/'java',jdk/'javac',deps,cpfile);write(out/'INPUTS-BEFORE.json',before)
source=sorted((S/'client-mod/src/main/java').rglob('*.java'));resources=S/'client-mod/src/main/resources'
for name in ('classes','harness','empty-sourcepath'):(out/name).mkdir()
(out/'sources.txt').write_text('\n'.join(map(str,source))+'\n')
steps=[]
def run(name,args,expected=True):
    write(out/(name+'-command.json'),{'argv':args,'cwd':str(S),'environment_overrides':{'PYTHONDONTWRITEBYTECODE':'1'},'timeout_seconds':40})
    start=time.monotonic()
    with (out/(name+'.log')).open('wb') as log:r=subprocess.run(args,cwd=S,stdout=log,stderr=subprocess.STDOUT,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'},timeout=40)
    step={'name':name,'exit':r.returncode,'seconds':time.monotonic()-start,'sha256':digest(out/(name+'.log'))};steps.append(step)
    write(out/'PROGRESS.json',steps)
    assert (r.returncode==0)==expected,step

try:
    closed=['-proc:none','-implicit:none','-sourcepath',str(out/'empty-sourcepath'),'--release','21']
    run('compile',[str(jdk/'javac'),'-J-Xmx384m','-J-XX:ActiveProcessorCount=1',*closed,'-cp',cp,'-d',str(out/'classes'),'@'+str(out/'sources.txt')])
    harness=sorted((V/'mixin').rglob('*.java'))
    run('harness-compile',[str(jdk/'javac'),'-J-Xmx256m','-J-XX:ActiveProcessorCount=1',*closed,'-cp',cp,'-d',str(out/'harness'),*map(str,harness)])
    services=out/'harness/META-INF/services';services.mkdir(parents=True)
    (services/'org.spongepowered.asm.service.IMixinService').write_text('probe.OfflineMixinService\n')
    (services/'org.spongepowered.asm.service.IGlobalPropertyService').write_text('probe.OfflineProperties\n')
    for mode in ['none','missing-input','missing-jump-read','missing-jump-effect','missing-travel','missing-acceleration']:
        run('mixin-'+mode,[str(jdk/'java'),'-Xmx256m','-XX:ActiveProcessorCount=1','-Dmixin.service=probe.OfflineMixinService','-Dmixin.env.disableRefMap=true','-cp',f'{out}/classes:{out}/harness:{resources}:{cp}','probe.ManagedWaterMixinProbe',str(out/('transformed-'+mode)),mode],mode=='none')
        if mode!='none':assert any(x in (out/('mixin-'+mode+'.log')).read_text() for x in ('InvalidInjectionException','InjectionError','InvalidInjectionPointException'))
    run('policy-compile',[str(jdk/'javac'),'-J-Xmx128m','-J-XX:ActiveProcessorCount=1',*closed,'-cp',f'{out}/classes:{cp}','-d',str(out/'harness'),str(V/'ManagedDryStepPolicyProbe.java'),str(V.parent/'managed-navigation/ManagedNavigationWireFixtures.java')])
    run('policy',[str(jdk/'java'),'-Xmx128m','-XX:ActiveProcessorCount=1','-cp',f'{out}/classes:{out}/harness','io.github.campione01.mineclientbridge.ManagedDryStepPolicyProbe'])
    run('wire-fixture',[str(jdk/'java'),'-Xmx128m','-XX:ActiveProcessorCount=1','-cp',f'{out}/classes:{out}/harness:{cp}','io.github.campione01.mineclientbridge.ManagedNavigationWireFixtures',str(out/'managed-wire.json')])
finally:
    after=capture(S,delta,jdk/'java',jdk/'javac',deps,cpfile);write(out/'INPUTS-AFTER.json',after)
    write(out/'OUTPUT-CLASS-HASHES.json',inventory(out,'*.class'))
    assert before==after,'source/dependency/toolchain changed during gate'
write(out/'RESULT.json',{'status':'passed','native_sources':len(source),'input_manifest_sha256':digest(out/'INPUTS-BEFORE.json'),
    'output_class_manifest_sha256':digest(out/'OUTPUT-CLASS-HASHES.json'),'steps':steps,'game_started':False})
print({'status':'passed','native_sources':len(source),'steps':len(steps)})

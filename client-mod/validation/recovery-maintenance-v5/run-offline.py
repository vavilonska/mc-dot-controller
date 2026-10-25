#!/usr/bin/env python3
"""Pinned offline compilation and actual recovery codec/ledger regressions. Never starts Minecraft."""
import argparse,hashlib,json,pathlib,subprocess
p=argparse.ArgumentParser();p.add_argument('--out',required=True);a=p.parse_args();s=pathlib.Path(__file__).resolve().parents[3];w=s.parents[1];root=s/'client-mod';out=pathlib.Path(a.out).resolve();out.mkdir(parents=True,exist_ok=False);classes=out/'classes-production';tests=out/'classes-tests';classes.mkdir();tests.mkdir();(out/'logs').mkdir()
cp=(w/'minecraft-runtime/compile-classpath-at.txt').read_text().strip();javac=str(w/'minecraft-runtime/local-jdk-tools/javac');sources=sorted((root/'src/main/java').rglob('*.java'));sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();hashes={str(p.relative_to(s)):sha(p) for p in sources};result={'scope':'offline only, no game/GLFW invocation/native entity construction','source_sha256':hashes,'runs':[]}
def run(name,cmd):
 r=subprocess.run(cmd,capture_output=True,text=True);(out/'logs'/f'{name}.stdout').write_text(r.stdout);(out/'logs'/f'{name}.stderr').write_text(r.stderr);result['runs'].append({'name':name,'argv':cmd,'exit_code':r.returncode});(out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(name,r.returncode,r.stdout[-200:],r.stderr[-500:],flush=True)
 if r.returncode:raise SystemExit(r.returncode)
run('compile-production',[javac,'-proc:none','-source','21','-target','21','-cp',cp,'-d',str(classes),*map(str,sources)])
testsources=sorted(p for n in ['recovery-short-input','recovery-interaction','recovery-interaction-v2','recovery-interaction-v3','recovery-damage-diag','recovery-respawn-ui','recovery-navigation-v4','recovery-maintenance-v5'] for p in (root/'validation'/n).glob('*.java'))
testhashes={str(p.relative_to(s)):sha(p) for p in testsources}
run('compile-tests',[javac,'-proc:none','-source','21','-target','21','-cp',str(classes)+':'+cp,'-d',str(tests),*map(str,testsources)])
runCp=str(tests)+':'+str(classes)+':'+cp;prefix='io.github.campione01.mineclientbridge.'
def java(name,clazz,args=(),flags=('recoveryInteractionV2',)):
 run(name,['java',*[f'-DmineclientBridge.{f}=true' for f in flags],'-cp',runCp,prefix+clazz,*map(str,args)])
fixtures=s.parent/'results/native/fixtures'
java('v5-disabled','RecoveryMaintenanceV5Checks',['--disabled'],('recoveryInteractionV3',))
java('v5-exclusive','RecoveryMaintenanceV5Checks',['--both-flags'],('recoveryMaintenanceV5','recoveryNavigationV4'))
java('v5-ui','RecoveryMaintenanceV5Checks',['--ui-v5'],('recoveryMaintenanceV5','recoveryDeathScreenUi','isolatedInput'))
java('v5','RecoveryMaintenanceV5Checks',[fixtures,out/'v5'],('recoveryMaintenanceV5',))
java('v4','RecoveryNavigationV4Checks',[fixtures,out/'v4'],('recoveryNavigationV4','isolatedInput'))
java('ui','RecoveryRespawnUiChecks',[fixtures,out/'ui',classes],('recoveryInteractionV3','recoveryDeathScreenUi','isolatedInput'))
java('v3','RecoveryInteractionV3Checks',[w/'mdc-recovery-interaction-test-r3/results/native/fixtures',out/'v3'],('recoveryInteractionV3',))
java('short','RecoveryShortInputChecks');java('short-wire','RecoveryShortInputWireChecks',[out/'short-wire']);java('v1','RecoveryInteractionChecks',[w/'mdc-recovery-interaction-test-r1/results/legacy57-fixtures',out/'v1','--preserve-fixtures']);java('v2','RecoveryInteractionV2Checks',[w/'mdc-recovery-interaction-test-r2/results/legacy94-fixtures',out/'v2'])
native=w/'minecraft-runtime/compile-only/minecraft-1.21.1-neoforge21.1.255-mdc-at-r2.jar'
java('pinned-maintenance','RecoveryMaintenancePinnedChecks',[native]);java('pinned-navigation','RecoveryNavigationPinnedChecks',[native]);java('pinned-respawn','RecoveryRespawnPinnedChecks',[native]);java('pinned','RecoveryInteractionPinnedChecks',[native]);java('wart','RecoveryWartPinnedChecks',[native,w/'minecraft-runtime/versions/1.21.1/1.21.1.jar',out/'wart-audit.json']);java('diag','RecoveryDamageDiagnosticChecks',[out/'diag-wire',native])
java('observation-wire','RecoveryMaintenanceV5ObservationWire',[w/'mdc-runtime-recovery-20261021-r1/respawn-test-preparation-r1/COLD-BED-TO-DOOR-GEOMETRY.json',out/'observation-wire',w/'mdc-runtime-recovery-20261021-r1/tnt-removal-cold-preparation-r1/COLD-TNT-FACTS.json',w/'mdc-runtime-recovery-20261021-r1/tnt-removal-cold-preparation-r1/FINITE-NINE-TNT-SERVICE-CANDIDATE.json'],('recoveryMaintenanceV5',))
assert hashes=={str(p.relative_to(s)):sha(p) for p in sources},'production source changed while compiling/testing'
assert testhashes=={str(p.relative_to(s)):sha(p) for p in testsources},'test source changed while compiling/testing'
base=w/'mdc-recovery-navigation-v4-r1/source/client-mod';changed=[]
for old in sorted((base/'src/main/java').rglob('*.java')):
 new=root/old.relative_to(base)
 if old.read_bytes()!=new.read_bytes():changed.append(str(old.relative_to(base)))
allowed={'RecoveryChallengeLease.java','RecoveryShortInputLedger.java','NativeRecoveryShortInput.java','BridgeServer.java','RecoveryInteraction.java','RecoveryInteractionDispatch.java','RecoveryDeathScreenUi.java','ScopedPlacementItemMixin.java','ScopedPlacementPacketMixin.java','ScopedPlacementSendMixin.java'}
assert {pathlib.Path(n).name for n in changed}==allowed,changed
for old in (base/'src/main/resources').rglob('*'):
 if old.is_file():assert old.read_bytes()==(root/old.relative_to(base)).read_bytes(),str(old)
result.update(production_sources=len(sources),production_classes=len(list(classes.rglob('*.class'))),old_java_delta=changed,classes_sha256={str(p.relative_to(classes)):sha(p) for p in sorted(classes.rglob('*.class'))},test_source_sha256={str(p.relative_to(s)):sha(p) for p in testsources},stable=True)
(out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print('PASS stable source/class manifest',out)

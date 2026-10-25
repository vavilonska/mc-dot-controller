#!/usr/bin/env python3
"""Pinned compile and offline production codec/oracle tests. No Minecraft startup."""
import argparse,hashlib,json,pathlib,subprocess
p=argparse.ArgumentParser();p.add_argument('--out',required=True);a=p.parse_args();s=pathlib.Path(__file__).resolve().parents[3];w=s.parents[1];root=s/'client-mod';out=pathlib.Path(a.out).resolve();out.mkdir(parents=True,exist_ok=False);classes=out/'classes-production';tests=out/'classes-tests';classes.mkdir();tests.mkdir();(out/'logs').mkdir()
cp=(w/'minecraft-runtime/compile-classpath-at.txt').read_text().strip();javac=str(w/'minecraft-runtime/local-jdk-tools/javac');sources=sorted((root/'src/main/java').rglob('*.java'));sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();hashes={str(p.relative_to(s)):sha(p) for p in sources};result={'scope':'offline only; no game/GLFW/native entity construction, no HTTP','source_sha256':hashes,'runs':[]}
def run(name,cmd):
 r=subprocess.run(cmd,capture_output=True,text=True);(out/'logs'/f'{name}.stdout').write_text(r.stdout);(out/'logs'/f'{name}.stderr').write_text(r.stderr);result['runs'].append({'name':name,'argv':cmd,'exit_code':r.returncode});(out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(name,r.returncode,r.stdout[-250:],r.stderr[-700:],flush=True)
 if r.returncode:raise SystemExit(r.returncode)
run('compile-production',[javac,'-proc:none','-source','21','-target','21','-cp',cp,'-d',str(classes),*map(str,sources)])
names=['recovery-short-input','recovery-interaction','recovery-interaction-v2','recovery-interaction-v3','recovery-damage-diag','recovery-respawn-ui','recovery-navigation-v4','recovery-maintenance-v5','recovery-survival-v6']
testsources=sorted(p for n in names for p in (root/'validation'/n).glob('*.java'));testhashes={str(p.relative_to(s)):sha(p) for p in testsources}
run('compile-tests',[javac,'-proc:none','-source','21','-target','21','-cp',str(classes)+':'+cp,'-d',str(tests),*map(str,testsources)])
runCp=str(tests)+':'+str(classes)+':'+cp;prefix='io.github.campione01.mineclientbridge.'
def java(name,clazz,args=(),flags=('recoverySurvivalV6',)):
 run(name,['java',*[f'-DmineclientBridge.{f}=true' for f in flags],'-cp',runCp,prefix+clazz,*map(str,args)])
fixtures=s.parent/'results/legacy338-fixtures';oldFixtures=w/'mdc-recovery-maintenance-v5-r1/results/native/fixtures'
java('v6','RecoverySurvivalV6Checks',[fixtures/'native-338-entry-journal.bin',out/'v6']);java('v6-exclusive','RecoverySurvivalV6Checks',['--both'],('recoverySurvivalV6','recoveryMaintenanceV5'));java('v6-disabled','RecoverySurvivalV6Checks',['--disabled'],('recoveryMaintenanceV5',))
java('legacy-oracle-new','RecoverySurvivalLegacyOracle',[fixtures/'native-338-entry-journal.bin',out/'legacy-oracle-new'])
oldClasses=w/'mdc-recovery-maintenance-v5-r1/results/native/full-r5/classes-production';oracle=out/'oracle-old-classes';oracle.mkdir()
run('compile-oracle-old',[javac,'-proc:none','-source','21','-target','21','-cp',str(oldClasses)+':'+cp,'-d',str(oracle),str(root/'validation/recovery-survival-v6/RecoverySurvivalLegacyOracle.java')])
run('legacy-oracle-old',['java','-DmineclientBridge.recoveryMaintenanceV5=true','-cp',str(oracle)+':'+str(oldClasses)+':'+cp,prefix+'RecoverySurvivalLegacyOracle',str(fixtures/'native-338-entry-journal.bin'),str(out/'legacy-oracle-old')])
for name in ['journal.bin','receipts.jsonl']:assert (out/'legacy-oracle-new'/name).read_bytes()==(out/'legacy-oracle-old'/name).read_bytes(),name
java('v5','RecoveryMaintenanceV5Checks',[oldFixtures,out/'v5'],('recoveryMaintenanceV5',))
java('v4','RecoveryNavigationV4Checks',[oldFixtures,out/'v4'],('recoveryNavigationV4','isolatedInput'))
java('ui','RecoveryRespawnUiChecks',[oldFixtures,out/'ui',classes],('recoveryInteractionV3','recoveryDeathScreenUi','isolatedInput'))
java('v3','RecoveryInteractionV3Checks',[w/'mdc-recovery-interaction-test-r3/results/native/fixtures',out/'v3'],('recoveryInteractionV3',))
java('short','RecoveryShortInputChecks',flags=('recoveryInteractionV2',));java('short-wire','RecoveryShortInputWireChecks',[out/'short-wire'],('recoveryInteractionV2',));java('v1','RecoveryInteractionChecks',[w/'mdc-recovery-interaction-test-r1/results/legacy57-fixtures',out/'v1','--preserve-fixtures'],('recoveryInteractionV2',));java('v2','RecoveryInteractionV2Checks',[w/'mdc-recovery-interaction-test-r2/results/legacy94-fixtures',out/'v2'],('recoveryInteractionV2',))
native=w/'minecraft-runtime/compile-only/minecraft-1.21.1-neoforge21.1.255-mdc-at-r2.jar'
for name,clazz in [('pinned-survival','RecoverySurvivalPinnedChecks'),('pinned-maintenance','RecoveryMaintenancePinnedChecks'),('pinned-navigation','RecoveryNavigationPinnedChecks'),('pinned-respawn','RecoveryRespawnPinnedChecks'),('pinned','RecoveryInteractionPinnedChecks')]:java(name,clazz,[native])
if (root/'validation/recovery-survival-v6/RecoverySurvivalV6ObservationWire.java').exists():java('observation-wire','RecoverySurvivalV6ObservationWire',[w/'mdc-runtime-recovery-20261021-r1/respawn-test-preparation-r1/COLD-BED-TO-DOOR-GEOMETRY.json',out/'observation-wire'])
assert hashes=={str(p.relative_to(s)):sha(p) for p in sources},'production changed during run';assert testhashes=={str(p.relative_to(s)):sha(p) for p in testsources},'tests changed during run'
result.update(production_sources=len(sources),production_classes=len(list(classes.rglob('*.class'))),classes_sha256={str(p.relative_to(classes)):sha(p) for p in sorted(classes.rglob('*.class'))},test_source_sha256=testhashes,resources_sha256={str(p.relative_to(s)):sha(p) for p in sorted((root/'src/main/resources').rglob('*')) if p.is_file()},stable=True,legacy338_exact=True)
(out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print('PASS stable',out)

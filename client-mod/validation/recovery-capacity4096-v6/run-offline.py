#!/usr/bin/env python3
"""Exact C8 4096/4MiB focused gate. No game or deployment. Frozen C7 remains untouched."""
import argparse,difflib,hashlib,json,pathlib,shutil,subprocess
p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--future-jsonl',required=True);a=p.parse_args()
s=pathlib.Path(__file__).resolve().parents[3];w=s.parents[1];c7=w/'mdc-recovery-survival-capacity-r1';c6=w/'mdc-recovery-survival-v6-r1';out=pathlib.Path(a.out).resolve();assert shutil.disk_usage(out.parent).free>=300*1024*1024
out.mkdir(parents=True,exist_ok=False);classes=out/'classes-production';tests=out/'classes-tests';oldoracle=out/'oracle-c7-classes'
for q in [classes,tests,oldoracle,out/'logs']:q.mkdir()
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();cp=(w/'minecraft-runtime/compile-classpath-at.txt').read_text().strip();javac=str(w/'minecraft-runtime/local-jdk-tools/javac');sources=sorted((s/'client-mod/src/main/java').rglob('*.java'));sourcehashes={str(p.relative_to(s)):sha(p) for p in sources};changed=[p for p in sources if sha(p)!=sha(c7/'source'/p.relative_to(s))];assert len(changed)==1 and changed[0].name=='RecoveryShortInputLedger.java'
ledger=changed[0];old=(c7/'source'/ledger.relative_to(s)).read_text();new=ledger.read_text();assert new.replace('SURVIVAL_MAX_HISTORY=4096;','SURVIVAL_MAX_HISTORY=1024;').replace('SURVIVAL_V6(SURVIVAL_MAX_HISTORY,4_194_304)','SURVIVAL_V6(SURVIVAL_MAX_HISTORY,2_097_152)')==old
resourcehashes={str(p.relative_to(s)):sha(p) for p in sorted((s/'client-mod/src/main/resources').rglob('*')) if p.is_file()};assert all(sha(c7/'source'/p)==h for p,h in resourcehashes.items())
(out/'ONLY-V6-TWO-CONSTANTS.diff').write_text(''.join(difflib.unified_diff(old.splitlines(keepends=True),new.splitlines(keepends=True),fromfile='C7/'+str(ledger.relative_to(s)),tofile='C8/'+str(ledger.relative_to(s)))))
fixture=w/'mdc-runtime-recovery-20261021-r1/nether-north-996-nine-stage-cold-frozen-r1/native-996-entry-journal.bin';public=fixture.with_name('public-ledger-996.json');future=pathlib.Path(a.future_jsonl).resolve();pins={str(p):sha(p) for p in [fixture,public,future]};assert pins[str(fixture)]=='ecf7ef54ca895c7b17a665ce0c572fcc7ac9eb1c123591f42de107067e16cfc6';assert pins[str(public)]=='7adf0f5e0882210cc18f21dd5b4b36efe366a0c94a090d15ffb82abd8a259fa9';assert pins[str(future)]=='a84e919a55f414640c19ffcbc9f274a20996f230b4c6f7867410414c4902135a'
testsources=sorted(pathlib.Path(__file__).parent.glob('*.java'));testhashes={str(p.relative_to(s)):sha(p) for p in testsources};frozenOldSources={str(p):sha(p) for p in sorted((c7/'source/client-mod/src/main/java').rglob('*.java'))};result={'scope':'offline C8 fullproduction compile and focused exact4096/4MiB tests; no world/runtime/game/HTTP/deployment','state':'RUNNING','source_sha256':sourcehashes,'resources_sha256':resourcehashes,'test_source_sha256':testhashes,'original_input_sha256':pins,'changed_production':[str(p.relative_to(s)) for p in changed],'all_methods_codec_protocol_source_exact':True,'free_before_bytes':shutil.disk_usage(out).free,'runs':[]}
def save():(out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
def run(name,cmd):
 assert shutil.disk_usage(out).free>=200*1024*1024,'free space reserve'
 r=subprocess.run(cmd,capture_output=True,text=True);(out/'logs'/f'{name}.stdout').write_text(r.stdout);(out/'logs'/f'{name}.stderr').write_text(r.stderr);result['runs'].append({'name':name,'argv':cmd,'exit_code':r.returncode});save();print(name,r.returncode,r.stdout[-700:],r.stderr[-1600:],flush=True)
 if r.returncode:raise SystemExit(r.returncode)
run('compile-fullproduction',[javac,'-proc:none','-source','21','-target','21','-cp',cp,'-d',str(classes),*map(str,sources)])
oldclasses=c7/'results/native-capacity/run-r2/classes-production';oldtests=c6/'results/native/full-r8/classes-tests';run('compile-focused-tests',[javac,'-proc:none','-source','21','-target','21','-cp',str(classes)+':'+str(oldtests)+':'+cp,'-d',str(tests),*map(str,testsources)])
prefix='io.github.campione01.mineclientbridge.';runtimecp=str(tests)+':'+str(oldtests)+':'+str(classes)+':'+cp
def java(name,clazz,args=(),flags=('recoverySurvivalV6',)):
 run(name,['java','-Xmx512m',*[f'-DmineclientBridge.{f}=true' for f in flags],'-cp',runtimecp,prefix+clazz,*map(str,args)])
java('capacity4096','RecoveryCapacity4096Checks',[fixture,future,out/'capacity4096'])
java('oracle-c8','RecoveryCapacity4096Oracle',[fixture,out/'oracle-c8'])
run('compile-oracle-c7',[javac,'-proc:none','-source','21','-target','21','-cp',str(oldclasses)+':'+cp,'-d',str(oldoracle),str(pathlib.Path(__file__).parent/'RecoveryCapacity4096Oracle.java')])
run('oracle-c7',['java','-Xmx512m','-DmineclientBridge.recoverySurvivalV6=true','-cp',str(oldoracle)+':'+str(oldclasses)+':'+cp,prefix+'RecoveryCapacity4096Oracle',str(fixture),str(out/'oracle-c7')])
for name in ['journal.bin','receipts.jsonl','digests.txt']:assert (out/'oracle-c7'/name).read_bytes()==(out/'oracle-c8'/name).read_bytes(),name
for name,candidate in [('receipts.jsonl','actual996-receipts.jsonl'),('digests.txt','actual996-digests.txt')]:assert (out/'oracle-c7'/name).read_bytes()==(out/'capacity4096'/candidate).read_bytes(),candidate
java('unchanged-short','RecoveryShortInputChecks',flags=('recoveryInteractionV2',))
java('unchanged-v5','RecoveryMaintenanceV5Checks',[w/'mdc-recovery-maintenance-v5-r1/results/native/fixtures',out/'unchanged-v5'],('recoveryMaintenanceV5',))
java('unchanged-v6','RecoverySurvivalV6Checks',[c6/'results/legacy338-fixtures/native-338-entry-journal.bin',out/'unchanged-v6'])
java('v6-exclusive','RecoverySurvivalV6Checks',['--both'],('recoverySurvivalV6','recoveryMaintenanceV5'))
java('v6-disabled','RecoverySurvivalV6Checks',['--disabled'],('recoveryMaintenanceV5',))
assert pins=={p:sha(pathlib.Path(p)) for p in pins};assert frozenOldSources=={p:sha(pathlib.Path(p)) for p in frozenOldSources};assert sourcehashes=={str(p.relative_to(s)):sha(p) for p in sources};assert testhashes=={str(p.relative_to(s)):sha(p) for p in testsources};assert resourcehashes=={str(p.relative_to(s)):sha(p) for p in sorted((s/'client-mod/src/main/resources').rglob('*')) if p.is_file()}
outputs={str(p.relative_to(classes)):sha(p) for p in sorted(classes.rglob('*.class'))};oldoutputs={str(p.relative_to(oldclasses)):sha(p) for p in sorted(oldclasses.rglob('*.class'))};assert outputs.keys()==oldoutputs.keys();changedclasses={p:h for p,h in outputs.items() if h!=oldoutputs[p]};assert set(changedclasses)=={'io/github/campione01/mineclientbridge/RecoveryShortInputLedger.class','io/github/campione01/mineclientbridge/RecoveryShortInputLedger$CapacityMode.class'},changedclasses
result.update(state='PASS_OFFLINE_NATIVE_C8_4096_4MIB',stable=True,production_sources=len(sources),production_classes=len(outputs),classes_sha256=outputs,changed_classes=changedclasses,no_class_added_or_removed=True,actual996_binary_receipts_digests_exact=True,original_inputs_and_C7_unchanged=True,free_after_bytes=shutil.disk_usage(out).free,not_run=['unrelated engine matrices','live Minecraft/loader/world','deployment'])
save();print('PASS',out,flush=True)

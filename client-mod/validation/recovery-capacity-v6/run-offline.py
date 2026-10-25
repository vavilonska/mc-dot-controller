#!/usr/bin/env python3
"""Focused native capacity compile/tests; only copied/synthetic local files, no game startup."""
import argparse,difflib,hashlib,json,pathlib,subprocess
p=argparse.ArgumentParser();p.add_argument('--out',required=True);a=p.parse_args()
s=pathlib.Path(__file__).resolve().parents[3];w=s.parents[1];old=w/'mdc-recovery-survival-v6-r1';out=pathlib.Path(a.out).resolve();out.mkdir(parents=True,exist_ok=False)
classes=out/'classes-production';tests=out/'classes-tests';oracle_old=out/'oracle-old-classes'
for p in [classes,tests,oracle_old,out/'logs']:p.mkdir()
cp=(w/'minecraft-runtime/compile-classpath-at.txt').read_text().strip();javac=str(w/'minecraft-runtime/local-jdk-tools/javac');sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
prod=sorted((s/'client-mod/src/main/java').rglob('*.java'));hashes={str(p.relative_to(s)):sha(p) for p in prod};changed=[p for p in prod if sha(p)!=sha(old/'source'/p.relative_to(s))]
assert {p.name for p in changed}=={'RecoveryShortInputLedger.java','NativeRecoveryShortInput.java'}
all_changed=[str(p.relative_to(s)) for p in sorted((s/'client-mod/src').rglob('*')) if p.is_file() and (not (old/'source'/p.relative_to(s)).exists() or sha(p)!=sha(old/'source'/p.relative_to(s)))]
assert set(all_changed)=={str(p.relative_to(s)) for p in changed},all_changed
patch=''.join(''.join(difflib.unified_diff((old/'source'/p.relative_to(s)).read_text().splitlines(keepends=True),p.read_text().splitlines(keepends=True),fromfile='C6/'+str(p.relative_to(s)),tofile='C7/'+str(p.relative_to(s)))) for p in changed);(out/'PRODUCTION-CAPACITY.diff').write_text(patch)
# Entire substantive behavior and codec methods remain byte-for-byte source text identical.
ledger=next(p for p in changed if p.name=='RecoveryShortInputLedger.java');oldledger=(old/'source'/ledger.relative_to(s)).read_text();newledger=ledger.read_text()
for start,end in [('    record Operation(', '    RecoveryShortInputLedger(Store'),('    synchronized Entry submit(', '    static final class FileStore')]:
 assert oldledger[oldledger.index(start):oldledger.index(end)]==newledger[newledger.index(start):newledger.index(end)],start
native=next(p for p in changed if p.name=='NativeRecoveryShortInput.java');oldnative=(old/'source'/native.relative_to(s)).read_text();newnative=native.read_text();start='        watchdog=Executors.newSingleThreadScheduledExecutor'
assert oldnative[oldnative.index(start):]==newnative[newnative.index(start):]
fixture=w/'mdc-runtime-recovery-20261021-r1/nether-west-481-four-stage-cold-frozen-r1/native-481-entry-journal.bin';fixture_sha=sha(fixture);assert fixture_sha=='ff0a3b42b6485fd70d876c11348d144321b3e845a55e46efc58551b131ab998a'
testsources=sorted(pathlib.Path(__file__).parent.glob('*.java'));testhashes={str(p.relative_to(s)):sha(p) for p in testsources}
result={'scope':'offline only; existing pinned compile classpath; no game/runtime/journal changes, no deployment or network','source_sha256':hashes,'changed_production':all_changed,'behavior_and_codec_source_exact':True,'original481_sha256':fixture_sha,'test_source_sha256':testhashes,'runs':[]}
def run(name,cmd):
 r=subprocess.run(cmd,capture_output=True,text=True);(out/'logs'/f'{name}.stdout').write_text(r.stdout);(out/'logs'/f'{name}.stderr').write_text(r.stderr);result['runs'].append({'name':name,'argv':cmd,'exit_code':r.returncode});(out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(name,r.returncode,r.stdout[-700:],r.stderr[-1500:],flush=True)
 if r.returncode:raise SystemExit(r.returncode)
run('compile-all-production',[javac,'-proc:none','-source','21','-target','21','-cp',cp,'-d',str(classes),*map(str,prod)])
oldclasses=old/'results/native/full-r8/classes-production';oldtests=old/'results/native/full-r8/classes-tests'
run('compile-focused-tests',[javac,'-proc:none','-source','21','-target','21','-cp',str(classes)+':'+str(oldtests)+':'+cp,'-d',str(tests),*map(str,testsources)])
prefix='io.github.campione01.mineclientbridge.';runCp=str(tests)+':'+str(oldtests)+':'+str(classes)+':'+cp
def java(name,clazz,args=(),flags=('recoverySurvivalV6',)):
 run(name,['java',*[f'-DmineclientBridge.{f}=true' for f in flags],'-cp',runCp,prefix+clazz,*map(str,args)])
java('capacity-v6','RecoveryCapacityV6Checks',[fixture,out/'capacity-v6'])
java('oracle-c7','RecoveryCapacityLegacyOracle',[fixture,out/'oracle-c7'])
run('compile-oracle-c6',[javac,'-proc:none','-source','21','-target','21','-cp',str(oldclasses)+':'+cp,'-d',str(oracle_old),str(pathlib.Path(__file__).parent/'RecoveryCapacityLegacyOracle.java')])
run('oracle-c6',['java','-DmineclientBridge.recoverySurvivalV6=true','-cp',str(oracle_old)+':'+str(oldclasses)+':'+cp,prefix+'RecoveryCapacityLegacyOracle',str(fixture),str(out/'oracle-c6')])
for name in ['journal.bin','receipts.jsonl','digests.txt']:
 assert (out/'oracle-c6'/name).read_bytes()==(out/'oracle-c7'/name).read_bytes(),name
for name,actual in [('receipts.jsonl','actual481-receipts.jsonl'),('digests.txt','actual481-digests.txt')]:
 assert (out/'oracle-c6'/name).read_bytes()==(out/'capacity-v6'/actual).read_bytes(),actual
java('legacy-short','RecoveryShortInputChecks',flags=('recoveryInteractionV2',))
java('legacy-v5','RecoveryMaintenanceV5Checks',[w/'mdc-recovery-maintenance-v5-r1/results/native/fixtures',out/'legacy-v5'],('recoveryMaintenanceV5',))
java('existing-v6','RecoverySurvivalV6Checks',[old/'results/legacy338-fixtures/native-338-entry-journal.bin',out/'existing-v6'])
java('v6-exclusive','RecoverySurvivalV6Checks',['--both'],('recoverySurvivalV6','recoveryMaintenanceV5'))
java('v6-disabled','RecoverySurvivalV6Checks',['--disabled'],('recoveryMaintenanceV5',))
assert hashes=={str(p.relative_to(s)):sha(p) for p in prod},'source changed during run';assert testhashes=={str(p.relative_to(s)):sha(p) for p in testsources};assert sha(fixture)==fixture_sha
outputs={str(p.relative_to(classes)):sha(p) for p in sorted(classes.rglob('*.class'))};oldoutputs={str(p.relative_to(oldclasses)):sha(p) for p in sorted(oldclasses.rglob('*.class'))}
removed=sorted(set(oldoutputs)-set(outputs));assert not removed
changedclasses=[p for p in outputs if outputs[p]!=oldoutputs.get(p)];assert all(p.split('/')[-1].startswith(('RecoveryShortInputLedger','NativeRecoveryShortInput')) for p in changedclasses),changedclasses
result.update(state='PASS_OFFLINE_NATIVE_CAPACITY',stable=True,production_source_count=len(prod),production_class_count=len(outputs),classes_sha256=outputs,changed_classes=changedclasses,removed_classes=removed,original481_untouched=True,actual481_binary_receipts_digests_exact=True,tests_not_run='Unrelated engine/world/live game/deployment suites intentionally not run')
(out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print('PASS',out,flush=True)

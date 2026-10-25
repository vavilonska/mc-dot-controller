#!/usr/bin/env python3
"""Offline compile, source-seam, actual ledger/codec and legacy checks. No game/network actions."""
import argparse,hashlib,json,pathlib,subprocess
p=argparse.ArgumentParser();p.add_argument('--out',required=True);a=p.parse_args()
s=pathlib.Path(__file__).resolve().parents[3];w=s.parents[1];root=s/'client-mod';out=pathlib.Path(a.out).resolve();out.mkdir(parents=True,exist_ok=False)
classes=out/'classes-production';tests=out/'classes-tests';classes.mkdir();tests.mkdir();(out/'logs').mkdir()
cp=(w/'minecraft-runtime/compile-classpath-at.txt').read_text().strip();javac=str(w/'minecraft-runtime/local-jdk-tools/javac');sources=sorted((root/'src/main/java').rglob('*.java'));sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest();hashes={str(f.relative_to(s)):sha(f) for f in sources}
report={'scope':'offline synthetic lease and actual production ledger/codec, no native gameplay capture','source_sha256':hashes,'runs':[],'game_started':False,'existing_endpoint_requested':False}
def run(name,cmd):
 r=subprocess.run(cmd,capture_output=True,text=True);(out/'logs'/f'{name}.stdout').write_text(r.stdout);(out/'logs'/f'{name}.stderr').write_text(r.stderr);report['runs'].append({'name':name,'argv':cmd,'exit_code':r.returncode});(out/'result.json').write_text(json.dumps(report,indent=2)+'\n');print(name,r.returncode,r.stdout[-500:],r.stderr[-500:],flush=True)
 if r.returncode:raise SystemExit(r.returncode)
run('compile-production',[javac,'-proc:none','-source','21','-target','21','-cp',cp,'-d',str(classes),*map(str,sources)])
testSources=sorted(f for folder in ['recovery-short-input','recovery-interaction','recovery-interaction-v2','recovery-interaction-v3','recovery-damage-diag'] for f in (root/'validation'/folder).glob('*.java'))
run('compile-tests',[javac,'-proc:none','-source','21','-target','21','-cp',str(classes)+':'+cp,'-d',str(tests),*map(str,testSources)])
runCp=str(tests)+':'+str(classes)+':'+cp
prefix='io.github.campione01.mineclientbridge.'
def java(name,clazz,args=(),flags=('recoveryInteractionV2',)):
 run(name,['java',*[f'-DmineclientBridge.{f}=true' for f in flags],'-cp',runCp,prefix+clazz,*map(str,args)])
java('v3','RecoveryInteractionV3Checks',[s.parent/'results/native/fixtures',out/'v3'],('recoveryInteractionV3',))
java('short','RecoveryShortInputChecks');java('short-wire','RecoveryShortInputWireChecks',[out/'short-wire'])
java('v1','RecoveryInteractionChecks',[w/'mdc-recovery-interaction-test-r1/results/legacy57-fixtures',out/'v1','--preserve-fixtures'])
java('v2','RecoveryInteractionV2Checks',[w/'mdc-recovery-interaction-test-r2/results/legacy94-fixtures',out/'v2'])
native=w/'minecraft-runtime/compile-only/minecraft-1.21.1-neoforge21.1.255-mdc-at-r2.jar'
java('pinned','RecoveryInteractionPinnedChecks',[native]);java('wart','RecoveryWartPinnedChecks',[native,w/'minecraft-runtime/versions/1.21.1/1.21.1.jar',out/'wart-audit.json'])
java('diag','RecoveryDamageDiagnosticChecks',[out/'diag-wire',native])
for old in ['recoveryShortInputV1','recoveryInteractionV1','recoveryInteractionV2']:java('flags-v3-'+old,'RecoveryInteractionChecks',['--both-flags'],('recoveryInteractionV3',old))
# Freeze legacy checks by exact method-source extraction; V3 cannot silently widen old freshness/TTL/effect seams.
base=w/'mdc-recovery-damage-diag-r1/source/client-mod/src/main/java/io/github/campione01/mineclientbridge';nativeRoot=root/'src/main/java/io/github/campione01/mineclientbridge'
def method(text,signature):
 start=text.index(signature);begin=text.index('{',start);depth=1;i=begin+1
 while depth:depth+=(text[i]=='{')-(text[i]=='}');i+=1
 return text[start:i]
unchanged={'NativeRecoveryShortInput.java':['private static boolean fresh(','private static boolean bound(','private static String contextProblem(','private static void cleanup('], 'RecoveryInteraction.java':['static String problem(','static boolean finalBinding(','static void rawOneShot(','static void mine(','static boolean release('], 'RecoveryShortInputLedger.java':['synchronized Entry submit(','synchronized boolean live(','private boolean expired(','synchronized boolean sample(','synchronized boolean claimCall(','private void invalidate(','synchronized void unknown(']}
for file,signatures in unchanged.items():
 for signature in signatures:assert method((base/file).read_text(),signature)==method((nativeRoot/file).read_text(),signature),(file,signature)
oldFresh=method((nativeRoot/'NativeRecoveryShortInput.java').read_text(),'private static boolean fresh(');assert 'age<=250_000_000L' in oldFresh and 'tick-c.tick()<=5' in oldFresh
report['unchanged_legacy_method_sources']=unchanged;report['source_unchanged_during_run']=all(sha(s/k)==v for k,v in hashes.items());assert report['source_unchanged_during_run']
report['test_source_sha256']={str(f.relative_to(s)):sha(f) for f in testSources};report['class_sha256']={str(f.relative_to(classes)):sha(f) for f in sorted(classes.rglob('*.class'))};report['pass']=True;(out/'result.json').write_text(json.dumps(report,indent=2)+'\n')

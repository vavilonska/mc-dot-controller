#!/usr/bin/env python3
"""Offline respawn gate, pinned-callgraph, real101 and existing recovery regressions. No game or GLFW calls."""
import argparse,hashlib,json,pathlib,subprocess
p=argparse.ArgumentParser();p.add_argument('--out',required=True);a=p.parse_args();s=pathlib.Path(__file__).resolve().parents[3];w=s.parents[1];root=s/'client-mod';out=pathlib.Path(a.out).resolve();out.mkdir(parents=True,exist_ok=False);classes=out/'classes-production';tests=out/'classes-tests';classes.mkdir();tests.mkdir();(out/'logs').mkdir()
cp=(w/'minecraft-runtime/compile-classpath-at.txt').read_text().strip();javac=str(w/'minecraft-runtime/local-jdk-tools/javac');sources=sorted((root/'src/main/java').rglob('*.java'));sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();hashes={str(p.relative_to(s)):sha(p) for p in sources};result={'scope':'offline only, no game/GLFW invocation/native entity construction','source_sha256':hashes,'runs':[]}
def run(name,cmd):
 r=subprocess.run(cmd,capture_output=True,text=True);(out/'logs'/f'{name}.stdout').write_text(r.stdout);(out/'logs'/f'{name}.stderr').write_text(r.stderr);result['runs'].append({'name':name,'argv':cmd,'exit_code':r.returncode});(out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(name,r.returncode,r.stdout[-300:],r.stderr[-600:],flush=True)
 if r.returncode:raise SystemExit(r.returncode)
run('compile-production',[javac,'-proc:none','-source','21','-target','21','-cp',cp,'-d',str(classes),*map(str,sources)])
testsources=sorted(p for n in ['recovery-short-input','recovery-interaction','recovery-interaction-v2','recovery-interaction-v3','recovery-damage-diag','recovery-respawn-ui'] for p in (root/'validation'/n).glob('*.java'))
run('compile-tests',[javac,'-proc:none','-source','21','-target','21','-cp',str(classes)+':'+cp,'-d',str(tests),*map(str,testsources)])
runCp=str(tests)+':'+str(classes)+':'+cp
prefix='io.github.campione01.mineclientbridge.'
def java(name,clazz,args=(),flags=('recoveryInteractionV2',)):
 run(name,['java',*[f'-DmineclientBridge.{f}=true' for f in flags],'-cp',runCp,prefix+clazz,*map(str,args)])
java('ui','RecoveryRespawnUiChecks',[s.parent/'results/native/fixtures',out/'ui',classes],('recoveryInteractionV3','recoveryDeathScreenUi','isolatedInput'))
java('flag-off','RecoveryRespawnUiChecks',['--flag-off'],('recoveryInteractionV3','isolatedInput'))
java('wrong-profile','RecoveryRespawnUiChecks',['--flag-off'],('recoveryInteractionV2','recoveryDeathScreenUi','isolatedInput'))
java('v3','RecoveryInteractionV3Checks',[w/'mdc-recovery-interaction-test-r3/results/native/fixtures',out/'v3'],('recoveryInteractionV3',))
java('short','RecoveryShortInputChecks');java('short-wire','RecoveryShortInputWireChecks',[out/'short-wire']);java('v1','RecoveryInteractionChecks',[w/'mdc-recovery-interaction-test-r1/results/legacy57-fixtures',out/'v1','--preserve-fixtures']);java('v2','RecoveryInteractionV2Checks',[w/'mdc-recovery-interaction-test-r2/results/legacy94-fixtures',out/'v2'])
native=w/'minecraft-runtime/compile-only/minecraft-1.21.1-neoforge21.1.255-mdc-at-r2.jar'
java('pinned','RecoveryInteractionPinnedChecks',[native]);java('wart','RecoveryWartPinnedChecks',[native,w/'minecraft-runtime/versions/1.21.1/1.21.1.jar',out/'wart-audit.json']);java('diag','RecoveryDamageDiagnosticChecks',[out/'diag-wire',native])
# Registration stays canceled; only dedicated button callback added; no old ledger/codec/profile change.
base=w/'mdc-recovery-interaction-test-r3/source/client-mod';prod=root/'src/main/java/io/github/campione01/mineclientbridge';old=base/'src/main/java/io/github/campione01/mineclientbridge'
for name in ['RecoveryShortInputLedger.java','RecoveryShortInputCodec.java','RecoveryInteraction.java','RecoveryInteractionDispatch.java','RecoveryChallengeLease.java','ClientInputIsolation.java','mixin/MouseHandlerMixin.java']:
 assert (prod/name).read_bytes()==(old/name).read_bytes(),name
assert (root/'src/main/resources/META-INF/accesstransformer.cfg').read_bytes()==(base/'src/main/resources/META-INF/accesstransformer.cfg').read_bytes()
text=(prod/'mixin/InputConstantsMixin.java').read_text();assert 'RecoveryDeathScreenUi.install(window);\n            callback.cancel();' in text
text=(prod/'RecoveryDeathScreenUi.java').read_text();assert text.index('stage=claimed')<text.index('if(window!=registeredWindow||window!=mc.getWindow().getWindow()||!sameBinding(mc,binding)||!hit(binding.button(),guiX,guiY))')<text.index('binding.button().onPress()')
assert 'lastRefusal' not in text and 'REPORTED_REFUSALS.add(reason)' in text
result['source_unchanged_during_run']=all(sha(s/k)==v for k,v in hashes.items());assert result['source_unchanged_during_run'];result['test_source_sha256']={str(p.relative_to(s)):sha(p) for p in testsources};result['class_sha256']={str(p.relative_to(classes)):sha(p) for p in sorted(classes.rglob('*.class'))};result['pass']=True;(out/'result.json').write_text(json.dumps(result,indent=2)+'\n')

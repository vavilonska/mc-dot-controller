#!/usr/bin/env python3
"""run_gate.py SOURCE_MANIFEST FRESH_RESULTS [--classes FRESH_PINNED_CLASSES CLASS_MANIFEST]."""
from pathlib import Path
import hashlib,json,os,subprocess,sys,time
V=Path(__file__).resolve().parent;S=V.parents[2];W=S.parent.parent
manifest=Path(sys.argv[1]).resolve();out=Path(sys.argv[2]).resolve();assert not out.exists() and S not in out.parents;out.mkdir()
def h(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def inv(p):return {str(f.relative_to(p)):h(f) for f in sorted(p.rglob('*')) if f.is_file()}
def write(p,v):p.write_text(json.dumps(v,indent=2,sort_keys=True)+'\n')
expected=json.loads(manifest.read_text())['files'];expected={p:(v['sha256'] if isinstance(v,dict) else v) for p,v in expected.items()};assert inv(S)==expected
cpfile=W/'minecraft-runtime/compile-classpath-at.txt';cp=cpfile.read_text().strip();deps=[Path(p) for p in cp.split(':')];jdk=W/'minecraft-runtime/jdk/jdk-21.0.12.1+1';java=jdk/'bin/java';javac=jdk/'bin/javac'
def inputs():return {'source_manifest_sha256':h(manifest),'sources':inv(S),'dependencies_ordered':[{'path':str(p),'sha256':h(p)} for p in deps], 'toolchain':{str(p):h(p) for p in [java,javac,jdk/'release',jdk/'lib/modules',jdk/'lib/server/libjvm.so']},'classpath_sha256':h(cpfile),'python':{'path':sys.executable,'sha256':h(sys.executable)},'external_class_manifest':({'path':str(Path(sys.argv[5]).resolve()),'sha256':h(sys.argv[5]),'class_inventory':inv(Path(sys.argv[4]).resolve())} if len(sys.argv)>3 else None)}
before=inputs();write(out/'INPUTS-BEFORE.json',before);steps=[]
def run(name,args,success=True):
 write(out/(name+'-command.json'),{'argv':args,'cwd':str(out),'timeout_seconds':45,'env':{'PYTHONDONTWRITEBYTECODE':'1'}});start=time.monotonic()
 with (out/(name+'.log')).open('w') as log:p=subprocess.run(args,cwd=out,stdout=log,stderr=subprocess.STDOUT,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'},timeout=45)
 row={'name':name,'exit_code':p.returncode,'seconds':time.monotonic()-start,'log_sha256':h(out/(name+'.log'))};steps.append(row);write(out/'PROGRESS.json',steps);print(json.dumps(row),flush=True);assert (p.returncode==0)==success,row
(out/'empty').mkdir();(out/'test-classes').mkdir();closed=['-proc:none','-implicit:none','-sourcepath',str(out/'empty'),'--release','21'];sources=sorted((S/'client-mod/src/main/java').rglob('*.java'))
external=len(sys.argv)>3
if external:
 assert sys.argv[3]=='--classes' and len(sys.argv)==6
 classes=Path(sys.argv[4]).resolve();class_manifest=Path(sys.argv[5]).resolve();class_pin=json.loads(class_manifest.read_text());assert inv(classes)==class_pin
 write(out/'EXTERNAL-CLASSES.json',{'path':str(classes),'manifest':str(class_manifest),'manifest_sha256':h(class_manifest),'classes':class_pin,'caller_must_bind_fresh_compile_to_same_source':True})
else:classes=out/'classes';classes.mkdir()
try:
 if not external:
  (out/'sources.txt').write_text('\n'.join(map(str,sources))+'\n');run('compile',[str(javac),'-J-Xmx384m','-J-XX:ActiveProcessorCount=1',*closed,'-cp',cp,'-d',str(classes),'@'+str(out/'sources.txt')])
 run('probe-compile',[str(javac),'-J-Xmx192m','-J-XX:ActiveProcessorCount=1',*closed,'-cp',str(classes)+':'+cp,'-d',str(out/'test-classes'),str(V/'ManagedReaderParityProbe.java')])
 for mode in ['none','swapped','subclass','wrong-holder']:
  run('probe-'+mode,[str(java),'-Xmx192m','-XX:ActiveProcessorCount=1','-cp',str(classes)+':'+str(out/'test-classes')+':'+cp,'io.github.campione01.mineclientbridge.ManagedReaderParityProbe',str(out/('proof-'+mode+'.json')),mode],mode=='none')
  if mode!='none':
   expected={'swapped':'exact holder maps to exact PercentageAttribute','subclass':'exact holder maps to exact PercentageAttribute','wrong-holder':'production reads exact official movement holder'}[mode]
   assert 'AssertionError: '+expected in (out/('probe-'+mode+'.log')).read_text()
finally:
 after=inputs();write(out/'INPUTS-AFTER.json',after);assert before==after,'inputs changed during gate';write(out/'PRODUCTION-CLASS-HASHES.json',inv(classes));write(out/'TEST-CLASS-HASHES.json',inv(out/'test-classes'))
 if external:assert inv(classes)==class_pin,'external production classes changed'
write(out/'RESULT.json',{'status':'passed','source_manifest_sha256':h(manifest),'input_manifest_sha256':h(out/'INPUTS-BEFORE.json'),'production_class_manifest_sha256':h(out/'PRODUCTION-CLASS-HASHES.json'),'native_sources':len(sources),'steps':steps,'scope':'registry-free actual compiled production and official native classes','registry_bootstrapped':False,'world_or_player_constructed':False,'game_started':False})

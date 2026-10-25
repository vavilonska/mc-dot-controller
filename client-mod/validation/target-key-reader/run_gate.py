#!/usr/bin/env python3
"""run_gate.py SOURCE_MANIFEST FRESH_RESULTS [--classes FRESH_PINNED_CLASSES CLASS_MANIFEST]."""
from pathlib import Path
import hashlib,json,os,subprocess,sys,time,zipfile
V=Path(__file__).resolve().parent;S=V.parents[2];W=S.parent.parent;python=Path(sys.executable).resolve()
manifest=Path(sys.argv[1]).resolve();out=Path(sys.argv[2]).resolve();assert not out.exists() and S not in out.parents;out.mkdir()
def h(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def inv(p):return {str(f.relative_to(p)):h(f) for f in sorted(p.rglob('*')) if f.is_file()}
def write(p,v):p.write_text(json.dumps(v,indent=2,sort_keys=True)+'\n')
expected=json.loads(manifest.read_text())['files'];expected={p:(v['sha256'] if isinstance(v,dict) else v) for p,v in expected.items()};assert inv(S)==expected
cpfile=W/'minecraft-runtime/compile-classpath-at.txt';cp=cpfile.read_text().strip();deps=[Path(p) for p in cp.split(':')];java=Path('/usr/bin/java').resolve();jdk=java.parent.parent;compiler=[str(java),'-Xmx384m','-XX:ActiveProcessorCount=1','-m','jdk.compiler/com.sun.tools.javac.Main']
baseline=W/'recovery-20261018-1115/checkpoint/delivery/mineclient-bridge-1.1.8-recovery-test.2.10.jar'
def inputs():return {'baseline_jar':{'path':str(baseline),'sha256':h(baseline)},'source_manifest_sha256':h(manifest),'sources':inv(S),'dependencies_ordered':[{'path':str(p),'sha256':h(p)} for p in deps], 'toolchain':{str(p):h(p) for p in [java,jdk/'release',jdk/'lib/modules',jdk/'lib/server/libjvm.so']},'classpath_sha256':h(cpfile),'python':{'path':str(python),'sha256':h(python)},'external_class_manifest':({'path':str(Path(sys.argv[5]).resolve()),'sha256':h(sys.argv[5]),'class_inventory':inv(Path(sys.argv[4]).resolve())} if len(sys.argv)>3 else None)}
before=inputs();write(out/'INPUTS-BEFORE.json',before);steps=[]
def run(name,args,success=True):
 write(out/(name+'-command.json'),{'argv':args,'cwd':str(out),'timeout_seconds':45,'env':{'PYTHONDONTWRITEBYTECODE':'1'}});start=time.monotonic()
 with (out/(name+'.log')).open('w') as log:p=subprocess.run(args,cwd=out,stdout=log,stderr=subprocess.STDOUT,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'},timeout=45)
 row={'name':name,'exit_code':p.returncode,'seconds':time.monotonic()-start,'log_sha256':h(out/(name+'.log'))};steps.append(row);write(out/'PROGRESS.json',steps);print(json.dumps(row),flush=True);assert (p.returncode==0)==success,row
(out/'empty').mkdir();(out/'test-classes').mkdir();closed=['-proc:none','-implicit:none','-sourcepath',str(out/'empty'),'-source','21','-target','21'];sources=sorted((S/'client-mod/src/main/java').rglob('*.java'))
external=len(sys.argv)>3
if external:
 assert sys.argv[3]=='--classes' and len(sys.argv)==6
 classes=Path(sys.argv[4]).resolve();class_manifest=Path(sys.argv[5]).resolve();class_pin=json.loads(class_manifest.read_text());assert inv(classes)==class_pin
 write(out/'EXTERNAL-CLASSES.json',{'path':str(classes),'manifest':str(class_manifest),'manifest_sha256':h(class_manifest),'classes':class_pin,'caller_must_bind_fresh_compile_to_same_source':True})
else:classes=out/'classes';classes.mkdir()
try:
 if not external:
  (out/'sources.txt').write_text('\n'.join(map(str,sources))+'\n');run('compile',[*compiler,*closed,'-cp',cp,'-d',str(classes),'@'+str(out/'sources.txt')])
 run('probe-compile',[*compiler,*closed,'-cp',str(classes)+':'+cp,'-d',str(out/'test-classes'),str(V/'TargetKeyReaderProbe.java'),str(V/'TargetReaderParityAudit.java')])
 run('key-probe',[str(java),'-Xmx192m','-XX:ActiveProcessorCount=1','-cp',str(classes)+':'+str(out/'test-classes')+':'+cp,'io.github.campione01.mineclientbridge.TargetKeyReaderProbe',str(out/'KEY-PROOF.json')])
 run('reader-audit',[str(java),'-Xmx192m','-XX:ActiveProcessorCount=1','-cp',str(classes)+':'+str(out/'test-classes')+':'+cp,'io.github.campione01.mineclientbridge.TargetReaderParityAudit',str(out/'READER-AUDIT.json')])
finally:
 write(out/'PRODUCTION-CLASS-HASHES.json',inv(classes));write(out/'TEST-CLASS-HASHES.json',inv(out/'test-classes'));after=inputs();write(out/'INPUTS-AFTER.json',after);assert before==after,'inputs changed during gate'
 if external:assert inv(classes)==class_pin,'external production classes changed'
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
with zipfile.ZipFile(baseline) as z:
 old={n:hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist() if n.endswith('.class')}
new=inv(classes);changed=[k for k in old if new.get(k)!=old[k]];added=sorted(set(new)-set(old));missing=sorted(set(old)-set(new))
prefix='io/github/campione01/mineclientbridge/'
expected_changed={prefix+n+'.class' for n in ('ScopedTargetAction','CapabilityTargetAction','TargetActionReaderPolicy')}
expected_added={prefix+'TargetActionKeySnapshot.class'}
debug_only={}
with zipfile.ZipFile(baseline) as z:
 for name in ('CapabilityTargetAction$ListFields','ScopedTargetAction$PolicyCells'):
  key=prefix+name+'.class';before_bytes=z.read(key);after_bytes=(classes/key).read_bytes();a,al=norm(before_bytes);b,bl=norm(after_bytes)
  assert a==b and al==bl,'change outside LineNumberTable line_number fields in '+key
  debug_only[key]={'baseline_sha256':old[key],'fresh_sha256':new[key],'normalized_sha256':hashlib.sha256(a).hexdigest(),'line_tables':al}
  expected_changed.add(key)
write(out/'DEBUG-ONLY-CLASS-PROOF.json',debug_only)
comparison={'baseline_classes':len(old),'fresh_classes':len(new),'unchanged_classes':len(old)-len(changed),'changed':changed,'added':added,'missing':missing,'expected_changed':sorted(expected_changed),'expected_added':sorted(expected_added),'debug_only_changed':sorted(debug_only)}
write(out/'BASELINE-CLASS-COMPARISON.json',comparison)
assert set(changed)==expected_changed and set(added)==expected_added and not missing,comparison
write(out/'RESULT.json',{'status':'passed','source_manifest_sha256':h(manifest),'input_manifest_sha256':h(out/'INPUTS-BEFORE.json'),'production_class_manifest_sha256':h(out/'PRODUCTION-CLASS-HASHES.json'),'native_sources':len(sources),'steps':steps,'scope':'actual official key objects, compiled production reader and registry-free official factory audit','compiler_change':'new explicit installed-Java module invocation with -source21 -target21; no --release claim','registry_bootstrapped':False,'world_or_player_constructed':False,'game_started':False})

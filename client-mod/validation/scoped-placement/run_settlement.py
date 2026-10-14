#!/usr/bin/env python3
"""Fresh compile; actual vanilla menu revision methods and source-exact guard extraction over synthetic readers."""
from pathlib import Path
import hashlib,json,os,re,subprocess,sys
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
JAVA=ROOT/'client-mod/src/main/java/io/github/campione01/mineclientbridge'
OUT=Path(sys.argv[1]).resolve();BASELINE=Path(sys.argv[2]).resolve()
EXTRA=[Path(p) for p in sys.argv[3:]]
if OUT.exists():raise SystemExit('Fresh output required; no reuse or automatic retry')
OUT.mkdir(parents=True)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(name,obj):(OUT/name).write_text(json.dumps(obj,indent=2)+'\n')
receipts=[];checks=[]
def check(ok,label):
 if not ok:raise AssertionError(label)
 checks.append(label)
def run(name,args):
 write(name+'-start.json',{'argv':list(map(str,args)),'timeout_seconds':90})
 with (OUT/(name+'.stdout')).open('w') as o,(OUT/(name+'.stderr')).open('w') as e:
  try:r=subprocess.run(list(map(str,args)),stdout=o,stderr=e,stdin=subprocess.DEVNULL,timeout=90);row={'name':name,'exit_code':r.returncode}
  except subprocess.TimeoutExpired:row={'name':name,'state':'owned_child_timeout_killed_reaped'}
 receipts.append(row);write(name+'-terminal.json',row)
 if row.get('exit_code')!=0:raise RuntimeError(name+' failed, inspect before new attempt')
JDK=Path(os.environ['JAVA_HOME']);CP=os.environ['MDC_NATIVE_CLASSPATH']
status='failed'
try:
 check(sha(BASELINE)=='ee48a41de9039740c2acd294399370060e1a8867e3f7e1dd1aa56281ccb360d7','exact published 9aed63f4 ScopedPlacement baseline')
 runtime_pins=json.loads((HERE/'settlement-runtime-pins.json').read_text())
 check(len(EXTRA)==len(runtime_pins),'exact additional runtime dependency inventory')
 for p,row in zip(EXTRA,runtime_pins):check(p.name==row['basename'] and sha(p)==row['sha256'],'trusted already-installed '+p.name)
 run('focused-placement',[sys.executable,HERE/'run.py',OUT/'focused'])
 current=JAVA/'ScopedPlacement.java';text=current.read_text();old=BASELINE.read_text();extract=[]
 def method(source,signature,path):
  start=source.index(signature);end=source.index('{',start)+1;depth=1
  while depth:depth+=(source[end]=='{')-(source[end]=='}');end+=1
  body=source[start:end];extract.append({'source_path':str(path),'source_sha256':sha(path),'signature':signature,'start_offset':start,'end_offset':end,'method_sha256':hashlib.sha256(body.encode()).hexdigest()});return body
 template=(HERE/'SettlementVanillaFixture.java.in').read_text()
 replacements={
 '// @EXACT_STACK_METHODS@':method(text,'static boolean exactDecrement(',current)+'\n'+method(text,'static boolean sameStack(',current),
 '// @EXACT_REVISION_METHOD@':method(text,'private boolean revisionPermitted(',current),
 '// @EXACT_CURRENT_MENU_CHECK@':method(text,'void check(LocalPlayer player)',current),
 '// @EXACT_BASELINE_MENU_CHECK@':method(old,'void check(LocalPlayer player)',BASELINE)}
 for marker,body in replacements.items():check(template.count(marker)==1,'one extraction marker '+marker);template=template.replace(marker,body)
 generated=OUT/'SettlementVanillaFixture.java';generated.write_text(template)
 write('EXTRACTION.json',{'method_slices':extract,'generated_source_sha256':sha(generated),'template_source_sha256':sha(HERE/'SettlementVanillaFixture.java.in'),'reader_model':'Synthetic typed slots, stack/count/component readers; exact extracted methods unchanged. Vanilla menu state methods execute from genuine dependency class.'})
 callback=method(text,'void check(Minecraft mc,boolean permitEffect,boolean ray)',current)
 check(callback.index('observed[0]=rawMenu.menu.getStateId()')<callback.index('checkCurrent(')<callback.index('rawMenu.menu.getStateId()==observed[0]')<callback.index('settlement.commit(observed[0])'),'revision snapshot validated throughout callback before commit')
 after=method(text,'void afterUse()',current)
 check(after.index('check(Minecraft.getInstance(),true,false)')<after.index('effectCount==1&&packetCount==1&&settled()')<after.index('settling=true'),'settlement gated after completed strict dispatch check')
 actions=(JAVA/'ClientActions.java').read_text();start=actions.index('private static void finish(String');finish=actions[start:actions.index('static boolean releaseDiscontinuousAttack',start)]
 check('!status.equals("succeeded") && a.scopedPlacement.attempted()' in finish and 'a.scopedPlacement.markUnknown()' in finish,'cancel/failure after effect remains unknown')
 check('released &= keyNeutral&&releaseBinding' in finish and 'released &= semanticContext' not in finish,'physical release separated from semantic cleanup')
 check('if(!semanticContext&&status.equals("succeeded"))' in finish and 'placement_cleanup_context_unconfirmed' in finish,'semantic cleanup cannot promote success')
 check('a.scopedPlacement.recordFailure(failure)' in actions,'specific guard failure captured')
 cleanup_template=(HERE/'SettlementCleanupFixture.java.in').read_text()
 for marker,signature in [('// @EXACT_ATTEMPTED_FAILURE_BLOCK@','if(a.scopedPlacement!=null && !status.equals("succeeded") && a.scopedPlacement.attempted())'),('// @EXACT_PLACEMENT_CLEANUP_BLOCK@','if(a.scopedPlacement!=null) {')]:
  body=method(finish,signature,JAVA/'ClientActions.java')
  # Report offsets relative to the full production file, not the finish() slice.
  extract[-1]['start_offset']+=start;extract[-1]['end_offset']+=start
  check(cleanup_template.count(marker)==1,'one cleanup extraction marker '+marker)
  cleanup_template=cleanup_template.replace(marker,body)
 cleanup_generated=OUT/'SettlementCleanupFixture.java';cleanup_generated.write_text(cleanup_template)
 write('CLEANUP-EXTRACTION.json',{'method_slices':extract[-2:],'generated_source_sha256':sha(cleanup_generated),'template_source_sha256':sha(HERE/'SettlementCleanupFixture.java.in'),'scope':'Exact placement finish blocks; synthetic guard and input observations; real production ActionRegistry.finishAfterCleanup and identity registry.'})
 classes=OUT/'classes';classes.mkdir();classpath=os.pathsep.join([str(OUT/'focused/classes'),CP,*map(str,EXTRA)])
 run('compile-vanilla-fixture',[JDK/'bin/javac','-proc:none','--release','21','-implicit:none','-cp',classpath,'-d',classes,generated,cleanup_generated])
 run('vanilla-settlement',[JDK/'bin/java','-Xmx384m','-XX:ActiveProcessorCount=1','-Xlog:class+init=info:file='+str(OUT/'vanilla-init.log'),'-cp',str(classes)+os.pathsep+classpath,'io.github.campione01.mineclientbridge.SettlementVanillaFixture'])
 run('cleanup-settlement',[JDK/'bin/java','-Xmx384m','-XX:ActiveProcessorCount=1','-Xlog:class+init=info:file='+str(OUT/'cleanup-init.log'),'-cp',str(classes)+os.pathsep+classpath,'io.github.campione01.mineclientbridge.SettlementCleanupFixture'])
 init=(OUT/'vanilla-init.log').read_text()+(OUT/'cleanup-init.log').read_text()
 check(not re.search(r"Initializing '(?:net/minecraft/client/Minecraft|net/minecraft/world/entity/Entity|io/github/campione01/mineclientbridge/(?:BridgeServer|ClientActions))'",init),'no real game/bridge initialization')
 run('vanilla-menu-javap',[JDK/'bin/javap','-c','-p','-classpath',CP,'net.minecraft.world.inventory.AbstractContainerMenu'])
 bytecode=(OUT/'vanilla-menu-javap.stdout').read_text();increment=bytecode.split('public int incrementStateId();')[1].split('public ')[0]
 check('32767' in increment and 'iand' in increment and 'iadd' in increment,'genuine vanilla increment modulo32768')
 check(all(sha(Path(row['source_path']))==row['source_sha256'] for row in extract),'source unchanged after checks')
 status='passed'
finally:write('RESULT.json',{'status':status,'checks':checks,'children':receipts,'game_started':False,'deployment':False,'live_settlement_proven':False,'original_T22_specific_exception_proven':False,'scope':'Genuine compilation, actual vanilla revision methods, production policy/fence execution, source-exact menu guard bodies with synthetic readers; no engine/world.'})
print('PASS offline settlement guard regression')

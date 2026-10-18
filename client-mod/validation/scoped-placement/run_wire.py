#!/usr/bin/env python3
"""Real placement wire codecs, exact terminal-source slice and synthetic readers. No game execution."""
from pathlib import Path
import hashlib,json,os,re,subprocess,sys
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
PACKAGE=ROOT/'client-mod/src/main/java/io/github/campione01/mineclientbridge'
OUT=Path(sys.argv[1]).resolve()
if OUT.exists():raise SystemExit('Refusing existing wire attempt; no automatic retry/overwrite')
OUT.mkdir(parents=True)
JDK=Path(os.environ['JAVA_HOME']);CP=os.environ['MDC_NATIVE_CLASSPATH'];receipts=[];status='failed'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(name,obj):(OUT/name).write_text(json.dumps(obj,indent=2)+'\n')
def run(label,args,timeout=180):
 write(label+'-start.json',{'argv':list(map(str,args)),'timeout_seconds':timeout})
 with (OUT/(label+'.stdout')).open('w') as o,(OUT/(label+'.stderr')).open('w') as e:
  try:r=subprocess.run(list(map(str,args)),stdin=subprocess.DEVNULL,stdout=o,stderr=e,timeout=timeout);result={'label':label,'exit_code':r.returncode,'state':'known_terminal'}
  except subprocess.TimeoutExpired:result={'label':label,'state':'owned_child_timeout_killed_reaped'}
 receipts.append(result);write(label+'-terminal.json',result)
 if result.get('exit_code')!=0:raise RuntimeError(label+' failed; no retry')
def extract(text,signature):
 start=text.index(signature);end=text.index('{',start)+1;depth=1
 while depth:depth+=(text[end]=='{')-(text[end]=='}');end+=1
 return start,end,text[start:end]
inputs=[PACKAGE/'ScopedPlacement.java',PACKAGE/'ScopedMining.java',PACKAGE/'ScopedNativePreflight.java',PACKAGE/'ScopedMovementWire.java',PACKAGE/'BridgeJson.java',PACKAGE/'ActionRegistry.java',PACKAGE/'CapabilitySnapshot.java',HERE/'PlacementWireProducer.java',HERE/'run_wire.py',HERE.parent/'movement-t13/WireV1Facts.java',HERE.parent/'movement-t13/WireV1Fixture.java']
frozen=[{'path':str(p.relative_to(ROOT)),'sha256':sha(p)} for p in inputs];write('INPUTS.json',frozen)
try:
 run('fresh-native-gate',[sys.executable,'-I','-B',HERE/'run.py',OUT/'native-gate'])
 generated=OUT/'generated';generated.mkdir();classes=OUT/'wire-classes';classes.mkdir();wires=OUT/'wire';wires.mkdir()
 source=(PACKAGE/'ScopedPlacement.java').read_text();signature='    JsonObject terminal(boolean neutral,boolean success)';start,end,body=extract(source,signature)
 mining=(PACKAGE/'ScopedMining.java').read_text();_,_,position=extract(mining,'    static JsonObject position(BlockPos p)')
 preamble='''package io.github.campione01.mineclientbridge;
import com.google.gson.JsonObject;
/** Test-only receiver. terminal() body and nested position() body are exact source extractions.
 * All context/count/settled inputs below are synthetic, not native world observations. */
final class ScopedPlacementTerminalSlice {
    static final String PROFILE=ScopedPlacement.PROFILE;
    final ClientActionRequest request;
    final BlockPos target,support;
    final int selected,initialCount;
    final long deadline;
    final SyntheticPlayer player;
    boolean attempted=true,unknown=false,syntheticSettled=true;
    int effectCount=1,packetCount=1,checks=7;
    ScopedPlacementTerminalSlice(ClientActionRequest request,int initial,int after,int slot,long deadline){
        this.request=request;this.initialCount=initial;this.selected=slot;this.deadline=deadline;
        support=new BlockPos(request.support().x(),request.support().y(),request.support().z());
        target=new BlockPos(support.getX(),support.getY()+1,support.getZ());player=new SyntheticPlayer(after);
    }
    boolean settled(){return syntheticSettled;}
    record SyntheticStack(int count){int getCount(){return count;}}
    record SyntheticPlayer(int count){SyntheticStack getMainHandItem(){return new SyntheticStack(count);}}
    record BlockPos(int x,int y,int z){int getX(){return x;}int getY(){return y;}int getZ(){return z;}}
    static final class ScopedMining {
'''
 suffix='\n    }\n'+body+'\n}\n';generated_source=preamble+position+suffix;receiver=generated/'ScopedPlacementTerminalSlice.java';receiver.write_text(generated_source)
 if generated_source.count(body)!=1 or sha(PACKAGE/'ScopedPlacement.java')!=frozen[0]['sha256']:raise AssertionError('terminal extraction changed')
 report={'production_source':'client-mod/src/main/java/io/github/campione01/mineclientbridge/ScopedPlacement.java','production_source_sha256':sha(PACKAGE/'ScopedPlacement.java'),'method_signature':signature,'start_offset':start,'end_offset':end,'terminal_method_sha256':hashlib.sha256(body.encode()).hexdigest(),'extracted_source_path':str(receiver.relative_to(OUT)),'extracted_source_sha256':sha(receiver),'position_method_sha256':hashlib.sha256(position.encode()).hexdigest(),'synthetic_readers':['player.getMainHandItem().getCount','settled()','BlockPos coordinate accessors'],'scope':'Exact unmodified production terminal method body, synthetic receiver/count/settled data. Actual surrounding codecs/classes. No live settlement proof.'}
 write('TERMINAL-EXTRACTION.json',report);(wires/'TERMINAL-EXTRACTION.json').write_text(json.dumps(report,indent=2)+'\n')
 cp=os.pathsep.join([str(OUT/'native-gate/classes'),CP]);empty=OUT/'empty-sourcepath';empty.mkdir()
 run('compile-wire-fixture',[JDK/'bin/javac','-J-Xmx384m','-J-XX:ActiveProcessorCount=1','-proc:none','--release','21','-encoding','UTF-8','-implicit:none','-sourcepath',empty,'-cp',cp,'-d',classes,receiver,HERE/'PlacementWireProducer.java',HERE.parent/'movement-t13/WireV1Facts.java',HERE.parent/'movement-t13/WireV1Fixture.java'])
 for material in ('cobblestone','crafting_table','furnace'):
  destination=wires if material=='cobblestone' else OUT/('wire-'+material)
  if destination!=wires:destination.mkdir()
  (destination/'TERMINAL-EXTRACTION.json').write_text(json.dumps(report,indent=2)+'\n') if destination!=wires else None
  run('emit-placement-wire-'+material,[JDK/'bin/java','-Xmx384m','-XX:ActiveProcessorCount=1','-Xlog:class+init=info:file='+str(OUT/(material+'-class-init.log')),'-cp',str(classes)+os.pathsep+cp,'io.github.campione01.mineclientbridge.PlacementWireProducer',destination,'minecraft:'+material])
  log=(OUT/(material+'-class-init.log')).read_text()
  if re.search(r"Initializing '(?:net/minecraft/client/Minecraft|net/minecraft/world/entity/Entity|io/github/campione01/mineclientbridge/(?:BridgeServer|ClientActions))'",log):raise AssertionError('unexpected real engine initialization')
 if frozen!=[{'path':str(p.relative_to(ROOT)),'sha256':sha(p)} for p in inputs]:raise AssertionError('input changed')
 write('WIRE-MANIFEST.json',{'files':[{'path':str(p.relative_to(OUT)),'sha256':sha(p)} for folder in (wires,OUT/'wire-crafting_table',OUT/'wire-furnace') for p in sorted(folder.glob('*.json'))]})
 status='passed'
finally:write('RESULT.json',{'status':status,'children':receipts,'terminal_extraction':'TERMINAL-EXTRACTION.json','wire_directory':'wire','game_started':False,'mixins_applied':False,'world_settlement_proven':False,'scope':'Actual compiled production witness/Entry/assembly/projection/HTTP bytes; exact terminal-source slice with synthetic readers. Python consumer must run separately.'})
print('PASS actual placement Java wire fixture; synthetic facts/readback only')

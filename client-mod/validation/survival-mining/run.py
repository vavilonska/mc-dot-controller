#!/usr/bin/env python3
"""Compile and exercise production closed-cell policy and actual HTTP wire; never start a game.
Prerequisites are pinned compiler-only jars and trusted JDK 21 used by movement-t13.
"""
from pathlib import Path
import hashlib,json,os,subprocess,sys
HERE=Path(__file__).resolve().parent;R=HERE.parents[2];O=Path(sys.argv[1]).resolve()
if O.exists():raise SystemExit('Refusing existing output; unknown states are never retried')
O.mkdir();(O/'classes').mkdir();(O/'tests').mkdir();(O/'inputs').mkdir()
J=Path(os.environ['JAVA_HOME'])/'bin';CP=os.environ['MDC_NATIVE_CLASSPATH'];receipts=[]
parts=('capability-runtime','capability-runtime/tests','resident-controller','navigation-controller','navigation-cursor','defense-watchdog','gameplay-helpers','building-controller','external-controller','multiagent-coordination')
for part in reversed(parts):sys.path.insert(0,str(R/part))
from mining_collect.mining.test_survival_mining import fixture,cell,LOGS
from resident_controller.capability_snapshot import validate_scoped_witness
from resident_controller import mining_snapshot
source=sorted((R/'client-mod/src/main/java').rglob('*.java'));tests=sorted(HERE.glob('*.java'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
inputs=[{'path':str(p.relative_to(R)),'sha256':sha(p)} for p in source+tests]
(O/'INPUTS.json').write_text(json.dumps(inputs,indent=2))
def run(label,cmd,cp_env=None):
 (O/(label+'-START.json')).write_text(json.dumps({'argv':cmd,'scope':'offline no world/server/client entrypoint'},indent=2))
 with (O/(label+'.stdout')).open('x') as out,(O/(label+'.stderr')).open('x') as err:
  p=subprocess.Popen(cmd,cwd=O,stdin=subprocess.DEVNULL,stdout=out,stderr=err,env=cp_env)
  (O/(label+'-PID.json')).write_text(json.dumps({'pid':p.pid,'owned':True}))
  try:code=p.wait(timeout=120)
  except subprocess.TimeoutExpired:p.kill();code=p.wait();raise RuntimeError('known timeout, owned process killed/reaped, no automatic retry')
 receipt={'label':label,'exit_code':code};receipts.append(receipt);(O/(label+'-TERMINAL.json')).write_text(json.dumps(receipt))
 if code:raise RuntimeError(label+' failed; inspect retained terminal evidence')
 print('PASS '+label,flush=True)
status='failed'
try:
 cases=[]
 for kind in LOGS:
  for axis in ('x','y','z'):cases.append(fixture('minecraft:'+kind+'_log',{'axis':axis}))
 for ore in ('minecraft:iron_ore','minecraft:deepslate_iron_ore'):cases.append(fixture(ore))
 contexts=[('minecraft:'+kind+'_leaves','MangroveLeavesBlock' if kind=='mangrove' else 'LeavesBlock',{'distance':'3','persistent':'false','waterlogged':'false'},True) for kind in LOGS]
 contexts += [('minecraft:short_grass','TallGrassBlock',{},False),('minecraft:fern','TallGrassBlock',{},False),
  ('minecraft:tall_grass','DoublePlantBlock',{'half':'lower'},False),('minecraft:large_fern','DoublePlantBlock',{'half':'upper'},False),
  ('minecraft:poppy','FlowerBlock',{},False),('minecraft:vine','VineBlock',dict.fromkeys(('up','north','south','east','west'),'false'),False),
  ('minecraft:coal_ore','DropExperienceBlock',{},True),('minecraft:deepslate','RotatedPillarBlock',{'axis':'y'},True)]
 for spec in contexts:
  d=fixture();cell(d,(1,65,1),*spec);cases.append(d)
 for i,d in enumerate(cases):
  validate_scoped_witness(*d)
  (O/'inputs'/f'{i:03}-native.json').write_text(json.dumps(d[0]))
  (O/'inputs'/f'{i:03}-bindings.json').write_text(json.dumps(d[1:]))
 run('compile-production',[str(J/'javac'),'-J-Xmx384m','-J-XX:ActiveProcessorCount=1','-proc:none','--release','21','-cp',CP,'-d',str(O/'classes'),*map(str,source)])
 cp=str(O/'classes')+os.pathsep+CP
 run('compile-tests',[str(J/'javac'),'-J-Xmx256m','-proc:none','--release','21','-cp',cp,'-d',str(O/'tests'),*map(str,tests)])
 cp=str(O/'tests')+os.pathsep+cp
 run('cell-policy-wire',[str(J/'java'),'-Xmx128m','-XX:ActiveProcessorCount=1','-Xlog:class+init=info:file='+str(O/'class-init.log'),'-cp',cp,
  'io.github.campione01.mineclientbridge.SurvivalMiningCellChecks',str(O/'inputs'),str(O/'wire')])
 for i,d in enumerate(cases):
  emitted=json.loads((O/'wire'/f'{i:03}-native.json').read_text());validate_scoped_witness(emitted,*d[1:])
 vocab=json.loads((O/'wire'/'vocabulary.json').read_text())
 assert set(vocab)==mining_snapshot.STATIC
 for id,row in vocab.items():
  assert row['class']==mining_snapshot.cell_class(id)
  assert row['target']==(id in mining_snapshot.BLOCKS)
  assert row['full_cube']==(id not in mining_snapshot.AIR| mining_snapshot.PLANTS)
  assert row['body_clear']==(id in mining_snapshot.AIR | (mining_snapshot.PLANTS-{'minecraft:vine'}))
  assert row['support']==(id not in mining_snapshot.AIR | mining_snapshot.PLANTS | mining_snapshot.LEAVES)
 log=(O/'class-init.log').read_text()
 for name in ('net/minecraft/client/Minecraft','net/minecraft/world/entity/Entity','io/github/campione01/mineclientbridge/ClientActions','io/github/campione01/mineclientbridge/BridgeServer'):
  assert "Initializing '"+name+"'" not in log
 assert inputs==[{'path':str(p.relative_to(R)),'sha256':sha(p)} for p in source+tests]
 status='passed'
finally:
 (O/'RESULT.json').write_text(json.dumps({'status':status,'production_java_sources':len(source),'wire_witnesses':len(cases),
  'runs':receipts,'scope':'fresh full production compile, pure production policy, real HTTP serializer, strict resident wire consumer; synthetic captured facts',
  'live_mining':'NOT_RUN','native_registry_shapes':'separate optional bounded registry bootstrap','deployment':False},indent=2))
print('PASS current Java wire -> Resident consumption and exact vocabulary agreement',flush=True)

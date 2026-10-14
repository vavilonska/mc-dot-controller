#!/usr/bin/env python3
"""Finite production placement compile/policy/seam audit. No game, socket, deployment or world write."""
from pathlib import Path
import hashlib,json,os,re,subprocess,sys,zipfile
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
JAVA=ROOT/'client-mod/src/main/java/io/github/campione01/mineclientbridge'
JDK=Path(os.environ['JAVA_HOME'])
CP=[Path(s) for s in os.environ['MDC_NATIVE_CLASSPATH'].split(os.pathsep)]
OUT=Path(sys.argv[1]).resolve()
if OUT.exists():raise SystemExit('Existing attempt forbidden; inspect terminal state before a new output directory')
OUT.mkdir(parents=True)
receipts=[]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(name,obj):(OUT/name).write_text(json.dumps(obj,indent=2)+'\n')
def run(label,args):
 write(label+'-start.json',{'argv':list(map(str,args)),'timeout_seconds':90})
 with (OUT/(label+'.stdout')).open('w') as o,(OUT/(label+'.stderr')).open('w') as e:
  try:r=subprocess.run(list(map(str,args)),stdin=subprocess.DEVNULL,stdout=o,stderr=e,timeout=90);result={'label':label,'exit_code':r.returncode,'state':'known_terminal'}
  except subprocess.TimeoutExpired:result={'label':label,'state':'owned_child_timeout_killed_reaped'}
 receipts.append(result);write(label+'-terminal.json',result)
 if result.get('exit_code')!=0:raise RuntimeError(label+' failed; no automatic retry')
def method(s,key):
 a=s.index(key);i=s.index('{',a)+1;depth=1
 while depth:depth+=(s[i]=='{')-(s[i]=='}');i+=1
 return s[a:i]
def check(ok,name):
 if not ok:raise AssertionError(name)
 checks.append(name)
status='failed';checks=[]
try:
 pins=json.loads((HERE.parent/'movement-t13/expected-prerequisites.json').read_text())
 for name in ['java','javac']:check(sha(JDK/'bin'/name)==pins[name+'_sha256'],'trusted '+name)
 check(len(CP)==len(pins['classpath']),'exact classpath inventory')
 for p,row in zip(CP,pins['classpath']):
  check(p.name==row['basename'] and sha(p)==row['sha256'],'trusted classpath '+p.name)
  with zipfile.ZipFile(p) as jar:check(not any(n.startswith('io/github/campione01/mineclientbridge/') and n.endswith('.class') for n in jar.namelist()),'no historical mod classes '+p.name)
 sources=sorted(JAVA.rglob('*.java'));frozen=[{'path':str(p.relative_to(ROOT)),'sha256':sha(p)} for p in sources];write('INPUTS.json',frozen)
 s=(JAVA/'ClientActions.java').read_text();legacy=method(s,'private static void place(Minecraft');cap=method(s,'private static void placeCapability(')
 baseline=json.loads((HERE/'baseline-methods.json').read_text())
 check(hashlib.sha256(legacy.encode()).hexdigest()==baseline['legacy_place_sha256'],'legacy place body unchanged')
 check('case "place_block" -> { if(a.capabilityGuard!=null)placeCapability(mc,a);else place(mc,a); }' in s,'actual selected capability branch')
 check(cap.index('a.scopedPlacement.beforeUse(mc,hit)')<cap.index('a.dispatched = true')<cap.index('ScopedPlacementDispatch.use('),'actual branch check/latch/token chronology')
 check('a.scopedPlacement.check(mc,a.dispatched,false)' in cap and 'a.placedStableTicks >= 5 && consumed' in cap,'real branch repeated checks and five stable tick gate')
 check('ScopedPlacementDispatch' not in legacy and 'scopedPlacement' not in legacy,'legacy has no new token')
 post=method(s,'private static void postTick()');check(post.index('RuntimeAction entered=active')<post.index('try {') and 'if(entered.scopedPlacement==null || active==entered)failException(failure)' in post,'placement postTick exception cannot finish replacement owner; legacy catch preserved')
 guard=(JAVA/'ScopedPlacement.java').read_text();effect=method(guard,'void beforeEffect(');send=method(guard,'void send(')
 check(effect.index('check(Minecraft.getInstance(),false,true)')<effect.index('"placement_effect_context_changed_after_hooks"')<effect.index('effectCount++'),'effect post-hook recount before latch')
 check(send.count('packetBinding(use)')==2 and send.index('packetBinding(use)')<send.index('check(Minecraft.getInstance(),true,false)')<send.rindex('packetBinding(use)')<send.index('packetCount++'),'exact packet fields before and after final checks')
 check('callbackFence.check(()->{'  in guard,'production uses poison-on-reentry helper')
 dispatch=(JAVA/'ScopedPlacementDispatch.java').read_text();check('finally{CALL.remove();}' in dispatch,'dynamic token cleanup finally')
 check('itemInstalled&&packetInstalled&&sendInstalled&&ScopedMovementEntities.ready()' in dispatch,'all installed seams gate readiness')
 config=json.loads((ROOT/'client-mod/src/main/resources/mineclient_bridge.mixins.json').read_text())
 for name in ['ScopedPlacementItemMixin','ScopedPlacementPacketMixin','ScopedPlacementSendMixin']:check(name in config['client'],'required registered '+name)
 classes=OUT/'classes';tests=OUT/'test-classes';classes.mkdir();tests.mkdir();empty=OUT/'empty-sourcepath';empty.mkdir()
 flags=['-J-Xmx384m','-J-XX:ActiveProcessorCount=1','-proc:none','--release','21','-encoding','UTF-8','-implicit:none','-sourcepath',empty]
 run('compile-all-production',[JDK/'bin/javac',*flags,'-cp',os.pathsep.join(map(str,CP)),'-d',classes,*sources])
 cp=os.pathsep.join(map(str,[classes,*CP]));run('compile-placement-tests',[JDK/'bin/javac',*flags,'-cp',cp,'-d',tests,*sorted(HERE.glob('*Checks.java'))])
 for test in sorted(HERE.glob('*Checks.java')):
  run(test.stem,[JDK/'bin/java','-Xmx384m','-XX:ActiveProcessorCount=1','-Xlog:class+init=info:file='+str(OUT/(test.stem+'-init.log')),'-cp',str(tests)+os.pathsep+cp,'io.github.campione01.mineclientbridge.'+test.stem])
 run('compiled-branch-javap',[JDK/'bin/javap','-c','-p','-classpath',classes,'io.github.campione01.mineclientbridge.ClientActions'])
 bytecode=(OUT/'compiled-branch-javap.stdout').read_text();part=bytecode.split('private static void placeCapability(')[1].split('private static boolean capabilityDispatchCheck')[0]
 check('ScopedPlacement.beforeUse' in part and 'ScopedPlacementDispatch.use' in part,'compiled selected branch contains real guard and token')
 for cls,name in [('net.minecraft.world.item.BlockItem','game-item-javap'),('net.minecraft.client.multiplayer.MultiPlayerGameMode','game-mode-javap'),('net.minecraft.client.multiplayer.ClientCommonPacketListenerImpl','game-send-javap')]:run(name,[JDK/'bin/javap','-c','-p','-classpath',CP[0],cls])
 item=(OUT/'game-item-javap.stdout').read_text().split('protected boolean placeBlock(')[1].split('public static boolean updateCustomBlockEntityTag')[0]
 check(item.count('Level.setBlock:')==1 and 'bipush        11' in item,'genuine vanilla placeBlock single setBlock flags11')
 sendcode=(OUT/'game-send-javap.stdout').read_text().split('public void send(net.minecraft.network.protocol.Packet<?>);')[1].split('return')[0]
 check(sendcode.index('NetworkRegistry.checkPacket')<sendcode.index('Connection.send'),'genuine send NeoForge hook precedes final injection target')
 for p in OUT.glob('*-init.log'):check(not re.search(r"Initializing '(?:net/minecraft/client/Minecraft|net/minecraft/world/entity/Entity|io/github/campione01/mineclientbridge/(?:BridgeServer|ClientActions))'",p.read_text()),'no real engine initialization '+p.name)
 check(frozen==[{'path':str(p.relative_to(ROOT)),'sha256':sha(p)} for p in sources],'source freeze unchanged')
 status='passed'
finally:write('RESULT.json',{'status':status,'checks':checks,'children':receipts,'game_started':False,'mixins_applied':False,'live_placement_proven':False,'deployment':False,'scope':'Actual production compilation, pure intent/callback/packet identity execution and source/bytecode boundary audit only.'})
print('PASS placement native offline gate; no live acceptance')

"""Finite actual-source wiring checks. Does not execute actual Minecraft lifecycle."""
from pathlib import Path
import hashlib,json,re,sys
ROOT=Path(__file__).resolve().parent
SOURCE=ROOT.parents[2]
GENERATED=Path(sys.argv[1])
REL=Path('client-mod/src/main/java/io/github/campione01/mineclientbridge')
def source(root,name):return (root/REL/(name+'.java')).read_text()
def method(text,signature):
 start=text.index(signature);brace=text.index('{',start);depth=1;end=brace+1
 while depth:depth+=(text[end]=='{')-(text[end]=='}');end+=1
 return text[start:end]
a=source(SOURCE,'ClientActions');m=source(SOURCE,'ScopedFlatMovement');entities=source(SOURCE,'ScopedMovementEntities');registry=source(SOURCE,'ActionRegistry')
checks=[]
def check(value,label):
 if not value:raise AssertionError(label)
 checks.append(label)
for row in json.loads((ROOT/'expected-production.json').read_text())['sources']:
 check(hashlib.sha256((SOURCE/row['path']).read_bytes()).hexdigest()==row['sha256'],'pinned direct production source '+Path(row['path']).stem)
for signature in ['static boolean ownsScopedMovement(', 'static String session()', 'static boolean ownsInput()', 'static long ownershipRevision()']:
 check(method(a,signature) in (GENERATED/'io/github/campione01/mineclientbridge/ClientActions.java').read_text(),'exact production owner-query excerpt '+signature)
for signature,digest in json.loads((ROOT/'expected-lifecycle-methods.json').read_text()).items():
 check(hashlib.sha256(method(a,signature).encode()).hexdigest()==digest,'reviewed combined lifecycle/callsite body '+signature)
historical=json.loads((ROOT/'historical-t13-lifecycle-methods.json').read_text())
for signature in ['private static void followPath(', 'private static void look(']:
 check(hashlib.sha256(method(a,signature).encode()).hexdigest()==historical[signature],'unchanged original T13 body '+signature)
check('if(active!=a)return; // A native hook may cancel or replace this exact owner.' in a and 'if(active==entered)failException(failure)' in a,'combined combat Pre exact-owner interruption fence')
check('active.scopedCombat.activate(active.entry);active.combat.bindScoped(active.scopedCombat)' in a and 'active.scopedMining.activate(active.entry)' in a,'combined exact Entry guard activation')
check('ScopedMiningDispatch.cleanup(a.scopedMining,mc.gameMode::stopDestroyBlock)' in a and 'a.scopedMining.terminal(released,status.equals("succeeded")' in a,'combined mining guarded cleanup and terminal evidence')
check(a.count('a.entry.ticks++')==1,'single native Pre increment')
pre=method(a,'private static void preTick()')
check(pre.index('context(mc,"pre_tick")')<pre.index('a.entry.ticks++')<pre.index('if (mc.isPaused())')<pre.index('case "follow_path"'),'Pre context/increment/pause/dispatch ordering')
check('active.scopedMovement.activate(active.entry)' in a,'exact active Entry activation call')
check('active.entry==entry' in a and 'ACTIONS.active()==entry' in a and 'entry.running()' in a,'owner binds runtime and registry exact Entry')
check('final long sourceNano, sourceTick, deadline;' in m and 'deadline=sourceNano+request.timeoutMs()*1_000_000L' in m and 'now>=sourceNano && now<deadline' in m,'original-source monotonic strict exclusive deadline retained')
check('MAX_TIMEOUT_MS = 8000' in source(SOURCE,'ScopedFlatPolicy'),'eight-second profile ceiling unchanged')
check('p.tick-sourceTick' not in m and 'tick-sourceTick' not in entities,'world-time differences no longer lifetime authority')
check('level.getGameTime()==p.tick' in m and 'current.frame.tick()==frame.tick()' in entities and 'level.getGameTime()==tick' in entities,'same-callback world-time equality retained at all three boundaries')
before=method(m,'void beforeEffect(')
check(before.index('int actionTicks=actionTicks()')<before.index('ScopedMovementEntities.capture')<before.index('entities.assertUnchanged()')<before.index('fence(mc,pose,true,actionTicks)')<before.index('account(pose,actionTicks)')<before.index('checks++'),'actual effect check ordering')
fence=method(m,'private void fence(')
check('actionEntry.ticks==actionTicks' in fence and 'ClientActions.ownershipRevision()==ownerRevision' in fence,'post-hook raw counter/owner fence')
account=method(m,'private void account(')
check(account.index('require(nextTickDistance')<account.index('tickDistance=nextTickDistance')<account.index('sampleActionTick=actionTicks'),'atomic failed-accounting boundary')
check(a.count('a.scopedMovement.beforeEffect(')==3,'all three native view/input fences remain')
follow=method(a,'private static void followPath(')
check(follow.index('a.scopedMovement.beforeEffect(mc)')<follow.index('var points')<follow.index('finish("succeeded", "path_reached")'),'successful path_reached follows same-Pre successful check; sample action tick equals entry ticks absent a failed/reentrant transition')
finish=method(a,'private static void finish(')
check(finish.index('active = null')<finish.index('a.input.forwardImpulse = a.input.leftImpulse = 0')<finish.index('a.scopedMovement.terminal(neutral)')<finish.index('ACTIONS.finishAfterCleanup'),'native owner-clear/input-neutral/terminal/registry-cleanup chronology')
check('input_release_unconfirmed' in registry and 'Entry old = existing(request)' in registry,'original registry release and no-replay behavior')
check('out.addProperty("last_entity_check_tick",lastEntityTick)' in m and 'out.addProperty("last_entity_check_action_tick",sampleActionTick)' in m and 'out.addProperty("timing_contract",TIMING_CONTRACT)' in m,'distinct mandatory terminal clock-domain fields')
result={'scope':'source wiring only; strict nanosecond boundary established by unchanged actual expression, not simulated exact System.nanoTime sampling','checks':checks,'passed':True}
Path(sys.argv[2]).write_text(json.dumps(result,indent=2)+'\n')
print('PASS source wiring checks='+str(len(checks)))

"""Review assertions for new callback branches; source relation only, not a gameplay simulation."""
from pathlib import Path
import argparse,json,hashlib
parser=argparse.ArgumentParser();parser.add_argument('--repo',type=Path,default=Path(__file__).resolve().parents[3]);args=parser.parse_args()
root=args.repo.resolve();j=root/'client-mod/src/main/java/io/github/campione01/mineclientbridge';a=(j/'ClientActions.java').read_text();m=(j/'ScopedStepDownMovement.java').read_text();p=(j/'ScopedNativePreflight.java').read_text();n=0
def check(ok,why):
 global n
 assert ok,why;n+=1
for text in ['active.scopedStepDown=scoped.stepDown','active.scopedStepDown.activate(active.entry)','a.scopedStepDown.beforeEffect(Minecraft.getInstance())','a.scopedStepDown!=null ? a.scopedStepDown.settled()','a.entry.result.add("step_down",a.scopedStepDown.terminal(neutral))','if(status.equals("succeeded") && !a.scopedStepDown.settled())','a.jump = a.scopedMovement==null && a.scopedStepDown==null && step.jump()','if(a.scopedStepDown!=null && active!=a)return;']:
 check(text in a,text)
branch=a[a.index('        if(a.scopedStepDown!=null) {'):a.index('        if(a.scopedLocalSegment!=null) {', a.index('        if(a.scopedStepDown!=null) {'))]
check(branch.index('beforeEffect')<branch.index('a.dispatched=true'),'input beforeEffect precedes direct input assignment')
check('event.getInput()!=input' in branch and branch.count('!ScopedFlatMovement.neutral(input)')==2,'input identity and neutrality before and after hooks')
for text in ['stepDown.admissionRecheck(mc)','stepDown.admissionRawFence(mc)','out.add("step_down", stepDown.facts())','if(capture.stepDown!=null){capture.requireMovementResponseBudget(parsed);capture.recheck(mc);}']:
 check(text in p,text)
check(m.index('actionEntry.ticks==actionTicks')<m.index('private void account('),'raw tick/owner fence precedes accounting')
check('player.getAttribute(Attributes.GRAVITY)==gravityAttribute' in m and 'gravityAttribute.getModifiers().isEmpty()' in m,'raw gravity identity and modifiers')
check('movement_budget_status","unarmed"' in m and m.count('MovementBudget.snapshot().get("status").getAsString().equals("unarmed")')==2,'unarmed at admission and pre-effect')
pins=json.loads((root/'capability-runtime/tests/mining_collect/references/accepted_movement_sha256.json').read_text())
for name,digest in pins.items():check(hashlib.sha256((j/name).read_bytes()).hexdigest()==digest,'old flat/collect source exact '+name)
print(json.dumps({'status':'passed','assertions':n,'scope':'Source relation + accepted flat/collect exact hashes; no actual ClientActions dispatch lifecycle'}))

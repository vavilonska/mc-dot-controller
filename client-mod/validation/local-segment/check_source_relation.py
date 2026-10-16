"""Production callback wiring assertions; never a replacement for actual loader/world tests."""
import argparse,hashlib,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,default=Path(__file__).resolve().parents[3]);a=p.parse_args()
r=a.repo.resolve();j=r/'client-mod/src/main/java/io/github/campione01/mineclientbridge'
a=(j/'ClientActions.java').read_text();m=(j/'ScopedLocalSegmentMovement.java').read_text();d=(j/'ScopedLocalSegmentDispatch.java').read_text();p=(j/'ScopedNativePreflight.java').read_text();count=0
def check(ok,why):
 global count
 assert ok,why;count+=1
for fragment in ('active.scopedLocalSegment=scoped.localSegment','active.scopedLocalSegment.activate(active.entry)',
 'ScopedLocalSegmentDispatch.nextTick()','ScopedLocalSegmentDispatch.arm(a.scopedLocalSegment);a.scopedLocalSegment.recordInput(a.jump,a.forward)',
 'if(a.scopedLocalSegment!=null){followLocalSegment(mc,a);return;}',
 'if(a.scopedLocalSegment!=null){a.scopedLocalSegment.beforeEffect(mc);if(active!=a)return;}',
 'a.entry.result.add("local_segment",a.scopedLocalSegment.terminal(neutral))',
 'if(status.equals("succeeded") && !a.scopedLocalSegment.settled())','owner.motionUnknown(reason);'):
 check(fragment in a,fragment)
for fragment in ('ScopedLocalSegmentDispatch.ready()','localSegment.admissionRawFence(mc)','localSegment.admissionRecheck(mc)',
 'out.add("local_segment", localSegment.facts())','capture.localSegment!=null'):
 check(fragment in p,fragment)
check(d.index('current.consumed=true;')<d.index('current.owner.beforeVanillaMove'),'token consumed before hooks/reentry')
check('current==null||entity!=current.owner.player' in d,'unarmed and unrelated entity untouched')
check('type!=MoverType.SELF' in d,'nonself refusal')
check('unknown_outcome",true' in m,'canonical uncertainty retained on original Entry')
check('requested.x==v.x&&requested.y==v.y&&requested.z==v.z' in m,'actual requested move exact')
check('v.x==pulseVx&&v.z==pulseVz&&v.y==(double).42F' in m,'postjump impulse exact')
check('horizontalDistance()==0&&forward==0' in m,'natural zero pulse readiness')
for name in ('ScopedLocalSegmentMovement.java','ScopedLocalSegmentDispatch.java','ScopedLocalSegmentPolicy.java','mixin/EntityLocalSegmentMixin.java'):
 text=(j/name).read_text();check('setDeltaMovement(' not in text and 'setPos(' not in text and 'setPosRaw(' not in text,name+' no physics writes')
check('EntityLocalSegmentMixin' in (r/'client-mod/src/main/resources/mineclient_bridge.mixins.json').read_text(),'required mixin registration')
pins=json.loads((r/'capability-runtime/tests/mining_collect/references/accepted_movement_sha256.json').read_text())
for name,digest in pins.items():check(hashlib.sha256((j/name).read_bytes()).hexdigest()==digest,'legacy accepted movement unchanged '+name)
print(json.dumps({'status':'passed','assertions':count,'scope':'Source relation, not FML/Mixin or live execution'}))

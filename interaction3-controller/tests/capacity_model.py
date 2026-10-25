"""Byte-only extrapolation from real v1 record shapes, not runnable future observations."""
import base64
import copy
from uuid import UUID
from interaction3_controller.legacy import encode,strict_json,PROFILE,MAX_RESPONSE
from interaction3_controller.schema import payload_digest
from support import ORIGINAL,PLAN


def modeled_record(old,index):
    rec=copy.deepcopy(old);q=rec['request'];q.update(profile=PROFILE,id=str(UUID(int=10000+index)),owner_generation=98+index,plan_version=1,plan_sha256=PLAN.sha256)
    # Preserve byte-volume of real receipt/evidence/observation forms; not live claims.
    if q['kind']=='move':q['jump_first']=False
    def transform(r):
        r.update(profile=PROFILE,id=q['id'],owner_generation=q['owner_generation'],plan_version=1,plan_sha256=PLAN.sha256,payload_digest=payload_digest(q),observation_refusal=None);return r
    for key in ('latest_native','terminal_native'):
        if rec.get(key):transform(rec[key])
    for e in rec['evidence']:
        if 'raw_base64' not in e:continue
        raw=base64.b64decode(e['raw_base64']);r=strict_json(raw)
        if isinstance(r,dict) and 'payload_digest' in r:raw=encode(transform(r))
        e['raw_base64']=base64.b64encode(raw).decode('ascii')
    obs=rec.get('observation')
    if obs:
        obs['profile']=PROFILE;obs['observation_refusal']=None
        for slot in obs.get('hotbar',[]):slot['max_damage']=131 if slot['item_id']=='minecraft:stone_pickaxe' else 0
    rec['plan']=PLAN.snapshot()
    return rec


def measurement():
    templates=[r for r in ORIGINAL['actions'].values() if r['request']['profile']=='recovery_interaction_v1']
    templates.sort(key=lambda r:len(encode(r)))
    outputs={}
    for label,chooser in [('median',lambda i:templates[len(templates)//2]),('p95',lambda i:templates[int(.95*(len(templates)-1))]),('maximum',lambda i:templates[-1]),('cyclic_actual37',lambda i:templates[i%len(templates)])]:
        data=copy.deepcopy(ORIGINAL)
        for i in range(256-len(ORIGINAL['actions'])):
            rec=modeled_record(chooser(i),i);data['actions'][rec['request']['id']]=rec
        n=len(encode(data));outputs[label]={'records':len(data['actions']),'bytes':n,'plus_three_reply_reserve':n+MAX_RESPONSE*2*3,'fits_with_reserve':n+MAX_RESPONSE*2*3<=8*1024*1024}
    return {'actual97_bytes':len(encode(ORIGINAL)),'max_bytes':8*1024*1024,'reserve_bytes':MAX_RESPONSE*2*3,'plan_raw_bytes':len(PLAN.raw),'plan_snapshot_bytes':len(encode(PLAN.snapshot())),'model':'Synthetic byte-volume extrapolation only: actual37 v1 shapes + v3 profile/PLAN fields/proof + null refusal and illustrative max_damage; not future valid/live records. No pruning.','projections':outputs}

if __name__=='__main__':print(encode(measurement()).decode())

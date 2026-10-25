"""Size-only synthetic workload from reviewed PLAN budgets and actual codec observation bytes.
No transport, no admission and no ledger mutation. Actual native inputs are hashed in output.
"""
import base64,copy,hashlib,json
from pathlib import Path
from uuid import uuid4
from support import ORIGINAL,OWNER,SESSION,WORLD,PLAYER,OBS,receipt
from maintenance5_controller.legacy import encode,strict_json,PROFILE,MAX_RESPONSE
from maintenance5_controller.plan import Plan
from maintenance5_controller.schema import request_valid,receipt_valid
B=Path(__file__).resolve().parents[3]
NAMES=('TNT-FIRST-CYCLE-CONTEXT-UNBOUND.json','TNT-COMBINED-TEST-REMAINING8-CONTEXT-UNBOUND.json','TNT-FORMAL-ALL9-CONTEXT-UNBOUND.json')
def workload(plan):
 for s in plan.data['navigation']:
  for _ in range(s['max_moves']):yield s['id'],'move',dict(forward=s['forward'],strafe=s['strafe'],samples=s['max_samples'],jump_first=s['jump_first'])
  for _ in range(s['max_looks']):yield s['id'],'look',dict(yaw=s['yaw'],pitch=s['pitch'])
 for s in plan.data['worksites']:
  for _ in range(s['max_looks']):yield s['id'],'look',dict(yaw=-90.,pitch=45.)
  for i in range(s['max_selects']):yield s['id'],'select_hotbar',dict(slot=2+i%2,stack_fingerprint=str(2+i%2)*64)
  for t in s['break_targets']:yield s['id'],'break_block',dict(t,stack_fingerprint='2'*64)
  for t in s['restore_targets']:yield s['id'],'place_block',dict(t,stack_fingerprint='3'*64)
def measure(observation_file,evidence_count=3,return_data=False,max_plan_raw=False):
 path=Path(observation_file);files={s:path/('task-station-'+s+'-synthetic-phase.json') for s in 'RSABC'} if path.is_dir() else {'all':path}
 inputs={k:dict(raw=f.read_bytes(),value=strict_json(f.read_bytes()),path=str(f)) for k,f in files.items()};data=copy.deepcopy(ORIGINAL);initial=len(encode(data));phases=[];sizes=[]
 for phase,name in enumerate(NAMES):
  file=B/'source/plans'/name;original=file.read_bytes();d=strict_json(original)
  # Different TEST/formal native contexts are synthetic here, not executable reviewed PLANs.
  ctx=dict(session=SESSION,world_generation=str(uuid4()),player_uuid=PLAYER,owner_id=OWNER);d['context']=ctx;pr=encode(d)
  if max_plan_raw:pr+=b'\n'*(16384-len(pr))
  p=Plan(pr,hashlib.sha256(pr).hexdigest());start=len(data['actions']);before=len(encode(data));kinds={}
  for stage,kind,args in workload(p):
   station='R' if stage=='R-first' else stage.split('-')[1] if stage.startswith('nav-') else stage.split('-')[2] if stage.startswith('align-return-') else stage
   obs=inputs[station if path.is_dir() else 'all']['value']
   q=dict(schema_version=1,profile=PROFILE,kind=kind,id=str(uuid4()),**ctx,owner_generation=len(data['actions'])+1,ttl_ms=2000 if kind=='break_block' else 1000,observation_id=OBS,plan_version=3,plan_sha256=p.sha256,stage_id=stage,**args);request_valid(q);r=receipt(q);receipt_valid(r,q);rraw=encode(r)
   e=dict(kind='status',http_status=200,complete=True,raw_base64=base64.b64encode(rraw).decode())
   record=dict(request=q,state='CLOSED',unknown_reasons=[],evidence=[copy.deepcopy(e) for _ in range(evidence_count)],latest_native=r,terminal_native=r,stop_attempted=False,observation=obs,plan=p.snapshot(),local_risk=dict(plan_sha256=p.sha256,stage_id=stage,gameplay_risk='ordinary_damage_collision_and_incomplete_maintenance',physical_settlement='not_observed',target_result='not_assessed',nearby_living_count=0))
   data['actions'][q['id']]=record;sizes.append(len(encode(record)));kinds[kind]=kinds.get(kind,0)+1
  phases.append(dict(template=name,template_sha256=hashlib.sha256(original).hexdigest(),template_bytes=len(original),bound_synthetic_plan_bytes=len(pr),new_records=len(data['actions'])-start,new_bytes=len(encode(data))-before,kinds=kinds))
 for aid,r in ORIGINAL['actions'].items():assert encode(data['actions'][aid])==encode(r)
 if return_data:return data
 total=len(encode(data));reserve=MAX_RESPONSE*2*3
 return dict(scope='SYNTHETIC size-only workload, not admissions or live results. Full original101, reviewed finite budgets, full PLANraw+parsed per record, actual codec maximum observation raw decoded without pruning, schema-valid synthetic requests/receipts.',observation_inputs={k:dict(path=v['path'],sha256=hashlib.sha256(v['raw']).hexdigest(),raw_bytes=len(v['raw']),stored_bytes=len(encode(v['value']))) for k,v in inputs.items()},evidence_count_per_action=evidence_count,max_plan_raw_stress=max_plan_raw,original_records=101,original_encoded_bytes=initial,phases=phases,projected_records=len(data['actions']),new_records=len(sizes),record_min_bytes=min(sizes),record_max_bytes=max(sizes),projected_encoded_bytes=total,cleanup_reserve_bytes=reserve,limit_bytes=24*1024*1024,remaining_after_reserve=24*1024*1024-total-reserve,count_limit=512,all_original_records_exact=True,warning='512 count does not promise all records fit 24MiB. Receipt sizes/poll counts may differ; per-intent bound and cleanup reserve remain authoritative.')
if __name__=='__main__':
 import sys
 print(json.dumps(measure(sys.argv[1],int(sys.argv[2]) if len(sys.argv)>2 else 3,max_plan_raw='--max-plan-raw' in sys.argv),indent=2))

"""Size-only actual338 + four reviewed operations; actual accepted v6 obs required.
No transport, no world writes. Requests/receipts synthetic, original338 retained.
"""
import argparse,base64,copy,hashlib,json
from pathlib import Path
from fixtures import *
from survival6_controller import schema
ap=argparse.ArgumentParser();ap.add_argument('--observation',required=True,type=Path);ap.add_argument('--max-plan-raw',action='store_true');args=ap.parse_args()
raw_obs=args.observation.read_bytes();assert len(raw_obs)<=65536;obs=strict_json(raw_obs);assert set(obs)==schema.OBS_KEYS and obs['profile']==PROFILE
raw_template=(C/'source/plans/SURVIVAL-V6-FOUR-OPERATION-TEST-CONTEXT-UNBOUND.json').read_bytes();d=strict_json(raw_template);d['context']=CTX
raw=encode(d);raw+=b' '*(16384-len(raw))if args.max_plan_raw else b'';p=Plan(raw,hashlib.sha256(raw).hexdigest());data=copy.deepcopy(BASE)
for i,stage in enumerate(p.data['survival']):
 q=request(stage['kind'],p,slot=stage.get('slot',1));q['stage_id']=stage['id'];q['owner_generation']=339+i;schema.request_valid(q);r=receipt(q);schema.receipt_valid(r,q)
 evidence=dict(kind='status',http_status=200,complete=True,raw_base64=base64.b64encode(encode(r)).decode())
 data['actions'][q['id']]=dict(request=q,state='CLOSED',unknown_reasons=[],evidence=[copy.deepcopy(evidence)for _ in range(8)],latest_native=r,terminal_native=r,stop_attempted=False,observation=obs,local_risk={'plan_sha256':p.sha256,'stage_id':stage['id'],'gameplay_risk':'ordinary_damage_interruption_and_unsuccessful_single_attempt','physical_settlement':'not_observed','outcome':'not_assessed'},plan=p.snapshot())
assert all(encode(data['actions'][k])==encode(v)for k,v in BASE['actions'].items())
size=len(encode(data));reserve=65536*6
print(json.dumps(dict(scope='Size-only actual338 + four synthetic operations /8 receipt each /actual accepted observation; not admission or all512 guarantee',old338_sha256=hashlib.sha256(BASE_RAW).hexdigest(),old_bytes=len(BASE_RAW),new_count=4,projected_count=len(data['actions']),template_sha256=hashlib.sha256(raw_template).hexdigest(),plan_raw_bytes=len(raw),observation_path=str(args.observation),observation_bytes=len(raw_obs),observation_sha256=hashlib.sha256(raw_obs).hexdigest(),projected_bytes=size,cleanup_reserve_bytes=reserve,remaining_after_reserve=24*1024*1024-size-reserve,old338_exact=True),indent=2))

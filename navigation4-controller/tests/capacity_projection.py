"""Offline size projection only. No game transport; no record is written to a real ledger."""
import base64,copy,hashlib
from pathlib import Path
from uuid import uuid4
from support import ORIGINAL,encode,receipt
from navigation4_controller.legacy import MAX_RESPONSE
from test_cold_geometry import scenario

def measure():
 data=copy.deepcopy(ORIGINAL);baseline=len(encode(data));sizes=[]
 # Seven actual codec synthetic source windows plus two clearly Python-modelled cold windows.
 names=['source','bed-head','bed-foot','floor-north','floor-west','chest','cut-sandstone','corridor-python','south-python']
 for i,name in enumerate(names):
  o,q,p=scenario(name,i);stage=p.stage(q['stage_id'])
  for _ in range(stage['max_moves']):
   q=copy.deepcopy(q);q['id']=str(uuid4());q['owner_generation']=len(data['actions'])+1;r=receipt(q)
   raw=encode(r);e={'operation':'status','http_status':200,'complete':True,'raw_base64':base64.b64encode(raw).decode(),'raw_sha256':hashlib.sha256(raw).hexdigest(),'received_utc':'2026-10-21T00:00:00+00:00'}
   record=dict(request=q,state='CLOSED',unknown_reasons=[],evidence=[copy.deepcopy(e) for _ in range(3)],latest_native=r,terminal_native=r,stop_attempted=False,observation=o,plan=p.snapshot(),local_risk={'arrival':'not_assessed'})
   data['actions'][q['id']]=record;sizes.append(len(encode(record)))
 for aid,record in ORIGINAL['actions'].items():assert encode(data['actions'][aid])==encode(record)
 total=len(encode(data));reserve=MAX_RESPONSE*2*3;limit=8*1024*1024
 assert len(sizes)==65 and total+reserve<limit
 return dict(scope='SYNTHETIC size-only projection; 101 actual records plus 65 full PLAN/geometry records and three ordinary receipt evidences each; NOT actual admissions or a guaranteed storage bound',original_records=101,original_encoded_bytes=baseline,projected_records=len(data['actions']),new_records=len(sizes),new_record_min_bytes=min(sizes),new_record_max_bytes=max(sizes),projected_encoded_bytes=total,reserved_bytes=reserve,limit_bytes=limit,remaining_after_reserve=limit-total-reserve,all_original_encoded_records_equal=True,warning='256 is count ceiling only. Larger raw receipts/status histories may hit 8MiB earlier; production preintent byte gate remains authoritative.')
if __name__=='__main__':
 import json
 print(json.dumps(measure(),indent=2))

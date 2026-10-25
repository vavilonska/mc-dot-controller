"""Limited offline real-file/fsync timing into fake POST callback, never HTTP.
Measured environment only; cannot guarantee native challenge survival or future latency.
"""
import copy,json,tempfile,time
from pathlib import Path
from uuid import uuid4
from support import Fake,clone,ORIGINAL,encode,request,make_plan
from test_first_cycle import cold
from capacity_projection import measure
from maintenance5_controller.controller import Controller

def run(observation_file,max_plan_raw=False):
 full=measure(observation_file,return_data=True,max_plan_raw=max_plan_raw);items=list(full['actions'].items());rows=[]
 for count in (101,(101+len(items))//2,len(items)):
  with tempfile.TemporaryDirectory() as tmp:
   d=Path(tmp)/'ledger';clone(d);data=copy.deepcopy(full);data['actions']=dict(items[:count]);(d/'ledger.json').write_bytes(encode(data))
   f=Fake();f.obs,p=cold();pd=p.data;pd['context']['world_generation']=str(uuid4());p=make_plan(pd);f.obs['world_generation']=pd['context']['world_generation'];f.obs['owner_generation']=count+1
   q=request('look',p);q['world_generation']=pd['context']['world_generation'];q['owner_generation']=count+1
   with Controller(d,f,p) as c:
    o=c.observe();timer=[None];start=time.perf_counter()
    def before(method,path,body):
     if path.endswith('start'):timer[0]=time.perf_counter()-start
    f.before=before;r=c.start(q);wall=time.perf_counter()-start
    assert timer[0] is not None and r['state']=='CLOSED' and len(f.posts())==1
    for aid,original in ORIGINAL['actions'].items():assert encode(c.report(aid))==encode(original)
    rows.append(dict(history_count_before=count,ledger_encoded_bytes_before=len(encode(data)),fresh_observe_return_to_fake_POST_seconds=timer[0],whole_start_seconds=wall,under_native_1000ms_at_fake_POST=timer[0]<1.,protocol_fixture_result=r['state']))
 return dict(max_plan_raw_stress=max_plan_raw,scope='Three finite timings with production Controller, original101 and synthetic full-task records, actual temp-file fsync and fake transport callback. No HTTP/game/credentials. Not future latency or live lease guarantee; no lease/TTL changes.',rows=rows)
if __name__=='__main__':
 import sys
 print(json.dumps(run(sys.argv[1],'--max-plan-raw' in sys.argv),indent=2))

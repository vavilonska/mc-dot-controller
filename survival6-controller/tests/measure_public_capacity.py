"""OFFLINE ONLY. Real481 source read-only; production persistence in TEMP, fake HTTP.
1024 model = unchanged real481 + explicitly synthetic realistic complete records.
No ticket extension, actual game transport, production ledger writes, or retries.
"""
import argparse,base64,copy,hashlib,importlib.util,json,os,sys,tempfile,time
from pathlib import Path
from uuid import uuid4
ap=argparse.ArgumentParser();ap.add_argument('--source',type=Path,default=Path(__file__).resolve().parents[2]);ap.add_argument('--counts',default='481,1023');ap.add_argument('--repeats',type=int,default=3);args=ap.parse_args()
C=args.source.parent;B=C.parent;F=B/'mdc-runtime-recovery-20261021-r1/nether-west-481-four-stage-cold-frozen-r1'
sys.path.insert(0,str(args.source/'survival6-controller'))
spec=importlib.util.spec_from_file_location('capacityfx',args.source/'survival6-controller/tests/fixtures.py');fx=importlib.util.module_from_spec(spec);spec.loader.exec_module(fx)
from survival6_controller import schema
from survival6_controller.legacy import Refused
from unittest.mock import patch
raw=(F/'public-ledger-481.json').read_bytes();sha=hashlib.sha256(raw).hexdigest();assert sha=='9d7db263ae7fc19832200a34828b0a5deac75a4c971de857f92b8139c7477847';base=fx.strict_json(raw)
last=max(base['actions'].values(),key=lambda r:r['request']['owner_generation'])
obs=fx.strict_json((F/'navigation/FINAL-AFTER-2.json').read_bytes());obs.update(session=fx.SESSION,world_generation=fx.WORLD)
pd=dict(version=4,kind='survival',context=fx.CTX,navigation=[dict(id='bench',source_bounds=dict(min_x=-64.2,max_x=-60.5,min_y=47.95,max_y=48.05,min_z=-.3,max_z=1.2),target=dict(x=-63.5,y=48.,z=.5),yaw=90.,pitch=0.,forward=.5,strafe=0.,jump_first=False,max_samples=4,max_moves=8,max_looks=0)],survival=[]);plan=fx.plan(pd)
result=dict(scope='Offline production code/persistence; real481 exact, >=482 synthetic copies; TEMP and fake HTTP only',source=str(args.source),source_sha256=sha,source_bytes=len(raw),admission_limit=fx.Controller.MAX_ACTIONS,models=[])
for target in map(int,args.counts.split(',')):
 data=copy.deepcopy(base)
 while len(data['actions'])<target:
  r=copy.deepcopy(last);q=r['request'];q.update(id=str(uuid4()),owner_generation=len(data['actions'])+1)
  term=fx.receipt(q);schema.receipt_valid(term,q);r.update(latest_native=term,terminal_native=copy.deepcopy(term));r['observation']['owner_generation']=q['owner_generation']
  r['evidence']=[dict(kind=kind,http_status=200,complete=True,raw_base64=base64.b64encode(fx.encode(term)).decode())for kind in ('start','status')];data['actions'][q['id']]=r
 modelraw=raw if target==481 else fx.encode(data)
 model=dict(count_before=target,synthetic_count=target-481,bytes_before=len(modelraw),trials=[])
 for trial in range(args.repeats):
  with tempfile.TemporaryDirectory(prefix='mdc-public-capacity-')as td:
   d=Path(td)/'ledger';fx.clone(d,modelraw)
   class Fake:
    endpoint=base['endpoint']
    def request(self,method,path,body=None):
     assert method=='POST'and path==fx.ROOT+'start';self.posts+=1;self.pre_ms=1000*(time.perf_counter()-self.started);self.pre_encodes=copy.deepcopy(encodes)
     disk=(d/'ledger.json').read_bytes();assert disk==latest[0];self.pending_sha=hashlib.sha256(disk).hexdigest();self.pending_bytes=len(disk)
     assert fx.strict_json(disk)['actions'][body['id']]['state']=='PENDING';return fx.RawReply(200,fx.encode(fx.receipt(body)))
   f=Fake();f.posts=0
   with fx.Controller(d,f,plan)as c:
    o=copy.deepcopy(obs);o.update(owner_generation=target+1,observation_id=str(uuid4()));c._last_observation=o;q=fx.request('move',plan,o);q.update(stage_id='bench',samples=1)
    encodes=[];latest=[None];original=fx.encode;patches=[]
    def codec(value):
     t=time.perf_counter();out=original(value);ms=1000*(time.perf_counter()-t)
     if isinstance(value,dict)and'actions'in value:encodes.append(dict(count=len(value['actions']),bytes=len(out),ms=ms));latest[0]=out
     return out
    for name,module in tuple(sys.modules.items()):
     if '_controller.'in name and getattr(module,'encode',None)is original:patches.append(patch.object(module,'encode',side_effect=codec))
    for p in patches:p.start()
    try:f.started=time.perf_counter();c.start(q);total=1000*(time.perf_counter()-f.started)
    finally:
     for p in reversed(patches):p.stop()
    assert f.posts==1 and c.report(q['id'])['state']=='CLOSED';assert all(fx.encode(c.ledger.data['actions'][k])==fx.encode(v)for k,v in base['actions'].items())
    row=dict(pre_post_ms=f.pre_ms,total_start_ms=total,pre_post_full_encodes=f.pre_encodes,total_full_encodes=encodes,pending_bytes=f.pending_bytes,pending_sha256=f.pending_sha,count_after=len(c.ledger.data['actions']),actual481_full_records_exact=True)
    if target+1==1024:
     c._last_observation=dict(o,observation_id=str(uuid4()),owner_generation=1025);q2=fx.request('move',plan,c._last_observation);q2.update(stage_id='bench',samples=1)
     try:c.start(q2)
     except Refused:pass
     else:raise AssertionError('1025th accepted')
     assert f.posts==1 and q2['id']not in c.ledger.data['actions'];row['intent1025_refused_zero_post']=True
   with fx.Controller(d,f,None)as c:
    assert all(fx.encode(c.ledger.data['actions'][k])==fx.encode(v)for k,v in base['actions'].items());assert c.report(q['id'])['state']=='CLOSED';row['reload_original481_exact']=True
   model['trials'].append(row)
 result['models'].append(model)
assert hashlib.sha256((F/'public-ledger-481.json').read_bytes()).hexdigest()==sha;result['original_source_unchanged']=True
print(json.dumps(result,indent=2))

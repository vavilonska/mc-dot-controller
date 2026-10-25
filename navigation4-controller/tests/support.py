"""Actual101 retained fixture; all new observations/actions are synthetic offline inputs."""
import copy
import hashlib
from pathlib import Path
from uuid import uuid4
from navigation4_controller.legacy import strict_json,encode,RawReply,PROFILE,ROOT
from navigation4_controller.schema import payload_digest,requested_calls
from navigation4_controller.plan import Plan
FIXTURES=Path(__file__).resolve().parents[3]/'results/legacy101-fixtures'
ORIGINAL=strict_json((FIXTURES/'public-ledger.json').read_bytes());OWNER=strict_json((FIXTURES/'public-owner.json').read_bytes())['owner_id'];ENDPOINT=ORIGINAL['endpoint']
SESSION='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';WORLD='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';PLAYER='cccccccc-cccc-4ccc-8ccc-cccccccccccc';OBS='dddddddd-dddd-4ddd-8ddd-dddddddddddd'
STAGE=dict(id='north',source_bounds=dict(min_x=-1,min_y=54.9,min_z=-2,max_x=1,max_y=55.1,max_z=1),target=dict(x=0.,y=55.,z=-1.),yaw=-180.,pitch=0.,forward=.5,strafe=0.,jump_first=False,max_samples=8,max_moves=3,max_looks=2)
PLAN_DATA=dict(version=2,kind='navigation',context=dict(session=SESSION,world_generation=WORLD,player_uuid=PLAYER,owner_id=OWNER),stages=[STAGE])
def make_plan(data):
 raw=encode(data);return Plan(raw,hashlib.sha256(raw).hexdigest())
PLAN=make_plan(PLAN_DATA)
def clone(directory):
 directory.mkdir(mode=0o700)
 for name,raw in (('ledger.json',encode(ORIGINAL)),('owner.json',encode({'owner_id':OWNER}))):
  (directory/name).write_bytes(raw);(directory/name).chmod(0o600)
 (directory/'owner.lock').touch(mode=0o600)
def observation():
 o=dict(schema_version=1,profile=PROFILE,session=SESSION,world_generation=WORLD,player_uuid=PLAYER,owner_generation=102,bound_owner_id=OWNER,unknown_lock=False,active_id=None,ready=True,reason='ready',paused=False,screen_open=False,alive=True,on_ground=True,health=20.,client_tick=100,observation_id=OBS,pose=dict(x=0.,y=55.,z=0.,yaw=-180.,pitch=0.),velocity=dict(x=0.,y=-.0784,z=0.),player_bbox=dict(min_x=-.3,max_x=.3,min_y=55.,max_y=56.8,min_z=-.3,max_z=.3),selected_slot=0,hotbar=[dict(slot=i,item_id='minecraft:air',count=0,damage=0,max_damage=0,stack_fingerprint='0'*64) for i in range(9)],ray=None,local_blocks=[],nearby_living=[],nearby_truncated=False,terrain_complete=True,observation_refusal=None,collision_boxes_complete=True,step_height=.6000000238418579,sprinting=False)
 for dy in range(-2,4):
  for dz in range(-2,3):
   for dx in range(-2,3):
    solid=dy<0;o['local_blocks'].append(dict(dx=dx,dy=dy,dz=dz,loaded=True,id='minecraft:stone' if solid else 'minecraft:air',collision=solid,fluid='minecraft:empty',collision_boxes=[[0.,0.,0.,1.,1.,1.]] if solid else []))
 return o
def request(kind='move',plan=PLAN):
 q=dict(schema_version=1,profile=PROFILE,kind=kind,id=str(uuid4()),session=SESSION,world_generation=WORLD,player_uuid=PLAYER,owner_id=OWNER,owner_generation=102,ttl_ms=1000,observation_id=OBS,plan_version=2,plan_sha256=plan.sha256,stage_id=plan.data['stages'][0]['id'])
 s=plan.data['stages'][0]
 if kind=='move':q.update(forward=s['forward'],strafe=s['strafe'],samples=2,jump_first=s['jump_first'])
 else:q.update(yaw=s['yaw'],pitch=s['pitch'])
 return q
def receipt(q,state='SETTLED',count=None):
 n=requested_calls(q);done=state=='SETTLED';count=(n if done else 0) if count is None else count
 r={k:q[k] for k in ('schema_version','profile','kind','id','session','owner_id','owner_generation','world_generation','player_uuid','plan_version','plan_sha256','stage_id')}
 r.update(state=state,protocol_state=state,reason='samples_complete' if q['kind']=='move' else 'one_shot_complete',requested_calls=n,applied_calls=count,input_invalidated=done,release_proven=done,settled=done,protocol_terminal=done,effect_state='calls_completed' if count else 'not_started',release_state=('proven' if count else 'not_needed') if done else 'pending',settlement_state='not_observed',gameplay_outcome='not_assessed',unknown_lock=state=='UNKNOWN',cancellation_generation=1 if done else 0,payload_digest=payload_digest(q),observation_refusal=None)
 return r
class Fake:
 endpoint=ENDPOINT
 def __init__(self):self.obs=observation();self.calls=[];self.req=None;self.fail=False;self.state='SETTLED';self.count=None;self.modify=lambda r:r;self.before=lambda *x:None
 def request(self,method,path,body=None):
  self.calls.append((method,path,copy.deepcopy(body)));self.before(method,path,body)
  if path==ROOT+'observe':return RawReply(200,encode(self.obs))
  if path.endswith('start'):self.req=copy.deepcopy(body)
  if self.fail:return RawReply(0,b'',False)
  return RawReply(200,encode(self.modify(receipt(self.req,self.state,self.count))))
 def posts(self):return [c for c in self.calls if c[0]=='POST']

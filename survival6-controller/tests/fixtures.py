"""Actual338 history plus explicit synthetic v6 observations and native-like replies.
No native/game/HTTP execution; finite lifecycle driven by an injected test clock.
"""
import copy,hashlib,json,sys
from pathlib import Path
from uuid import uuid4
C=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(C/'source/survival6-controller'))
from survival6_controller import Controller,Plan
from survival6_controller.legacy import encode,strict_json,RawReply,PROFILE,ROOT
from survival6_controller.schema import payload_digest,requested_calls
BASE_RAW=(C/'results/legacy338-fixtures/public-ledger-338.json').read_bytes();BASE=strict_json(BASE_RAW)
LAST=max(BASE['actions'].values(),key=lambda r:r['request']['owner_generation'])
OWNER=LAST['request']['owner_id'];PLAYER=LAST['request']['player_uuid'];ENDPOINT=BASE['endpoint']
SESSION='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaa60';WORLD='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbb60';OBS='dddddddd-dddd-4ddd-8ddd-dddddddddd60';TARGET='eeeeeeee-eeee-4eee-8eee-eeeeeeeeee60'
CTX=dict(owner_id=OWNER,player_uuid=PLAYER,session=SESSION,world_generation=WORLD)
STAGE=dict(id='north',source_bounds=dict(min_x=-1,min_y=54.9,min_z=-2,max_x=1,max_y=55.1,max_z=1),target=dict(x=0.,y=55.,z=-1.),yaw=-180.,pitch=0.,forward=.5,strafe=0.,jump_first=False,max_samples=8,max_moves=3,max_looks=2)
DATA=dict(version=4,kind='survival',context=CTX,navigation=[STAGE],survival=[dict(id='bread-slot',kind='select_hotbar',max_intents=1,slot=1),dict(id='axe-slot',kind='select_hotbar',max_intents=1,slot=8),dict(id='strike',kind='attack_blaze',max_intents=1),dict(id='eat',kind='consume_bread',max_intents=1,max_use_ticks=40)])
def plan(data=None,suffix=b''):
 raw=encode(data or DATA)+suffix;return Plan(raw,hashlib.sha256(raw).hexdigest())
def base_observation():
 o=dict(schema_version=1,profile=PROFILE,session=SESSION,world_generation=WORLD,player_uuid=PLAYER,owner_generation=339,bound_owner_id=OWNER,unknown_lock=False,active_id=None,ready=True,reason='ready',paused=False,screen_open=False,alive=True,on_ground=True,health=20.,client_tick=100,observation_id=OBS,pose=dict(x=0.,y=55.,z=0.,yaw=-180.,pitch=0.),velocity=dict(x=0.,y=-.0784,z=0.),player_bbox=dict(min_x=-.3,max_x=.3,min_y=55.,max_y=56.8,min_z=-.3,max_z=.3),selected_slot=0,hotbar=[dict(slot=i,item_id='minecraft:air',count=0,damage=0,max_damage=0,stack_fingerprint='0'*64) for i in range(9)],ray=None,local_blocks=[],nearby_living=[],nearby_truncated=False,terrain_complete=True,observation_refusal=None,collision_boxes_complete=True,step_height=.6000000238418579,sprinting=False,local_primed_tnt=dict(count=0,complete=True,overflow=False))
 for dy in range(-2,4):
  for dz in range(-2,3):
   for dx in range(-2,3):
    solid=dy<0;o['local_blocks'].append(dict(dx=dx,dy=dy,dz=dz,loaded=True,id='minecraft:stone' if solid else 'minecraft:air',collision=solid,fluid='minecraft:empty',collision_boxes=[[0.,0.,0.,1.,1.,1.]] if solid else []))
 o['hotbar'][2].update(item_id='minecraft:stone_pickaxe',count=1,damage=106,max_damage=131,stack_fingerprint='2'*64)
 o['hotbar'][3].update(item_id='minecraft:andesite',count=64,damage=0,max_damage=0,stack_fingerprint='3'*64)
 o['selected_slot']=2
 return o

def observation():
 o=base_observation();o['selected_slot']=1;o['health']=8.
 o['hotbar'][1].update(item_id='minecraft:bread',count=4,damage=0,max_damage=0,stack_fingerprint='1'*64)
 o['hotbar'][8].update(item_id='minecraft:iron_axe',count=1,damage=3,max_damage=250,stack_fingerprint='8'*64)
 o['nearby_living']=[dict(id=12,type='minecraft:blaze',x=0.,y=55.,z=-2.,alive=True)]
 o['survival']=dict(complete=True,food_level=12,saturation=0.,is_using_item=False,used_hand=None,use_remaining_ticks=0,hurt_time=7,entity_reach=3.,attack_strength=1.,entity_hit=dict(entity_id=12,uuid=TARGET,type='minecraft:blaze',provider_class='net.minecraft.world.entity.monster.Blaze',alive=True,health=20.,bbox=dict(min_x=-.3,max_x=.3,min_y=55.,max_y=56.8,min_z=-2.3,max_z=-1.7),point=dict(x=0.,y=56.62,z=-1.7)))
 return o

def request(kind,p,obs=None,slot=1):
 o=obs or observation();sid='north'if kind in('move','look')else 'bread-slot'if kind=='select_hotbar'and slot==1 else 'axe-slot'if kind=='select_hotbar'else 'strike'if kind=='attack_blaze'else 'eat'
 q={k:o[k]for k in('session','world_generation','player_uuid','owner_generation','observation_id')}
 q.update(schema_version=1,profile=PROFILE,kind=kind,id=str(uuid4()),owner_id=OWNER,ttl_ms=4000 if kind=='consume_bread'else 1000,plan_version=4,plan_sha256=p.sha256,stage_id=sid)
 if kind=='move':q.update(forward=.5,strafe=0.,samples=2,jump_first=False)
 elif kind=='look':q.update(yaw=-180.,pitch=0.)
 elif kind=='select_hotbar':q.update(slot=slot,stack_fingerprint=str(slot)*64)
 elif kind=='attack_blaze':q.update(target_entity_id=12,target_uuid=TARGET,target_type='minecraft:blaze',stack_fingerprint='8'*64)
 else:q.update(stack_fingerprint='1'*64,max_use_ticks=40)
 return q

def receipt(q,state='SETTLED',count=None,outcome=None):
 n=requested_calls(q);done=state=='SETTLED';count=(n if done else 0)if count is None else count
 r={k:q[k]for k in('schema_version','profile','kind','id','session','owner_id','owner_generation','world_generation','player_uuid','plan_version','plan_sha256','stage_id')}
 game='not_assessed'if q['kind']in('move','look','select_hotbar')else ('attack_returned_observe_outcome'if q['kind']=='attack_blaze'else 'use_consume')if count else 'not_observed'
 r.update(state=state,protocol_state=state,reason='synthetic_complete'if done else 'synthetic_active',requested_calls=n,applied_calls=count,input_invalidated=done,release_proven=done,settled=done,protocol_terminal=done,effect_state='calls_completed'if count else 'not_started',release_state=('proven'if count else 'not_needed')if done else 'pending',settlement_state='not_observed',gameplay_outcome=outcome or game,unknown_lock=state=='UNKNOWN',cancellation_generation=1 if done else 0,payload_digest=payload_digest(q),observation_refusal=None)
 return r
class Clock:
 def __init__(self):self.t=0.;self.sleeps=[]
 def __call__(self):return self.t
 def sleep(self,t):self.sleeps.append(t);self.t+=t
class Fake:
 endpoint=ENDPOINT
 def __init__(self):self.obs=observation();self.calls=[];self.q=None;self.mode='normal';self.clock=Clock();self.before=lambda *a:None;self.historical=None
 def request(self,method,path,body=None):
  self.calls.append((method,path,copy.deepcopy(body)));self.before(method,path,body)
  if path.endswith('observe'):return RawReply(200,encode(self.obs))
  if self.historical:return RawReply(200,encode(self.historical['terminal_native']))
  if path.endswith('start'):self.q=copy.deepcopy(body)
  if self.mode=='lost'and path.endswith('start'):return RawReply(0,b'',False)
  if self.mode=='zero':r=receipt(self.q,count=0)
  elif self.mode=='unknown':r=receipt(self.q,'UNKNOWN',1)
  elif self.mode in('duration','never'):
   done=self.mode=='duration'and self.clock.t>=4.
   r=receipt(self.q,'SETTLED'if done else 'ACTIVE',1)
  else:r=receipt(self.q,outcome='use_fail'if self.mode=='fail_returned'else None)
  return RawReply(200,encode(r))
 def starts(self):return [c for c in self.calls if c[1].endswith('start')]
 def stops(self):return [c for c in self.calls if c[1].endswith('stop')]

def clone(path,raw=BASE_RAW):
 path.mkdir(mode=0o700)
 for name,data in(('ledger.json',raw),('owner.json',encode({'owner_id':OWNER})),('owner.lock',b'')):
  (path/name).write_bytes(data);(path/name).chmod(0o600)

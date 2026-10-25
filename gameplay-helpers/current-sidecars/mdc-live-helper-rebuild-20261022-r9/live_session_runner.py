"""Isolated same-context live sidecar; C8 production is imported, never patched."""
import copy, hashlib, math, os, time, uuid
from pathlib import Path
from survival6_controller import Plan
from survival6_controller.legacy import PROFILE, Refused, encode, strict_json
from survival6_controller.policy import gate
from navigation4_controller.geometry import box_values, observation_geometry, required, clear_body, support
from local_corridor import LocalCorridor
from grounded_contact import current_support

OWNER='68fdcff1-27be-4b7c-a289-8b62ba225b84'
PLAYER='8ab85510-7fe8-3224-95e5-a92489e2434f'
BATCH_SECONDS=300.; START_RESERVE=8.; MAX_INTENTS=128; MAX_NEW_STAGES=16
class Maintenance(Exception): pass
class Gameplay(Exception): pass
class Rollover(Exception): pass

def finite(x): return type(x) in (int,float) and math.isfinite(x)
def sha(x): return isinstance(x,str) and len(x)==64 and all(c in '0123456789abcdef' for c in x)
def arrived(o,s):
 p,t=o['pose'],s['target'];return math.hypot(p['x']-t['x'],p['z']-t['z'])<=.1 and abs(p['y']-t['y'])<=.05

def idle(c):
 d=c.ledger.data
 if d.get('unknown_lock') is not False or any(r.get('state')!='CLOSED' for r in d['actions'].values()): raise Maintenance('global_unknown_or_unreleased_history')
 return d

def validate_spec(raw, expected):
 if type(raw) is not bytes or len(raw)>4096 or not sha(expected) or hashlib.sha256(raw).hexdigest()!=expected: raise Maintenance('pinned_session_spec_required')
 d=strict_json(raw)
 keys={'schema_version','kind','baseline_sha256','baseline_count','owner_id','player_uuid','mission','batch_seconds','start_reserve_seconds','batch_max_intents','batch_max_new_stages','enable_bread','enable_exact_ray_blaze'}
 if not isinstance(d,dict) or set(d)!=keys or type(d.get('schema_version')) is not int or d.get('schema_version')!=1 or d.get('kind')!='survival6_live_corridor_session': raise Maintenance('closed_session_spec_required')
 if d['owner_id']!=OWNER or d['player_uuid']!=PLAYER or not sha(d['baseline_sha256']) or type(d['baseline_count']) is not int or not 1<=d['baseline_count']<4096: raise Maintenance('original_authority_and_history_required')
 if any(type(d[k]) is not int or d[k]!=v for k,v in [('batch_seconds',300),('start_reserve_seconds',8),('batch_max_intents',128),('batch_max_new_stages',16)]): raise Maintenance('unchanged_explicit_batch_bounds_required')
 m=d['mission']
 if not isinstance(m,dict) or set(m)!={'kind','stop_x'} or m['kind']!='west_corridor' or not finite(m['stop_x']) or not -3e7<m['stop_x']<3e7: raise Maintenance('closed_local_corridor_mission_required')
 if any(type(d[k]) is not bool for k in ('enable_bread','enable_exact_ray_blaze')): raise Maintenance('explicit_survival_switches_required')
 return d

def grounded(o):
 v=o['velocity'];return o.get('on_ground') is True and o.get('sprinting') is False and o.get('collision_boxes_complete') is True and all(finite(v[k]) for k in 'xyz') and math.hypot(v['x'],v['z'])<=.03 and abs(v['y'])<=.1

def actual_geometry(o):
 if not grounded(o): raise Gameplay('not_grounded_slow')
 p=o['pose'];b=box_values(o['player_bbox'])
 if abs(b[1]-p['y'])>1e-5 or abs((b[0]+b[3])/2-p['x'])>1e-5 or abs((b[2]+b[5])/2-p['z'])>1e-5: raise Maintenance('bbox_pose_mismatch')
 cells,boxes=observation_geometry(o);required(cells,[b[0],b[1]-1,b[2],b[3],b[4],b[5]]);clear_body(b,boxes);current_support(b,boxes)

def redirected(o,s):
 """Same logical target/budget; direction derives from actual residual, not an old sign."""
 p,t=o['pose'],s['target'];dx,dz=t['x']-p['x'],t['z']-p['z']
 if abs(dx)>=abs(dz): wx,wz=math.copysign(.5,dx),0.
 else: wx,wz=0.,math.copysign(.5,dz)
 a=math.radians(p['yaw']);r=copy.deepcopy(s)
 r.update(yaw=p['yaw'],pitch=p['pitch'],forward=-wx*math.sin(a)+wz*math.cos(a),strafe=wx*math.cos(a)+wz*math.sin(a))
 b=box_values(o['player_bbox'])
 r['source_bounds']={k+'_'+axis:v for axis,i in zip('xz',(0,2)) for k,v in [('min',min(b[i],b[i]+t[axis]-p[axis])),('max',max(b[i+3],b[i+3]+t[axis]-p[axis]))]}
 r['source_bounds'].update(min_y=min(p['y'],t['y'])-.05,max_y=max(p['y'],t['y'])+.05)
 along=max(abs(dx),abs(dz));samples=1 if along<=.25 else 2 if along<=.45 else 4
 return r,samples

class Session:
 def __init__(self,c,*,initial_observation,baseline_raw,expected_baseline_sha256,session_spec_raw,expected_session_spec_sha256,outdir,confirm_world,session_started_at,stop_requested=lambda:False,on_event=lambda e:None,monotonic=time.monotonic,sleep=time.sleep):
  self.c=c;self.clock=monotonic;self.sleep=sleep;self.last_clock=None;self.stop_requested=stop_requested;self.on_event=on_event
  self.spec=validate_spec(session_spec_raw,expected_session_spec_sha256)
  if expected_baseline_sha256!=self.spec['baseline_sha256'] or type(baseline_raw) is not bytes or hashlib.sha256(baseline_raw).hexdigest()!=expected_baseline_sha256: raise Maintenance('baseline_pin_mismatch')
  self.baseline=strict_json(baseline_raw)
  if c.owner_id!=OWNER or c.ledger.data!=self.baseline or len(idle(c)['actions'])!=self.spec['baseline_count']: raise Maintenance('exact_initial_history_required')
  self.timeout=getattr(c.transport,'scheduling_quantum',getattr(c.transport,'timeout',None))
  if not finite(self.timeout) or not .05<=self.timeout<=.5: raise Maintenance('bounded_transport_required')
  self.out=Path(outdir)
  if self.out.exists() or any(p.is_symlink() for p in (self.out,*self.out.parents)): raise Maintenance('new_evidence_directory_required_no_effect_resume')
  self.out.mkdir(parents=True,mode=0o700);self.trace=self.out/'trace.jsonl';self.trace.touch(mode=0o600)
  self.serial=str(uuid.uuid4());self.reserved=set(self.baseline['actions']);self.batch=None;self.stage=None;self.stage_number=0;self.last_id=None;self.finish_called=False;self.pending=[];self.attempted=[];self.completed=[];self.batch_number=0;self.consume_state=None;self.checkpoint=None
  if initial_observation.get('player_uuid')!=self.spec['player_uuid']:raise Maintenance('pinned_initial_player_required')
  self.ctx={k:initial_observation['bound_owner_id' if k=='owner_id' else k] for k in ('session','world_generation','player_uuid','owner_id')}
  self.check_context(initial_observation)
  if not callable(confirm_world) or confirm_world(copy.deepcopy(initial_observation)) is not True: raise Maintenance('actual_formal_world_not_confirmed')
  if c.ledger.data!=self.baseline: raise Maintenance('world_callback_changed_history')
  if not finite(session_started_at) or not 0<=self.now()-session_started_at<=300: raise Maintenance('original_session_started_monotonic_required')
  self.planner=LocalCorridor(preferred='west',stop_x=self.spec['mission']['stop_x'])
  self.emit('session_open',spec_sha256=expected_session_spec_sha256,spec=self.spec,context=self.ctx,started_at=session_started_at,initial_observation=initial_observation)
  self.open_batch(session_started_at,initial_observation)
 def now(self):
  n=self.clock()
  if not finite(n) or (self.last_clock is not None and n<self.last_clock): raise Maintenance('invalid_or_regressing_clock')
  self.last_clock=n;return n
 def emit(self,event,**fields):
  e=dict(event=event,session_id=self.serial,**fields)
  with self.trace.open('ab') as f:f.write(encode(e)+b'\n');f.flush();os.fsync(f.fileno())
  self.on_event(copy.deepcopy(e))
 def flush(self):
  while self.pending:
   event,fields=self.pending[0];self.emit(event,**fields);self.pending.pop(0)
 def check_context(self,o):
  d=idle(self.c)
  if o.get('profile')!=PROFILE or o.get('bound_owner_id')!=OWNER or o.get('unknown_lock') is not False or o.get('active_id') is not None: raise Maintenance('authority_or_action_state_unavailable')
  if any(o.get('bound_owner_id' if k=='owner_id' else k)!=v for k,v in self.ctx.items()): raise Gameplay('world_or_session_changed_no_new_action')
  if o.get('owner_generation')!=len(d['actions'])+1: raise Maintenance('owner_generation_mismatch')
  if o.get('alive') is not True: raise Gameplay('player_dead_no_automatic_respawn')
  if o.get('paused') is not False or o.get('screen_open') is not False: raise Gameplay('ordinary_ui_or_pause_active')
  if o.get('ready') is not True: raise Gameplay('native_context_temporarily_not_ready')
 def fresh(self):
  o=self.c.observe();self.now();self.check_context(o);self.pending.append(('observation',dict(observation=o)));return o
 def stable(self):
  deadline=self.now()+2.;previous=None
  while deadline-self.now()>=self.timeout:
   o=self.fresh()
   if self.now()>deadline: raise Gameplay('settle_read_window_exceeded')
   tick=o.get('client_tick')
   if type(tick) is not int or tick<0: raise Maintenance('invalid_tick')
   if grounded(o):
    if previous is not None and tick>previous:return o
    if previous is not None and tick<previous:raise Maintenance('tick_regressed')
    previous=tick if previous is None else previous
   else:previous=None
   if deadline-self.now()<self.timeout+.05:break
   self.sleep(.05)
  raise Gameplay('physical_motion_not_yet_stable')
 def stage_uses(self,sid):
  return sum(r['request'].get('profile') in (PROFILE,'recovery_maintenance_v5') and r['request'].get('stage_id')==sid and all(r['request'].get(k)==self.ctx[k] for k in ('session','world_generation','player_uuid')) for r in self.c.ledger.data['actions'].values())
 def open_batch(self,start,o):
  idle(self.c);self.check_context(o)
  left=4096-len(self.c.ledger.data['actions'])
  if left<=0:raise Maintenance('global_record_capacity_reached')
  pool=[]
  for _ in range(min(128,left)):
   aid=str(uuid.uuid4())
   if aid in self.reserved:raise Maintenance('generated_id_collision_no_retry')
   self.reserved.add(aid);pool.append(aid)
  self.batch_number+=1
  self.batch=dict(id=f'{self.serial}:b{self.batch_number}',start=start,deadline=start+300.,ids=pool,cursor=0,new_stages=0)
  self.emit('batch_open',batch=self.batch,carried_stage=self.stage,carried_uses=self.stage_uses(self.stage['id']) if self.stage else 0,history_count=len(self.c.ledger.data['actions']),fresh_observation_id=o['observation_id'])
 def ensure_batch(self,new_stage=False):
  b=self.batch
  if self.now()+8+self.timeout<b['deadline'] and b['cursor']<len(b['ids']) and (not new_stage or b['new_stages']<16):return
  idle(self.c);o=self.fresh();self.flush()
  self.emit('batch_checkpoint',batch_id=b['id'],original_deadline=b['deadline'],reason='budget_or_finite_pool',unfinished_stage=self.stage,used=self.stage_uses(self.stage['id']) if self.stage else 0)
  self.open_batch(self.now(),o)
 def new_stage_id(self,kind):
  self.ensure_batch(new_stage=True);self.stage_number+=1;self.batch['new_stages']+=1
  return f'ls.{self.serial.replace(chr(45),chr(95))}.{kind}.{self.stage_number}'
 def bind(self,nav=None,survival=None):
  data=dict(version=4,kind='survival',context=self.ctx,navigation=[] if nav is None else [nav],survival=[] if survival is None else [survival])
  raw=encode(data);p=Plan(raw,hashlib.sha256(raw).hexdigest());self.emit('plan_bound',plan=p.snapshot());self.c.plan=p;return p
 def request(self,o,kind,sid,**args):
  if self.now()+8>self.batch['deadline']: raise Rollover('budget_changed_before_new_intent')
  aid=self.batch['ids'][self.batch['cursor']];self.batch['cursor']+=1
  q={k:o[k] for k in ('session','world_generation','player_uuid','owner_generation','observation_id')}
  q.update(schema_version=1,profile=PROFILE,kind=kind,id=aid,owner_id=OWNER,ttl_ms=4000 if kind=='consume_bread' else 1000,plan_version=4,plan_sha256=self.c.plan.sha256,stage_id=sid,**args)
  return q
 def effect(self,q):
  self.last_id=q['id'];self.finish_called=False;self.attempted.append(q['id']);self.pending.append(('pre_start',dict(request=copy.deepcopy(q),batch_id=self.batch['id'])))
  # No sidecar trace/fsync, polling or callback between entry and original-ID finish.
  try:
   self.c.start(q)
  except BaseException:
   rec=self.c.ledger.data['actions'].get(q['id'])
   if rec is not None and rec.get('state')!='CLOSED':
    self.finish_called=True;self.c.finish_one_step(q['id'],clock=self.clock,sleep=self.sleep)
   raise
  self.finish_called=True;rec=self.c.finish_one_step(q['id'],clock=self.clock,sleep=self.sleep)
  self.flush()
  if hasattr(self.c.transport,'timings'):
   timings,self.c.transport.timings=self.c.transport.timings,[];self.emit('transport_response_timing',action_id=q['id'],read_response_only=True,native_deadlines_unchanged=True,timings=timings)
  self.emit('action_finished',action_id=q['id'],request=q,terminal=rec.get('terminal_native'),public_state=rec.get('state'))
  if rec.get('request')!=q or rec.get('state')!='CLOSED' or not isinstance(rec.get('terminal_native'),dict):raise Maintenance('original_action_unresolved_no_reissue')
  term=rec['terminal_native'];self.c._validate_receipt(term,q)
  if term['release_proven'] is not True or term['protocol_terminal'] is not True or term['unknown_lock'] is not False:raise Maintenance('release_or_known_state_not_proven')
  idle(self.c)
  if term['applied_calls']!=term['requested_calls']:raise Gameplay('known_zero_or_partial_no_reissue')
  return self.fresh()
 def survival(self,o):
  v=o['survival'];slots={s['slot']:s for s in o['hotbar']};kind=None;extra={};stage={}
  if v.get('is_using_item') is not False:raise Gameplay('preexisting_use_not_adopted')
  # No HP20, hurt0, no-fire, inventory-original or empty-nearby requirement.
  bread=slots[1];axe=slots[8];food_key=(bread['stack_fingerprint'],bread['count'],v['food_level'])
  if self.spec['enable_bread'] and v['food_level']<20 and bread['item_id']=='minecraft:bread' and bread['count']>0 and food_key!=self.consume_state:
   if o['selected_slot']!=1:kind='select_hotbar';extra=dict(slot=1,stack_fingerprint=bread['stack_fingerprint']);stage['slot']=1
   else:kind='consume_bread';extra=dict(stack_fingerprint=bread['stack_fingerprint'],max_use_ticks=40);stage['max_use_ticks']=40
  elif self.spec['enable_exact_ray_blaze'] and axe['item_id']=='minecraft:iron_axe' and axe['count']==1 and axe['damage']<axe['max_damage']:
   ray=v.get('entity_hit')
   if isinstance(ray,dict) and ray.get('type')=='minecraft:blaze' and ray.get('alive') is True and ray.get('health',0)>0:
    if o['selected_slot']!=8:kind='select_hotbar';extra=dict(slot=8,stack_fingerprint=axe['stack_fingerprint']);stage['slot']=8
    elif v.get('attack_strength',0)>=1:
     kind='attack_blaze';extra=dict(target_entity_id=ray['entity_id'],target_uuid=ray['uuid'],target_type='minecraft:blaze',stack_fingerprint=axe['stack_fingerprint'])
  if kind is None:return False
  sid=self.new_stage_id(kind);stage.update(id=sid,kind=kind,max_intents=1);self.bind(survival=stage)
  o=self.fresh();q=self.request(o,kind,sid,**extra)
  try:gate(o,q,OWNER,self.c.ledger.data['actions'],self.c.plan)
  except Refused:
   self.emit('survival_live_gate_changed_no_post',kind=kind,stage_id=sid);return False
  if kind=='consume_bread':self.consume_state=food_key
  self.effect(q);return True
 def advance(self):
  if self.stop_requested() is True:return dict(state='STOPPED',reason='explicit_stop_requested',close_required=True)
  self.ensure_batch();o=self.fresh()
  if self.survival(o):return None
  o=self.stable();actual_geometry(o)
  if self.stage is not None and arrived(o,self.stage):
   self.planner.arrived(self.stage);self.completed.append(self.stage['id']);self.emit('stage_arrived',stage=self.stage,observation=o);self.stage=None
  if self.stage is None:
   if o['pose']['x']<=self.spec['mission']['stop_x']+.1:return dict(state='GOAL_REACHED',reason='pinned_west_goal_observed',close_required=False)
   sid=self.new_stage_id('nav');s=self.planner.choose(o,sid)
   if s is None:return dict(state='GAMEPLAY_BLOCKED',reason=getattr(self.planner,'reason','no_current_local_route'),close_required=False)
   self.stage=s;self.emit('navigation_target',stage=s,observation=o)
  if self.stage_uses(self.stage['id'])>=8:
   self.emit('stage_exhausted_known',stage=self.stage,used=8);self.planner.blocked(self.stage);self.stage=None;return None
  stage,samples=redirected(o,self.stage);self.bind(nav=stage)
  o=self.fresh();actual_geometry(o)
  if arrived(o,self.stage):return None
  stage,samples=redirected(o,self.stage)
  if stage!=self.c.plan.stage(stage['id']):
   self.bind(nav=stage);o=self.fresh();actual_geometry(o)
   if arrived(o,self.stage):return None
  q=self.request(o,'move',stage['id'],forward=stage['forward'],strafe=stage['strafe'],samples=samples,jump_first=False)
  try:gate(o,q,OWNER,self.c.ledger.data['actions'],self.c.plan)
  except Refused as e:
   self.emit('navigation_gate_blocked_no_post',stage=self.stage,observation=o,reason=str(e))
   if 'nearby' in str(e):raise Gameplay('temporary_nearby_admission_block_same_stage')
   self.planner.blocked(self.stage);self.stage=None;return None
  self.effect(q);return None
 def checkpoint_observe(self):
  # Read-only while gameplay is blocked/dead/in UI. No new context adoption.
  idle(self.c);o=self.c.observe();self.now()
  if o.get('profile')!=PROFILE or o.get('bound_owner_id')!=OWNER or o.get('unknown_lock') is not False or o.get('active_id') is not None:raise Maintenance('checkpoint_authority_or_action_state_unavailable')
  if o.get('owner_generation')!=len(self.c.ledger.data['actions'])+1:raise Maintenance('checkpoint_owner_generation_mismatch')
  return o
 def material(self,o):
  keys=('session','world_generation','player_uuid','alive','ready','paused','screen_open','pose','player_bbox','velocity','on_ground','sprinting','health','selected_slot','hotbar','survival','nearby_living','nearby_truncated','local_blocks','local_primed_tnt','collision_boxes_complete')
  return hashlib.sha256(encode({k:o.get(k) for k in keys})).hexdigest()
 def enter_checkpoint(self,state,reason):
  o=self.checkpoint_observe();self.flush()
  self.checkpoint=dict(state=state,reason=reason,signature=self.material(o))
  self.emit('gameplay_checkpoint',state=state,reason=reason,close_required=False,observation=o,unfinished_stage=self.stage,used=self.stage_uses(self.stage['id']) if self.stage else 0)
  return dict(state=state,reason=reason,close_required=False)
 def poll_checkpoint(self):
  if self.checkpoint is None:return None
  self.sleep(.25);o=self.checkpoint_observe();signature=self.material(o)
  if signature==self.checkpoint['signature']:return None
  self.checkpoint['signature']=signature
  try:self.check_context(o)
  except Gameplay:
   self.emit('gameplay_observation',state=self.checkpoint['state'],close_required=False,observation=o);return None
  self.emit('gameplay_resume',reason='actual_material_facts_changed',observation=o,unfinished_stage=self.stage,used=self.stage_uses(self.stage['id']) if self.stage else 0)
  self.checkpoint=None;return None
 def step(self):
  """One bounded advance/read; ordinary checkpoints retain THIS Session object."""
  try:
   if self.stop_requested() is True:return self.result('STOPPED','explicit_stop_requested',True)
   if self.checkpoint is not None:return self.poll_checkpoint()
   try:outcome=self.advance()
   except Rollover:return None
   except Gameplay as e:return self.enter_checkpoint('GAMEPLAY_CHECKPOINT',str(e))
   if outcome is None:return None
   if outcome['close_required']:return self.result(**outcome)
   return self.enter_checkpoint(outcome['state'],outcome['reason'])
  except BaseException as e:
   # effect() owns original-ID finish; this never re-enters it or reissues.
   return self.result('MAINTENANCE_REQUIRED',str(e)[:180],True,exception_type=type(e).__name__[:64])
 def result(self,state,reason,close_required,**extra):
  exact=all(self.c.ledger.data['actions'].get(a)==r for a,r in self.baseline['actions'].items())
  if not exact:state,reason,close_required='MAINTENANCE_REQUIRED','historical_record_changed',True
  r=dict(schema_version=1,runner='survival6-live-session-r1',state=state,reason=reason,close_required=close_required,session_id=self.serial,batches=self.batch_number,attempted_ids=self.attempted,completed_stages=self.completed,unfinished_stage=self.stage,unfinished_uses=self.stage_uses(self.stage['id']) if self.stage else 0,historical_prefix_exact=exact,final_count=len(self.c.ledger.data['actions']),unknown_lock=self.c.ledger.data['unknown_lock'],**extra)
  self.flush();self.emit('session_result',result=r)
  with (self.out/'RESULT.json').open('wb') as f:f.write(encode(r));f.flush();os.fsync(f.fileno())
  return r

def run(controller,**kwargs):
 """Retain one Session through ordinary checkpoints; only stop/maintenance ends."""
 s=Session(controller,**kwargs)
 while True:
  result=s.step()
  if result is not None and result['close_required']:return result

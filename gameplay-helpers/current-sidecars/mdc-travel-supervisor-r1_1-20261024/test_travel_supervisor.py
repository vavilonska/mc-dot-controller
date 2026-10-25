import copy, hashlib, importlib.util, json, pathlib, sys, tempfile, unittest
from travel_supervisor import Supervisor, HttpTransport, UnknownInput, released_terminal

import boundary_contract as core
def frame():
 return {'private_singleplayer':True,'paused':False,'screen_open':False,
  'world':{'world_generation':'w','dimension':'minecraft:overworld','navigation_guard':{'rebind_ready':False}},
  'player':{'uuid':'p','generation':'g','alive':True,'health':20.,'using_item':False,'selected_slot':0,
   'offhand':{'id':'minecraft:shield'},'mainhand':{'id':'minecraft:stone_sword'},
   'inventory':[{'slot':0,'id':'minecraft:stone_sword'}], 'eye_position':{'x':0,'y':1.62,'z':0},
   'entity_interaction_range':3.,'attack_strength':1.},
  'client_action':{'action_session':'s','status':'idle','input_owner':'direct'},
  'held_inputs':{'neutral':True,'keys':[],'raw_keys':0,'world_mouse_buttons':0},
  'nearby':{'entities':[]},'crosshair':{}}
def body(action='use_item'):
 return {'action_id':'original','action':action,'expected_world_generation':'w','expected_player_uuid':'p',
         'expected_action_session':'s','timeout_ms':1000}
def rejection(b):
 digest=hashlib.sha256(json.dumps(b,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
 return {'ok':False,'error':'capability_source_expired','native_admission':{
  'schema_version':1,'action_id':b['action_id'],'action':b['action'],'action_session':'s',
  'request_payload_sha256':digest,'digest_format':'sorted-json-utf8/1','stage':'hooks_possible',
  'reason':'capability_source_expired','boundary_schema_version':2,'ordinary_start_entered':True,
  'input_transfer_entered':False,'registration_entered':False,'reentry_observed':False,
  'effects_none_proven':False,'dispatch_authority':False,'retry_authority':False}}
def terminal(b,release=True,status='succeeded'):
 r={} if release is None else {'input_release_confirmed':release}
 return {'action_id':b['action_id'],'action':b['action'],'action_session':'s','status':status,'input_owner':'direct','result':r}
class Client:
 def __init__(self,out):self.out=out;self.request=lambda *a:None;self.log=[]
 def note(self,event,**v):self.log.append((event,v))
class Fake:
 def __init__(self):
  self.s=frame();self.calls=[];self.post=(202,dict(body(),action_session='s',status='running'))
  self.status=(404,{'error':'action_not_found'});self.raise_get=False;self.raw_fail=None;self.sv=None
 def __call__(self,method,path,payload=None):
  self.calls.append((method,path,copy.deepcopy(payload)))
  if method=='GET':
   if self.raise_get:raise TimeoutError('get')
   return copy.deepcopy(self.status if '/action/status' in path else (200,self.s))
  if path=='/control/action':
   assert self.sv.pending is not None
   if isinstance(self.post,Exception):raise self.post
   return copy.deepcopy(self.post)
  if path==self.raw_fail:raise TimeoutError('raw')
  if path=='/control/key':
   k,a=payload['mapping'],payload['action']
   if k=='key.use':
    down=a=='down';was=self.s['held_inputs']['world_mouse_buttons']>0
    self.s['held_inputs'].update(neutral=not down,keys=['key.use'] if down else [],world_mouse_buttons=1 if down else 0)
    self.s['player']['using_item']=down
    return 200,{'ok':True,'scope':'world','mapping':'key.use','action':a,'key_type':'mouse','button':1,'was_down':was,'down':down,'mapping_down':down}
   elif k.startswith('key.hotbar.'):
    self.s['player']['selected_slot']=int(k.rsplit('.',1)[1])-1
    self.s['player']['mainhand']=copy.deepcopy(next(v for v in self.s['player']['inventory'] if v['slot']==self.s['player']['selected_slot']))
  return 200,{'ok':True}
class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.d=pathlib.Path(self.tmp.name)
  self.f=Fake();self.c=Client(self.d);self.t=[0.]
  self.v=Supervisor(self.c,self.f,core.bound_pre_input_rejection,weapon_slot=0,lock_path=self.d/'lock',clock=lambda:self.t[0],sleep=lambda _:None)
  self.f.sv=self.v;self.v.install();self.addCleanup(self.v.close)
 def posts(self,path=None):return [x for x in self.f.calls if x[0]=='POST' and (path is None or x[1]==path)]
 def test_known_assert_run_enters_guard_and_handoff(self):
  self.v.close();hf=self.d/'HANDOFF'
  self.v.sleep=lambda _:hf.touch()
  def mission():raise AssertionError('bed_not_yet_collected')
  self.assertEqual(self.v.run(mission,hf),'HANDOFF_NEUTRAL')
  self.assertEqual([x[2]['action'] for x in self.posts('/control/key')],['down','up'])
 def test_real_boundary_409_404_neutral_no_repost(self):
  b=body();self.f.post=(409,rejection(b));self.v.request('POST','/control/action',b)
  self.v.resolve_step();self.assertIsNone(self.v.pending)
  self.assertEqual(self.v.last_resolution['status'],'not_dispatched');self.assertEqual(len(self.posts()),1)
  self.v.defend_step();self.assertTrue(self.v.held_use)
 def test_action_once_refusal_returns_immediately_to_outer_guard(self):
  from travel_supervisor import KnownStop
  b=body();self.f.post=(409,rejection(b))
  with self.assertRaises(KnownStop):self.v.action_once(b)
  self.assertIsNone(self.v.pending);self.assertEqual(len(self.posts('/control/action')),1)
 def test_handoff_during_first_action_prevents_second_post(self):
  self.v.close();hf=self.d/'HANDOFF';raw=self.f
  def transport(method,path,payload=None):
   if method=='GET' and '/action/status' in path:
    hf.touch();self.f.status=(200,terminal(body()))
   return raw(method,path,payload)
  self.v.transport=transport
  def mission():
   self.v.action_once(body());b=body();b['action_id']='second';self.v.action_once(b)
  self.assertEqual(self.v.run(mission,hf),'HANDOFF_NEUTRAL')
  self.assertEqual(len(self.posts('/control/action')),1)
 def test_lost_post_404_never_cancel_or_guard(self):
  self.f.post=TimeoutError('lost')
  with self.assertRaises(TimeoutError):self.v.request('POST','/control/action',body())
  self.t[0]=100;self.v.cycle(True);self.v.cycle(True)
  self.assertIsNotNone(self.v.pending);self.assertEqual(len(self.posts()),1)
 def test_running_after_lost_reply_not_cancelled_for_fire(self):
  self.f.post=TimeoutError('lost')
  with self.assertRaises(TimeoutError):self.v.request('POST','/control/action',body())
  st=dict(body(),status='running',action_session='s',input_owner='native');self.f.status=(200,st)
  self.f.s['client_action']=st;self.f.s['player']['on_fire']=True
  self.v.cycle();self.assertEqual(len(self.posts()),1)
  self.t[0]=7;self.v.cycle();self.v.cycle()
  self.assertEqual(len(self.posts('/control/action/cancel')),1)
 def test_cancel_requires_exact_active_current_state(self):
  self.v.request('POST','/control/action',body());self.f.status=(200,dict(body(),status='running',action_session='s'))
  self.t[0]=9;self.v.cycle(True);self.assertEqual(len(self.posts('/control/action/cancel')),0)
 def test_known_terminal_release_then_guard(self):
  b=body();self.v.request('POST','/control/action',b);self.f.status=(200,terminal(b,status='failed'))
  self.v.cycle();self.assertIsNone(self.v.pending);self.v.cycle();self.assertTrue(self.v.held_use)
 def test_explicit_unknown_terminal_no_new_input(self):
  b=body();self.v.request('POST','/control/action',b);st=terminal(b);st['result']['unknown_outcome']=True
  self.f.status=(200,st);self.v.cycle();self.v.cycle();self.assertEqual(len(self.posts()),1)
 def test_raw_attack_uncertain_stays_read_only(self):
  self.f.raw_fail='/control/key'
  with self.assertRaises(TimeoutError):self.v.key('key.attack')
  self.v.cycle();self.v.cycle(True);self.assertEqual(len(self.posts()),1);self.assertIsNotNone(self.v.raw_pending)
 def test_nonuse_hold_rejected_before_input(self):
  from travel_supervisor import KnownStop
  with self.assertRaises(KnownStop):self.v.key('key.forward','down')
  self.assertFalse(self.posts());self.assertIsNone(self.v.raw_pending)
 def test_recursive_unknown_and_malformed_flags_refused(self):
  from travel_supervisor import unknown
  for key in ('unknown_outcome','requires_handoff','no_auto_resume','requires_reconciliation_before_retry','unknown_attack_outcome'):
   for value in (True,None,0,'false',{},[]):self.assertTrue(unknown({'result':{'nested':[{'x':{key:value}}]}}))
   self.assertFalse(unknown({'result':{'nested':[{key:False}]}}))
 def test_defense_look_exception_preserves_unknown_and_shield(self):
  self.enemy();self.f.raw_fail='/control/look';self.v.cycle();n=len(self.posts());self.v.cycle()
  self.assertEqual(len(self.posts()),n);self.assertTrue(self.v.held_use);self.assertIsNotNone(self.v.raw_pending)
 def test_get_timeout_is_one_attempt_not_infinite(self):
  self.f.raise_get=True;n=len(self.f.calls);self.v.cycle();self.assertEqual(len(self.f.calls),n+1)
  self.f.raise_get=False;self.v.cycle();self.assertTrue(self.v.held_use)
 def test_no_navready_gate_for_stationary_guard(self):
  self.assertFalse(self.f.s['world']['navigation_guard']['rebind_ready']);self.v.cycle();self.assertTrue(self.v.held_use)
 def test_foreign_held_and_owner_no_mutation(self):
  self.f.s['held_inputs'].update(neutral=False,keys=['key.forward']);self.v.cycle();self.assertFalse(self.posts())
 def test_real_mouse_one_own_receipt_guard_and_handoff(self):
  self.v.cycle();self.assertEqual(self.f.s['held_inputs']['world_mouse_buttons'],1)
  self.assertIsNotNone(self.v.use_binding);self.v.cycle();self.assertEqual(self.v.mode,'GUARDING')
  self.assertTrue(self.v.cycle(True));self.assertEqual(self.v.mode,'HANDOFF_NEUTRAL')
  self.assertIsNone(self.v.use_binding);self.assertEqual(self.f.s['held_inputs']['world_mouse_buttons'],0)
 def test_exact_g1045_wire_does_not_reject_own_mouse(self):
  fixture=json.loads((pathlib.Path(__file__).parent/'G1045-REAL-USE-WIRE.json').read_text());raw=self.v.transport
  def transport(method,path,payload=None):
   code,obj=raw(method,path,payload)
   if method=='POST' and path=='/control/key' and payload.get('action')=='down':
    self.f.s['held_inputs']=copy.deepcopy(fixture['held_inputs_after'])
    self.f.s['player']['using_item']=False
    return 200,copy.deepcopy(fixture['use_down_reply'])
   return code,obj
  self.v.transport=transport;self.v.cycle();self.v.cycle()
  self.assertEqual(self.v.mode,'GUARDING');self.assertTrue(self.v.cycle(True));self.assertEqual(self.v.mode,'HANDOFF_NEUTRAL')
 def test_foreign_mouse_one_is_not_our_shield(self):
  self.f.s['held_inputs'].update(neutral=False,keys=['key.use'],world_mouse_buttons=1)
  self.v.cycle();self.assertFalse(self.posts());self.assertIsNone(self.v.use_binding)
 def test_uncertain_use_down_does_not_establish_ownership(self):
  self.f.raw_fail='/control/key';self.v.cycle();self.v.cycle(True)
  self.assertIsNone(self.v.use_binding);self.assertEqual(len(self.posts()),1)
 def test_workbench_selected_switches_weapon_before_use(self):
  self.f.s['player'].update(selected_slot=5,mainhand={'id':'minecraft:crafting_table'})
  self.v.cycle();keys=[x[2]['mapping'] for x in self.posts('/control/key')]
  self.assertEqual(keys[:2],['key.hotbar.1','key.use']);self.assertEqual(self.v.mode,'GUARDING')
 def test_wrong_button_release_reply_keeps_ownership_unresolved(self):
  self.v.cycle();raw=self.v.transport
  def changed(method,path,payload=None):
   code,obj=raw(method,path,payload)
   if method=='POST' and path=='/control/key' and payload.get('action')=='up':obj['button']=0
   return code,obj
  self.v.transport=changed;self.assertFalse(self.v.cycle(True))
  self.assertIsNotNone(self.v.raw_pending);self.assertIsNotNone(self.v.use_binding)
 def test_context_change_and_death_do_not_rearm(self):
  self.f.s['world']['world_generation']='new';self.assertTrue(self.v.cycle());self.assertFalse(self.posts())
  self.f.s=frame();self.f.s['player']['alive']=False;self.assertTrue(self.v.cycle());self.assertFalse(self.posts())
 def test_flock_prevents_second_owner(self):
  v=Supervisor(Client(self.d),self.f,core.bound_pre_input_rejection,weapon_slot=0,lock_path=self.d/'lock')
  with self.assertRaises(BlockingIOError):v.install()
 def test_initial_missing_or_false_release_cannot_arm(self):
  self.v.close()
  for release in (None,False):
   self.f.s['client_action']=terminal(body(),release)
   from travel_supervisor import KnownStop
   with self.assertRaises(KnownStop):self.v.install()
   self.assertIsNone(self.v.lock)
 def test_pre_rejection_existing_id_never_consumes_old_terminal(self):
  b=body();self.f.post=(409,rejection(b));self.v.request('POST','/control/action',b)
  self.f.status=(200,terminal(b));self.v.cycle();self.assertIsNotNone(self.v.pending)
 def test_pre_rejection_existing_running_cannot_cancel(self):
  b=body();self.f.post=(409,rejection(b));self.v.request('POST','/control/action',b)
  st=dict(body(),status='running',action_session='s',input_owner='native')
  self.f.status=(200,st);self.f.s['client_action']=st;self.t[0]=100
  self.v.cycle(True);self.v.cycle(True);self.assertEqual(len(self.posts('/control/action/cancel')),0)
 def test_keyboard_interrupt_in_watch_retains_owner_until_release(self):
  self.v.close();n=[0]
  def sleep(_):
   n[0]+=1
   if n[0]==1:raise KeyboardInterrupt()
  self.v.sleep=sleep
  self.assertEqual(self.v.run(lambda:None,self.d/'absent'),'HANDOFF_NEUTRAL')
  self.assertEqual([x[2]['action'] for x in self.posts('/control/key')],['down','up'])
 def test_wrong_digest_does_not_clear_404(self):
  b=body();r=rejection(b);r['native_admission']['request_payload_sha256']='bad';self.f.post=(409,r)
  self.v.request('POST','/control/action',b);self.v.cycle();self.assertIsNotNone(self.v.pending)
 def test_legacy_and_managed_boundary(self):
  for a in ('break_block','place_block','click_slot'):
   b=body(a);self.assertTrue(released_terminal(terminal(b,None),b))
   self.assertFalse(released_terminal(terminal(b,False),b));b['capability_guard']={}
   self.assertFalse(released_terminal(terminal(b,None),b))
  b=body('follow_path');self.assertFalse(released_terminal(terminal(b,None),b))
  for a,k in [('place_block','dispatched'),('click_slot','click_dispatched')]:
   b=body(a);t=terminal(b,None,'failed');t['result'][k]=True;self.assertFalse(released_terminal(t,b))
 def enemy(self):
  self.f.s['nearby']['entities']=[{'uuid':'h','type':'minecraft:husk','alive':True,'distance':2.,'line_of_sight':True,
   'bounding_box':{'min':{'x':-.3,'y':0,'z':1.7},'max':{'x':.3,'y':1.8,'z':2.3}}}]
  self.f.s['crosshair']={'type':'entity','uuid':'h','location':{'x':0,'y':1.,'z':1.7}}
 def test_actual_husk_single_known_click_fresh_ray(self):
  self.enemy();self.v.cycle();attacks=[x for x in self.posts('/control/key') if x[2]['mapping']=='key.attack']
  self.assertEqual(len(attacks),1);self.assertTrue(self.v.held_use)
 def test_cooldown_wrong_target_no_attack(self):
  self.enemy();self.f.s['player']['attack_strength']=.5;self.v.cycle()
  self.assertFalse([x for x in self.posts('/control/key') if x[2]['mapping']=='key.attack'])
 def test_no_post_retry_after_pending(self):
  self.v.request('POST','/control/action',body())
  with self.assertRaises(UnknownInput):self.v.request('POST','/control/action',body())
  self.assertEqual(len(self.posts()),1)
if __name__=='__main__':unittest.main(verbosity=2)

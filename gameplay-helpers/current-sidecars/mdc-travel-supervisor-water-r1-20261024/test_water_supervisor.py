import copy, pathlib, sys, tempfile, unittest
BASE=pathlib.Path(__file__).resolve().parent.parent/'mdc-travel-supervisor-r1_1-20261024'
sys.path.insert(0,str(BASE))
from travel_supervisor import KnownStop
from boundary_contract import bound_pre_input_rejection
from test_travel_supervisor import Fake, Client, frame, terminal, body, rejection
from water_supervisor import WaterFirstSupervisor

class WaterTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.d=pathlib.Path(self.tmp.name)
  self.f=Fake();self.c=Client(self.d);self.t=0.
  self.sv=WaterFirstSupervisor(self.c,self.f,bound_pre_input_rejection,weapon_slot=0,
   lock_path=self.d/'lock',clock=lambda:self.t,sleep=lambda _:None)
  self.f.sv=self.sv;self.sv.install();self.addCleanup(self.sv.close)
 def wet(self):self.f.s['player'].update(in_water=True,eye_in_water=True,air=200,max_air=300,on_ground=False)
 def dry(self):self.f.s['player'].update(in_water=False,eye_in_water=False,air=300,max_air=300,on_ground=True)
 def posts(self,path='/control/action'):return [x for x in self.f.calls if x[0]=='POST' and x[1]==path]
 def end(self,status='failed',reason='deadline_exceeded',extra=None):
  b=self.sv.pending['body'];st=terminal(b,release=None,status=status);st['reason']=reason
  if extra:st['result'].update(extra)
  self.f.status=(200,st);self.f.s['client_action']=copy.deepcopy(st)
  self.f.s['held_inputs'].update(neutral=True,keys=[],raw_keys=0,world_mouse_buttons=0)
  self.f.s['player']['using_item']=False
  return st
 def test_own_real_use_wire_up_fresh_neutral_before_recover(self):
  self.sv.cycle();self.assertTrue(self.sv.held_use);self.wet();self.sv.cycle()
  calls=self.f.calls;up=next(i for i,x in enumerate(calls) if x[0]=='POST' and x[1]=='/control/key' and x[2]['action']=='up')
  rec=next(i for i,x in enumerate(calls) if x[0]=='POST' and x[1]=='/control/action')
  self.assertTrue(any(x[0]=='GET' and x[1]=='/control/state?radius=0' for x in calls[up+1:rec]))
  b=self.posts()[0][2];self.assertEqual(b['action'],'recover_environment');self.assertEqual(b['timeout_ms'],15000)
  self.assertEqual(b['waypoints'],[]);self.assertEqual(len(b),7);self.assertFalse(self.sv.held_use)
 def test_known_deadline_still_water_new_id_not_old_retry(self):
  self.wet();self.sv.cycle();old=self.sv.pending['body']['action_id'];st=self.end()
  self.sv.cycle();self.assertIsNone(self.sv.pending);self.assertNotIn('input_release_confirmed',st['result'])
  self.sv.cycle();self.assertEqual(len(self.posts()),2);self.assertNotEqual(self.sv.pending['body']['action_id'],old)
  self.assertEqual(self.posts('/control/key'),[])
 def test_dry_success_returns_to_guard(self):
  self.wet();self.sv.cycle();self.end('succeeded','environment_dry_observed');self.dry()
  self.sv.cycle();self.sv.cycle();self.assertIsNone(self.sv.pending);self.assertEqual(self.sv.mode,'GUARDING')
 def test_explicit_unknown_keeps_original_no_new_segment(self):
  self.wet();self.sv.cycle();self.end(extra={'unknown_outcome':True})
  self.sv.cycle();self.sv.cycle();self.assertEqual(len(self.posts()),1);self.assertIsNotNone(self.sv.pending)
 def test_unknown_lost_post_404_no_guard_no_cancel(self):
  self.wet();self.f.post=TimeoutError('lost');self.sv.cycle();self.t=60.;self.sv.cycle();self.sv.cycle(True)
  self.assertEqual(len(self.posts()),1);self.assertIsNotNone(self.sv.pending);self.assertFalse(self.posts('/control/action/cancel'))
 def test_fresh_other_id_does_not_release_legacy(self):
  self.wet();self.sv.cycle();self.end();self.f.s['client_action']['action_id']='someone_else'
  self.sv.cycle();self.assertIsNotNone(self.sv.pending)
 def test_newer_current_cleanup_diagnostic_is_not_ignored(self):
  self.wet();self.sv.cycle();self.end()
  self.f.s['client_action']['result']['input_release_diagnostics']={'failed_stage':'late_cleanup'}
  self.sv.cycle();self.assertIsNotNone(self.sv.pending);self.assertEqual(len(self.posts()),1)
 def test_explicit_false_release_is_not_legacy_missing(self):
  self.wet();self.sv.cycle();self.end(extra={'input_release_confirmed':False});self.sv.cycle()
  self.assertIsNotNone(self.sv.pending)
 def test_other_recover_not_created_by_water_branch_not_accepted(self):
  b=body('recover_environment');b['waypoints']=[];self.sv.request('POST','/control/action',b)
  self.end();self.sv.cycle();self.assertIsNotNone(self.sv.pending)
 def test_unknown_own_use_up_does_not_send_recover(self):
  self.sv.cycle();self.wet();self.f.raw_fail='/control/key';self.sv.cycle();self.sv.cycle()
  self.assertFalse(self.posts());self.assertIsNotNone(self.sv.raw_pending)
 def test_foreign_use_water_does_not_claim_or_release(self):
  self.wet();self.f.s['held_inputs'].update(neutral=False,keys=['key.use'],world_mouse_buttons=1)
  self.sv.cycle();self.assertFalse(self.posts());self.assertFalse(self.posts('/control/key'))
 def test_air_fall_observation_priority(self):
  self.dry();self.sv.state(0);self.f.s['player'].update(air=290,on_ground=False)
  self.sv.cycle();self.assertEqual(len(self.posts()),1)
 def test_known_mission_endpoint_water_stops_next_action(self):
  b=body('follow_path');st=terminal(b);st['reason']='path_reached';raw=self.f
  def transport(method,path,payload=None):
   if method=='GET' and '/action/status' in path:
    self.f.status=(200,st);self.f.s['client_action']=copy.deepcopy(st);self.wet()
   return raw(method,path,payload)
  self.sv.transport=transport
  with self.assertRaisesRegex(KnownStop,'water_at_known_endpoint'):self.sv.action_once(b)
  self.assertEqual(len(self.posts()),1);self.assertIsNone(self.sv.pending)
  self.sv.cycle();self.assertEqual(len(self.posts()),2)
 def test_context_death_busy_never_new_water_input(self):
  for mutate in ('context','dead','busy'):
   with self.subTest(mutate=mutate):
    self.f.s=frame();self.wet()
    if mutate=='context':self.f.s['world']['world_generation']='new'
    elif mutate=='dead':self.f.s['player']['alive']=False
    else:self.f.s['client_action'].update(status='running',input_owner='native')
    self.sv.cycle();self.assertFalse(self.posts())
 def test_preinput_rejection_then_existing_running_remains_readonly(self):
  self.wet();raw=self.f
  def transport(method,path,payload=None):
   if method=='POST' and path=='/control/action':self.f.post=(409,rejection(payload))
   return raw(method,path,payload)
  self.sv.transport=transport;self.sv.cycle();b=self.sv.pending['body']
  st=dict(b,action_session='s',status='running');self.f.status=(200,st);self.f.s['client_action']=st
  self.t=100.;self.sv.cycle(True);self.assertTrue(self.sv.pending['exists_after_pre'])
  self.assertEqual(len(self.posts()),1);self.assertFalse(self.posts('/control/action/cancel'))
 def test_no_stale_air_latch_after_max_air(self):
  self.dry();self.sv.state(0);self.f.s['player']['air']=290;self.sv.state(0);self.assertTrue(self.sv._air_falling)
  self.dry();self.sv.cycle();self.assertFalse(self.posts());self.assertEqual(self.sv.mode,'GUARDING')

if __name__=='__main__':unittest.main(verbosity=2)

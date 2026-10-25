import copy,hashlib,json,sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE),str(HERE.parent/'MDC-RECOVERY-RESTORED-F1220-20261022T1433Z/C8-source/survival6-controller')]
import rebuilt_session as r
import run_recovery as cli
import zero_attempt_handoff as handoff

def setup():
 serial=str(uuid4());ctx=dict(session=str(uuid4()),world_generation=str(uuid4()),player_uuid=r.PLAYER,owner_id=r.OWNER)
 baseline=dict(actions={str(uuid4()):dict(state='CLOSED',request={}) for _ in range(2)},unknown_lock=False)
 base=r.encode(baseline);bh=hashlib.sha256(base).hexdigest()
 spec=dict(schema_version=1,kind='survival6_live_corridor_session',baseline_sha256=bh,baseline_count=2,owner_id=r.OWNER,player_uuid=r.PLAYER,mission=dict(kind='west_corridor',stop_x=-635.),batch_seconds=300,start_reserve_seconds=8,batch_max_intents=128,batch_max_new_stages=16,enable_bread=True,enable_exact_ray_blaze=True)
 raw=r.encode(spec);sh=hashlib.sha256(raw).hexdigest();batch=dict(id=serial+':b1',start=100.,deadline=400.,ids=[str(uuid4()) for _ in range(128)],cursor=0,new_stages=0)
 obs=dict(profile=r.PROFILE,bound_owner_id=r.OWNER,session=ctx['session'],world_generation=ctx['world_generation'],player_uuid=r.PLAYER,owner_generation=3,unknown_lock=False,active_id=None,alive=True,ready=True,paused=False,screen_open=False,client_tick=10,on_ground=True,sprinting=False,collision_boxes_complete=True,velocity=dict(x=0.,y=0.,z=0.))
 result=dict(state='MAINTENANCE_REQUIRED',reason='observation unavailable',exception_type='Refused',close_required=True,attempted_ids=[],completed_stages=[],unfinished_stage=None,unfinished_uses=0,batches=1,historical_prefix_exact=True,unknown_lock=False,final_count=2,session_id=serial)
 events=[dict(event='session_open',session_id=serial,context=ctx,spec=spec,spec_sha256=sh,started_at=100.),dict(event='batch_open',session_id=serial,batch=batch,carried_stage=None,carried_uses=0,history_count=2),dict(event='reconstructed_helper_open',session_id=serial,version='rebuild-20261022-r2-startup-wait'),dict(event='session_result',session_id=serial,result=result)]
 c=types.SimpleNamespace(owner_id=r.OWNER,ledger=types.SimpleNamespace(data=baseline),transport=types.SimpleNamespace(timeout=.5))
 kw=dict(old_trace=b'\n'.join(r.encode(e) for e in events)+b'\n',old_result=r.encode(result),initial_observation=obs,baseline_raw=base,expected_baseline_sha256=bh,session_spec_raw=raw,expected_session_spec_sha256=sh,confirm_world=lambda o:True,session_started_at=999.)
 return c,kw,events

class Tests(unittest.TestCase):
 def restored(self,td):
  c,kw,events=setup();clock=[450.];emitted=[]
  kw.update(outdir=Path(td)/'new',monotonic=lambda:clock[0],sleep=lambda n:clock.__setitem__(0,clock[0]+n),on_event=emitted.append)
  s=handoff.restore(c,**kw)
  return s,c,kw,events,clock,emitted
 def test_restores_exact_serial_original_deadline_pool_and_budget(self):
  with tempfile.TemporaryDirectory() as td:
   s,c,kw,events,clock,out=self.restored(td)
   self.assertEqual(s.serial,events[0]['session_id']);self.assertEqual(s.batch,events[1]['batch']);self.assertEqual(s.batch_number,1);self.assertEqual(s.stage_number,0)
   self.assertEqual(s.reserved,set(c.ledger.data['actions'])|set(s.batch['ids']));self.assertFalse(s.attempted);self.assertEqual([x['event'] for x in out],['zero_attempt_maintenance_restored','maintenance_batch_restored'])
 def test_expired_batch_rollover_preserves_old_ids_and_same_serial(self):
  with tempfile.TemporaryDirectory() as td:
   s,c,kw,events,clock,out=self.restored(td);old=set(s.batch['ids']);serial=s.serial
   c.observe=lambda:dict(kw['initial_observation'],observation_id=str(uuid4()))
   s.ensure_batch();self.assertEqual(s.serial,serial);self.assertEqual(s.batch_number,2);self.assertTrue(old<=s.reserved);self.assertFalse(old&set(s.batch['ids']));self.assertEqual(s.batch['deadline'],clock[0]+300.)
 def test_nonzero_unknown_context_or_tampered_trace_refused_before_evidence(self):
  for mode in ('attempt','unknown','context','batch','extra'):
   with self.subTest(mode=mode),tempfile.TemporaryDirectory() as td:
    c,kw,events=setup();out=Path(td)/'new';kw['outdir']=out;kw['monotonic']=lambda:450.
    if mode=='attempt':events[-1]['result']['attempted_ids']=[str(uuid4())];kw['old_result']=r.encode(events[-1]['result'])
    if mode=='unknown':c.ledger.data['unknown_lock']=True
    if mode=='context':kw['initial_observation']['session']=str(uuid4())
    if mode=='batch':events[1]['batch']['cursor']=1
    if mode=='extra':events.insert(2,dict(event='decision_accepted'))
    kw['old_trace']=b'\n'.join(r.encode(e) for e in events)+b'\n'
    with self.assertRaises(r.Maintenance):handoff.restore(c,**kw)
    self.assertFalse(out.exists())
 def test_fresh_and_checkpoint_wait_preserve_stage_token_and_serial(self):
  for method in ('fresh','checkpoint_observe'):
   with self.subTest(method=method),tempfile.TemporaryDirectory() as td:
    s,c,kw,events,clock,out=self.restored(td);s.stage=dict(id='keep-stage',max_moves=8);s.decision_token={'token':'keep'};before=copy.deepcopy((s.serial,s.stage,s.batch,s.reserved,s.decision_token));calls=[]
    def observe():
     calls.append('GET')
     if len(calls)<3:raise r.Refused('observation unavailable')
     return copy.deepcopy(kw['initial_observation'])
    c.observe=observe;self.assertEqual(getattr(s,method)(),kw['initial_observation']);self.assertEqual(len(calls),3);self.assertEqual(before,(s.serial,s.stage,s.batch,s.reserved,s.decision_token));self.assertFalse(s.attempted)
 def test_stable_uses_same_retrying_fresh_without_extra_action(self):
  with tempfile.TemporaryDirectory() as td:
   s,c,kw,events,clock,out=self.restored(td);calls=[]
   def observe():
    calls.append('GET')
    if len(calls)==1:raise r.Refused('observation unavailable')
    return dict(kw['initial_observation'],client_tick=10+len(calls))
   c.observe=observe;self.assertGreater(s.stable()['client_tick'],10);self.assertEqual(len(calls),3);self.assertFalse(s.attempted)
 def test_stable_recovers_after_more_than_two_seconds_unavailable(self):
  with tempfile.TemporaryDirectory() as td:
   s,c,kw,events,clock,out=self.restored(td);calls=[];start=clock[0]
   def observe():
    calls.append('GET')
    if len(calls)<=2:
     clock[0]+=1.2
     raise r.Refused('observation unavailable')
    return dict(kw['initial_observation'],client_tick=10+len(calls))
   c.observe=observe;self.assertGreater(s.stable()['client_tick'],10);self.assertEqual(len(calls),4);self.assertGreater(clock[0]-start,2.);self.assertFalse(s.attempted);self.assertIsNone(s.checkpoint)
 def test_two_successful_slow_reads_still_prove_actual_stability(self):
  with tempfile.TemporaryDirectory() as td:
   s,c,kw,events,clock,out=self.restored(td);calls=[];start=clock[0]
   def observe():
    calls.append('GET');clock[0]+=1.2
    return dict(kw['initial_observation'],client_tick=10+len(calls))
   c.observe=observe;self.assertGreater(s.stable()['client_tick'],10);self.assertEqual(len(calls),2);self.assertGreater(clock[0]-start,2.);self.assertFalse(s.attempted);self.assertIsNone(s.checkpoint)
 def test_intermittent_unavailable_does_not_erase_two_actual_grounded_frames(self):
  with tempfile.TemporaryDirectory() as td:
   s,c,kw,events,clock,out=self.restored(td);calls=[]
   def observe():
    calls.append('GET')
    if len(calls)%2:
     clock[0]+=1.2
     raise r.Refused('observation unavailable')
    return dict(kw['initial_observation'],client_tick=10+len(calls))
   c.observe=observe;self.assertGreater(s.stable()['client_tick'],10);self.assertEqual(len(calls),4);self.assertFalse(s.attempted);self.assertIsNone(s.checkpoint)
 def test_unknown_lock_or_invalid_schema_never_retries(self):
  with tempfile.TemporaryDirectory() as td:
   s,c,kw,events,clock,out=self.restored(td);calls=[]
   def observe():calls.append('GET');raise r.Refused('closed v6 observation required')
   c.observe=observe
   with self.assertRaises(r.Refused):s.fresh()
   self.assertEqual(calls,['GET']);c.ledger.data['unknown_lock']=True
   with self.assertRaises(r.Maintenance):s.fresh()
   self.assertEqual(calls,['GET'])
 def test_cancel_during_read_wait_stops_without_new_action(self):
  with tempfile.TemporaryDirectory() as td:
   s,c,kw,events,clock,out=self.restored(td);cancel=[False];s.stop_requested=lambda:cancel[0]
   def observe():cancel[0]=True;raise r.Refused('observation unavailable')
   c.observe=observe;result=s.step();self.assertEqual(result['state'],'STOPPED');self.assertFalse(result['attempted_ids'])
 def test_only_observe_get_has_two_second_transport(self):
  calls=[]
  class Base:
   def __init__(self,endpoint,token,timeout):self.timeout=timeout
   def request(self,method,path,body=None):calls.append((method,path,self.timeout));return 'reply'
  t=cli.make_transport(Base,'http://127.0.0.1:38121','fake','profile','/r/');t.pool={'a'}
  t.request('GET','/r/observe');t.request('GET','/r/status?id=a');t.request('POST','/r/start',dict(profile='profile',id='a'));t.request('POST','/r/stop',dict(id='a'))
  self.assertEqual([v[2] for v in calls],[2.,5.,5.,5.])
  with self.assertRaises(ValueError):t.request('POST','/r/start',dict(profile='profile',id='a'))
  self.assertEqual(len(calls),4)
if __name__=='__main__':unittest.main(verbosity=2)

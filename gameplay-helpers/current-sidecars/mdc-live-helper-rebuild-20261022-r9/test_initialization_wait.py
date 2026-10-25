"""Read-only startup regression: no native requests or real ledger accesses."""
import copy,sys,unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE),str(HERE.parent/'MDC-RECOVERY-RESTORED-F1220-20261022T1433Z/C8-source/survival6-controller')]
import rebuilt_session as r
import run_recovery as c
OBS=dict(session='s',world_generation='w',player_uuid=r.PLAYER,bound_owner_id=r.OWNER)
class Tests(unittest.TestCase):
 def call(self,confirm,observations=None,stop=lambda:False):
  waits=[];created=[];times=[12.]
  def sleep(n):times[0]+=400.  # Exceeds old constructor deadline while no Session exists.
  def constructor(controller,**kw):
   self.assertEqual(kw['session_started_at'],times[0]);self.assertTrue(kw['confirm_world'](kw['initial_observation']))
   created.append(kw);return SimpleNamespace(label='new-session')
  def ready(*a,**kw):
   if stop():raise r.Gameplay('initialization_cancelled_before_session')
   return copy.deepcopy(next(observations) if observations is not None else OBS)
  with patch.object(r,'wait_ready',ready),patch.object(r,'RebuiltSession',constructor),patch.object(r,'run_existing',lambda s:s):
   result=r.run(object(),session_spec_raw=r.encode(dict(player_uuid=r.PLAYER)),confirm_world=confirm,on_initial_wait=waits.append,sleep=sleep,monotonic=lambda:times[0],stop_requested=stop)
  return result,waits,created
 def test_timeout_then_success_only_one_session_after_long_wait(self):
  calls=[]
  def confirm(o):
   calls.append(o)
   if len(calls)==1:raise r.InitializationWait('read-only timeout')
   return True
  result,waits,created=self.call(confirm)
  self.assertEqual(result.label,'new-session');self.assertEqual(len(calls),2);self.assertEqual(len(waits),1);self.assertEqual(len(created),1);self.assertEqual(created[0]['session_started_at'],412.)
 def test_wrong_identity_never_constructs_or_retries(self):
  calls=[]
  with self.assertRaises(r.Maintenance):self.call(lambda o:calls.append(o) or False)
  self.assertEqual(len(calls),1)
 def test_changed_context_after_confirmation_refused(self):
  changed=dict(OBS,world_generation='different')
  with self.assertRaisesRegex(r.Maintenance,'context_changed'):self.call(lambda o:True,iter([OBS,changed]))
 def test_explicit_cancel_during_read_only_wait_no_session(self):
  stop=[False]
  def confirm(o):stop[0]=True;raise r.InitializationWait('timeout')
  with self.assertRaises(r.Gameplay):self.call(confirm,stop=lambda:stop[0])
 def test_transport_timeout_and_connection_loss_transient_not_bad_identity(self):
  for error in (TimeoutError('timed out'),ConnectionResetError('closed'),c.http.client.IncompleteRead(b'')):
   with self.subTest(error=type(error).__name__),patch.object(c,'singleplayer_state',side_effect=[error,{'ok':True}]):
    with self.assertRaises(r.InitializationWait):c.initial_identity_read('http://127.0.0.1:38121','fake','/control/status',r.InitializationWait)
    self.assertEqual(c.initial_identity_read('http://127.0.0.1:38121','fake','/control/status',r.InitializationWait),{'ok':True})
  with patch.object(c,'singleplayer_state',side_effect=ValueError('identity mismatch')):
   with self.assertRaises(ValueError):c.initial_identity_read('http://127.0.0.1:38121','fake','/control/status',r.InitializationWait)
 def test_response_timeout_and_scheduling_quantum_are_separate(self):
  class Base:
   def __init__(self,endpoint,token,timeout):self.timeout=timeout
  t=c.make_transport(Base,'http://127.0.0.1:38121','fake','p','/r/')
  self.assertEqual(t.timeout,5.)
  self.assertEqual(t.scheduling_quantum,.5)
if __name__=='__main__':unittest.main(verbosity=2)

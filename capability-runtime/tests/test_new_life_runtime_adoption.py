"""Exact accepted receipt adopts only idle ephemeral Runtime cache state."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import tempfile,threading,time,unittest
from unittest.mock import patch
from mdc_skills.core import Runtime,Observation
from mdc_toolbox.runtime_adapter import OwnerRuntimeBackend
from mdc_toolbox import new_life_acknowledgment as lane
from resident_controller import new_life_acknowledgment as proof
import test_new_life_ack_fences as fences

class NewLifeRuntimeAdoptionTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.client=SimpleNamespace(_capability_owner=None,_capability_fault=None)
  self.runtime=Runtime(self.client,Path(self.tmp.name)/'runtime');self.backend=OwnerRuntimeBackend(self.runtime)
  maker=fences.NewLifeFenceTests();maker.setUp()
  try:
   maker.submit();maker.sample('one',12);maker.sample('two',13)
   self.receipt=deepcopy(maker.result());self.command=deepcopy(maker.command)
  finally:maker.tearDown()
  p=self.receipt['new_life_acknowledgment'];o=p['origin']['context']
  self.runtime._session_id='watchdog';self.runtime._context=tuple(o[k] for k in ('world_generation','dimension','player_uuid','action_session'))
  self.runtime._last_tick=11;self.runtime._preflight_request_id='old_read'
  self.runtime._last=Observation({'old':True},None,{'old':True},11,self.runtime._context,1.,'old_read','old_owner','fingerprint')
  self.runtime._navigation_binding=SimpleNamespace(seen=True)
  self.context={'life_command':self.command,'gateway_request_id':'ack','gateway_session':'watchdog','runtime_binding':lane.runtime_binding(self.runtime)}
  self.original_journal=deepcopy(self.runtime._journal);self.original_bytes=self.runtime._path.read_bytes()
 def tearDown(self):
  self.runtime._lease_active=False;self.runtime._job_control=None;self.runtime.close();self.tmp.cleanup()
 def outcome(self,receipt=None):return lane.outcome(self.backend,self.context,receipt or self.receipt)
 def assert_history(self):
  self.assertEqual(self.runtime._journal,self.original_journal);self.assertEqual(self.runtime._path.read_bytes(),self.original_bytes)
  self.assertTrue(self.runtime._navigation_binding.seen)
 def test_destination_adoption_invalidates_only_old_observation_authority(self):
  p=self.receipt['new_life_acknowledgment'];p['new_context'].update(world_generation='destination',dimension='minecraft:the_nether')
  result=self.outcome();self.assertEqual(result['state'],'succeeded');self.assertTrue(result['result']['runtime_context_adoption']['adopted'])
  self.assertEqual(self.runtime._context[:2],('destination','minecraft:the_nether'));self.assertEqual(self.runtime._last_tick,13)
  self.assertIsNone(self.runtime._last);self.assertIsNone(self.runtime._preflight_request_id);self.assert_history()
 def test_same_context_never_regresses_tick_floor(self):
  self.runtime._last_tick=99;self.context['runtime_binding']=lane.runtime_binding(self.runtime)
  self.assertEqual(self.outcome()['state'],'succeeded');self.assertEqual(self.runtime._last_tick,99);self.assert_history()
 def test_duplicate_original_is_noop_after_newer_job_and_unknown(self):
  self.assertEqual(self.outcome()['state'],'succeeded')
  self.runtime._job_generation+=1;self.runtime._owner='new_owner';self.runtime._context=('newer','elsewhere','player','session')
  self.runtime._last_tick=999;self.runtime._preflight_request_id='newer_preflight';self.backend._quarantined=True
  before=lane.runtime_binding(self.runtime);self.assertEqual(self.outcome()['state'],'succeeded')
  self.assertEqual(lane.runtime_binding(self.runtime),before);self.assertTrue(self.backend._quarantined);self.assert_history()
 def test_owner_context_tick_preflight_and_same_object_observation_mutations_refuse(self):
  mutations=(lambda r:setattr(r,'_owner','new_owner'),lambda r:setattr(r,'_job_generation',1),lambda r:setattr(r,'_context',('other',)*4),
   lambda r:setattr(r,'_last_tick',12),lambda r:setattr(r,'_preflight_request_id','other'),lambda r:r._last.raw.update(old=False),
   lambda r:setattr(r,'_last',deepcopy(r._last)),lambda r:setattr(r,'_last_observation_clock',{'changed':True}))
  for mutate in mutations:
   with self.subTest(mutate=mutate):
    self.tearDown();self.setUp();mutate(self.runtime);before=lane.runtime_binding(self.runtime)
    result=self.outcome();self.assertEqual(result['state'],'blocked');self.assertEqual(lane.runtime_binding(self.runtime),before)
    self.assertTrue(result['result']['new_life_acknowledgment']['rearmed']);self.assertEqual(result['evidence']['gateway_receipt'],self.receipt)
    self.assertEqual(result['effect_certainty'],'none_proven');self.assertEqual(result['cleanup_certainty'],'not_needed');self.assert_history()
 def test_owner_unknown_reacquisition_and_clock_barriers_are_not_cleared(self):
  mutations=(lambda:setattr(self.backend,'_active',{}),lambda:setattr(self.backend,'_quarantined',True),
   lambda:setattr(self.runtime,'_lease_active',True),lambda:setattr(self.runtime,'_job_control',object()),
   lambda:setattr(self.runtime,'_observation_reacquisition',object()),lambda:setattr(self.runtime,'_observation_clock_failed',True),
   lambda:setattr(self.runtime,'observation_clock_contract','client-pre-tick-v1'),lambda:setattr(self.client,'_capability_owner',{}),
   lambda:setattr(self.client,'_capability_fault','unknown'),lambda:self.runtime._journal.update(pending='unknown_original'))
  for mutate in mutations:
   with self.subTest(mutate=mutate):
    self.tearDown();self.setUp();mutate();before=lane.runtime_binding(self.runtime);journal=deepcopy(self.runtime._journal)
    result=self.outcome();self.assertEqual(result['state'],'blocked');self.assertEqual(lane.runtime_binding(self.runtime),before)
    self.assertEqual(self.runtime._journal,journal)
    self.runtime._journal['pending']=None
 def test_locks_do_not_wait_during_exact_read(self):
  self.backend._lock.acquire()
  try:
   start=time.monotonic();result=self.outcome();self.assertLess(time.monotonic()-start,.1);self.assertEqual(result['state'],'blocked')
  finally:self.backend._lock.release()
  ready=threading.Event();done=threading.Event()
  def hold():
   with self.runtime._mutex:ready.set();done.wait(2)
  thread=threading.Thread(target=hold);thread.start();ready.wait(1)
  try:
   start=time.monotonic();result=self.outcome();self.assertLess(time.monotonic()-start,.1);self.assertEqual(result['state'],'blocked')
  finally:done.set();thread.join(1)
  self.assert_history()
 def test_malformed_receipt_never_changes_cache(self):
  before=lane.runtime_binding(self.runtime)
  for edit in (lambda r:r.update(request_id='other'),lambda r:r['new_life_acknowledgment'].update(rearmed=1),
   lambda r:r['new_life_acknowledgment']['samples'][1].update(tick=True)):
   v=deepcopy(self.receipt);edit(v)
   with self.assertRaises(ValueError):self.outcome(v)
   self.assertEqual(lane.runtime_binding(self.runtime),before);self.assert_history()
 def test_newer_lifecycle_marker_prevents_older_receipt_rewind(self):
  self.runtime._new_life_adoption={'request_id':'newer','session_id':'watchdog','command_sha256':'different','defense_epoch':999}
  before=lane.runtime_binding(self.runtime);result=self.outcome()
  self.assertEqual(result['state'],'blocked');self.assertEqual(lane.runtime_binding(self.runtime),before);self.assert_history()
 def test_replaced_client_is_not_the_captured_runtime_binding(self):
  self.runtime.client=SimpleNamespace(_capability_owner=None,_capability_fault=None)
  before=lane.runtime_binding(self.runtime);self.assertEqual(self.outcome()['state'],'blocked')
  self.assertEqual(lane.runtime_binding(self.runtime),before);self.assert_history()
 def test_changed_valid_proof_for_same_original_is_not_reported_adopted(self):
  self.assertEqual(self.outcome()['state'],'succeeded');before=lane.runtime_binding(self.runtime)
  for edit in (lambda p:p['new_context'].update(world_generation='forged_destination'),
               lambda p:p.update(new_generation='55555555-5555-4555-8555-555555555555'),
               lambda p:p['samples'][1].update(tick=14)):
   v=deepcopy(self.receipt);edit(v['new_life_acknowledgment']);result=self.outcome(v)
   self.assertEqual(result['state'],'blocked');self.assertEqual(result['result']['runtime_context_adoption']['reason'],'original_receipt_conflict')
   self.assertEqual(lane.runtime_binding(self.runtime),before);self.assert_history()
 def test_blocked_local_adoption_can_reconcile_exact_original_without_submit(self):
  from mdc_toolbox.service import ToolboxService
  self.backend._lock.acquire()
  try:blocked=self.outcome()
  finally:self.backend._lock.release()
  self.assertEqual(blocked['state'],'blocked')
  record={'job_kind':'new_life_acknowledgment','dispatch_started':True,'state':'blocked','result':blocked['result'],
      'backend_context':deepcopy(self.context),'job_id':'job','request_ids':['ack']}
  applied=[];calls=[]
  service=SimpleNamespace(_lock=threading.RLock(),backend=self.backend,_lookup=lambda args:record,
      _public_job=lambda value:deepcopy(value),store=SimpleNamespace(get=lambda **kwargs:record),
      _apply=lambda *args:applied.append(args),_unknown=lambda *args:(_ for _ in ()).throw(AssertionError(args)))
  def read(rid):calls.append(rid);return deepcopy(self.receipt)
  self.client.result=read;self.client.submit=lambda *args,**kw:(_ for _ in ()).throw(AssertionError('resubmit'))
  ToolboxService._reconcile(service,{})
  self.assertEqual(calls,['ack']);self.assertEqual(applied[0][1]['state'],'succeeded');self.assert_history()
 def test_unrelated_blocked_controls_never_enter_new_life_reconciliation(self):
  from mdc_toolbox.service import ToolboxService
  original={'job_kind':'new_life_acknowledgment','dispatch_started':True,'state':'blocked','request_ids':['ack'],
      'result':{'new_life_acknowledgment':{'rearmed':True},'runtime_context_adoption':{'adopted':False,'gateway_request_id':'ack'}}}
  for edit in (lambda r:r.update(job_kind='mutation'),lambda r:r.update(job_kind='pause_acknowledgment'),
               lambda r:r['result']['new_life_acknowledgment'].update(rearmed=1),
               lambda r:r['result']['runtime_context_adoption'].update(adopted=True),
               lambda r:r['result']['runtime_context_adoption'].update(gateway_request_id='foreign')):
   record=deepcopy(original);edit(record)
   service=SimpleNamespace(_lock=threading.RLock(),_lookup=lambda args:record,_public_job=lambda v:deepcopy(v))
   with patch.object(lane,'exchange',side_effect=AssertionError('unrelated record lookup')):
    self.assertEqual(ToolboxService._reconcile(service,{}),record)
 def test_proven_blocked_receipt_survives_later_lookup_failures_and_conflicts(self):
  from mdc_toolbox.service import ToolboxService
  self.backend._lock.acquire()
  try:blocked=self.outcome()
  finally:self.backend._lock.release()
  record={'job_kind':'new_life_acknowledgment','dispatch_started':True,'state':'blocked','result':blocked['result'],
      'backend_context':deepcopy(self.context),'job_id':'job','request_ids':['ack'],'evidence':blocked['evidence']}
  conflict=deepcopy(self.receipt);conflict['new_life_acknowledgment']['new_context']['world_generation']='different'
  for reply in (None,{'bad':'receipt'},OSError('unavailable'),conflict):
   events=[];before=deepcopy(record);cache=lane.runtime_binding(self.runtime)
   def read(rid):
    if isinstance(reply,Exception):raise reply
    return deepcopy(reply)
   self.client.result=read
   service=SimpleNamespace(_lock=threading.RLock(),backend=self.backend,_lookup=lambda args:record,
       _public_job=lambda value:deepcopy(value),store=SimpleNamespace(get=lambda **kwargs:record,save=lambda *args:events.append(args)),
       _apply=lambda *args:(_ for _ in ()).throw(AssertionError('changed known result')),
       _unknown=lambda *args:(_ for _ in ()).throw(AssertionError('lost known proof')))
   self.assertEqual(ToolboxService._reconcile(service,{}),before);self.assertEqual(record,before)
   self.assertEqual(lane.runtime_binding(self.runtime),cache);self.assertEqual(len(events),1);self.assert_history()
 def test_lost_reply_exact_lookup_adopts_without_submit(self):
  self.client.result=lambda rid:deepcopy(self.receipt)
  self.client.submit=lambda *a,**kw:(_ for _ in ()).throw(AssertionError('replayed original'))
  result=lane.exchange(self.backend,self.context,read_only=True);self.assertEqual(result['state'],'succeeded');self.assert_history()
 def test_shutdown_first_reader_pins_before_worker_adoption_lock(self):
  pinned=threading.Event();locked=threading.Event();outputs={};errors=[]
  different=deepcopy(self.receipt);different['new_life_acknowledgment']['new_context']['world_generation']='conflicting'
  before=lane.runtime_binding(self.runtime)
  def worker():
   try:
    with self.backend._lock:
     locked.set();self.assertTrue(pinned.wait(2))
     outputs['worker']=lane.outcome(self.backend,deepcopy(self.context),different,backend_locked=True)
   except BaseException as e:errors.append(e)
  thread=threading.Thread(target=worker);thread.start();self.assertTrue(locked.wait(2))
  try:
   outputs['shutdown']=self.outcome();pinned.set();thread.join(2)
   self.assertFalse(thread.is_alive());self.assertEqual(errors,[])
   self.assertEqual(outputs['shutdown']['result']['runtime_context_adoption']['reason'],'runtime_backend_busy')
   self.assertEqual(outputs['worker']['result']['runtime_context_adoption']['reason'],'original_receipt_conflict')
   self.assertEqual(outputs['worker']['evidence']['gateway_receipt'],self.receipt)
   self.assertEqual(lane.runtime_binding(self.runtime),before)
   self.assertEqual(self.outcome()['state'],'succeeded');self.assert_history()
  finally:pinned.set();thread.join(2)
 def test_first_receipt_copy_is_immutable_and_full_receipt_is_bound(self):
  self.backend._lock.acquire();original=deepcopy(self.receipt)
  try:result=self.outcome()
  finally:self.backend._lock.release()
  result['evidence']['gateway_receipt']['new_life_acknowledgment']['new_context']['world_generation']='consumer_mutation'
  different=deepcopy(original);different['unexpected_metadata']='changed'
  refused=self.outcome(different)
  self.assertEqual(refused['result']['runtime_context_adoption']['reason'],'original_receipt_conflict')
  self.assertEqual(refused['evidence']['gateway_receipt'],original)
  self.assertEqual(self.outcome()['state'],'succeeded');self.assert_history()
 def test_late_blocked_unknown_and_conflicting_results_cannot_downgrade_adoption(self):
  from mdc_toolbox.service import ToolboxService
  self.backend._lock.acquire()
  try:blocked=self.outcome()
  finally:self.backend._lock.release()
  succeeded=self.outcome();self.assertEqual(succeeded['state'],'succeeded')
  service=ToolboxService(self.backend,Path(self.tmp.name)/'toolbox',start_workers=False)
  record={'job_id':'life_job','request_id':'life_public','job_kind':'new_life_acknowledgment',
      'backend_context':deepcopy(self.context),**deepcopy(succeeded)}
  service.store.create(record)
  conflict=deepcopy(succeeded)
  for part in (conflict['result']['new_life_acknowledgment'],conflict['evidence']['gateway_receipt']['new_life_acknowledgment']):
   part['new_context']['world_generation']='different'
  try:
   for incoming in (blocked,{'state':'unknown','effect_certainty':'none_proven','cleanup_certainty':'unknown'},conflict):
    with service._lock:service._apply('life_job',incoming,'new_life_ack_shutdown_read')
    saved=service.store.get(job_id='life_job')
    self.assertEqual(saved['state'],'succeeded');self.assertEqual(saved['result'],succeeded['result'])
    self.assertEqual(saved['evidence'],succeeded['evidence'])
   with service._lock:service._unknown('life_job','late lookup failed','shutdown_unknown')
   saved=service.store.get(job_id='life_job');self.assertEqual(saved['state'],'succeeded')
   self.assertEqual(saved['result'],succeeded['result']);self.assertEqual(saved['evidence'],succeeded['evidence'])
   self.assert_history()
  finally:service.store.close()

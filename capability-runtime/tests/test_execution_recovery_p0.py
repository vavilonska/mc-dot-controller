"""P0 recovery regressions: production Runtime/service, synthetic transport only."""
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from mdc_skills.core import Runtime, SkillError
from mdc_toolbox import ToolboxService, ToolboxResponseError, check_response
from mdc_toolbox.control import JobControl
from mdc_toolbox.runtime_adapter import OwnerRuntimeBackend
from mdc_toolbox.__main__ import serve
from support_core import Clock, move, arrived
from test_runtime_ownership import LeaseClient


class ReadLeaseClient(LeaseClient):
    def __init__(self, clock, directory):
        super().__init__(clock, directory)
        self.lose_release = False
        self.lose_read = False
        self.heartbeat_stops = []
        self.reconcile_reads = []
    def session(self):
        return {**super().session(), 'private_singleplayer': True,
                'execution_policy': 'noncombat', 'capability_cancel_schema_version': 1}
    def release_capability(self, *args, **kwargs):
        if self.lose_release:self.fault = True
        return super().release_capability(*args, **kwargs)
    def result(self, request_id):
        self.reconcile_reads.append(request_id)
        if request_id not in self.results:return None
        if self.lose_read:raise OSError('synthetic read receipt lost')
        return super().result(request_id)
    def stop_capability_heartbeat(self, owner):self.heartbeat_stops.append(owner)


class ObservationRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.clock = Clock()
        self.client = ReadLeaseClient(self.clock, self.root/'runtime')
        self.runtime = Runtime(self.client, self.root/'runtime', clock=self.clock, sleeper=self.clock.sleep)
        self.backend = OwnerRuntimeBackend(self.runtime)
        self.service = ToolboxService(self.backend, self.root/'service')
        self.session = self.backend.describe()['session_ref']
    def tearDown(self):
        self.service.shutdown(timeout=.05)
        self.runtime.close()
        self.temp.cleanup()
    def observe(self, **extra):
        return self.service.call('mdc_observe', {'api_version':'mdc.toolbox/1','session_ref':self.session,
             'profile':'inventory','request_id':'read-once',**extra})
    def status(self, response):
        return self.service.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'status',
             'session_ref':self.session,'job_id':response['job_id']})
    def assert_no_second_owner(self, response):
        original_calls=deepcopy(self.client.calls)
        original_controls=deepcopy(self.client.controls)
        duplicate=self.observe()
        self.assertEqual(duplicate['job_id'],response['job_id'])
        other=self.observe(request_id='other-read')
        self.assertEqual(other['error']['code'],'owner_busy')
        cancelled=self.service.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'cancel',
             'session_ref':self.session,'job_id':response['job_id'],'cancel_request_id':'cancel-read'})
        self.assertEqual(cancelled['state'],'unknown')
        reconciled=self.service.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'reconcile',
             'session_ref':self.session,'job_id':response['job_id']})
        self.assertEqual(reconciled['state'],'unknown')
        self.assertEqual(reconciled['request_ids'],response['request_ids'])
        self.assertEqual(self.client.calls,original_calls)
        self.assertEqual(self.client.controls,original_controls)
        return original_calls,original_controls
    def test_successful_observation_is_durable_and_preserves_flat_native_payload(self):
        response=self.observe()
        self.assertIsInstance(response['state'],dict)
        self.assertEqual(response['job_request_id'],'read-once')
        self.assertEqual(response['job_state'],'succeeded')
        self.assertEqual(response['cleanup_certainty'],'confirmed')
        record=self.status(response)
        self.assertEqual(record['state'],'succeeded')
        self.assertEqual(record['request_id'],'read-once')
        self.assertEqual(record['result']['request_id'],response['request_id'])
        self.assertEqual(len(record['request_ids']),4)
        self.assertIsNone(self.backend._active)
        self.assertFalse(self.backend._quarantined)
        self.assertIsNone(self.client.lease)
        count=len(self.client.calls)
        self.assertEqual(self.observe(),response)
        self.assertEqual(len(self.client.calls),count)
        self.assertTrue(self.service.shutdown()['cleanup_confirmed'])
    def test_release_lost_keeps_job_owner_ids_and_shutdown_unknown(self):
        self.client.lose_release=True
        response=self.observe()
        self.assertEqual(response['state'],'unknown',response)
        self.assertEqual(response['cleanup_certainty'],'unknown')
        self.assertEqual(response['request_id'],'read-once')
        self.assertEqual(len(response['request_ids']),4)
        self.assertIsNotNone(response['result'])
        self.assertTrue(self.backend._quarantined)
        self.assertEqual(self.backend._active['context']['job_id'],response['job_id'])
        self.assertEqual(response['context']['owner_context']['original_request_ids'],response['request_ids'])
        calls,controls=self.assert_no_second_owner(response)
        stopped=self.service.shutdown()
        self.assertEqual(stopped,{'cleanup_confirmed':False,'unresolved_job_ids':[response['job_id']]})
        self.service=ToolboxService(self.backend,self.root/'service')
        reopened=self.status(response)
        self.assertEqual(reopened['state'],'unknown')
        self.assertEqual(reopened['request_ids'],response['request_ids'])
        self.assertEqual(self.client.calls,calls)
        self.assertEqual(self.client.controls,controls)
    def test_acquire_lost_is_one_unknown_job_without_observation_replay(self):
        self.client.fault=True
        response=self.observe()
        self.assertEqual(response['state'],'unknown')
        self.assertEqual(len(response['request_ids']),1)
        self.assertEqual(self.client.calls,[])
        self.assertEqual(len(self.client.controls),1)
        self.assert_no_second_owner(response)
        self.assertFalse(self.service.shutdown()['cleanup_confirmed'])
    def test_read_lost_has_exact_identity_and_no_release_retry(self):
        self.client.lose_read=True
        response=self.observe()
        self.assertEqual(response['state'],'unknown')
        self.assertEqual(len(response['request_ids']),2)
        self.assertEqual(len(self.client.controls),1)
        self.assert_no_second_owner(response)
    def test_shutdown_during_read_is_bounded_and_persists_original_job(self):
        entered=threading.Event();unblock=threading.Event()
        capture=self.backend._capture_observation
        def blocked_capture(*args):
            value=capture(*args)
            entered.set();unblock.wait(2)
            return value
        self.backend._capture_observation=blocked_capture
        replies=[]
        worker=threading.Thread(target=lambda:replies.append(self.observe()))
        worker.start()
        self.assertTrue(entered.wait(1))
        record=self.service.store.get(request_id='read-once')
        self.assertEqual(len(record['request_ids']),2)
        started=time.monotonic()
        stopped=self.service.shutdown(timeout=.03)
        self.assertLess(time.monotonic()-started,.5)
        self.assertFalse(stopped['cleanup_confirmed'])
        self.assertEqual(stopped['unresolved_job_ids'],[record['job_id']])
        calls=deepcopy(self.client.calls)
        unblock.set();worker.join(1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(replies[0]['state'],'unknown')
        self.assertEqual(replies[0]['request_ids'],record['request_ids'])
        self.assertEqual(self.client.calls,calls)
        self.service=ToolboxService(self.backend,self.root/'service')
        reopened=self.status(record)
        self.assertEqual(reopened['state'],'unknown')
        self.assertEqual(reopened['request_ids'],record['request_ids'])
    def test_request_conflict_error_keeps_original_job_identity(self):
        original=self.observe()
        conflict=self.observe(profile='player')
        self.assertEqual(conflict['error']['code'],'request_conflict')
        self.assertEqual(conflict['job_id'],original['job_id'])
        self.assertEqual(conflict['request_id'],'read-once')
        self.assertEqual(conflict['request_ids'],original['request_ids'])
    def test_post_admission_error_keeps_generated_identity_without_mutating_input(self):
        args={'api_version':'mdc.toolbox/1','session_ref':self.session,'profile':'inventory'}
        def fail_after_admission(record):raise ValueError('synthetic serialization failure')
        self.service._observation_response=fail_after_admission
        result=self.service.call('mdc_observe',args)
        self.assertEqual(result['error']['code'],'internal_error')
        self.assertTrue(result['job_id'].startswith('job_'))
        self.assertTrue(result['request_id'].startswith('observe_'))
        self.assertEqual(len(result['request_ids']),4)
        self.assertNotIn('request_id',args)
        self.assertEqual(self.status(result)['state'],'succeeded')

    def test_shutdown_between_worker_completion_and_reply_keeps_observation(self):
        service=self.service
        original_lock=service._lock
        stopped=threading.Event();resume=threading.Event()
        class DeliveryGapLock:
            armed=True
            def __enter__(self):original_lock.acquire();return self
            def __exit__(self,*args):
                gap=(self.armed and threading.current_thread().name=='observer'
                     and not service._workers and len(service.store.all())==1)
                if gap:self.armed=False
                original_lock.release()
                if gap:stopped.set();self_outer.assertTrue(resume.wait(2))
        self_outer=self
        service._lock=DeliveryGapLock()
        replies=[]
        worker=threading.Thread(name='observer',target=lambda:replies.append(self.observe()))
        worker.start();self.assertTrue(stopped.wait(2))
        record=service.store.get(request_id='read-once')
        self.assertEqual(record['state'],'succeeded')
        shutdown=service.shutdown(.05)
        self.assertTrue(shutdown['cleanup_confirmed'])
        resume.set();worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(replies[0]['job_id'],record['job_id'])
        self.assertEqual(replies[0]['job_state'],'succeeded')
        self.assertEqual(replies[0]['cleanup_certainty'],'confirmed')
        self.assertEqual(replies[0]['request_ids'],record['request_ids'])

    def test_public_error_checker_retains_full_unknown_envelope(self):
        self.client.lose_release=True
        response=self.observe()
        with self.assertRaises(ToolboxResponseError) as caught:check_response(response)
        error=caught.exception
        self.assertEqual(error.job_id,response['job_id'])
        self.assertEqual(error.request_id,'read-once')
        self.assertEqual(error.request_ids,tuple(response['request_ids']))
        self.assertEqual(error.response,response)
        response['request_ids'].clear()
        self.assertEqual(len(error.request_ids),4)
        self.assertEqual(len(error.response['request_ids']),4)


class LastOwnerCheckpointFreshnessTests(unittest.TestCase):
    def run_case(self, mode):
        with tempfile.TemporaryDirectory() as directory:
            clock=Clock();client=ReadLeaseClient(clock,directory)
            runtime=Runtime(client,directory,clock=clock,sleeper=clock.sleep)
            control=JobControl({'job_id':'owner-job','request_id':'owner-request','deadline_at':time.time()+30,
                                'budget':{'max_actions':3,'max_observations':8,'cleanup_reserve_actions':1}})
            runtime.begin_job(control)
            before=runtime.observe()
            original=deepcopy(before.raw);captured=before.captured_at
            owner_check=control.owner_check
            calls=[]
            def blocking_owner_check():
                owner_check()
                record=runtime._journal['records'].get(runtime.pending_request_id,{})
                if record.get('kind')=='mutation' and record.get('status')=='reserved':
                    # _reserve invokes consume before reserving. This hook is
                    # the final _exchange owner checkpoint after existing TTL.
                    calls.append(record['request_id'])
                    if mode=='age':clock.now=captured+.801
                    elif mode=='reverse':clock.now=captured-.001
                    elif mode=='cancel':control.cancel_event.set()
                    elif mode=='deadline':control.budget.deadline=control.budget.clock()-1
            control.owner_check=blocking_owner_check
            try:
                outcome=runtime.execute('move',move(),arrived,before=before)
                self.assertEqual(len(calls),1)
                self.assertEqual(client.action_count,0)
                self.assertEqual(before.raw,original)
                self.assertEqual(before.captured_at,captured)
                self.assertFalse(runtime.has_unresolved_execution)
                self.assertEqual(runtime._job_effect_certainty,'none_proven')
                record=runtime._journal['records'][calls[0]]
                self.assertEqual(record['evidence']['submission_outcome'],'stopped_before_dispatch')
                expected={'age':'preflight_observation_stale','reverse':'preflight_observation_stale',
                          'cancel':'cancel_requested','deadline':'original_deadline_elapsed'}[mode]
                self.assertEqual(outcome.reason,expected)
                self.assertEqual(record['reason'],expected)
            finally:runtime.finish_job();runtime.close()
    def test_age_expiry_inside_final_owner_io_blocks(self):self.run_case('age')
    def test_reversed_clock_inside_final_owner_io_blocks(self):self.run_case('reverse')
    def test_cancel_inside_final_owner_io_blocks(self):self.run_case('cancel')
    def test_deadline_inside_final_owner_io_blocks(self):self.run_case('deadline')


class OversizedResponseIdentityTests(unittest.TestCase):
    def test_transport_size_error_retains_original_job_id(self):
        class Service:
            shutdown_result={'cleanup_confirmed':False,'unresolved_job_ids':['job_original']}
            def call(self,*args):return {'api_version':'mdc.toolbox/1','job_id':'job_original','request_id':'request_original',
                 'session_ref':'session_original','request_ids':['native_original'],'state':'unknown',
                 'cleanup_certainty':'unknown','effect_certainty':'known','continuation':'reconcile_original_id_required',
                 'error':{'code':'outcome_unknown'},'result':{'padding':'x'*(1024*1024)}}
            def shutdown(self):return self.shutdown_result
        source=io.BytesIO(b'{"id":"tb_1","tool":"mdc_job","arguments":{}}\n');sink=io.BytesIO()
        serve(Service(),source,sink)
        envelope=json.loads(sink.getvalue())
        self.assertEqual(envelope['id'],'tb_1')
        result=envelope['result']
        self.assertEqual(result['job_id'],'job_original')
        self.assertEqual(result['request_id'],'request_original')
        self.assertEqual(result['request_ids'],['native_original'])
        self.assertEqual(result['state'],'unknown')
        self.assertEqual(result['effect_certainty'],'known')
        self.assertEqual(result['error']['code'],'response_too_large')
        with self.assertRaises(ToolboxResponseError) as caught:check_response(result)
        self.assertEqual(caught.exception.job_id,'job_original')


if __name__=='__main__':unittest.main()

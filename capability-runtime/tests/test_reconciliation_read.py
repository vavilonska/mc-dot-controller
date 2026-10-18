"""Public diagnostic owner-chain while UNKNOWN; real mailboxes, synthetic native GET."""
from copy import deepcopy
import json
from pathlib import Path
import time
import unittest
from unittest.mock import patch
import base_watchdog
import test_capability_ownership as owners
from test_compact_observation import CompactEndpoint,wire
from mdc_skills.core import Runtime
from mdc_toolbox import ToolboxService
from mdc_toolbox.runtime_adapter import OwnerRuntimeBackend
from reconciliation_read import validate,MAX_RECORDS

class ReconciliationTests(unittest.TestCase):
    until=owners.ActualGatewayOwnershipTests.until
    def setUp(self):
        wire()
        original=base_watchdog.run
        def request_only(*a,**k):return original(*a,**{**k,'execution_policy':'request_only'})
        with patch.object(owners,'CombatEndpoint',CompactEndpoint),patch.object(base_watchdog,'run',request_only):
            owners.ActualGatewayOwnershipTests.setUp(self)
        self.runtime=Runtime(self.client,self.root/'runtime',wait_timeout=1)
        self.backend=OwnerRuntimeBackend(self.runtime)
        self.service=ToolboxService(self.backend,self.root/'jobs')
        self.session_ref=self.backend.describe()['session_ref']
        # Register a real durable observation and then model its UNKNOWN result.
        prior=self.service.call('mdc_observe',{'api_version':'mdc.toolbox/1','session_ref':self.session_ref,'request_id':'original','profile':'compact'})
        self.assertEqual(prior['job_state'],'succeeded',prior)
        self.job_id=prior['job_id'];record=self.service.store.get(job_id=self.job_id)
        record.update(state='unknown',effect_certainty='unknown',cleanup_certainty='unknown',continuation='reconcile_original_id_required')
        self.service.store.save(record)
        self.original=deepcopy(self.service.store.get(job_id=self.job_id));self.bridge.compact_reads.clear()
        self.backend._quarantined=True;self.client._capability_fault='synthetic_original_heartbeat_unknown'
        self.dog.handoff_latched=True;self.dog.attention('synthetic_original_unknown')
        self.resident.paused=True;self.resident.reason='synthetic_original_unknown'
        self.until(lambda:self.client.reconciliation_session().get('state')=='paused')
        self.posts=len(self.bridge.posts)
    def tearDown(self):
        self.client._capability_fault=None
        self.service.close();self.runtime.close()
        owners.ActualGatewayOwnershipTests.tearDown(self)
    def read(self,request='read-one',**overrides):
        args={'api_version':'mdc.toolbox/1','profile':'reconciliation','session_ref':self.session_ref,
            'request_id':request,'original_job_id':self.job_id}
        args.update(overrides)
        return self.service.call('mdc_observe',args)
    def assert_original(self):
        self.assertEqual(self.service.store.get(job_id=self.job_id),self.original)
        self.assertTrue(self.backend._quarantined)
        self.assertEqual(self.client._capability_fault,'synthetic_original_heartbeat_unknown')
        self.assertTrue(self.dog.handoff_latched)
        self.assertEqual(len(self.bridge.posts),self.posts)
    def test_public_unknown_owner_can_read_without_settlement_or_lease(self):
        result=self.read();self.assertEqual(result.get('diagnostic',{}).get('state'),'succeeded',result)
        self.assertTrue(result['lease_free']);self.assertFalse(result['settles_original'])
        self.assertEqual(result['original_before']['job_id'],self.job_id)
        self.assertEqual(result['original_before']['state'],'unknown')
        self.assertIn('external_controller',result['diagnostic']['result']['compact'])
        self.assertIn('native_fall_rescue_status',result['diagnostic']['result']['compact'])
        self.assertEqual(len(self.bridge.compact_reads),1)
        again=self.read();self.assertEqual(again['diagnostic']['request_digest'],result['diagnostic']['request_digest'])
        self.assertEqual(len(self.bridge.compact_reads),1);self.assert_original()
        denied=self.service.call('mdc_observe',{'api_version':'mdc.toolbox/1','profile':'compact','request_id':'not-a-read','session_ref':self.session_ref})
        self.assertEqual(denied['error']['code'],'owner_busy')
    def test_failed_native_read_never_cancels_or_releases_original(self):
        self.bridge.mode_name='lost'
        result=self.read();self.assertEqual(result['diagnostic']['state'],'unknown',result)
        self.assertEqual(len(self.bridge.compact_reads),1);self.read();self.assertEqual(len(self.bridge.compact_reads),1)
        self.assert_original()
    def test_page_ahead_remains_diagnostic_unknown_without_guard_relaxation(self):
        self.bridge.mode_name='page_ahead';result=self.read()
        self.assertEqual(result['diagnostic']['state'],'unknown',result);self.assert_original()
    def test_closed_public_scope_and_original_identity(self):
        for overrides in ({'original_job_id':'other'},{'bounds':{'radius':2}},{'selectors':{'query':'mutate'}},
                          {'acquisition_profile':'x'},{'wait_ms':10},{'request_id':'original'}):
            with self.subTest(overrides=overrides):self.assertIn('error',self.read(**overrides))
        self.assertEqual(self.bridge.compact_reads,[]);self.assert_original()
    def test_old_job_context_can_be_compared_with_new_gateway_without_settlement(self):
        record=self.service.store.get(job_id=self.job_id);record['session_ref']='old-retained-session'
        self.service.store.save(record);self.original=deepcopy(self.service.store.get(job_id=self.job_id))
        result=self.read(session_ref='old-retained-session')
        self.assertEqual(result['diagnostic']['state'],'succeeded',result)
        self.assertTrue(result['diagnostic']['session_changed'])
        self.assertEqual(result['diagnostic']['original_session_ref'],'old-retained-session')
        self.assertEqual(result['original_after']['state'],'unknown');self.assert_original()
    def test_same_query_id_cannot_bind_another_original_job(self):
        first=self.read();self.assertEqual(first['diagnostic']['state'],'succeeded')
        other=deepcopy(self.original);other.update(job_id='job_other',request_id='other-original',event_cursor=0)
        self.service.store.create(other)
        result=self.read(original_job_id='job_other')
        self.assertEqual(result['diagnostic']['reason'],'reconciliation_id_conflict',result)
        self.assertEqual(len(self.bridge.compact_reads),1);self.assert_original()

    def test_mailbox_capacity_failure_is_explicit_and_preserves_evidence(self):
        root=self.client.root/'reconciliation'/'results';root.mkdir(parents=True,exist_ok=True)
        for i in range(MAX_RECORDS):(root/(str(i)+'.json')).write_text('{}')
        result=self.read();self.assertEqual(result['diagnostic']['reason'],'reconciliation_history_full')
        self.assertEqual(len(list(root.glob('*.json'))),MAX_RECORDS);self.assertEqual(self.bridge.compact_reads,[]);self.assert_original()

class ReconciliationNodeTests(unittest.TestCase):
    import test_route_local_frontdoor as route
    until=route.RouteLocalFrontdoorTests.until
    rpc=route.RouteLocalFrontdoorTests.rpc
    call=route.RouteLocalFrontdoorTests.call
    finish=route.RouteLocalFrontdoorTests.finish
    submit=route.RouteLocalFrontdoorTests.submit
    def setUp(self):
        wire()
        with patch.object(self.route,'Endpoint',CompactEndpoint):self.route.RouteLocalFrontdoorTests.setUp(self)
    def tearDown(self):self.route.RouteLocalFrontdoorTests.tearDown(self)
    def test_lost_second(self):
        original=self.finish(self.submit());self.assertEqual(original['state'],'unknown',original)
        self.expected_mcp_exit=2;posts=deepcopy(self.bridge.posts)
        args={'api_version':'mdc.toolbox/1','profile':'reconciliation','request_id':'diagnose-original',
            'session_ref':original['session_ref'],'original_job_id':original['job_id']}
        result=self.call('mdc_observe',args)
        self.assertEqual(result.get('diagnostic',{}).get('state'),'succeeded',result)
        self.assertEqual(result['original_before']['state'],'unknown')
        self.assertEqual(result['original_after']['state'],'unknown')
        self.assertEqual(self.bridge.posts,posts)
        self.assertEqual(len(self.bridge.compact_reads),1)
        again=self.call('mdc_observe',args);self.assertEqual(again['diagnostic']['request_digest'],result['diagnostic']['request_digest'])
        self.assertEqual(len(self.bridge.compact_reads),1);self.assertEqual(self.bridge.posts,posts)
        status=self.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'status',
            'session_ref':original['session_ref'],'job_id':original['job_id']})
        self.assertEqual(status['state'],'unknown');self.assertEqual(status['request_ids'],original['request_ids'])

if __name__=='__main__':unittest.main()

"""Bounded failure evidence crosses real immutable mailboxes without owner settlement."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs,urlsplit
import json,os,tempfile,time,unittest
import reconciliation_read as gateway
from resident_controller import reconciliation_read as resident_read
from resident_controller.controller import Resident
from resident_controller.ipc import QueueClient,atomic_json,read_json
from resident_controller.transport import BridgeError
from test_compact_read_cost import diagnostic
from test_reconciliation_read import ReconciliationTests


def cost(rid):
    value=diagnostic();value['request_id']=rid;return value

class ReconciliationFailureEvidence(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.gr=self.root/'gateway';rr=self.root/'resident'
        for f in ('inbox','working','results'):(rr/f).mkdir(parents=True)
        self.resident=Resident(SimpleNamespace(),rr);self.resident.session_id='resident';self.resident.paused=True;self.resident.reason='original_unknown'
        self.original=rr/'results/original.json';atomic_json(self.original,{'request_id':'original','status':'uncertain','native_action_id':'old-action'})
        self.original_bytes=self.original.read_bytes();self.q=QueueClient(rr)
        atomic_json(self.gr/'state.json',{'implementation':'native-defense-watchdog-v5','reconciliation_read_profile':gateway.VERSION,'session_id':'gateway','updated_at':time.time()})
        self.client=SimpleNamespace(root=self.gr);self.commands=[]
        def submit(command,request_id=None):self.commands.append({**command,'request_id':request_id,'session_id':'resident'});return request_id
        self.dog=SimpleNamespace(session_id='gateway',q=SimpleNamespace(session=lambda:{'session_id':'resident'},submit=submit,reconciliation_result=self.q.reconciliation_result),capability_lease={'owner_id':'old-owner'},handoff_latched=True)
        self.request=gateway.submit(self.client,'query-one','gateway','old-job');gateway.tick(self.dog,self.gr);self.command=self.commands[0]
    def tearDown(self):self.tmp.cleanup()
    def failure(self,diagnostic_value=None,status='reported'):
        d=cost(self.command['request_id']) if diagnostic_value is None else diagnostic_value
        error=BridgeError('compact_observation_budget_exhausted',status=409,compact_observation_diagnostic=d,compact_observation_diagnostic_status=status)
        self.resident.command_error(self.command,error)
        return self.q.reconciliation_result(self.command['request_id'])
    def result(self):gateway.tick(self.dog,self.gr);return gateway.result(self.client,self.request)
    def preserved(self):
        self.assertEqual(self.original.read_bytes(),self.original_bytes);self.assertEqual(self.resident.reason,'original_unknown');self.assertTrue(self.resident.paused)
        self.assertTrue(self.dog.handoff_latched);self.assertEqual(self.dog.capability_lease,{'owner_id':'old-owner'});self.assertEqual(len(self.commands),1)
    def test_same_request_cost_reaches_public_mailbox_without_settlement(self):
        resident=self.failure();result=self.result();d=cost(self.command['request_id'])
        self.assertEqual(resident['diagnostic_request_digest'],gateway.digest(self.request));self.assertEqual(result['request'],self.request)
        self.assertEqual(result['request_digest'],gateway.digest(self.request));self.assertEqual(result['compact_observation_diagnostic'],d)
        self.assertEqual(result['read_failure_reason'],'compact_observation_budget_exhausted');self.assertEqual(result['state'],'unknown')
        self.assertFalse(result['execution_authority']);self.assertFalse(result['settles_original']);self.preserved()
        before=(gateway.folders(self.gr)/'results/query-one.json').read_bytes();self.resident.command_error(self.command,ValueError('late_error'))
        gateway.tick(self.dog,self.gr);self.assertEqual((gateway.folders(self.gr)/'results/query-one.json').read_bytes(),before);self.preserved()
    def test_foreign_or_contradictory_cost_is_explicit_invalid(self):
        self.failure(cost('another-query'));result=self.result()
        self.assertNotIn('compact_observation_diagnostic',result);self.assertEqual(result['compact_observation_diagnostic_status'],'invalid');self.preserved()
        for key,value in [('request_id','foreign'),('terrain_elapsed_nanos','9000001'),('callback_budget_nanos','999999999')]:
            bad=cost(self.command['request_id']);bad[key]=value
            out=resident_read.failure_fields({'compact_observation_diagnostic':bad,'compact_observation_diagnostic_status':'reported'},self.command['request_id'])
            self.assertEqual(out,{'compact_observation_diagnostic_status':'invalid'})
    def test_foreign_resident_reply_cannot_smuggle_cost(self):
        reply=self.failure();reply['diagnostic_request_digest']='f'*64
        self.dog.q.reconciliation_result=lambda rid:reply
        result=self.result();self.assertNotIn('compact_observation_diagnostic',result);self.assertNotIn('read_failure_reason',result);self.preserved()
    def test_reread_normalizes_tampered_same_file_without_rewriting_history(self):
        self.failure();self.result();p=gateway.folders(self.gr)/'results/query-one.json';value=read_json(p)
        value['compact_observation_diagnostic']['request_id']='foreign';atomic_json(p,value);before=p.read_bytes()
        result=gateway.result(self.client,self.request);self.assertEqual(result['compact_observation_diagnostic_status'],'invalid')
        self.assertNotIn('compact_observation_diagnostic',result);self.assertEqual(p.read_bytes(),before);self.preserved()
    def test_reason_and_missing_status_are_bounded(self):
        self.assertEqual(resident_read.failure_fields({'read_failure_reason':'x'*101},self.command['request_id']),{'compact_observation_diagnostic_status':'missing'})
        self.assertEqual(resident_read.failure_fields({'compact_observation_diagnostic_status':{'unexpected':'value'}},self.command['request_id']),{'compact_observation_diagnostic_status':'invalid'})

class PublicUnknownFailureEvidence(unittest.TestCase):
    until=ReconciliationTests.until
    setUp=ReconciliationTests.setUp
    tearDown=ReconciliationTests.tearDown
    read=ReconciliationTests.read
    assert_original=ReconciliationTests.assert_original
    def test_original_job_unknown_stays_unchanged_with_cost_visible(self):
        original_request=self.bridge.request
        def request(method,path,body=None):
            if path.startswith('/control/compact-observation?'):
                self.bridge.compact_reads.append(path);rid=parse_qs(urlsplit(path).query)['request_id'][0]
                raise BridgeError('compact_observation_budget_exhausted',status=409,compact_observation_diagnostic=cost(rid),compact_observation_diagnostic_status='reported')
            return original_request(method,path,body)
        self.bridge.request=request
        value=self.read();d=value['diagnostic']
        self.assertEqual(d['state'],'unknown');self.assertEqual(d['compact_observation_diagnostic_status'],'reported')
        self.assertEqual(d['compact_observation_diagnostic']['request_id'],d['queue_request_id'])
        self.assertFalse(value['settles_original']);self.assertEqual(len(self.bridge.compact_reads),1);self.assert_original()
        again=self.read();self.assertEqual(again['diagnostic']['request_digest'],d['request_digest']);self.assertEqual(len(self.bridge.compact_reads),1);self.assert_original()

if __name__=='__main__':unittest.main()

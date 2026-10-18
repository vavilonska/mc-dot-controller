"""Production boundary regressions: original deadlines and isolated retention."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch
import reconciliation_read as gateway
from resident_controller import reconciliation_read as diagnostic
from resident_controller import controller
from resident_controller.ipc import QueueClient,atomic_json,read_json

class ResidentBoundaries(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.gets=[]
        for f in ('inbox','working','results'):(self.root/f).mkdir()
        bridge=SimpleNamespace(request=lambda *a:self.gets.append(a) or {'control':{'private_singleplayer':True}})
        self.resident=controller.Resident(bridge,self.root);self.resident.session_id='resident';self.resident.publish=lambda:None
        self.resident.bridge_identity={};self.resident.observation_policy=lambda:{}
        self.client=QueueClient(self.root)
        atomic_json(self.root/'session.json',{'session_id':'resident','state':'paused'})
        self.original=self.root/'results/original-execution.json'
        atomic_json(self.original,{'request_id':'original-execution','status':'succeeded','native_action_id':'original-native'})
        self.original_bytes=self.original.read_bytes()
    def tearDown(self):self.tmp.cleanup()
    def command(self,name='query'):
        now=time.time();r={'schema_version':1,'op':'reconciliation_observe','request_id':name,'watchdog_session':'gateway',
            'original_job_id':'old-job','created_at':now,'expires_at':now+5,'radius':1}
        return {'op':'reconciliation_observe','radius':1,'expected_resident_session':'resident','session_id':'resident',
            'request_id':'reconcile_'+uuid.uuid5(uuid.NAMESPACE_OID,'gateway:reconciliation:'+name).hex,'submitted_at':now,
            'diagnostic_request':r,'diagnostic_request_digest':gateway.digest(r)}
    def run_read(self,c):
        with patch.object(diagnostic,'validate',side_effect=lambda raw,*a,**k:(raw,None)):
            try:self.resident.command(c)
            except (ValueError,KeyError,TypeError) as exc:self.resident.command_error(c,exc)
        return self.client.reconciliation_result(c['request_id'])
    def preserved(self):self.assertEqual(self.original.read_bytes(),self.original_bytes)
    def test_exact_deadline_blocks_queued_get_after_public_timeout(self):
        c=self.command()
        with patch.object(diagnostic.time,'time',return_value=c['diagnostic_request']['expires_at']+100):r=self.run_read(c)
        self.assertEqual(self.gets,[]);self.assertEqual(r['status'],'failed');self.preserved()
        self.assertEqual(r['diagnostic_request_digest'],c['diagnostic_request_digest'])
    def test_deadline_crossed_during_get_never_becomes_success(self):
        c=self.command();ticks=iter([c['submitted_at'],c['diagnostic_request']['expires_at']+1,c['diagnostic_request']['expires_at']+1])
        with patch.object(diagnostic.time,'time',side_effect=lambda:next(ticks)):r=self.run_read(c)
        self.assertEqual(len(self.gets),1);self.assertEqual(r['status'],'failed');self.preserved()
    def test_retention_isolated_for_success_error_stale_seen_and_stop(self):
        with patch.object(controller,'MAX_RESULTS',1):
            c=self.command('success');self.assertEqual(self.run_read(c)['status'],'succeeded')
            c=self.command('error');c['radius']=2;self.assertEqual(self.run_read(c)['status'],'failed')
            for name,change in [('stale',{'session_id':'old'}),('seen',{}),('stopped',{})]:
                c=self.command(name);c.update(change)
                if name=='seen':self.resident.seen.add(c['request_id'])
                if name=='stopped':self.resident.running=False
                atomic_json(self.root/'inbox'/(c['request_id']+'.json'),c);self.resident.read_commands()
                self.assertIsNotNone(self.client.reconciliation_result(c['request_id']))
                self.preserved()
        self.assertEqual(len(list((self.root/'results').glob('*.json'))),1)
        self.assertEqual(len(list((self.root/'reconciliation-results').glob('*.json'))),5)
    def test_malformed_reserved_file_and_ordinary_command_cannot_reach_mutator(self):
        c=self.command('malformed');p=self.root/'inbox'/(c['request_id']+'.json');p.write_text('{')
        self.resident.read_commands();self.assertEqual(self.client.reconciliation_result(c['request_id'])['status'],'failed')
        c=self.command('forged');c['op']='direct';c['body']={'action':'jump'}
        self.run_read(c);self.assertEqual(self.gets,[]);self.preserved()
        with self.assertRaisesRegex(ValueError,'reserved_reconciliation_request_id'):
            self.client.submit({'op':'direct'},request_id=c['request_id'])
    def test_immutable_result_duplicate_does_not_resubmit_and_capacity_refuses(self):
        c=self.command();r=self.run_read(c);before=(self.root/'reconciliation-results'/(c['request_id']+'.json')).read_bytes()
        self.resident.command_error(c,ValueError('late_error'))
        self.assertEqual((self.root/'reconciliation-results'/(c['request_id']+'.json')).read_bytes(),before)
        body={k:v for k,v in c.items() if k not in ('request_id','session_id','submitted_at')}
        self.assertEqual(self.client.submit(body,request_id=c['request_id']),c['request_id']);self.assertEqual(list((self.root/'inbox').glob('*.json')),[])
        for i in range(255):atomic_json(self.root/'reconciliation-results'/('retained'+str(i)+'.json'),{'proof':i})
        with self.assertRaisesRegex(ValueError,'reconciliation_resident_history_full'):
            self.client.submit(body,request_id=self.command('next')['request_id'])
        self.preserved();self.assertEqual(len(list((self.root/'reconciliation-results').glob('*.json'))),256)
    def test_request_digest_and_derived_id_cannot_change_deadline(self):
        for name in ('digest','id','deadline'):
            c=self.command(name)
            if name=='digest':c['diagnostic_request_digest']='0'*64
            elif name=='id':c['request_id']='reconcile_forged'
            else:c['diagnostic_request']['expires_at']+=1
            self.assertEqual(self.run_read(c)['status'],'failed')
        self.assertEqual(self.gets,[]);self.preserved()
    def test_saturated_startup_preserves_claimed_and_inbox_diagnostic_evidence(self):
        history=self.root/'reconciliation-results';history.mkdir()
        for i in range(256):atomic_json(history/(str(i)+'.json'),{'retained':i})
        saved=[]
        for folder in ('inbox','working'):
            c=self.command(folder);path=self.root/folder/(c['request_id']+'.json');atomic_json(path,c)
            saved.append((path,path.read_bytes()))
        status={'protocol':'mineclient-bridge','schema_version':2,'run_id':'run','process_id':1,'in_world':False}
        action={'action_schema_version':1,'action_session':'action','status':'idle'}
        self.resident.bridge.request=lambda method,path: status if path=='/control/status' else action
        with patch.object(controller,'MAX_RESULTS',1):self.resident.start()
        for path,raw in saved:self.assertEqual(path.read_bytes(),raw)
        self.assertEqual(len(list(history.glob('*.json'))),256);self.preserved()
        self.resident.lock.close()

    def test_startup_reserved_diagnostic_is_not_replayed_or_pruned(self):
        c=self.command();atomic_json(self.root/'working'/(c['request_id']+'.json'),c)
        status={'protocol':'mineclient-bridge','schema_version':2,'run_id':'run','process_id':1,'in_world':False}
        action={'action_schema_version':1,'action_session':'action','status':'idle'}
        self.resident.bridge.request=lambda method,path: status if path=='/control/status' else action
        with patch.object(controller,'MAX_RESULTS',1):self.resident.start()
        self.assertEqual(self.client.reconciliation_result(c['request_id'])['status'],'uncertain');self.preserved()
        self.resident.lock.close()

if __name__=='__main__':unittest.main()

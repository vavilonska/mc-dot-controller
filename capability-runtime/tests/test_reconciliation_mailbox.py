"""Pure bounded diagnostic queue fault tests; no game or execution owner calls."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest.mock import patch
import reconciliation_read as d
from resident_controller.ipc import atomic_json,read_json

class MailboxTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        atomic_json(self.root/'state.json',{'implementation':'native-defense-watchdog-v5','reconciliation_read_profile':d.VERSION,
            'session_id':'gateway','updated_at':time.time()})
        self.client=SimpleNamespace(root=self.root)
        self.calls=[]
        class Q:
            def session(s):return {'session_id':'resident'}
            def submit(s,command,request_id=None):self.calls.append((deepcopy(command),request_id));return request_id
            def reconciliation_result(s,rid):return None
        self.dog=SimpleNamespace(session_id='gateway',q=Q(),owner={'id':'original'},rpc={'id':'original-rpc'},capability_lease={'owner_id':'original-owner'},latest={'sentinel':True})
    def tearDown(self):self.temp.cleanup()
    def test_exact_closed_scope_and_duplicates(self):
        body=d.submit(self.client,'read','gateway','job_old')
        self.assertEqual(d.submit(self.client,'read','gateway','job_old'),body)
        for changed in ({**body,'radius':True},{**body,'radius':2},{**body,'op':'direct'},{**body,'endpoint':'release-all'},
                        {**body,'expires_at':body['created_at']+6},{**body,'request_id':'../escape'}):
            with self.assertRaises(ValueError):d.validate(changed)
        with self.assertRaises(ValueError):d.submit(self.client,'read','gateway','job_other')
        with self.assertRaises(ValueError):d.submit(self.client,'read2','gateway','job_old')
        self.assertEqual(self.calls,[])
    def test_restart_claimed_read_is_never_submitted(self):
        body=d.submit(self.client,'read','gateway','job_old');root=d.folders(self.root)
        (root/'inbox/read.json').rename(root/'working/read.json')
        d.tick(self.dog,self.root);r=d.result(self.client,body)
        self.assertEqual(r['state'],'unknown');self.assertEqual(r['reason'],'diagnostic_previous_run_not_replayed')
        d.tick(self.dog,self.root);self.assertEqual(self.calls,[])
    def test_expired_query_never_reaches_native_and_owner_unchanged(self):
        body=d.submit(self.client,'read','gateway','job_old')
        with patch.object(d.time,'time',return_value=body['expires_at']+1):d.tick(self.dog,self.root)
        self.assertEqual(d.result(self.client,body)['state'],'blocked');self.assertEqual(self.calls,[])
        self.assertEqual(self.dog.owner,{'id':'original'});self.assertEqual(self.dog.rpc,{'id':'original-rpc'})
    def test_lost_read_terminal_is_immutable_and_no_fallback(self):
        body=d.submit(self.client,'read','gateway','job_old');d.tick(self.dog,self.root)
        self.assertEqual(len(self.calls),1);self.assertEqual(self.calls[0][0]['op'],'reconciliation_observe')
        self.assertEqual(self.calls[0][0]['diagnostic_request'],body)
        self.assertEqual(self.calls[0][0]['diagnostic_request_digest'],d.digest(body))
        self.assertTrue(self.calls[0][1].startswith('reconcile_'))
        self.assertEqual(set(self.calls[0][0]),{'op','radius','expected_resident_session','diagnostic_request','diagnostic_request_digest'})
        with patch.object(d.time,'time',return_value=body['expires_at']+1):d.tick(self.dog,self.root)
        original=d.result(self.client,body);self.assertEqual(original['state'],'unknown')
        d.tick(self.dog,self.root);self.assertEqual(d.result(self.client,body),original);self.assertEqual(len(self.calls),1)
        self.assertEqual(self.dog.capability_lease,{'owner_id':'original-owner'});self.assertEqual(self.dog.latest,{'sentinel':True})
    def test_forged_reply_binds_exact_native_request_and_session(self):
        body=d.submit(self.client,'read','gateway','job_old');d.tick(self.dog,self.root)
        self.dog.q.reconciliation_result=lambda rid:{'request_id':'foreign','session_id':'resident','status':'succeeded','result':{}}
        d.tick(self.dog,self.root);self.assertEqual(d.result(self.client,body)['state'],'unknown');self.assertEqual(len(self.calls),1)

if __name__=='__main__':unittest.main()

import tempfile
from pathlib import Path
import unittest
from gate_off_case import run_gate_off_case
from gate_probe_contract import probe_body
R="00000000-0000-0000-0000-000000000001"
S="00000000-0000-0000-0000-000000000002"
W="00000000-0000-0000-0000-000000000003"
P="00000000-0000-0000-0000-000000000004"

class Client:
    def __init__(self,root):self.root=Path(root);self.posts=[];self.timeout=False
    def session(self):return {'session_id':R,'state':'ready','active_request_id':None,'active_action_id':None,'pending':0,'bridge_identity':{'action_session':S}}
    def submit(self,body,request_id):self.posts.append((body,request_id));return request_id
    def wait(self,rid,timeout):
        if self.timeout:return {'request_id':rid,'status':'pending'}
        return {'request_id':rid,'session_id':R,'status':'succeeded','result':{'request_id':rid,'body':probe_body(dict(self.posts[-1][0],request_id=rid),R),'probe_passed':True,'http_status':409,'native_error':'encounter_stage1_disabled','expected_rejection':True,'ownership_and_inputs_unchanged':True,'targets_declared_unspawned_test_identifiers':True}}

class GateOffCaseTest(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.c=Client(self.t.name)
        self.binding={'resident_session':R,'action_session':S,'world_generation':W,'player_uuid':P}
    def run_case(self):return run_gate_off_case(self.c,'unique',self.binding,authorization_ref='explicit-test-approval')
    def test_exact_probe_pass_is_persisted(self):
        self.assertTrue(self.run_case()['probe_passed']);self.assertEqual(len(self.c.posts),1)
        self.assertTrue((self.c.root/'gate-off-case-evidence/unique.intent.json').exists())
    def test_unknown_wait_never_retries(self):
        self.c.timeout=True;self.assertFalse(self.run_case()['probe_passed']);self.assertEqual(len(self.c.posts),1)
    def test_old_intent_blocks_reentry_without_second_submission(self):
        self.run_case()
        with self.assertRaises(FileExistsError):self.run_case()
        self.assertEqual(len(self.c.posts),1)
    def test_foreign_session_refuses_before_submission(self):
        self.binding['resident_session']='foreign'
        with self.assertRaises(ValueError):self.run_case()
        self.assertEqual(self.c.posts,[])
    def test_missing_permission_reference_refuses(self):
        with self.assertRaises(ValueError):run_gate_off_case(self.c,'unique',self.binding,authorization_ref='')
        self.assertEqual(self.c.posts,[])

    def test_other_world_old_success_cannot_supply_this_probe(self):
        old_wait=self.c.wait
        def mismatched(rid,timeout):
            value=old_wait(rid,timeout)
            value['result']['body']['expected_world_generation']=P
            return value
        self.c.wait=mismatched
        self.assertFalse(self.run_case()['probe_passed'])
        self.assertEqual(len(self.c.posts),1)

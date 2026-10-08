import json
from pathlib import Path
import tempfile
import time
import unittest
from intent_client import IntentClient
class AdapterChecks(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        for name in ('inbox','working','results'):(self.root/name).mkdir()
        (self.root/'state.json').write_text(json.dumps({'implementation':'native-defense-watchdog-v5','session_id':'gateway-session','state':'ready','pending':0,'updated_at':time.time()}))
        self.client=IntentClient(self.root)
    def tearDown(self):self.tmp.cleanup()
    def test_submit_preserves_requested_id_and_binds_gateway_session(self):
        self.assertEqual(self.client.submit({'op':'observe'},request_id='a'),'a')
        body=json.loads((self.root/'inbox/a.json').read_text())
        self.assertEqual(body,{'op':'observe','_watchdog_session_id':'gateway-session'})
    def test_repeated_id_does_not_replay(self):
        self.client.submit({'op':'observe'},'a');self.client.submit({'op':'direct'},'a')
        self.assertEqual(json.loads((self.root/'inbox/a.json').read_text())['op'],'observe')
    def test_result_is_queueclient_compatible_and_retains_backing_ids(self):
        (self.root/'results/a.json').write_text(json.dumps({'intent_id':'a','session_id':'gateway-session','queue_request_id':'resident-a','result':{'request_id':'resident-a','session_id':'resident-session','status':'succeeded','result':{'state':{}}}}))
        r=self.client.wait('a',1)
        self.assertEqual((r['request_id'],r['session_id']),('a','gateway-session'))
        self.assertEqual(r['queue_request_id'],'resident-a');self.assertEqual(r['queue_session_id'],'resident-session')
    def test_one_pending_intent(self):
        self.client.submit({'op':'observe'},'a')
        with self.assertRaisesRegex(ValueError,'one_pending'):self.client.submit({'op':'observe'},'b')
    def test_stop_blocks_new_intents(self):
        (self.root/'STOP').write_text('stop')
        with self.assertRaisesRegex(ValueError,'not_accepting'):self.client.submit({'op':'observe'})
    def test_pending_wait_never_resubmits(self):
        self.assertEqual(self.client.wait('a',0)['status'],'pending')
        self.assertEqual(list((self.root/'inbox').iterdir()),[])
if __name__=='__main__':unittest.main()

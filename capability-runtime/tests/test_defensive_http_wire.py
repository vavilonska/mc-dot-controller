"""Actual production registry/ActionResponses/BridgeJson bytes through Bridge and both consumers.
The emitted terminal observations are explicit model inputs, not live game proof.
"""
from copy import deepcopy
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
import json,os,threading,unittest
from mdc_skills.defensive_combat import verified
from resident_controller.controller import Resident
from resident_controller.transport import Bridge,BridgeError

class DefensiveHttpWireTests(unittest.TestCase):
    def setUp(self):
        fixture=os.environ.get('MDC_DEFENSIVE_COMBAT_WIRE')
        if not fixture:self.skipTest('Requires production ActionResponses+BridgeJson fixture')
        self.rows=json.loads(Path(fixture).read_text())['rows'];self.calls=[];self.response=b'{}';self.status=200;p=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*_):pass
            def do_GET(self):
                p.calls.append(self.path);self.send_response(p.status);self.send_header('Content-Length',str(len(p.response)));self.end_headers();self.wfile.write(p.response)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.bridge=Bridge('http://127.0.0.1:'+str(self.server.server_port),'synthetic-test-only')
    def tearDown(self):
        if hasattr(self,'server'):self.server.shutdown();self.server.server_close();self.thread.join(2)
    def read(self,row,name):
        self.response=row[name+'_http'].encode();self.status=row[name+'_status']
        return self.bridge.request('GET','/control/action/status?action_id='+row['request']['action_id'])
    def test_running_and_terminal_through_resident_and_runtime_verifier(self):
        for row in self.rows:
            request=row['request'];running=self.read(row,'running');terminal=self.read(row,'terminal')
            self.assertEqual(row['running_status'],202);self.assertEqual(row['terminal_status'],200)
            for value in (running,terminal):
                self.assertEqual(value['protocol'],'mineclient-bridge');self.assertIs(type(value['schema_version']),int);self.assertEqual(value['schema_version'],2)
                task=SimpleNamespace(action_id=request['action_id'],command={'action':'combat_entity','scoped_native_preflight':{'profile':'combat-defensive-local-v1'}},encounter_request=None,last_action_result=None,fall_rescue=None)
                resident=SimpleNamespace(bridge_identity={'action_session':value['action_session']})
                Resident.accept_action_status(resident,task,value)
                self.assertEqual(task.last_action_result,value)
            args=(request['defensive_policy'],request['target_entity_id'],request['target_uuid'],request['target_type'])
            self.assertFalse(verified(running,*args));self.assertTrue(verified(terminal,*args))
        self.assertEqual(len(self.calls),4)
    def test_optional_null_omitted_by_actual_codec(self):
        for row in self.rows:
            value=self.read(row,'nullable');self.assertNotIn('initial_player_health',value['result']['combat'])
            self.assertTrue(value['result']['input_release_confirmed'])
    def test_actual_error_is_known_readonly_failure_one_get(self):
        for row in self.rows:
            with self.assertRaises(BridgeError) as caught:self.read(row,'error')
            self.assertEqual(caught.exception.status,409);self.assertFalse(caught.exception.uncertain)
            self.assertEqual(str(caught.exception),'defensive_profile_mode_binding')
        self.assertEqual(len(self.calls),2)
    def test_wire_terminal_offense_wrong_mode_and_identity_are_rejected(self):
        for row in self.rows:
            native=self.read(row,'terminal');r=row['request'];args=(r['defensive_policy'],r['target_entity_id'],r['target_uuid'],r['target_type'])
            for key,value in (('attack_dispatches',True),('attack_dispatches',1),('offensive_effects_allowed',True),('target_uuid','foreign')):
                bad=deepcopy(native);bad['result']['combat'][key]=value;self.assertFalse(verified(bad,*args))
            bad=deepcopy(native);bad['result']['combat']['defensive_policy']['schema_version']=True;self.assertFalse(verified(bad,*args))
            for key,value in (('protocol','foreign'),('schema_version',True),('schema_version',1)):
                bad=deepcopy(native);bad[key]=value;self.assertFalse(verified(bad,*args))
                task=SimpleNamespace(action_id=r['action_id'],command={'scoped_native_preflight':{'profile':'combat-defensive-local-v1'}},encounter_request=None,last_action_result=None,fall_rescue=None)
                resident=SimpleNamespace(bridge_identity={'action_session':bad['action_session']})
                with self.assertRaises(BridgeError) as caught:Resident.accept_action_status(resident,task,bad)
                self.assertTrue(caught.exception.uncertain);self.assertEqual(task.action_id,r['action_id']);self.assertIsNone(task.last_action_result)
            for key in ('protocol','schema_version'):
                bad=deepcopy(native);bad.pop(key);self.assertFalse(verified(bad,*args))
if __name__=='__main__':unittest.main()

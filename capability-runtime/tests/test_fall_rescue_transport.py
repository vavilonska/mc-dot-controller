"""Actual production Bridge -> loopback HTTP, no Minecraft or credentials read."""
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import unittest
from resident_controller.transport import Bridge, BridgeError


class FallTransportTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.response = b'{"observed":true}'
        parent = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_GET(self): self.exchange()
            def do_POST(self): self.exchange()
            def exchange(self):
                raw = self.rfile.read(int(self.headers.get('Content-Length', 0)))
                parent.calls.append((self.command,self.path,json.loads(raw) if raw else None,self.headers.get('Authorization')))
                self.send_response(200)
                self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(parent.response)))
                self.end_headers(); self.wfile.write(parent.response)
        self.server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start()
        self.bridge = Bridge('http://127.0.0.1:'+str(self.server.server_port),'synthetic-test-only')
        self.arm = {'fall_rescue_schema_version':1,'arm_id':'a'*32,'owner_id':'b'*32,
            'expected_action_session':'c'*32,'expected_world_generation':'test-world',
            'expected_player_uuid':'test-player','ttl_ms':5000,'max_episodes':1,'permitted_action_ids':[]}
        self.renew = {k:self.arm[k] for k in ('fall_rescue_schema_version','arm_id','owner_id','ttl_ms')}
        self.renew['expected_arm_revision'] = 1
        self.disarm = {k:self.arm[k] for k in ('fall_rescue_schema_version','arm_id','owner_id')}
    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(2)
    def test_all_four_routes_reach_actual_http(self):
        for op,body in (('arm',self.arm),('renew',self.renew),('status',None),('disarm',self.disarm)):
            self.assertEqual(self.bridge.request('GET' if body is None else 'POST','/control/fall-rescue/'+op,body),{'observed':True})
        self.assertEqual(len(self.calls),4)
        self.assertTrue(all(c[3]=='Bearer synthetic-test-only' for c in self.calls))
        self.assertEqual(self.calls[0][2],self.arm)
    def test_wrong_method_query_body_rejected_before_http(self):
        bad = [('GET','arm',None),('POST','status',{}),('DELETE','disarm',self.disarm),
            ('GET','status?owner=x',None),('GET','status',{}),('POST','arm?x=1',self.arm),('POST','unknown',{})]
        for op,base in (('arm',self.arm),('renew',self.renew),('disarm',self.disarm)):
            bad.append(('POST',op,{**base,'extra':True}))
            for key in base:
                b=deepcopy(base);del b[key];bad.append(('POST',op,b))
        for key,value in (('ttl_ms',True),('ttl_ms',999),('ttl_ms',600001),('max_episodes',True),
                          ('max_episodes',17),('permitted_action_ids',['x','x']),('permitted_action_ids',[{}]),
                          ('permitted_action_ids',['x'+str(i) for i in range(65)]),('owner_id',' ')):
            bad.append(('POST','arm',{**self.arm,key:value}))
        for method,op,body in bad:
            with self.subTest(method=method,op=op,body=body):
                with self.assertRaises(BridgeError): self.bridge.request(method,'/control/fall-rescue/'+op,body)
        self.assertEqual(self.calls,[])
    def test_duplicate_response_and_oversize_are_unknown_without_retry(self):
        for raw in (b'{"armed":true,"armed":false}', b' '*(32769)):
            self.response=raw
            with self.assertRaises(BridgeError) as caught:
                self.bridge.request('POST','/control/fall-rescue/arm',self.arm)
            self.assertTrue(caught.exception.uncertain)
        self.assertEqual(len(self.calls),2)

if __name__=='__main__': unittest.main()

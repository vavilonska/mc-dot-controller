"""Canonical Java bytes → real Bridge HTTP → real Resident/gateway/Runtime/public service.

Only the game observations/effects are modeled. Java receipt/parser, HTTP wrapper,
codec, Bridge transport and all ownership/validation methods are production code.
"""
from copy import deepcopy
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json,os,subprocess,threading,unittest
from unittest.mock import patch
from test_fall_adjudication_owner_chain import AdjudicationTests,Endpoint
import test_attached_fall_owner_chain as attached
from resident_controller.transport import Bridge,BridgeError
from resident_controller.fall_rescue_adjudication_wire import ROOT
class CanonicalHttpTests(unittest.TestCase):
    until=AdjudicationTests.until
    submit=AdjudicationTests.submit
    finish=AdjudicationTests.finish
    unknown=AdjudicationTests.unknown
    adjudicate=AdjudicationTests.adjudicate
    def setUp(self):
        with patch.object(attached,'Endpoint',Endpoint):attached.AttachedChainTests.setUp(self)
        self.codec=subprocess.Popen([os.environ['MDC_ADJUDICATION_JAVA'],'-Xmx128m','-XX:ActiveProcessorCount=1',
            '-cp',os.environ['MDC_ADJUDICATION_CODEC_CP'],'io.github.campione01.mineclientbridge.FallRescueAdjudicationCodec'],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.codec_lock=threading.Lock();self.native_requests={};self.http_bytes=[];self.codec_override=None;parent=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*_):pass
            def do_GET(self):self.exchange()
            def do_POST(self):self.exchange()
            def exchange(self):
                raw=self.rfile.read(int(self.headers.get('Content-Length',0)));body=json.loads(raw) if raw else None
                if self.command=='POST':parent.native_requests[body['adjudication_id']]=deepcopy(body)
                payload=parent.bridge.request(self.command,self.path,body) if parent.codec_override is None else {}
                identity=(body['adjudication_id'] if body else self.path.split('=',1)[1] if '=' in self.path else None)
                message=deepcopy(parent.codec_override) if parent.codec_override is not None else {'payload':payload}
                if identity in parent.native_requests:message['native_request']=parent.native_requests[identity]
                status,encoded=parent.encode(message);parent.http_bytes.append(encoded)
                self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(encoded)))
                self.end_headers();self.wfile.write(encoded)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.http_thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.http_thread.start()
        native=Bridge('http://127.0.0.1:'+str(self.server.server_port),'synthetic-test-only')
        self.real_bridge=native
        endpoint=self.bridge
        class Router:
            def __getattr__(self,k):return getattr(endpoint,k)
            def request(self,method,path,body=None):
                return native.request(method,path,body) if path.startswith(ROOT) else endpoint.request(method,path,body)
        self.resident.bridge=Router()
    def encode(self,message):
        with self.codec_lock:
            self.codec.stdin.write(json.dumps(message)+'\n');self.codec.stdin.flush()
            line=self.codec.stdout.readline();status,encoded=line.split('\t',1)
            return int(status),encoded.rstrip('\n').encode()
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.http_thread.join(2)
        self.codec.stdin.close();self.codec.wait(3);self.assertEqual(self.codec.returncode,0,self.codec.stderr.read())
        self.codec.stdout.close();self.codec.stderr.close()
        AdjudicationTests.tearDown(self)
    def test_canonical_owner_release(self):
        r=self.unknown();value=self.adjudicate(r)
        self.assertTrue(value['adjudication']['authority_released'],value);self.assertEqual(value['state'],'unknown')
        self.assertGreaterEqual(len(self.http_bytes),2)
        self.assertTrue(all(json.loads(b)['protocol']=='mineclient-bridge' for b in self.http_bytes))
        self.assertTrue(self.dog.explicit_after_adjudication);self.assertIsNone(self.runtime.pending_request_id)
    def test_pending_error_and_optional_null_codec(self):
        self.codec_override={'payload':{'adjudication_schema_version':1,'inspection':{'optional_diagnostic':None}},'not_found':'pending-original'}
        parsed=self.real_bridge.request('GET',ROOT+'/status?adjudication_id=pending-original')
        self.assertEqual(parsed['receipt']['status'],'not_found');self.assertEqual(parsed['inspection'],{})
        self.assertEqual(parsed['schema_version'],2)
        self.codec_override={'payload':{},'reject':True}
        with self.assertRaises(BridgeError) as caught:self.real_bridge.request('GET',ROOT+'/prepare')
        self.assertEqual(caught.exception.status,409)
        from resident_controller import fall_rescue_adjudication_wire as wire
        with self.assertRaises(ValueError):wire.inspection(parsed,{},released=True)
if __name__=='__main__':unittest.main()

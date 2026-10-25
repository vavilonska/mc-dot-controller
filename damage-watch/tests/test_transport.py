"""Controlled ephemeral loopback only; never a game endpoint or a real secret."""
import http.server
import socket
import threading
import time
import unittest
from damage_watch.transport import HttpTransport
from damage_watch.schema import PATH
from damage_watch.strict import Invalid

TOKEN='offline-test-token-not-a-real-secret'

class Handler(http.server.BaseHTTPRequestHandler):
    mode='normal';calls=[]
    def log_message(self,*_):pass
    def do_GET(self):
        type(self).calls.append((self.command,self.path,self.headers.get('Authorization')))
        mode=type(self).mode
        if mode=='headers':time.sleep(.4)
        raw=TOKEN.encode() if mode=='echo' else b'x'*140000 if mode=='large' else b'{}'
        self.send_response(302 if mode=='redirect' else 200)
        if mode=='redirect':self.send_header('Location','/never-follow')
        self.send_header('Content-Length',str(100 if mode=='dribble' else len(raw)));self.end_headers()
        try:
            if mode=='dribble':
                for i in range(100):self.wfile.write(b'x');self.wfile.flush();time.sleep(.03)
            else:self.wfile.write(raw)
        except (OSError,ConnectionError):pass

class TransportTests(unittest.TestCase):
    def setUp(self):
        Handler.mode='normal';Handler.calls=[];self.server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);self.server.daemon_threads=True
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.endpoint='http://127.0.0.1:'+str(self.server.server_port);self.t=HttpTransport(self.endpoint,TOKEN)
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join()
    def test_only_exact_get_no_post_no_redirect_no_retry(self):
        r=self.t.get(PATH,timeout_s=.3);self.assertTrue(r.complete);self.assertEqual(r.body,b'{}');self.assertEqual(Handler.calls,[('GET',PATH,'Bearer '+TOKEN)])
        with self.assertRaises(Invalid):self.t.get(PATH+'?extra=1',timeout_s=.3)
        self.assertFalse(hasattr(self.t,'post'));self.assertEqual(len(Handler.calls),1)
        Handler.mode='redirect';r=self.t.get(PATH,timeout_s=.3);self.assertEqual(r.status,302);self.assertEqual(len(Handler.calls),2)
    def test_absolute_slow_headers_and_dribble_deadline(self):
        for mode in ('headers','dribble'):
            Handler.mode=mode;before=len(Handler.calls);begin=time.monotonic();r=self.t.get(PATH,timeout_s=.15);elapsed=time.monotonic()-begin
            self.assertFalse(r.complete);self.assertLess(elapsed,.35);self.assertEqual(len(Handler.calls),before+1)
            if mode=='dribble':self.assertGreater(len(r.body),0)
    def test_bound_preserves_prefix_and_echo_quarantined(self):
        Handler.mode='large';r=self.t.get(PATH,timeout_s=.3);self.assertFalse(r.complete);self.assertEqual(len(r.body),131073);self.assertEqual(r.error,'response_too_large')
        Handler.mode='echo';r=self.t.get(PATH,timeout_s=.3);self.assertFalse(r.complete);self.assertEqual(r.body,b'');self.assertEqual(r.error,'secret_quarantined')
    def test_connection_refusal_explicit_and_endpoint_restrictions(self):
        sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
        r=HttpTransport('http://127.0.0.1:'+str(port),TOKEN).get(PATH,timeout_s=.2);self.assertEqual(r.error,'connection_unavailable');self.assertIsNone(r.status)
        for endpoint in ('http://localhost:1234','http://example.org:1234','http://secret@127.0.0.1:1234','https://127.0.0.1:1234','http://127.0.0.1:1234/extra'):
            with self.assertRaises(Invalid):HttpTransport(endpoint,TOKEN)
        for timeout in (0,.751,float('inf')):
            with self.assertRaises(Invalid):self.t.get(PATH,timeout_s=timeout)

if __name__=='__main__':unittest.main()

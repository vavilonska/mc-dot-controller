"""Only controlled ephemeral loopback fixture; never a game endpoint."""
import contextlib
import http.server
import threading
import time
import unittest
from short_input_controller.transport import HttpTransport, MAX_RESPONSE
from short_input_controller.storage import Refused

TOKEN='fixture-not-a-real-game-token'


@contextlib.contextmanager
def server(mode):
    class Handler(http.server.BaseHTTPRequestHandler):
        count=0
        def do_GET(self):
            Handler.count+=1
            if self.headers.get('Authorization') != 'Bearer '+TOKEN: raise AssertionError('auth fixture')
            if mode=='redirect':
                self.send_response(302);self.send_header('Location','http://127.0.0.1:1/never');self.end_headers();return
            if mode=='slowheaders':
                try:
                    for byte in b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}':
                        self.wfile.write(bytes([byte]));self.wfile.flush();time.sleep(.03)
                except (BrokenPipeError,ConnectionResetError):pass
                return
            raw=(b'x'*(MAX_RESPONSE+10) if mode=='oversize' else TOKEN.encode() if mode=='secret' else b'{"x":1,"x":2}')
            self.send_response(200);self.send_header('Content-Length',str(len(raw)+(5 if mode=='truncated' else 0)));self.end_headers()
            self.wfile.write(raw)
        def log_message(self,*_):pass
    srv=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=srv.serve_forever,daemon=True);thread.start()
    try:yield 'http://127.0.0.1:'+str(srv.server_port), Handler
    finally:srv.shutdown();srv.server_close();thread.join()


class TransportTests(unittest.TestCase):
    def test_raw_original_not_reserialized(self):
        with server('raw') as (url,h):
            r=HttpTransport(url,TOKEN).request('GET','/control/recovery-short-input/v1/observe')
            self.assertEqual(r.body,b'{"x":1,"x":2}');self.assertTrue(r.complete);self.assertEqual(h.count,1)
    def test_bounds_redirect_truncation_secret(self):
        for mode in ('oversize','redirect','truncated','secret'):
            with self.subTest(mode=mode),server(mode) as (url,h):
                r=HttpTransport(url,TOKEN).request('GET','/control/recovery-short-input/v1/observe')
                self.assertLessEqual(len(r.body),MAX_RESPONSE);self.assertEqual(h.count,1)
                if mode=='redirect':self.assertEqual(r.status,302)
                else:self.assertFalse(r.complete)
                self.assertNotIn(TOKEN.encode(),r.body)
    def test_absolute_header_deadline(self):
        with server('slowheaders') as (url,h):
            start=time.monotonic();r=HttpTransport(url,TOKEN,.1).request('GET','/control/recovery-short-input/v1/observe')
            self.assertFalse(r.complete);self.assertLess(time.monotonic()-start,.5);self.assertEqual(h.count,1)
    def test_no_remote_or_credential_url(self):
        for url in ('https://127.0.0.1:2','http://example.org:80','http://token@127.0.0.1:2','http://127.0.0.1:2/other'):
            with self.assertRaises(Refused):HttpTransport(url,TOKEN)

if __name__=='__main__':unittest.main()

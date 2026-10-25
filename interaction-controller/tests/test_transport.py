"""Explicit ephemeral loopback server only; never the saved game endpoint."""
import http.server
import threading
import unittest
from interaction_controller.transport import HttpTransport,MAX_RESPONSE
from interaction_controller.legacy import Refused,strict_json

TOKEN='offline-fixture-not-a-real-token'

class TransportTests(unittest.TestCase):
    def test_new_root_original_bytes_and_strict_duplicates(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            count=0
            def do_GET(self):
                Handler.count+=1
                self.assert_path=self.path
                raw=b'{"profile":"recovery_interaction_v1","profile":"duplicate"}'
                self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
            def log_message(self,*_):pass
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            t=HttpTransport('http://127.0.0.1:'+str(server.server_port),TOKEN)
            result=t.request('GET','/control/recovery-interaction/v1/observe')
            self.assertTrue(result.complete);self.assertEqual(Handler.count,1)
            with self.assertRaises(Refused):strict_json(result.body)
            with self.assertRaises(Refused):t.request('POST','/control/arbitrary-effect',{})
            self.assertEqual(Handler.count,1)
        finally:server.shutdown();server.server_close();thread.join()
    def test_no_remote_or_url_secret(self):
        for endpoint in ('http://example.org:80','http://secret@127.0.0.1:1','https://127.0.0.1:1'):
            with self.assertRaises(Refused):HttpTransport(endpoint,TOKEN)

if __name__=='__main__':unittest.main()

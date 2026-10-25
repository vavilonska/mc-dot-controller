import importlib.util,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.dont_write_bytecode=True
spec=importlib.util.spec_from_file_location('recovery_cli',Path(__file__).with_name('run_recovery.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class BaseTransport:
 def __init__(self,endpoint,token,timeout):self.endpoint=endpoint;self.timeout=timeout;self.calls=[]
 def request(self,method,path,body=None):self.calls.append((method,path,body));return 'reply'
class Tests(unittest.TestCase):
 def test_transport_single_current_pool_start_original_stop(self):
  root='/control/recovery-interaction/v3/';t=m.make_transport(BaseTransport,'http://127.0.0.1:38121','test-token','recovery_survival_v6',root)
  q=dict(id='a',profile='recovery_survival_v6');t.pool={'a','old-unused'}
  self.assertEqual(t.request('POST',root+'start',q),'reply')
  with self.assertRaises(ValueError):t.request('POST',root+'start',q)
  t.pool={'b'}
  with self.assertRaises(ValueError):t.request('POST',root+'start',dict(q,id='old-unused'))
  self.assertEqual(t.request('POST',root+'stop',dict(id='a')),'reply')
  self.assertEqual(t.request('GET',root+'status?id=a'),'reply')
  with self.assertRaises(ValueError):t.request('POST','/control/command',{})
  with self.assertRaises(ValueError):t.request('POST',root+'stop',dict(id='b'))
  self.assertEqual(len(t.calls),3)
 def test_private_input_and_no_overwrite(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'token';m.write_new(p,b'not-a-real-token')
   self.assertEqual(m.safe_read(p,512,True),b'not-a-real-token')
   with self.assertRaises(FileExistsError):m.write_new(p,b'replace')
   p.chmod(0o644)
   with self.assertRaises(ValueError):m.safe_read(p,512,True)
   link=Path(td)/'link';link.symlink_to(p)
   with self.assertRaises(ValueError):m.safe_read(link,512)
 def test_singleplayer_read_only_endpoint_and_secret_redaction(self):
  calls=[]
  class Response:
   status=200
   def read(self,n):return b'{"private_singleplayer":true}'
  class Conn:
   def __init__(self,*a,**kw):pass
   def request(self,*a,**kw):calls.append((a,kw))
   def getresponse(self):return Response()
   def close(self):pass
  with patch.object(m.http.client,'HTTPConnection',Conn):
   self.assertTrue(m.singleplayer_state('http://127.0.0.1:38121','fake-secret')['private_singleplayer'])
  self.assertEqual(calls[0][0],('GET','/control/state?radius=0'))
  with self.assertRaises(ValueError):m.singleplayer_state('https://example.com:443','fake-secret')
if __name__=='__main__':unittest.main(verbosity=2)

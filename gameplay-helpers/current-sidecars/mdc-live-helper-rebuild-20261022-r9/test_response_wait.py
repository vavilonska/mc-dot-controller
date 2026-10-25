import unittest
import run_recovery as m
class Fake:
 def __init__(self,endpoint,token,timeout):self.endpoint=endpoint;self.timeout=timeout;self.calls=[]
 def request(self,method,path,body=None):self.calls.append((method,path,body));return type('Reply',(),dict(complete=False))()
class Tests(unittest.TestCase):
 def test_response_wait_is_not_native_ttl(self):
  root='/control/recovery-interaction/v3/'
  t=m.make_transport(Fake,'http://127.0.0.1:38121','fake','recovery_survival_v6',root)
  self.assertEqual(t.timeout,5.);self.assertEqual(t.scheduling_quantum,.5);self.assertEqual(t.observer.timeout,2.)
  q=dict(id='new',profile='recovery_survival_v6',ttl_ms=1000,samples=8);t.pool={'new'}
  t.request('GET',root+'observe');t.request('POST',root+'start',q)
  self.assertEqual(q['ttl_ms'],1000);self.assertEqual(q['samples'],8)
  with self.assertRaises(ValueError):t.request('POST',root+'start',q)
  self.assertEqual(len(t.calls),1);self.assertEqual(t.timings[-1]['operation'],'start')
  self.assertIsNotNone(t.timings[-1]['from_observe_return_seconds'])
 def test_unknown_response_only_gets_may_be_repeated(self):
  root='/control/recovery-interaction/v3/';t=m.make_transport(Fake,'http://127.0.0.1:38121','fake','recovery_survival_v6',root)
  q=dict(id='a',profile='recovery_survival_v6');t.pool={'a'};t.request('POST',root+'start',q)
  for _ in range(3):t.request('GET',root+'status?id=a')
  self.assertEqual([x[0] for x in t.calls],['POST','GET','GET','GET'])
if __name__=='__main__':unittest.main(verbosity=2)

import importlib.util,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sp=importlib.util.spec_from_file_location('trip',Path(__file__).with_name('exposure-roundtrip.py'));m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m)
class Connection:
    def __init__(self,*a,**kw):self.args=a;self.kw=kw;self.calls=[];self.closed=False
    def request(self,*a,**kw):self.calls.append((a,kw))
    def getresponse(self):return self
    status=200
    def read(self):return json.dumps({'fixture':'state'}).encode()
    def close(self):self.closed=True
class Tests(unittest.TestCase):
    def test_real_state_uses_radius_zero_two_seconds_get_only(self):
        with tempfile.TemporaryDirectory() as d:
            c=object.__new__(m.Client);c.out=Path(d);c.token='fixture-not-a-credential';holder=[]
            def factory(*a,**kw):conn=Connection(*a,**kw);holder.append(conn);return conn
            with patch.object(m.http.client,'HTTPConnection',factory):self.assertEqual(c.state(),{'fixture':'state'})
            conn=holder[0];self.assertEqual(conn.kw['timeout'],2);self.assertEqual(conn.calls[0][0],('GET','/control/state?radius=0'));self.assertTrue(conn.closed)
    def test_read_failure_records_without_any_input_or_implicit_retry(self):
        with tempfile.TemporaryDirectory() as d:
            c=object.__new__(m.Client);c.out=Path(d);c.token='fixture-not-a-credential';conn=Connection()
            with patch.object(m.http.client,'HTTPConnection',return_value=conn),patch.object(conn,'getresponse',side_effect=TimeoutError):
                with self.assertRaises(TimeoutError):c.state()
            self.assertEqual(len(conn.calls),1);self.assertTrue(conn.closed)
            row=json.loads(Path(d,'events.jsonl').read_text());self.assertEqual(row['event'],'read_failed');self.assertNotIn(c.token,Path(d,'events.jsonl').read_text())
if __name__=='__main__':unittest.main(verbosity=2)

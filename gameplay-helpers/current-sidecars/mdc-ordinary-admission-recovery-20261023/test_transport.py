import importlib.util,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import idle_guard as idle
from test_roundtrip import Fake,state,plan,m as trip
from test_state_read import Connection

class Tests(unittest.TestCase):
    def test_actual_shared_client_get_two_post_five_no_retry_real_note(self):
        with tempfile.TemporaryDirectory() as d:
            c=object.__new__(idle.Client);c.out=Path(d);c.token='offline-fixture';seen=[]
            def factory(*a,**kw):
                conn=Connection(*a,**kw);seen.append(conn);return conn
            with patch.object(idle.http.client,'HTTPConnection',factory):
                c.state();c.request('GET','/control/action/status?action_id=original')
                c.request('POST','/control/action',{'action_id':'new','timeout_ms':6000})
            self.assertEqual([x.kw['timeout'] for x in seen],[2,2,5])
            self.assertEqual(seen[0].calls[0][0][:2],('GET','/control/state?radius=32'))
            self.assertTrue(all(x.closed for x in seen))
            rows=[json.loads(x) for x in Path(d,'events.jsonl').read_text().splitlines()]
            post=next(x for x in rows if x['event']=='one_shot_request');self.assertEqual(post['body']['timeout_ms'],6000)
            self.assertNotIn(c.token,Path(d,'events.jsonl').read_text())
            self.assertIs(trip.Client.request,idle.Client.request)
            sp=importlib.util.spec_from_file_location('combat_transport_check',Path(__file__).with_name('shield-axe.py'));combat=importlib.util.module_from_spec(sp);sp.loader.exec_module(combat)
            self.assertIs(combat.idle.Client,idle.Client)
    def test_post_timeout_is_recorded_once_and_never_resubmitted(self):
        with tempfile.TemporaryDirectory() as d:
            c=object.__new__(idle.Client);c.out=Path(d);c.token='offline-fixture';conn=Connection()
            with patch.object(idle.http.client,'HTTPConnection',return_value=conn),patch.object(conn,'getresponse',side_effect=TimeoutError):
                with self.assertRaises(TimeoutError):c.request('POST','/control/action',{'action_id':'once'})
            self.assertEqual(len(conn.calls),1);self.assertTrue(conn.closed)
            rows=[json.loads(x) for x in Path(d,'events.jsonl').read_text().splitlines()]
            self.assertEqual(rows[-1]['event'],'request_uncertain_no_reissue')
    def test_shared_watch_lost_start_running_and_fire_does_not_cancel(self):
        with tempfile.TemporaryDirectory() as d:
            class EscapeFake(Fake):
                def request(self,method,path,body=None):
                    if path=='/control/action' and body['action']=='follow_path':
                        self.calls.append((method,path,body));self.records[body['action_id']]=body
                        raise TimeoutError('lost follow response')
                    if path.startswith('/control/action/status'):
                        uid=path.split('=')[1];self.polls[uid]=self.polls.get(uid,0)+1
                        if self.polls[uid]==1:
                            return 200,dict(action_id=uid,action_session='session',status='running')
                    return super().request(method,path,body)
            c=EscapeFake(d,'success');s=c.state();w=idle.Watch(c,plan()['retreat'],s);w.start_retreat(s,'test')
            s['player']['on_fire']=True;w.step(s);self.assertTrue(w.pending);self.assertFalse(w.cancel_sent)
            w.step(s);self.assertFalse(w.pending);self.assertEqual(len(c.cancelled),0)
            self.assertEqual(len([x for x in c.calls if x[1]=='/control/action']),1)
if __name__=='__main__':unittest.main(verbosity=2)

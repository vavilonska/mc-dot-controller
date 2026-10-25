"""Actual production Client HTTP serialization/parser + complete return/closure, never game HTTP."""
import copy,http.client,json,tempfile,threading,time,unittest
from types import SimpleNamespace
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from test_roundtrip import m,Fake,plan
from test_plan_place import placeplan

class Backend(Fake):
    def __init__(self,out,mode='pre'):
        super().__init__(out,'success');self.scenario=mode;self.rejected=None;self.ready_reads=0;self.absence_seen=False;self.old_404=0
    def state(self):
        s=super().state()
        if self.absence_seen:
            self.ready_reads+=1
            s['world']['navigation_guard']['rebind_ready']=self.ready_reads>=3 and self.scenario!='unsettled'
            s['world']['navigation_guard']['stable_ticks']=3 if s['world']['navigation_guard']['rebind_ready'] else 0
        return s
    def request(self,method,path,body=None):
        if path.startswith('/control/state?'):return 200,self.state()
        if path=='/control/action' and body['action']=='follow_path' and body['waypoints'][-1]['x']==0 and self.rejected is None:
            self.rejected=copy.deepcopy(body);self.calls.append((method,path,copy.deepcopy(body)))
            proof=dict(schema_version=1,boundary_schema_version=2,ordinary_start_entered=True,input_transfer_entered=False,registration_entered=False,reentry_observed=False,action_id=body['action_id'],action='follow_path',action_session='session',request_payload_sha256=m.digest(body),digest_format='sorted-json-utf8/1',stage='hooks_possible',reason='navigation_not_settled',effects_none_proven=False,dispatch_authority=False,retry_authority=False)
            if self.scenario=='late':proof.update(input_transfer_entered=True,stage='input_transfer')
            if self.scenario=='existing':proof.update(stage='validation',effects_none_proven=True,reason='action_id_payload_mismatch')
            return 409,dict(ok=False,error=proof['reason'],native_admission=proof)
        if path.startswith('/control/action/status') and self.rejected and path.endswith(self.rejected['action_id']):
            if self.scenario=='existing':return 200,dict(action_id=self.rejected['action_id'],action_session='session',status='succeeded',result={'input_release_confirmed':True})
            self.old_404+=1;self.absence_seen=True;return 404,dict(ok=False,error='action_not_found')
        code,o=super().request(method,path,body)
        if path.startswith('/control/action/status') and o.get('action') is None:
            b=self.records.get(path.split('=')[1])
            if b and b['action']=='place_block' and b['target']['x']==3:o.update(status='failed',reason='support_face_not_in_reach_or_visible')
        return code,o

class HTTPFixture:
    def __init__(self,out,mode='pre'):self.backend=Backend(out,mode)
    def __enter__(self):
        fixture=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*_):pass
            def do_GET(self):self.handle_json('GET')
            def do_POST(self):self.handle_json('POST')
            def handle_json(self,method):
                body=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0')))) if method=='POST' else None
                code,obj=fixture.backend.request(method,self.path,body)
                if fixture.backend.scenario=='lost' and method=='POST' and fixture.backend.rejected and body.get('action_id')==fixture.backend.rejected['action_id']:
                    self.close_connection=True;return
                raw=json.dumps(obj).encode();self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        original=http.client.HTTPConnection
        self.patch=patch.object(m.http.client,'HTTPConnection',side_effect=lambda host,port,**kw:original('127.0.0.1',self.server.server_port,**kw));self.patch.start();return self
    def __exit__(self,*_):self.patch.stop();self.server.shutdown();self.server.server_close();self.thread.join()

def client(out):
    c=object.__new__(m.Client);c.out=Path(out);c.token='offline-fixture';return c

class Tests(unittest.TestCase):
    def test_true_http_409_404_unstable_ready_new_return_uuid_complete_doors(self):
        with tempfile.TemporaryDirectory() as d,HTTPFixture(d) as f:
            p=placeplan();p['steps'][0]['known_tunnel']=True
            out=m.run(client(d),p);self.assertEqual(out['phase'],'COVERED_DISARMED');self.assertFalse(out['work_success'])
            starts=[x[2] for x in f.backend.calls if x[1]=='/control/action'];returns=[b for b in starts if b['action']=='follow_path' and b['waypoints'][-1]['x']==0]
            self.assertEqual(len(returns),2);self.assertNotEqual(returns[0]['action_id'],returns[1]['action_id']);self.assertFalse(f.backend.cancelled);self.assertGreaterEqual(f.backend.ready_reads,3)
            rows=[json.loads(x) for x in Path(d,'events.jsonl').read_text().splitlines()]
            evidence=next(x for x in rows if x['event']=='original_request_unregistered_no_reissue')
            self.assertEqual(evidence['original_response']['http_status'],409);self.assertFalse(evidence['original_response']['body']['native_admission']['effects_none_proven']);self.assertEqual(evidence['original_status']['error'],'action_not_found')
            self.assertEqual(out['retreat']['rejected_unregistered_count'],1);self.assertTrue(out['retreat']['closure_confirmed'])
    def test_true_http_lost_reply_and_late_rejection_404_never_replace(self):
        for mode in ('lost','late'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d,HTTPFixture(d,mode) as f:
                p=placeplan();p['retreat']['retreat_timeout_ms']=50
                now=[time.monotonic()]
                def fast_clock():now[0]+=1;return now[0]
                # Only the resolver's wall clock is accelerated; actual Client.request, sockets, bytes and parser are unchanged.
                with patch.object(m,'time',SimpleNamespace(monotonic=fast_clock,sleep=lambda _:None)):
                    out=m.run(client(d),p)
                self.assertEqual(out['phase'],'NEEDS_OPERATOR')
                returns=[x[2] for x in f.backend.calls if x[1]=='/control/action' and x[2]['action']=='follow_path' and x[2]['waypoints'][-1]['x']==0]
                self.assertEqual(len(returns),1);self.assertEqual(out['return_resolution']['action_id'],returns[0]['action_id'])
                self.assertFalse(any(x.get('event')=='original_request_unregistered_no_reissue' for x in map(json.loads,Path(d,'events.jsonl').read_text().splitlines())))
    def test_validation_payload_mismatch_existing_id_is_not_our_terminal_or_cancel(self):
        with tempfile.TemporaryDirectory() as d,HTTPFixture(d,'existing') as f:
            out=m.run(client(d),placeplan());self.assertEqual(out['phase'],'NEEDS_OPERATOR')
            self.assertEqual(out['reason'],'pre_input_rejection_original_id_exists_no_replacement');self.assertFalse(f.backend.cancelled)
            self.assertEqual(len([x for x in f.backend.calls if x[1]=='/control/action' and x[2]['action']=='follow_path' and x[2]['waypoints'][-1]['x']==0]),1)
    def test_native_wait_death_context_or_explicit_stop_never_submits(self):
        for changed in ('dead','context','stop'):
            with self.subTest(changed=changed),tempfile.TemporaryDirectory() as d:
                c=Fake(d,'success');s=c.state();s['world']['navigation_guard']['rebind_ready']=False
                w=m.idle.Watch(c,plan()['retreat'],s);w.start_retreat(s,'test')
                if changed=='dead':s['player']['alive']=False
                if changed=='context':s['player']['generation']='respawn'
                w.step(s,disarm=changed=='stop');self.assertEqual(len(c.calls),0);self.assertIn(w.phase,('NEEDS_OPERATOR','DISARMED'))
    def test_v2_receipt_never_accepts_late_reentry_malformed_or_unbound(self):
        with tempfile.TemporaryDirectory() as d:
            f=Backend(d);b=dict(action='follow_path',action_id='id',expected_action_session='session',waypoints=[dict(x=0,y=60,z=0)])
            code,obj=f.request('POST','/control/action',b);self.assertTrue(m.idle.bound_pre_input_rejection(code,obj,b))
            for key,value in [('input_transfer_entered',True),('registration_entered',True),('reentry_observed',True),('input_transfer_entered',0),('boundary_schema_version',1),('ordinary_start_entered',False),('request_payload_sha256','wrong'),('action_session','other')]:
                altered=copy.deepcopy(obj);altered['native_admission'][key]=value;self.assertFalse(m.idle.bound_pre_input_rejection(code,altered,b),(key,value))
            self.assertFalse(m.idle.bound_pre_input_rejection(500,obj,b));self.assertFalse(m.idle.bound_pre_input_rejection(None,None,b))
    def test_continuously_unsettled_is_bounded_known_released_not_unknown_404_loop(self):
        with tempfile.TemporaryDirectory() as d,HTTPFixture(d,'unsettled') as f:
            t=time.monotonic();out=m.run(client(d),placeplan());elapsed=time.monotonic()-t
            self.assertEqual(out['phase'],'NEEDS_OPERATOR');self.assertLess(elapsed,5);self.assertFalse(out['retreat']['original_pending']);self.assertFalse(f.backend.cancelled)
            self.assertEqual(len([x for x in f.backend.calls if x[1]=='/control/action' and x[2]['action']=='follow_path' and x[2]['waypoints'][-1]['x']==0]),1)
if __name__=='__main__':unittest.main(verbosity=2)

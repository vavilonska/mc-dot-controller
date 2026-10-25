"""Two focused real-HTTP/runtime tests. No game connection and no input-token read."""
import copy,http.client,importlib.util,json,sys,tempfile,threading,unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('room_runtime',HERE/'room-combat.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
from test_roundtrip import Fake,plan as oldplan

def plan():
    p=oldplan();p['steps']=p['steps'][:1]
    p['steps'][0]['known_tunnel']=True;p['steps'][0]['action']['sneak']=False
    p['retreat'].update(exposure_origin=dict(x=2,y=60,z=0),waypoints=[dict(x=2,y=60,z=0),p['start_anchor']],target_mode='closest_blaze_within_3m',max_seconds=15,allow_presence_risk=True)
    return p

class Backend(Fake):
    def __init__(self,out,reject):
        super().__init__(out,'success');self.reject=reject;self.rejected=None;self.absence=False;self.ready_reads=0;self.hits=0;self.keys=[]
        self.s['player'].update(mainhand={'id':'minecraft:iron_axe'},entity_interaction_range=3,attack_strength=1)
    def state(self):
        s=super().state();p=s['player'];p['eye_position']=dict(x=p['x'],y=p['y']+1.62,z=p['z'])
        s['nearby']['entities']=[] if self.hits else [dict(uuid='blaze-1',type='minecraft:blaze',alive=True,x=3,y=60,z=0,line_of_sight=True)]
        s['crosshair']=dict(type='entity',uuid='blaze-1',entity_type='minecraft:blaze',location=dict(x=3,y=61,z=0))
        if self.absence:
            self.ready_reads+=1;s['world']['navigation_guard']['rebind_ready']=self.ready_reads>=3
        return s
    def request(self,method,path,body=None):
        if path.startswith('/control/state?'):return 200,self.state()
        if path in ('/control/look','/control/key'):
            self.calls.append((method,path,copy.deepcopy(body)))
            if path=='/control/key':
                self.keys.append(body)
                if body['mapping']=='key.attack':self.hits+=1
                if body['mapping']=='key.use':
                    down=body['action']=='down';self.s['player']['using_item']=down;self.s['held_inputs'].update(neutral=not down,keys=['key.use'] if down else [])
            return 200,dict(ok=True)
        if self.reject and path=='/control/action' and body['action']=='follow_path' and body['waypoints'][-1]['x']==2 and self.rejected is None:
            self.rejected=copy.deepcopy(body);self.calls.append((method,path,copy.deepcopy(body)))
            proof=dict(schema_version=1,boundary_schema_version=2,ordinary_start_entered=True,input_transfer_entered=False,registration_entered=False,reentry_observed=False,action_id=body['action_id'],action='follow_path',action_session='session',request_payload_sha256=m.trip.digest(body),digest_format='sorted-json-utf8/1',stage='hooks_possible',reason='navigation_not_settled',effects_none_proven=False,dispatch_authority=False,retry_authority=False)
            return 409,dict(ok=False,error='navigation_not_settled',native_admission=proof)
        if self.rejected and path.startswith('/control/action/status') and path.endswith(self.rejected['action_id']):
            self.absence=True;return 404,dict(ok=False,error='action_not_found')
        return super().request(method,path,body)

class Fixture:
    def __init__(self,out,reject):self.backend=Backend(out,reject)
    def __enter__(self):
        fixture=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*_):pass
            def do_GET(self):self.exchange('GET')
            def do_POST(self):self.exchange('POST')
            def exchange(self,method):
                body=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0')))) if method=='POST' else None
                code,obj=fixture.backend.request(method,self.path,body);raw=json.dumps(obj).encode()
                self.send_response(code);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        original=http.client.HTTPConnection
        self.patch=patch.object(http.client,'HTTPConnection',side_effect=lambda host,port,**kw:original('127.0.0.1',self.server.server_port,**kw));self.patch.start();return self
    def __exit__(self,*_):self.patch.stop();self.server.shutdown();self.server.server_close();self.thread.join()

def client(out):
    c=object.__new__(m.Client);c.out=Path(out);c.token='offline-fixture';c.entities=False;return c

class Tests(unittest.TestCase):
    def test_normal_known_outbound_same_process_one_attack_return_both_doors(self):
        with tempfile.TemporaryDirectory() as d,Fixture(d,False) as f:
            r=m.run(client(d),plan());self.assertEqual(r['phase'],'COVERED_DISARMED');self.assertEqual(r['known_attack_clicks'],1)
            self.assertEqual(f.backend.hits,1);self.assertFalse(f.backend.cancelled);self.assertTrue(r['retreat']['closure_confirmed']);self.assertTrue(r['retreat']['neutral'])
            posts=[x[2] for x in f.backend.calls if x[1]=='/control/action'];self.assertEqual(len(posts),5);self.assertEqual(len({x['action_id'] for x in posts}),5)
            self.assertTrue(all('expected_navigation_epoch' in b for b in posts));self.assertTrue(all('capability_guard' not in b for b in posts))
            rows=list(map(json.loads,Path(d,'events.jsonl').read_text().splitlines()));self.assertTrue(any(r['event']=='combat_armed' for r in rows))
    def test_bound_outbound_rejected_404_unstable_ready_returns_without_combat_or_repeat(self):
        with tempfile.TemporaryDirectory() as d,Fixture(d,True) as f:
            r=m.run(client(d),plan());self.assertEqual(r['phase'],'COVERED_DISARMED');self.assertEqual(r['known_attack_clicks'],0)
            posts=[x[2] for x in f.backend.calls if x[1]=='/control/action'];self.assertEqual(len(posts),4);self.assertEqual(len({x['action_id'] for x in posts}),4)
            self.assertEqual(sum(b['action_id']==f.backend.rejected['action_id'] for b in posts),1);self.assertFalse(f.backend.cancelled);self.assertGreaterEqual(f.backend.ready_reads,3)
            rows=list(map(json.loads,Path(d,'events.jsonl').read_text().splitlines()));self.assertFalse(any(r['event']=='combat_armed' for r in rows))
            raw=next(r for r in rows if r['event']=='known_unregistered_no_reissue');self.assertFalse(raw['original_response']['native_admission']['effects_none_proven']);self.assertEqual(raw['original_status']['error'],'action_not_found')
if __name__=='__main__':unittest.main(verbosity=2)

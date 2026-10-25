import copy,importlib.util,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sp=importlib.util.spec_from_file_location('trip',Path(__file__).with_name('exposure-roundtrip.py'));m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m)

def state():
    return dict(private_singleplayer=True,paused=False,screen_open=False,world=dict(world_generation='world',dimension='minecraft:the_nether',navigation_guard=dict(epoch=7,rebind_ready=True,stable_ticks=3)),
      player=dict(uuid='player',generation='generation',alive=True,health=17,x=0.,y=60.,z=0.,using_item=False,selected_slot=2,
       mainhand={'id':'minecraft:stone_pickaxe'},offhand={'id':'minecraft:shield'},inventory=[dict(slot=2,id='minecraft:stone_pickaxe',count=1,item_fingerprint='pick'),dict(slot=6,id='minecraft:cobbled_deepslate',count=8,item_fingerprint='block')]),
      client_action=dict(action_session='session',status='idle'),held_inputs=dict(neutral=True,keys=[]),nearby=dict(entities=[]),capability_guard_monotonic=dict(schema_version=2,source_nano='1',source_clock={'contract':'client-pre-tick-v1','count':'12','generation':'clock'}))
def plan():
    s=state();anchor={'x':0,'y':60,'z':0};cfg=dict(arm=True,exclusive_control=True,known_tunnel=True,route_evidence=['actually walked'],expected_context=m.idle.context(s),exposure_origin=anchor,cover_anchor=anchor,waypoints=[anchor],closure_verified=True,closure_evidence=['both rays actually placed'],closure_actions=[
      dict(action='place_block',target=dict(x=1,y=60,z=0),support=dict(x=1,y=60,z=-1),face='south',hotbar_slot=6,expected_block_id='minecraft:cobbled_deepslate'),
      dict(action='place_block',target=dict(x=1,y=61,z=0),support=dict(x=1,y=62,z=0),face='down',hotbar_slot=6,expected_block_id='minecraft:cobbled_deepslate')])
    return dict(start_anchor=anchor,retreat=cfg,steps=[dict(action=dict(action='follow_path',waypoints=[dict(x=2,y=60,z=0)],timeout_ms=1000),return_waypoints=[anchor],return_evidence=['reverse known segment']),dict(action=dict(action='break_block',target=dict(x=3,y=60,z=0),hotbar_slot=2,timeout_ms=1000),return_waypoints=[anchor],return_evidence=['actually walked back'])])

class Fake(m.Client):
    # Only transport/state are fake. Actual Client.note and actual constructors are used.
    def __init__(self,out,mode):self.out=Path(out);self.s=state();self.mode=mode;self.calls=[];self.records={};self.cancelled=set();self.last_source=None;self.polls={}
    def state(self):
        self.s['capability_guard_monotonic']['source_nano']=str(int(self.s['capability_guard_monotonic']['source_nano'])+1)
        self.last_source=copy.deepcopy(self.s['capability_guard_monotonic']);return copy.deepcopy(self.s)
    def request(self,method,path,body=None):
        self.calls.append((method,path,copy.deepcopy(body)))
        if method=='POST':self.note('one_shot_request',method=method,path=path,body=body)
        if path=='/control/action':
            assert body['expected_navigation_epoch']==7 and body['expected_origin']==m.idle.point(self.s['player'])
            if 'capability_guard'in body:assert body['capability_guard']==self.last_source
            self.records[body['action_id']]=copy.deepcopy(body)
            if body['action']=='break_block':
                if self.mode=='guard_start':
                    out=dict(ok=False,error='capability_source_expired',capability_source_freshness={'phase':'guard_start','schema_version':2},native_admission=dict(action_id=body['action_id'],action_session='session',action='break_block',request_payload_sha256=m.digest(body),digest_format='sorted-json-utf8/1',boundary_schema_version=2,ordinary_start_entered=True,input_transfer_entered=False,registration_entered=False,reentry_observed=False,retry_authority=False,stage='hooks_possible',reason='capability_source_expired',dispatch_authority=False,effects_none_proven=False))
                    self.note('response',http_status=409,body=out);return 409,out
                if self.mode in ('lost','lost_harm'):
                    self.s['client_action'].update(status='running',action_id=body['action_id']);self.s['held_inputs']['neutral']=False
                    raise TimeoutError('lost once POST response')
            return 202,dict(action_id=body['action_id'],action_session='session',status='running')
        if path=='/control/action/cancel':
            self.cancelled.add(body['action_id']);self.s['client_action']['status']='cancelled';self.s['held_inputs']['neutral']=True
            return 200,dict(ok=True)
        if path.startswith('/control/action/status'):
            uid=path.split('=')[1];b=self.records[uid]
            if b['action']=='break_block' and self.mode=='guard_start':return 404,dict(ok=False,error='action_not_found')
            if b['action']=='break_block' and self.mode in ('lost','lost_harm') and uid not in self.cancelled:
                self.polls[uid]=self.polls.get(uid,0)+1
                if self.mode=='lost_harm':self.s['player']['on_fire']=True
                if self.polls[uid]==1:return 200,dict(action_id=uid,action_session='session',status='running')
            status='cancelled' if uid in self.cancelled else 'succeeded';r={'input_release_confirmed':True}
            if b['action']=='follow_path':self.s['player'].update(b['waypoints'][-1])
            elif b['action']=='place_block':r.update(target=b['target'],observed_block='minecraft:cobbled_deepslate',placement_effect_verification='observed')
            self.s['client_action'].update(status=status,action_id=uid);self.s['held_inputs']['neutral']=True
            out=dict(action_id=uid,action_session='session',status=status,reason='fixture_terminal',result=r);self.note('response',http_status=200,body=out);return 200,out
        if path.startswith('/control/terrain'):
            needed=m.guard.needed_cells(self.s,{'x':3,'y':60,'z':0})
            return 200,dict(world_generation='world',cells=[dict(zip(('x','y','z'),p),id='minecraft:netherrack',status='loaded',known=True,fluid='minecraft:empty',hazards=[]) for p in needed])
        raise AssertionError(path)

class Tests(unittest.TestCase):
    @patch.object(m.time,'sleep',lambda _:None)
    def test_exact_guard_start_rejection_get404_fresh_neutral_automatically_returns_and_closes(self):
        with tempfile.TemporaryDirectory() as d:
            c=Fake(d,'guard_start');out=m.run(c,plan())
            self.assertEqual(out['phase'],'COVERED_DISARMED');self.assertTrue(out['actions'][1]['no_dispatch'])
            self.assertFalse(out['actions'][1]['original_response']['native_admission']['effects_none_proven']);self.assertFalse(out['work_success'])
            posts=[x[2] for x in c.calls if x[1]=='/control/action'];self.assertEqual(len(posts),5)
            self.assertEqual(len({x['action_id'] for x in posts}),5);self.assertEqual([x['action'] for x in posts],['follow_path','break_block','follow_path','place_block','place_block'])
            rows=[json.loads(l) for l in Path(d,'events.jsonl').read_text().splitlines()];self.assertTrue(any(x['event']=='known_unregistered_no_reissue' for x in rows))
            self.assertEqual(json.loads(Path(d,'STATUS.json').read_text())['phase'],'COVERED_DISARMED')
    @patch.object(m.time,'sleep',lambda _:None)
    def test_lost_post_running_is_followed_to_success_without_cancel_or_replay(self):
        with tempfile.TemporaryDirectory() as d:
            c=Fake(d,'lost');out=m.run(c,plan());self.assertEqual(out['phase'],'COVERED_DISARMED')
            self.assertEqual(len(c.cancelled),0);self.assertTrue(out['actions'][1]['success']);self.assertEqual(out['actions'][1]['terminal']['status'],'succeeded')
            starts=[x[2] for x in c.calls if x[1]=='/control/action'];self.assertEqual(len(starts),5);self.assertEqual(len({x['action_id'] for x in starts}),5)
    @patch.object(m.time,'sleep',lambda _:None)
    def test_original_only_escape_keeps_running_despite_fire_but_explicit_stop_cancels_once(self):
        for explicit_stop in (False,True):
            with self.subTest(explicit_stop=explicit_stop),tempfile.TemporaryDirectory() as d:
                c=Fake(d,'lost_harm');s=c.state();b=m.guard.bind_action(plan()['steps'][1]['action'],s,{'id':'minecraft:netherrack'})
                try:c.request('POST','/control/action',b)
                except TimeoutError:pass
                if explicit_stop:Path(d,'DISARM').touch()
                out=m.execute_one(c,b,s,original_only=True)
                self.assertTrue(out['released']);self.assertEqual(len(c.cancelled),int(explicit_stop))
                self.assertEqual(out['terminal']['status'],'cancelled' if explicit_stop else 'succeeded')
                self.assertEqual(len([x for x in c.calls if x[1]=='/control/action']),1)
    @patch.object(m.time,'sleep',lambda _:None)
    def test_successful_work_also_returns_and_closes_before_handoff(self):
        with tempfile.TemporaryDirectory() as d:
            c=Fake(d,'success');out=m.run(c,plan());self.assertEqual(out['phase'],'COVERED_DISARMED')
            self.assertTrue(all(a['success'] for a in out['actions']));self.assertTrue(out['work_success']);self.assertTrue(out['retreat']['closure_confirmed'])
            self.assertEqual(len([x for x in c.calls if x[1]=='/control/action']),5)
    def test_later_phase_wrong_binding_and_context_never_prove_no_dispatch(self):
        with tempfile.TemporaryDirectory() as d:
            c=Fake(d,'guard_start');s=c.state();b=m.guard.bind_action(plan()['steps'][1]['action'],s,{'id':'minecraft:netherrack'});code,o=c.request('POST','/control/action',b)
            self.assertTrue(m.guard_start_rejected(code,o,b))
            for key,val in [('stage','input_transfer'),('action_id','wrong'),('request_payload_sha256','wrong')]:
                bad=copy.deepcopy(o);bad['native_admission'][key]=val;self.assertFalse(m.guard_start_rejected(code,bad,b))
            bad=copy.deepcopy(o);bad['capability_source_freshness']['phase']='after_input_release';self.assertFalse(m.guard_start_rejected(code,bad,b))
            changed=state();changed['player']['generation']='respawn';self.assertFalse(m.fresh_released(changed,m.idle.context(state())))
if __name__=='__main__':unittest.main(verbosity=2)

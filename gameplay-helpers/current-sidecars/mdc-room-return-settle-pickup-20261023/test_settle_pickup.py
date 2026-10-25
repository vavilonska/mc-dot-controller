"""Known terminal handoff, transient air, and finite risk-aware pickup only."""
import copy,json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from test_room_http import m,Backend,Fixture,client,plan

class SettleBackend(Backend):
    def __init__(self,out,never=False):
        super().__init__(out,False);self.finished_first=False;self.air_reads=0;self.never=never;self.first_id=None
    def state(self):
        s=super().state()
        if self.finished_first:
            self.air_reads+=1
            if self.never or self.air_reads<3:
                s['player'].update(x=.098,y=60.575,z=0);s['world']['navigation_guard']['rebind_ready']=False
            else:s['player'].update(x=.04,y=60,z=0);s['world']['navigation_guard']['rebind_ready']=True
            self.s['player'].update(m.idle.point(s['player']))
        return s
    def request(self,method,path,body=None):
        if path=='/control/action' and self.first_id is None:self.first_id=body['action_id']
        code,o=super().request(method,path,body)
        if path.startswith('/control/action/status') and path.endswith(self.first_id or 'NONE') and o.get('status')=='succeeded':
            self.finished_first=True;o['result'].update(x=.04,y=60,z=0)
        return code,o

def return_cfg(s):
    cfg=plan()['retreat'];cfg.update(exposure_origin=m.idle.point(s['player']),waypoints=[dict(x=0,y=60,z=0),dict(x=1,y=61,z=0),cfg['cover_anchor']]);return cfg

class PickupBackend(Backend):
    def __init__(self,out):super().__init__(out,False);self.got_rod=False
    def request(self,method,path,body=None):
        code,o=super().request(method,path,body)
        if path.startswith('/control/action/status'):
            b=self.records.get(path.split('=')[1],{})
            if b.get('action')=='follow_path' and b['waypoints'][0].get('x')==2.5 and not self.got_rod:
                self.got_rod=True;self.s['player']['health']-=.64;self.s['player']['inventory'].append(dict(slot=9,id='minecraft:blaze_rod',count=1))
            if b.get('action')=='place_block' and b['target']['x']==3:
                o.update(status='failed',reason='support_face_not_in_reach_or_visible')
        return code,o

class Tests(unittest.TestCase):
    def test_real_http_completed_segment_air_wait_ready_only_next_id(self):
        with tempfile.TemporaryDirectory() as d:
            fx=Fixture(d,False);fx.backend=SettleBackend(d)
            with fx:
                c=client(d);s=c.state();w=m.idle.Watch(c,return_cfg(s),s);w.start_retreat(s,'test');w.step(c.state())
                first=w.body['action_id'];deadline=w.handoff_deadline
                self.assertEqual(w.phase,'SEGMENT_CHECK');self.assertFalse(w.pending)
                w.step(c.state());self.assertEqual(w.phase,'SEGMENT_CHECK');self.assertEqual(w.segment_index,0);self.assertEqual(w.body['action_id'],first)
                w.step(c.state());self.assertEqual(w.segment_index,0);self.assertEqual(w.handoff_deadline,deadline)
                w.step(c.state());self.assertEqual(w.segment_index,1);self.assertEqual(w.completed_segments,[first]);self.assertNotEqual(w.body['action_id'],first)
                self.assertEqual(w.body['waypoints'],[dict(x=1,y=61,z=0)]);self.assertEqual(w.admission_deadline,deadline)
                self.assertEqual(w.admission_response['http_status'],202);self.assertEqual(w.phase,'RETREATING')
            starts=[x[2] for x in fx.backend.calls if x[1]=='/control/action'];self.assertEqual(len(starts),2)
    def test_never_ready_dead_context_or_owner_no_new_post(self):
        for fault in ('timeout','dead','context','owner','outside'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as d:
                b=SettleBackend(d,True);c=client(d);c.request=b.request;s=b.state();w=m.idle.Watch(c,return_cfg(s),s);w.start_retreat(s,'test');w.step(b.state())
                s=b.state()
                if fault=='timeout':w.handoff_deadline=time.monotonic()-1
                if fault=='dead':s['player']['alive']=False
                if fault=='context':s['player']['generation']='new-generation'
                if fault=='owner':s['client_action']['status']='running';s['held_inputs']['neutral']=False
                if fault=='outside':s['player'].update(x=3,y=60,z=0);s['world']['navigation_guard']['rebind_ready']=True
                w.step(s);self.assertEqual(w.phase,'NEEDS_OPERATOR');self.assertEqual(w.segment_index,0)
                self.assertEqual(len([x for x in b.calls if x[1]=='/control/action']),1)
    def test_real_http_pickup_gain_small_damage_restore_failed_still_returns_seals(self):
        with tempfile.TemporaryDirectory() as d:
            fx=Fixture(d,False);fx.backend=PickupBackend(d)
            with fx:
                p=plan();p['retreat']['damage_policy']=dict(stop_health=14,max_observed_damage=4,fire_grace_seconds=2)
                p['pickup_actions']=[
                  dict(known_tunnel=True,route_evidence=['already walked floor'],action=dict(action='follow_path',waypoints=[dict(x=2.5,y=60,z=0)],timeout_ms=1000,sneak=False)),
                  dict(known_tunnel=True,route_evidence=['reverse same floor'],action=dict(action='follow_path',waypoints=[dict(x=2,y=60,z=0)],timeout_ms=1000,sneak=False)),
                  dict(route_evidence=['actual support and former rail'],action=dict(action='place_block',target=dict(x=3,y=60,z=0),support=dict(x=3,y=59,z=0),face='up',hotbar_slot=6,expected_block_id='minecraft:cobbled_deepslate',timeout_ms=1000,sneak=True,jump=False))]
                r=m.run(client(d),p)
            self.assertEqual(r['phase'],'COVERED_DISARMED');self.assertEqual(r['pickup']['observed_gain'],1);self.assertEqual(r['reason'],'support_face_not_in_reach_or_visible')
            self.assertEqual(fx.backend.hits,0);self.assertFalse(fx.backend.cancelled);self.assertTrue(r['retreat']['closure_confirmed'])
            rows=list(map(json.loads,Path(d,'events.jsonl').read_text().splitlines()));self.assertFalse(any(x['event']=='combat_armed' for x in rows))
if __name__=='__main__':unittest.main(verbosity=2)

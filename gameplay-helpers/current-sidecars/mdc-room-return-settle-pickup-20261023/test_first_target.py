"""Only the initial target acquisition branch; fixed deadline and existing risk remain."""
import json,tempfile,unittest
from pathlib import Path
from test_room_http import m,Backend,Fixture,client,plan
from damage_policy import DamagePolicy

class ArrivalBackend(Backend):
    def __init__(self,out):super().__init__(out,False);self.frames=0
    def state(self):
        self.frames+=1;s=super().state()
        if not self.hits:
            s['nearby']['entities'][0]['x']=2;s['crosshair']['location']['x']=2
        if self.frames<3:s['nearby']['entities']=[]
        elif self.hits:s['nearby']['entities']=[dict(uuid='new-other',type='minecraft:blaze',alive=True,x=1,y=60,z=0,line_of_sight=True)]
        return s

def cfg():
    c=plan()['retreat'];c.update(exposure_origin=dict(x=0,y=60,z=0),waypoints=[dict(x=0,y=60,z=0)],wait_for_first_target=True,require_target_los=True)
    return c

class Tests(unittest.TestCase):
    def test_bbox_near_edge_candidate_without_extending_final_ray_reach(self):
        with tempfile.TemporaryDirectory() as d:
            b=ArrivalBackend(d);s=b.state();e=dict(type='minecraft:blaze',uuid='edge',alive=True,x=3.2,y=60,z=0,line_of_sight=True,
              bounding_box=dict(min=dict(x=2.9,y=60,z=-.3),max=dict(x=3.5,y=61.8,z=.3)))
            self.assertTrue(m.combat.candidate_reachable(s,e));e.pop('bounding_box');self.assertFalse(m.combat.candidate_reachable(s,e))
            s['crosshair'].update(uuid='edge',location=dict(x=3.01,y=61.62,z=0));self.assertFalse(m.combat.ready_hit(s,'edge'))
    def test_real_http_unselected_wait_then_visible_arrival_one_hit_no_retarget_return(self):
        with tempfile.TemporaryDirectory() as d:
            fixture=Fixture(d,False);fixture.backend=ArrivalBackend(d)
            with fixture as fx:
                c=client(d);c.entities=True;s=c.state();f=m.combat.Fight(c,cfg(),s,100)
                self.assertIsNone(f.uid);deadline=f.deadline
                for i in range(30):
                    s=c.state();f.step(s,100+i*.2)
                    if f.phase=='RETREATING':break
                self.assertEqual(f.uid,'blaze-1');self.assertEqual(f.attack_attempts,1);self.assertEqual(f.deadline,deadline)
                self.assertEqual(f.reason,'locked_target_unavailable_no_chase')
                r=m.finish_return(c,f.escape,s,f.reason,[],f.attack_attempts)
                self.assertEqual(r['phase'],'COVERED_DISARMED');self.assertTrue(r['retreat']['closure_confirmed'])
            rows=list(map(json.loads,Path(d,'events.jsonl').read_text().splitlines()))
            self.assertEqual(sum(x['event']=='first_target_locked_once' for x in rows),1)
            self.assertEqual(fx.backend.keys[0],dict(mapping='key.use',action='down'))
    def test_no_target_fixed_15_second_deadline_never_attack_or_move_early(self):
        with tempfile.TemporaryDirectory() as d:
            b=ArrivalBackend(d);c=client(d);s=b.state();s['nearby']['entities']=[]
            c.request=b.request;f=m.combat.Fight(c,cfg(),s,100)
            f.step(s,100);self.assertEqual(f.phase,'WAIT_FIRST_TARGET');self.assertIsNone(f.uid)
            s=b.state();s['nearby']['entities']=[];f.step(s,114.99)
            self.assertEqual(f.phase,'WAIT_FIRST_TARGET');self.assertEqual(f.deadline,115)
            f.step(s,115);self.assertEqual(f.phase,'RETREAT_RELEASE');self.assertEqual(f.reason,'bout_deadline_retreat')
            self.assertEqual(f.attack_attempts,0);self.assertFalse(any(x[1]=='/control/action' for x in b.calls))
    def test_existing_damage_budget_stops_while_waiting_for_first_target(self):
        with tempfile.TemporaryDirectory() as d:
            b=ArrivalBackend(d);c=client(d);s=b.state();s['nearby']['entities']=[];c.request=b.request
            p=DamagePolicy(dict(stop_health=14,max_observed_damage=4,fire_grace_seconds=2),s)
            f=m.combat.Fight(c,cfg(),s,100,risk_policy=p);f.step(s,100)
            s=b.state();s['nearby']['entities']=[];s['player']['health']=14;f.step(s,100.2)
            self.assertEqual(f.reason,'damage_policy_stop_health');self.assertEqual(f.phase,'RETREAT_RELEASE');self.assertEqual(f.attack_attempts,0)
if __name__=='__main__':unittest.main(verbosity=2)

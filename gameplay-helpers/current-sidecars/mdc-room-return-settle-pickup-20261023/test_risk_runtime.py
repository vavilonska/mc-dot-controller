"""Only risk budget, final owned-key approach, fresh LOS and one real-HTTP complete bout."""
import copy,json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from test_room_http import m,Backend,Fixture,client,plan
from test_roundtrip import state
from damage_policy import DamagePolicy

CFG=dict(stop_health=14,max_observed_damage=4,fire_grace_seconds=2)

class ApproachBackend(Backend):
    def __init__(self,out):
        super().__init__(out,False);self.s['player'].update(x=0,y=61,z=0);self.approaching=False;self.walking=False;self.injected=False;self.prefix_hit=False;self.fight_hit=False
    def state(self):
        if self.walking:
            self.s['player'].update(x=0,y=60,z=.9)
            if not self.injected:self.s['player']['health']-=.64;self.injected=True
        s=super().state();s['player']['blocking']=s['player'].get('using_item',False)
        s['nearby']['entities']=[] if self.hits else [dict(uuid='blaze-1',type='minecraft:blaze',alive=True,x=0,y=60,z=2.9,line_of_sight=True)]
        s['crosshair']=dict(type='entity',uuid='blaze-1',entity_type='minecraft:blaze',location=dict(x=0,y=61,z=2.9))
        return s
    def request(self,method,path,body=None):
        if path=='/control/action' and body['action']=='follow_path' and not self.prefix_hit:
            self.s['player']['health']-=.2;self.prefix_hit=True
        if path=='/control/look' and self.injected and not self.fight_hit:
            self.s['player']['health']-=.1;self.fight_hit=True
        if path=='/control/key' and body['mapping']=='key.forward':
            self.walking=body['action']=='down'
            # Simulate independent actual held keys instead of treating key responses as pose proof.
            keys=set(self.s['held_inputs']['keys'])
            if self.walking:keys.add('key.forward')
            else:keys.discard('key.forward')
            self.s['held_inputs'].update(keys=sorted(keys),neutral=not keys)
        return super().request(method,path,body)

def riskplan():
    p=plan();room=dict(x=0,y=61,z=0);prior=dict(x=0,y=61,z=.2);last=dict(x=0,y=60,z=.9)
    p['start_anchor']=room;p['steps']=[
      dict(known_tunnel=True,action=dict(action='follow_path',waypoints=[prior],timeout_ms=1000,sneak=False),return_waypoints=[room],return_evidence=['walked']),
      dict(known_tunnel=True,action=dict(action='follow_path',waypoints=[last],timeout_ms=1000,sneak=False),return_waypoints=[prior,room],return_evidence=['walked'])]
    p['retreat'].update(exposure_origin=last,cover_anchor=room,waypoints=[last,prior,room],damage_policy=CFG,require_target_los=True)
    p['shield_approach']=dict(origin=prior,target=last,yaw=0,timeout_seconds=5)
    return p

class Tests(unittest.TestCase):
    def test_damage_budget_cumulative_heal_does_not_reset_and_absolute_floor(self):
        s=state();s['player']['health']=20;p=DamagePolicy(CFG,s)
        s['player']['health']=19.36;self.assertIsNone(p.observe(s,0));self.assertAlmostEqual(p.total,.64)
        s['player']['health']=20;self.assertIsNone(p.observe(s,1))
        s['player']['health']=16.6;self.assertEqual(p.observe(s,2),'damage_policy_observed_damage_limit')
        s['player']['health']=15;q=DamagePolicy(CFG,s);s['player']['health']=14
        self.assertEqual(q.observe(s,0),'damage_policy_stop_health')
    def test_fire_latched_two_seconds_or_one_known_hit_liquid_immediate(self):
        s=state();s['player']['health']=20;p=DamagePolicy(CFG,s);s['player']['on_fire']=True
        self.assertIsNone(p.observe(s,10,0));s['player']['on_fire']=False
        self.assertIsNone(p.observe(s,11.9,0));self.assertEqual(p.observe(s,12,0),'damage_policy_fire_deadline')
        q=DamagePolicy(CFG,s);s['player']['on_fire']=True;self.assertIsNone(q.observe(s,10,3))
        self.assertEqual(q.observe(s,10.2,4),'damage_policy_fire_one_known_hit_complete')
        r=DamagePolicy(CFG,s);s['player']['in_lava']=True;self.assertEqual(r.observe(s,0),'in_lava')
    def test_los_closest_and_explicit_fresh_validation(self):
        with tempfile.TemporaryDirectory() as d:
            c=client(d);s=state();s['player']['mainhand']={'id':'minecraft:iron_axe'}
            s['nearby']['entities']=[dict(uuid='wall',type='minecraft:blaze',alive=True,x=.2,y=60,z=0,line_of_sight=False),dict(uuid='visible',type='minecraft:blaze',alive=True,x=2,y=60,z=0,line_of_sight=True)]
            cfg=plan()['retreat'];cfg.update(exposure_origin=m.idle.point(s['player']),require_target_los=True)
            f=m.combat.Fight(c,cfg,s,0);self.assertEqual(f.uid,'visible')
            cfg['target_uuid']='wall'
            with self.assertRaises(m.idle.Refused):m.combat.Fight(c,cfg,s,0)
    def test_real_http_shield_approach_tolerates_small_hit_fights_then_returns(self):
        with tempfile.TemporaryDirectory() as d:
            fixture=Fixture(d,False);fixture.backend=ApproachBackend(d)
            with fixture as f:r=m.run(client(d),riskplan())
            self.assertEqual(r['phase'],'COVERED_DISARMED');self.assertEqual(r['known_attack_clicks'],1);self.assertTrue(f.backend.injected)
            self.assertTrue(f.backend.prefix_hit);self.assertTrue(f.backend.fight_hit)
            keys=f.backend.keys;forward=[x for x in keys if x['mapping']=='key.forward'];self.assertEqual([x['action'] for x in forward],['down','up'])
            i=next(i for i,x in enumerate(keys) if x['mapping']=='key.forward' and x['action']=='up')
            self.assertEqual(keys[i+1],dict(mapping='key.use',action='up'))
            starts=[x[2] for x in f.backend.calls if x[1]=='/control/action']
            # Only the prefix is an outbound follow. Last approach is raw owned forward/use, not another native start.
            before_attack=next(i for i,x in enumerate(f.backend.calls) if x[1]=='/control/key' and x[2]['mapping']=='key.attack')
            self.assertEqual(len([x for x in f.backend.calls[:before_attack] if x[1]=='/control/action']),1)
            self.assertEqual(len(starts),6);self.assertEqual(len({b['action_id'] for b in starts}),6)
            self.assertFalse(f.backend.cancelled);self.assertTrue(r['retreat']['neutral'])
    def test_final_key_read_failure_releases_each_owned_key_once_no_fight(self):
        with tempfile.TemporaryDirectory() as d:
            backend=ApproachBackend(d);c=client(d);s=backend.state();s['player'].update(z=.2)
            calls=[];reads=[0]
            def request(method,path,body=None):calls.append((path,copy.deepcopy(body)));return 200,dict(ok=True)
            def read():
                reads[0]+=1
                if reads[0]==1:
                    v=copy.deepcopy(s);v['player']['blocking']=True;return v
                if reads[0]==2:raise TimeoutError('actual observation gap')
                return s
            with patch.object(c,'request',request),patch.object(c,'state',read):
                r=m.shield_approach(c,riskplan()['shield_approach'],s,m.idle.context(s),DamagePolicy(CFG,s),20)
            self.assertFalse(r['success']);self.assertTrue(r['released'])
            self.assertEqual([b['action'] for path,b in calls if path=='/control/key' and b['mapping']=='key.forward'],['down','up'])
            self.assertEqual([b['action'] for path,b in calls if path=='/control/key' and b['mapping']=='key.use'],['down','up'])
if __name__=='__main__':unittest.main(verbosity=2)

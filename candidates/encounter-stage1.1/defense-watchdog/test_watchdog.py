import copy
import unittest
from watchdog import Watchdog

TARGET='22222222-2222-4222-8222-222222222222'
def observation():
    return {'state': {'world':{'world_generation':'test-world','game_time':100},
                      'client_action':{'action_session':'test-action-session'}, 'screen_open':False,'paused':False,
                      'player': {'uuid':'test-player','alive':True,'health':20,'inventory':[{'slot':0,'id':'minecraft:iron_sword','count':1}]},
                      'nearby': {'entities':[]}}, 'action':{'status':'idle'}, 'status':{'held_mappings':[]},
            'combat':{'active':False,'reason':'not_started','melee_closing_schema_version':2}}
class Queue:
    def __init__(self):
        self.obs=observation();self.calls=[];self.results={};self.hold_observe=False;self.start_failure=None
    def submit(self,cmd):
        self.obs['combat']['melee_closing_schema_version']=2
        p=self.obs['state']['player'];p.setdefault('x',.5);p.setdefault('y',64);p.setdefault('z',.5)
        p.setdefault('on_ground',True);p.setdefault('eye_position',{'x':.5,'y':65.62,'z':.5})
        for e in self.obs['state']['nearby']['entities']:
            e.setdefault('x',p['x']+e.get('distance',2));e.setdefault('y',p['y']);e.setdefault('z',p['z'])
            e.setdefault('bounding_box',{'min':{'x':e['x']-.3,'y':e['y'],'z':e['z']-.3},'max':{'x':e['x']+.3,'y':e['y']+1.95,'z':e['z']+.3}})
        key=str(len(self.calls)+1);self.calls.append((key,copy.deepcopy(cmd)))
        op=cmd['op'];result={}
        if op=='observe':
            if self.hold_observe:return key
            self.obs['state']['world']['game_time'] += 1
            result=copy.deepcopy(self.obs)
        elif op=='cancel':
            for old,oldcmd in self.calls[:-1]:
                if oldcmd['op']=='action' and old not in self.results:
                    self.results[old]={'status':'cancelled','reason':'cancel_requested'}
            self.obs['action']['status']='cancelled'
            if self.obs['combat'].get('active') or self.obs['combat'].get('held_mappings'):
                self.obs['combat'].update(active=False,phase='stopped',reason='explicit_cancel')
            self.obs['combat']['melee_closing_schema_version']=2
            result={'ok':True}
        elif op=='combat_start':
            if self.start_failure:
                self.results[key]=copy.deepcopy(self.start_failure);return key
            self.obs['combat']={'active':True,'target_uuid':cmd['target_uuid'],'reason':'tracking_hostile','attack_attempts':0,'melee_closing_schema_version':2}
            result=copy.deepcopy(self.obs['combat'])
        elif op=='action':
            self.obs['action']['status']='running';return key
        self.results[key]={'status':'succeeded','result':result}
        return key
    def result(self,key):return self.results.get(key)
class Checks(unittest.TestCase):
    def setUp(self):
        self.now=0;self.q=Queue();self.d=Watchdog(self.q,clock=lambda:self.now)
    def tick(self,n=1,step=.1):
        for _ in range(n):self.d.tick();self.now+=step
    def threat(self,kind='minecraft:zombie',distance=2):
        self.q.obs['state']['nearby']['entities']=[{'uuid':TARGET,'type':kind,'alive':True,'health':20,'distance':distance}]
    def ready(self):self.tick(2)
    def ops(self):return [c['op'] for _,c in self.q.calls]
    def test_no_io_at_construction(self):self.assertEqual(self.q.calls,[])
    def test_idle_thinking_gap_detects_and_starts_combat(self):
        self.threat();self.tick(8)
        self.assertEqual(self.ops()[:4],['observe','cancel','observe','combat_start'])
        self.assertEqual(self.d.phase,'combat');self.assertEqual(self.d.started_target,TARGET)
        self.assertTrue(next(c for _,c in self.q.calls if c['op']=='combat_start')['approach'])
    def test_navigation_is_cancelled_before_fresh_target_start(self):
        self.ready();self.assertTrue(self.d.submit_owner('walk',{'op':'action','action':'follow_path','waypoints':[]}))
        self.threat();self.tick(15)
        self.assertLess(self.ops().index('cancel'),self.ops().index('combat_start'))
        self.assertEqual(self.d.completed[0]['result']['status'],'cancelled')
    def test_no_owner_navigation_or_chat_can_override_active_combat(self):
        self.threat();self.tick(8)
        before=len(self.q.calls)
        self.assertFalse(self.d.submit_owner('walk',{'op':'action'}))
        self.assertFalse(self.d.submit_owner('chat',{'op':'direct','endpoint':'command'}))
        self.assertEqual(before,len(self.q.calls))
    def test_target_death_then_safe_observation_allows_new_owner_task(self):
        self.threat();self.tick(8)
        self.q.obs['combat']={'active':False,'reason':'combat_aim_released_target_dead'}
        self.q.obs['state']['nearby']['entities']=[]
        self.tick(8)
        for _ in range(10):
            if self.d.submit_owner('newwalk',{'op':'action'}):break
            self.tick()
        self.assertIsNotNone(self.d.owner)
    def test_player_or_pet_is_never_targeted(self):
        for kind in ('minecraft:player','minecraft:wolf','minecraft:cat','minecraft:piglin'):
            self.threat(kind);self.tick(8)
        self.assertNotIn('combat_start',self.ops())
    def test_threat_beyond_six_blocks_does_not_start(self):
        self.threat(distance=7);self.tick(8);self.assertNotIn('combat_start',self.ops())
    def test_stop_marker_path_cancels_once_then_ends(self):
        self.threat();self.tick(8);self.d.stop();self.tick(3)
        self.assertTrue(self.d.stopped);self.assertTrue(self.d.cancel_confirmed)
        calls=len(self.q.calls);self.tick(5);self.assertEqual(calls,len(self.q.calls))
    def test_uncertain_cancel_is_not_retried_or_followed_by_attack(self):
        self.threat();self.tick(2)
        self.q.results[self.d.rpc['id']]={'status':'uncertain','reason':'transport_failed'}
        self.tick(15)
        self.assertFalse(self.d.armed);self.assertNotIn('combat_start',self.ops())
        self.assertEqual(self.ops().count('cancel'),1)
    def test_pending_observation_requests_cancel_after_two_seconds(self):
        self.q.hold_observe=True;self.tick();self.now=3;self.tick()
        self.assertEqual(self.ops(),['observe','cancel']);self.assertFalse(self.d.armed)
    def test_missing_weapon_does_not_claim_combat_started(self):
        self.q.obs['state']['player']['inventory']=[];self.threat();self.tick(10)
        self.assertEqual(self.d.reason,'threat_without_hotbar_weapon');self.assertNotIn('combat_start',self.ops())
    def test_dead_player_requires_operator_recovery_and_never_respawns(self):
        self.q.obs['state']['player'].update(alive=False,health=0);self.tick(20)
        self.assertFalse(self.d.armed);self.assertEqual(self.ops().count('cancel'),1)
        self.assertTrue(set(self.ops())<= {'observe','cancel'})
    def test_damage_with_unknown_attacker_cancels_navigation(self):
        self.ready();self.d.submit_owner('walk',{'op':'action'});self.q.obs['state']['player']['health']=16
        self.tick(12);self.assertIn('cancel',self.ops());self.assertTrue(self.d.armed)
        self.assertNotIn('combat_start',self.ops());self.assertEqual(self.d.targeting.last_damage['source'],'unknown')
    def test_target_changes_before_start_are_reobserved_not_blindly_replayed(self):
        self.threat();self.q.start_failure={'status':'failed','reason':'combat_target_not_observed_hostile'}
        self.tick(5);self.q.obs['state']['nearby']['entities']=[];self.tick(10)
        self.assertTrue(self.d.armed);self.assertEqual(self.ops().count('combat_start'),1)
    def test_stopped_combat_failure_does_not_restart_forever(self):
        self.threat();self.tick(8);self.q.obs['combat']={'active':False,'reason':'combat_flat_approach_blocked'}
        self.tick(12);self.assertTrue(self.d.armed);self.assertEqual(self.ops().count('combat_start'),1)
        self.assertEqual(self.d.phase,'watching')
    def test_only_one_owner_request_at_a_time(self):
        self.ready();self.assertTrue(self.d.submit_owner('a',{'op':'action'}))
        self.assertFalse(self.d.submit_owner('b',{'op':'action'}))
    def test_no_resubmission_while_owner_action_pending(self):
        self.ready();self.d.submit_owner('a',{'op':'action'});self.tick(20)
        self.assertEqual(self.ops().count('action'),1)
    def test_failed_observation_cancels_navigation_before_disarming(self):
        self.ready();self.d.submit_owner('walk',{'op':'action'})
        self.q.hold_observe=True;self.tick(5)
        self.assertEqual(self.d.rpc['kind'],'observe')
        self.q.results[self.d.rpc['id']]={'status':'failed','reason':'transport_failed'}
        self.tick(3)
        self.assertIn('cancel',self.ops());self.assertEqual(self.q.obs['action']['status'],'cancelled')
        self.assertFalse(self.d.armed)
    def test_uncertain_owner_action_cannot_admit_new_input(self):
        self.ready();self.d.submit_owner('walk',{'op':'action'})
        self.q.results[self.d.owner['request_id']]={'status':'uncertain','reason':'transport_failed'}
        self.tick()
        self.assertFalse(self.d.armed);self.assertFalse(self.d.submit_owner('new',{'op':'direct'}))
        self.assertIn('cancel',self.ops())
    def test_stop_false_ok_is_not_confirmed_release(self):
        self.ready();self.d.stop();self.tick()
        self.q.results[self.d.rpc['id']]={'status':'succeeded','result':{'ok':False}}
        self.tick()
        self.assertTrue(self.d.stopped);self.assertFalse(self.d.cancel_confirmed)
        self.assertEqual(self.d.reason,'input_release_unconfirmed')
    def test_false_ok_threat_cancel_never_starts_combat(self):
        self.threat();self.tick(2)
        self.q.results[self.d.rpc['id']]={'status':'succeeded','result':{'ok':False}}
        self.tick(5)
        self.assertFalse(self.d.armed);self.assertNotIn('combat_start',self.ops())
    def test_inherited_active_combat_failure_is_not_restarted(self):
        self.threat();self.q.obs['combat']={'active':True,'target_uuid':TARGET,'reason':'tracking_hostile'}
        self.tick(3)
        self.q.obs['combat']={'active':False,'reason':'combat_flat_approach_blocked'}
        self.tick(8)
        self.assertTrue(self.d.armed);self.assertNotIn('combat_start',self.ops())
        self.assertEqual(self.d.phase,'watching')
if __name__=='__main__':unittest.main()

import copy
import importlib.util
import math
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from watchdog import Watchdog
from ranged_tactics import RangedMemory, retreat_plan
from test_watchdog import Queue, TARGET


def witch():
    return {'uuid':TARGET,'entity_id':4,'type':'minecraft:witch','alive':True,'health':26,'distance':4,
            'x':4.5,'y':64,'z':.5,
            'bounding_box':{'min':{'x':4.2,'y':64,'z':.2},'max':{'x':4.8,'y':65.95,'z':.8}}}


def terrain():
    cells=[]
    for x in range(-4,6):
        for z in range(-4,5):
            for y in range(63,67):
                floor=y==63
                cells.append({'x':x,'y':y,'z':z,'status':'loaded','known':True,'collision_known':True,
                              'fluid':'minecraft:empty','hazards':[],'full_top_support':floor,
                              'collision_empty':not floor,'collision_bounds':[0,0,0,1,1,1] if floor else []})
    return {'complete':True,'world_generation':'test-world','cells':cells}


class RangedQueue(Queue):
    def __init__(self):
        super().__init__()
        self.obs['state']['player'].update(x=.5,y=64,z=.5,on_ground=True,
             eye_position={'x':.5,'y':65.62,'z':.5},selected_slot=0,offhand={'id':'minecraft:shield','count':1})
        self.obs['state']['nearby'].update(entities=[witch()],truncated=False)
        self.obs['status']={'held_mappings':[]}
        self.obs['state']['crosshair']={'type':'miss'}
        self.terrain=terrain()
        self.obs['combat']['melee_closing_schema_version']=2
    def submit(self,command):
        self.obs['combat']['melee_closing_schema_version']=2
        request=super().submit(command)
        self.obs['combat']['melee_closing_schema_version']=2
        if command['op']=='observe' and request in self.results and command.get('terrain'):
            self.results[request]['result']['terrain']=copy.deepcopy(self.terrain)
        if command['op']=='combat_start' and self.results[request]['status']=='succeeded':
            self.obs['combat'].update(phase='waiting_in_range',attack_dispatches=0,request_id=request,melee_closing_schema_version=2)
            self.results[request]['result']=copy.deepcopy(self.obs['combat'])
        return request


class RangedIntegrationChecks(unittest.TestCase):
    def setUp(self):
        self.now=0;self.q=RangedQueue();self.d=Watchdog(self.q,clock=lambda:self.now)
    def tick(self,n=1,step=.1):
        for _ in range(n):self.d.tick();self.now+=step
    def ops(self,op):return [c for _,c in self.q.calls if c['op']==op]
    def until(self,predicate,steps=100):
        for _ in range(steps):
            if predicate():return
            self.tick()
        self.fail('expected phase not reached: '+str(self.d.status()))
    def test_witch_uses_existing_approach_without_false_potion_shield(self):
        self.tick(8)
        start=self.ops('combat_start')[0]
        self.assertTrue(start['approach']);self.assertFalse(start['shield'])
        self.assertFalse(self.d.status()['ranged']['shield_blocks_potions_confirmed'])
    def test_unpatched_resident_never_enables_sampled_approach(self):
        self.d.latest=copy.deepcopy(self.q.obs)
        self.d.latest['combat'].pop('melee_closing_schema_version',None)
        self.d.send('start_combat',{'op':'combat_start','target_uuid':TARGET,'approach':False,'shield':True})
        self.assertEqual(self.ops('combat_start'),[])
        self.assertEqual(self.d.ranged_context['reason'],'patched_melee_closing_required')

    def test_no_closing_progress_exits_static_lock_and_uses_known_retreat(self):
        self.until(lambda:self.d.ranged_move is not None)
        self.assertEqual(len(self.ops('combat_start')),1)
        self.assertEqual(len(self.ops('action')),1)
        route=self.ops('action')[0]['waypoints']
        self.assertLessEqual(len(route),2);self.assertLess(route[-1]['x'],.5)
        self.assertGreater(self.d.targeting.excluded[TARGET],self.now)
    def test_unknown_terrain_releases_navigation_without_blind_move_or_regrab(self):
        self.q.terrain={'complete':False,'cells':[]}
        self.tick(110)
        self.assertEqual(self.ops('action'),[]);self.assertEqual(len(self.ops('combat_start')),1)
        self.assertTrue(self.d.armed);self.assertEqual(self.d.phase,'watching')
    def test_poison_does_not_cancel_short_verified_retreat(self):
        self.until(lambda:self.d.ranged_move is not None)
        before=len(self.ops('cancel'))
        for hp in (19,18,17):
            self.q.obs['state']['player']['health']=hp;self.tick(4)
        self.assertEqual(len(self.ops('cancel')),before);self.assertIsNotNone(self.d.ranged_move)
    def test_retreat_success_is_observed_then_navigation_released(self):
        self.until(lambda:self.d.ranged_move is not None)
        request=self.d.ranged_move['id'];end=self.ops('action')[0]['waypoints'][-1]
        self.q.obs['state']['player'].update(end);self.q.obs['action']['status']='succeeded'
        self.q.results[request]={'status':'succeeded','result':{}}
        self.tick(4)
        self.assertIsNone(self.d.ranged_move);self.assertEqual(self.d.phase,'watching')
        self.assertGreater(self.d.ranged_last['actual_distance'],4)
    def test_manual_takeover_of_retreat_remains_hard_pause(self):
        self.until(lambda:self.d.ranged_move is not None)
        request=self.d.ranged_move['id']
        self.q.results[request]={'status':'cancelled','reason':'direct_takeover'}
        self.tick(5);self.assertFalse(self.d.armed)
        self.assertEqual(self.d.reason,'ranged_retreat_interrupted_owner_control')
    def test_new_action_owner_before_retreat_dispatch_prevents_action(self):
        self.until(lambda:self.d.rpc and self.d.rpc['kind']=='ranged_fresh')
        self.q.results[self.d.rpc['id']]['result']['action']['status']='running'
        self.tick();self.assertEqual(self.ops('action'),[]);self.assertFalse(self.d.armed)
    def test_changed_action_session_before_retreat_prevents_action(self):
        self.until(lambda:self.d.rpc and self.d.rpc['kind']=='ranged_fresh')
        self.q.results[self.d.rpc['id']]['result']['state']['client_action']['action_session']='replacement'
        self.tick();self.assertEqual(self.ops('action'),[]);self.assertFalse(self.d.armed)
    def test_new_held_manual_key_prevents_retreat(self):
        self.until(lambda:self.d.rpc and self.d.rpc['kind']=='ranged_fresh')
        self.q.results[self.d.rpc['id']]['result']['status']['held_mappings']=['key.forward']
        self.tick();self.assertEqual(self.ops('action'),[]);self.assertFalse(self.d.armed)
    def test_late_available_terrain_cannot_be_stamped_fresh(self):
        self.until(lambda:self.d.rpc and self.d.rpc['kind']=='ranged_terrain')
        self.now+=10;self.tick()
        self.assertEqual(self.ops('action'),[]);self.assertEqual(self.d.reason,'ranged_late_observation_no_blind_movement')
    def test_late_available_fresh_state_cannot_dispatch_retreat(self):
        self.until(lambda:self.d.rpc and self.d.rpc['kind']=='ranged_fresh')
        self.now+=10;self.tick();self.assertEqual(self.ops('action'),[])
    def test_stop_during_retreat_has_stopped_not_busy_status(self):
        self.until(lambda:self.d.ranged_move is not None)
        self.d.stop();self.tick(3)
        self.assertTrue(self.d.stopped);self.assertTrue(self.d.cancel_confirmed)
        self.assertEqual(self.d.status()['state'],'stopped')
    def test_owner_escape_grace_requires_actual_separation_progress(self):
        self.q.terrain={'complete':False,'cells':[]};self.tick(45)
        command={'op':'action','action':'follow_path','waypoints':[{'x':-1.5,'y':64,'z':.5}],
                 '_navigation_defense_epoch':self.d.defense_epoch}
        self.until(lambda:self.d.rpc is None)
        self.assertTrue(self.d.submit_owner('escape',command))
        state=copy.deepcopy(self.q.obs['state'])
        self.d.observe_escape_progress(state);self.assertTrue(self.d.damage_requires_cancel(state))
        state['player']['x']=-.5
        self.d.observe_escape_progress(state);self.assertFalse(self.d.damage_requires_cancel(state))
        self.d.observe_escape_progress(state);self.assertTrue(self.d.damage_requires_cancel(state))
    def test_stationary_after_undamaged_progress_does_not_keep_escape_grace(self):
        self.q.terrain={'complete':False,'cells':[]};self.tick(45)
        self.until(lambda:self.d.rpc is None)
        self.assertTrue(self.d.submit_owner('escape',{'op':'action','action':'follow_path',
                           'waypoints':[{'x':-1.5,'y':64,'z':.5}],
                           '_navigation_defense_epoch':self.d.defense_epoch}))
        self.q.obs['state']['player']['x']=-.5;self.tick(10)
        count=len(self.ops('cancel'))
        self.q.obs['state']['player']['health']=19;self.tick(8)
        self.assertGreater(len(self.ops('cancel')),count)

    def test_escape_progress_uses_observation_identity_with_advancing_clock(self):
        self.q.terrain={'complete':False,'cells':[]};self.tick(45)
        self.until(lambda:self.d.rpc is None)
        self.assertTrue(self.d.submit_owner('escape',{'op':'action','action':'follow_path',
                           'waypoints':[{'x':-1.5,'y':64,'z':.5}],
                           '_navigation_defense_epoch':self.d.defense_epoch}))
        def advancing_clock():
            self.now+=.000001
            return self.now
        self.d.clock=advancing_clock
        state=copy.deepcopy(self.q.obs['state']);state['player']['x']=-.5
        self.d.observe_escape_progress(state)
        self.assertFalse(self.d.damage_requires_cancel(state))
        self.assertTrue(self.d.damage_requires_cancel(copy.deepcopy(state)))

    def test_uncertain_retreat_never_replays_movement(self):
        self.until(lambda:self.d.ranged_move is not None)
        request=self.d.ranged_move['id'];self.q.results[request]={'status':'uncertain','reason':'transport_failed'}
        self.tick(8)
        self.assertFalse(self.d.armed);self.assertEqual(len(self.ops('action')),1)


class RangedPolicyChecks(unittest.TestCase):
    def test_reentry_does_not_reset_zero_attack_budget(self):
        q=RangedQueue();s=q.obs['state'];t=witch();memory=RangedMemory()
        memory.begin(s,t,0);memory.begin(s,t,4)
        self.assertEqual(memory.records[TARGET]['started_at'],0)
        reason=memory.observe(s,t,{'active':True,'target_uuid':TARGET,'attack_dispatches':0,'request_id':'again'},6,False)
        self.assertIn(reason,('no_observed_closing_progress','no_attack_dispatch_before_deadline'))
    def test_two_distinct_lost_sessions_without_attack_exit(self):
        q=RangedQueue();m=RangedMemory();m.begin(q.obs['state'],witch(),0)
        for i in (1,2):
            result=m.observe(q.obs['state'],None,{'active':False,'target_uuid':TARGET,'request_id':str(i),
                              'reason':'combat_aim_released_target_missing','attack_dispatches':0},i,False)
        self.assertEqual(result,'repeated_target_loss_without_attack')
    def test_dispatch_without_observed_health_progress_is_bounded(self):
        q=RangedQueue();m=RangedMemory();m.begin(q.obs['state'],witch(),0)
        reason=m.observe(q.obs['state'],witch(),{'active':True,'target_uuid':TARGET,'attack_dispatches':7,'request_id':'one'},7,False)
        self.assertEqual(reason,'no_observed_target_health_progress')
    def test_dry_flat_retreat_is_bounded_and_never_claims_safe_cover(self):
        q=RangedQueue();plan=retreat_plan(q.obs['state'],terrain(),witch())
        self.assertIsNotNone(plan);self.assertLessEqual(len(plan['waypoints']),2)
        self.assertGreater(plan['planned_distance'],plan['initial_distance'])
        self.assertFalse(plan['safe_position_guaranteed'])
    def test_fluid_unknown_floor_and_different_world_reject(self):
        q=RangedQueue()
        for change in ('water','unknown','world'):
            land=terrain()
            if change=='world':land['world_generation']='other'
            else:
                for cell in land['cells']:
                    if change=='water':cell['fluid']='minecraft:water'
                    else:cell['known']=False
            self.assertIsNone(retreat_plan(q.obs['state'],land,witch()))
    def test_swept_corner_unknown_cell_cannot_be_skipped_by_sampling(self):
        q=RangedQueue();q.obs['state']['player'].update(x=.01,z=.12)
        target=witch();target.update(x=-4,z=.12)
        allowed={(-1,-1),(-1,0),(0,-1),(0,0),(1,0),(2,0)}
        land=terrain();land['cells']=[c for c in land['cells'] if (c['x'],c['z']) in allowed]
        plan=retreat_plan(q.obs['state'],land,target)
        if plan:self.assertNotIn({'x':1.5,'y':64,'z':.5},plan['waypoints'])
    def test_no_retreat_toward_another_observed_hostile(self):
        q=RangedQueue();other=witch();other.update(uuid='other',type='minecraft:zombie',x=-1.5,distance=2)
        q.obs['state']['nearby']['entities'].append(other)
        plan=retreat_plan(q.obs['state'],terrain(),witch())
        if plan:self.assertTrue(all(p['x']>=.5 for p in plan['waypoints']))


class EyeReachPatchChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from resident_controller import native_combat
        cls.module=native_combat
    def sample(self):
        q=RangedQueue();s=q.obs['state'];s['player']['selected_slot']=0
        t=witch();t.update(type='minecraft:zombie',x=.5,y=65,z=3.5,distance=3)
        t['bounding_box']={'min':{'x':.2,'y':65,'z':3.2},'max':{'x':.8,'y':66.95,'z':3.8}}
        s['nearby']['entities']=[t]
        s['crosshair']={'type':'entity','uuid':TARGET,'entity_id':4,'entity_type':t['type'],
                        'location':{'x':.5,'y':65.94,'z':3.2},'distance_euclidean':math.hypot(2.7,1.94)}
        return s,t
    def test_actual_eye_distance_accepts_legal_pick_despite_large_feet_distance(self):
        s,t=self.sample();self.assertGreater(s['crosshair']['distance_euclidean'],3)
        self.assertTrue(self.module.crosshair_target_in_reach(s,TARGET,4,t['type']))
    def test_missing_hit_location_never_guesses_from_legacy_distance(self):
        s,t=self.sample();del s['crosshair']['location'];s['crosshair']['distance_euclidean']=1
        self.assertFalse(self.module.crosshair_target_in_reach(s,TARGET,4,t['type']))
    def test_wrong_uuid_or_too_far_eye_point_is_not_attackable(self):
        s,t=self.sample();self.assertFalse(self.module.crosshair_target_in_reach(s,'other',4,t['type']))
        s['crosshair']['location']['z']=5
        self.assertFalse(self.module.crosshair_target_in_reach(s,TARGET,4,t['type']))
    def test_unpicked_aabb_at_three_blocks_keeps_closing(self):
        s,t=self.sample();s['world']['game_time']=101;s['crosshair']={'type':'miss'}
        t.update(y=64,z=3.8);t['bounding_box']={'min':{'x':.2,'y':64,'z':3.5},'max':{'x':.8,'y':65.95,'z':4.1}}
        calls=[]
        def request(method,path,body=None):
            calls.append((method,path,body));return copy.deepcopy(s) if method=='GET' else {'ok':True}
        land=terrain();cache=SimpleNamespace(terrain_received_at=1.0,state=s,cells={(c['x'],c['y'],c['z']):c for c in land['cells']})
        resident=SimpleNamespace(paused=False,active=None,pending=[],cache=cache,bridge=SimpleNamespace(request=request),
             bridge_identity={'action_session':'test'},aim=SimpleNamespace(active=True,target_uuid=TARGET,prepare=lambda *a:None))
        combat=self.module.NativeCombat().prepare({'target_uuid':TARGET,'shield':False},s)
        combat.last_tick=100
        with patch('time.monotonic',return_value=1.0):combat.advance(resident)
        self.assertEqual(combat.phase,'approaching')
        self.assertTrue(any(b=={'mapping':'key.forward','action':'down'} for _,_,b in calls))

    def test_approach_swept_corner_cannot_skip_lava_between_samples(self):
        s,t=self.sample();s['player'].update(x=.01,y=64,z=.12)
        t.update(x=3.885936,y=64,z=1.108494)
        cells={(c['x'],c['y'],c['z']):c for c in terrain()['cells']}
        for key,cell in cells.items():
            if key[0]==1 and key[2]==-1:cell['fluid']='minecraft:lava'
        self.assertFalse(self.module.flat_corridor_clear(s,t,cells))

if __name__=='__main__':unittest.main()

"""Synthetic state-machine/geometry tests. These are not live End acceptance."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from mdc_skills import expedition as ex, dimensions, threats
from mdc_skills.core import Observation, Outcome, SkillError, atomic_write


def cell(x, y, z, solid=False, kind=None):
    return dict(x=x, y=y, z=z, id=kind or ('minecraft:end_stone' if solid else 'minecraft:air'),
        status='loaded', known=True, id_truncated=False, properties_truncated=False, properties={},
        collision_known=True, collision_empty=not solid, full_top_support=solid,
        collision_bounds=[0, 0, 0, 1, 1, 1] if solid else [], fluid='minecraft:empty',
        fluid_truncated=False, hazards=[], air=not solid)


def sample(*, tick=1, x=.5, y=64, z=.5, entities=(), items=(), gateways=()):
    rows = [dict(slot=i, id=item, count=count, empty=False) for i, (item, count) in enumerate(items)]
    player = dict(x=x, y=y, z=z, eye_position=dict(x=x, y=y+1.62, z=z),
        health=20, max_health=20, food=20, on_ground=True, alive=True, selected_slot=0, effects_truncated=False, effects=[],
        inventory=rows, inventory_total=len(rows), inventory_truncated=False,
        armor=[{'slot': 'head', 'id': 'minecraft:carved_pumpkin'}],
        **{k: False for k in threats.ENVIRONMENT_FLAGS})
    world = dict(world_generation='world', dimension=dimensions.END, game_time=tick)
    nearby = dict(entities=list(entities), truncated=False, returned=len(entities), total=len(entities),
        end_gateways=list(gateways), end_gateways_truncated=False)
    cells = [cell(a,b,c,b==y-1) for a in range(int(x)-6,int(x)+7)
             for b in range(y-2,y+7) for c in range(int(z)-6,int(z)+7)]
    terrain = dict(complete=True, world_generation='world', dimension=dimensions.END, cells=cells)
    return Observation(dict(player=player,world=world,nearby=nearby),terrain,{},tick,
                       ('world',dimensions.END,'player','session'),0,'obs-'+str(tick))


def entity(kind, uid='one', hp=20, **kw):
    return dict(uuid=uid,entity_id=1,type='minecraft:'+kind,alive=hp>0,health=hp,x=.5,y=64,z=2.5,**kw)


def settings(**kw):
    return dict(boxes=1,max_actions=32,max_seconds=7200,max_walk_distance=100,
        max_search_steps=20,max_crystals=16,max_dragon_strikes=256,max_shulker_strikes=64,
        block_id='minecraft:cobblestone',min_health=12,**kw)


def data(phase='dragon'):
    now=time.time()
    return dict(schema_version=1,job_id='test',settings=settings(),owner='owner',context=['world',dimensions.END,'player','session'],
        phase=phase,status='active',inflight=None,created_unix=now,deadline_unix=now+7200,last_wall_clock=now,
        actions_reserved=0,walk_reserved=0.,search_steps=0,completed_steps=0,request_ids=[],visited={},
        crystals={},crystal_work=None,dragon=None,dragon_damage=[],gateway=None,outer_origin=None,
        shulker_target=None,shulker_entity_id=None,shulkers_dead=[],shulker_damage=[],initial_shells=0,
        initial_boxes=0,sword='minecraft:iron_sword',pickaxe='minecraft:iron_pickaxe')


class FakeRuntime:
    def __init__(self, root, observations=(), status='succeeded'):
        self.journal_directory=Path(root)
        self._mutex=threading.RLock();self._owner='owner'
        self.has_unresolved_execution=False;self.pending_request_id=None
        self.observations=list(observations);self.commands=[];self.status=status;self.sleeps=[];self.evidence={}
        self.sleeper=self.sleeps.append
    def _open(self):pass
    def observe(self, **kwargs):
        assert self.observations, 'unexpected observe'
        return self.observations.pop(0)
    def execute(self, skill, command, verify, **kwargs):
        self.commands.append(deepcopy(command))
        # Submission must already be durable, even if transport now fails.
        checkpoints=list(self.journal_directory.glob('end-expedition-*.json'))
        if checkpoints:
            checkpoint=ex._read(checkpoints[0])
            assert checkpoint['actions_reserved'] == len(self.commands)
            assert checkpoint['inflight'] is not None
        return Outcome(self.status,self.status,('req-'+str(len(self.commands)),),deepcopy(self.evidence),kwargs.get('before'))
    def require_success(self, result):
        if not result.ok:raise SkillError(result.reason,status=result.status)
        return result.last_observation
    def result(self, skill, observations=(), **evidence):
        values=list(observations)
        return Outcome('succeeded',skill,(),dict(server_confirmed=False,**evidence),values[-1])


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
    def test_impossible_pearl_health_setting_stops_before_observation_or_mutation(self):
        runtime=FakeRuntime(self.directory.name)
        with self.assertRaisesRegex(SkillError,'less15'):
            ex.end_expedition(runtime,job_id='health',min_health=15)
        self.assertFalse(runtime.commands)
    def test_actual_max_health_must_cover_pearl_cost_before_checkpoint_admission(self):
        before=sample();before.player['max_health']=16
        runtime=FakeRuntime(self.directory.name,[before])
        with self.assertRaisesRegex(SkillError,'max_health_cannot_cover'):
            ex.end_expedition(runtime,job_id='health')
        self.assertFalse(runtime.commands)
        self.assertFalse(ex._path(runtime,'health').exists())


class KnownNoShotTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.runtime=FakeRuntime(self.directory.name,status='failed');self.data=data('gateway')
        self.runner=ex._Runner(self.runtime,ex._path(self.runtime,'test'),self.data)
        self.runtime.evidence={'native':{'action':'gateway_pearl','status':'failed','result':
            {'dispatched':False,'input_release_confirmed':True}}}
    def execute(self,callback):
        return self.runner.step('gateway',lambda:self.runner.execute('gateway',
            {'op':'action','action':'gateway_pearl','timeout_ms':50},lambda a,b:False,before=sample()),
            known_no_effect=callback)
    def test_explicit_released_no_shot_can_return_without_rethrow(self):
        updates=[];self.execute(lambda result:updates.append(result.reason))
        self.assertEqual(updates,['failed']);self.assertIsNone(self.data['inflight'])
        self.assertEqual(self.data['request_ids'],['req-1']);self.assertEqual(len(self.runtime.commands),1)
    def test_missing_dispatched_flag_is_never_no_effect(self):
        del self.runtime.evidence['native']['result']['dispatched']
        updates=[]
        with self.assertRaises(SkillError):self.execute(lambda result:updates.append(result))
        self.assertFalse(updates);self.assertIsNotNone(self.data['inflight'])
    def test_dispatched_shot_is_never_replayed_or_classified_no_effect(self):
        self.runtime.evidence['native']['result']['dispatched']=True
        updates=[]
        with self.assertRaises(SkillError):self.execute(lambda result:updates.append(result))
        self.assertFalse(updates);self.assertIsNotNone(self.data['inflight'])
    def test_unknown_cannot_trigger_return_even_if_payload_claims_no_shot(self):
        self.runtime.status='unknown';updates=[]
        with self.assertRaises(SkillError):self.execute(lambda result:updates.append(result))
        self.assertFalse(updates);self.assertIsNotNone(self.data['inflight'])


class GeometryTests(unittest.TestCase):
    def test_only_observed_supported_frontier(self):
        s=sample();p=ex.choose_frontier(s,{},toward={'x':50,'y':64,'z':0})
        self.assertTrue(ex._standable(s,p));self.assertLessEqual(p['x'],6)
        self.assertGreater(p['x'],0)
    def test_unknown_void_not_walkable(self):
        s=sample()
        for c in s.terrain['cells']:
            if c['x']>0 and c['y']==63:c['known']=False
        routes=ex.observed_routes(s)
        self.assertTrue(all(v[-1]['x']<=0 for v in routes.values()))
    def test_no_fresh_frontier_is_honest_blocker(self):
        s=sample();visited={key:3 for key in ex.observed_routes(s)}
        with self.assertRaisesRegex(SkillError,'no_fresh_reachable'):ex.choose_frontier(s,visited)
    def test_single_step_up_and_overhead_are_checked(self):
        s=sample()
        for c in s.terrain['cells']:
            if c['x']==1 and c['z']==0 and c['y']==64:c.update(cell(1,64,0,True))
        routes=ex.observed_routes(s)
        self.assertIn('1,65,0',routes)
        for c in s.terrain['cells']:
            if c['x']==0 and c['z']==0 and c['y']==66:c.update(cell(0,66,0,True))
        # The direct up edge is excluded; a genuinely observed detour can remain.
        routes=ex.observed_routes(s)
        self.assertNotEqual(routes.get('1,65,0'),[{'x':0,'y':64,'z':0},{'x':1,'y':65,'z':0}])
    def test_calm_enderman_requires_pumpkin_aggression_evidence(self):
        calm=entity('enderman',aggressive=False)
        s=sample(entities=[calm]);ex._safe_exposure(s,12)
        s.player['armor']=[]
        with self.assertRaisesRegex(SkillError,'pumpkin'):ex._safe_exposure(s,12)
        s.player['armor']=[{'slot':'head','id':'minecraft:carved_pumpkin'}]
        calm['aggressive']=True
        with self.assertRaisesRegex(SkillError,'angry_enderman'):ex._safe_exposure(s,12)
    def test_levitation_not_safe_landing(self):
        s=sample();s.player['effects']=[{'id':'minecraft:levitation'}]
        with self.assertRaisesRegex(SkillError,'unsafe_end_effect'):ex._safe_exposure(s,12)
    def test_gateway_requires_exact_fresh_loaded_export(self):
        g=dict(x=90,y=75,z=0,id='minecraft:end_gateway',properties={},cooling_down=False,loaded=True)
        s=sample(gateways=[g]);self.assertEqual(ex._gateways(s),[{'x':90,'y':75,'z':0}])
        s.state['nearby']['end_gateways_truncated']=True
        with self.assertRaisesRegex(SkillError,'complete_loaded_gateway'):ex._gateways(s)
    def test_crystal_base_is_derived_from_observed_target(self):
        s=sample();c=entity('end_crystal');c.update(x=2.5,y=85,z=.5)
        candidates=ex._base_candidates(s,c)
        self.assertTrue(candidates)
        for _,_,_,base,direction in candidates:
            self.assertEqual(base['x'],2+direction['x']*3)
            self.assertEqual(base['z'],direction['z']*3)
            self.assertTrue(ex._standable(s,base))


class DurableTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.runtime=FakeRuntime(self.directory.name)
        self.path=ex._path(self.runtime,'test');self.data=data()
        atomic_write(self.path,self.data)
        self.runner=ex._Runner(self.runtime,self.path,self.data)
    def test_budget_persisted_before_submission(self):
        s=sample()
        self.runner.step('one_action',lambda:self.runner.execute('x',{'op':'action','action':'attack_entity','timeout_ms':50},lambda a,b:True,before=s))
        result=ex._read(self.path)
        self.assertEqual(result['actions_reserved'],1);self.assertIsNone(result['inflight'])
        self.assertTrue(self.runtime.commands[0]['require_pumpkin'])
        self.assertEqual(result['request_ids'],['req-1'])
    def test_unknown_freezes_exact_step_and_ids(self):
        self.runtime.status='unknown'
        with self.assertRaises(SkillError):
            self.runner.step('uncertain',lambda:self.runner.execute('x',{'op':'action','action':'attack_entity','timeout_ms':50},lambda a,b:True,before=sample()))
        saved=ex._read(self.path)
        self.assertEqual(saved['inflight']['status'],'unknown')
        with self.assertRaisesRegex(SkillError,'no_replay'):
            self.runner.step('never_retry',lambda:None)
        self.assertEqual(len(self.runtime.commands),1)
    def test_action_and_walk_budget_stop_before_transport(self):
        self.data['settings']['max_actions']=0
        with self.assertRaisesRegex(SkillError,'action_budget'):
            self.runner.step('budget',lambda:self.runner.execute('x',{'action':'attack_entity'},lambda a,b:True,before=sample()))
        self.assertFalse(self.runtime.commands)
        self.data['inflight']=None;self.data['settings']['max_actions']=5;self.data['settings']['max_walk_distance']=1
        with self.assertRaisesRegex(SkillError,'walk_budget'):
            self.runner.step('walk',lambda:self.runner.execute('x',{'action':'follow_path','waypoints':[{'x':10,'y':64,'z':.5}]},lambda a,b:True,before=sample()))
        self.assertFalse(self.runtime.commands)
    def test_expired_deadline_never_resets(self):
        self.data['deadline_unix']=time.time()-1
        with self.assertRaisesRegex(SkillError,'deadline'):self.runner.snapshot()
        self.assertFalse(self.runtime.commands)
    def test_same_dimension_new_player_context_stops(self):
        s=sample();s=Observation(s.state,s.terrain,s.raw,s.tick,('world',dimensions.END,'other','session'),0,'new')
        self.runtime.observations=[s]
        with self.assertRaisesRegex(SkillError,'context_changed'):self.runner.snapshot()
    def test_restart_refuses_interrupted_composite_even_without_unknown_runtime(self):
        self.data['inflight']={'label':'pearl','status':'running','reserved_actions':1}
        atomic_write(self.path,self.data)
        with self.assertRaisesRegex(SkillError,'no_replay'):
            ex.end_expedition(self.runtime,job_id='test',resume=True,**self.data['settings'])
        self.assertFalse(self.runtime.commands)
    def test_restart_cannot_expand_budget(self):
        atomic_write(self.path,self.data)
        modified=dict(self.data['settings'],max_actions=99)
        with self.assertRaisesRegex(SkillError,'cannot_change'):
            ex.end_expedition(self.runtime,job_id='test',resume=True,**modified)
    def test_history_status_is_not_goal_completion(self):
        self.assertTrue(ex.expedition_status(self.runtime,'test')['historical_only'])


class PhaseEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.runtime=FakeRuntime(self.directory.name)
        self.data=data();self.path=ex._path(self.runtime,'test')
        self.runner=ex._Runner(self.runtime,self.path,self.data)
    def test_no_local_crystals_never_sets_global_clear(self):
        self.data['phase']='crystals';ex._crystal_step(self.runner,sample())
        self.assertEqual(self.data['phase'],'dragon')
        self.assertNotIn('all_world_crystals_absent',self.data)
    def test_missing_dragon_is_search_not_victory(self):
        self.data['dragon']={'uuid':'dragon','entity_id':1,'dead_observed':False}
        with patch.object(self.runner,'frontier') as frontier:ex._dragon_step(self.runner,sample())
        frontier.assert_called_once();self.assertEqual(self.data['phase'],'dragon')
        self.assertFalse(self.data['dragon']['dead_observed'])
    def test_preexisting_dead_dragon_does_not_unlock_gateway(self):
        dead=entity('ender_dragon','dragon',0)
        with self.assertRaisesRegex(SkillError,'local_living_dragon'):ex._remember_targets(self.runner,sample(entities=[dead]))
        self.data['dragon']={'uuid':'dragon','entity_id':1,'dead_observed':False}
        with self.assertRaisesRegex(SkillError,'without_local_damage'):ex._dragon_step(self.runner,sample(entities=[dead]))
    def test_actual_local_dragon_damage_then_death_unlocks_gateway(self):
        self.data['dragon']={'uuid':'dragon','entity_id':1,'dead_observed':False}
        self.data['dragon_damage']=[{'target_uuid':'dragon','observed_health_loss':10}]
        ex._dragon_step(self.runner,sample(entities=[entity('ender_dragon','dragon',0)]))
        self.assertEqual(self.data['phase'],'gateway');self.assertTrue(self.data['dragon']['dead_observed'])
    def test_gateway_cannot_skip_dragon(self):
        # Module import is lazy and not an alternative action implementation.
        import sys
        with patch.dict(sys.modules,{'mdc_skills.mobility':SimpleNamespace()}):
            with self.assertRaisesRegex(SkillError,'local_actual_dragon'):
                ex._gateway_step(self.runner,sample())
        self.assertFalse(self.runtime.commands)
    def test_crystal_disappearance_without_shot_is_not_removal(self):
        self.data['crystal_work']={'uuid':'one','entity_id':1,'stage':'shoot'}
        with self.assertRaisesRegex(SkillError,'no_inferred_removal'):ex._crystal_step(self.runner,sample())
        self.assertFalse(self.runtime.commands)
    def test_shulker_disappearance_is_not_death(self):
        self.data.update(phase='outer',dragon={'dead_observed':True},gateway={'crossing_request_ids':['pearl']},outer_origin={'x':1000,'y':64,'z':0},shulker_target='one',shulker_entity_id=1)
        with self.assertRaisesRegex(SkillError,'not_death'):ex._outer_step(self.runner,sample())
        self.assertFalse(self.data['shulkers_dead'])
    def test_shell_inventory_gain_and_kill_required_before_craft(self):
        self.data.update(phase='outer',dragon={'dead_observed':True},gateway={'crossing_request_ids':['pearl']},outer_origin={'x':1000,'y':64,'z':0},shulkers_dead=['one'])
        ex._outer_step(self.runner,sample(items=[('minecraft:shulker_shell',2)]))
        self.assertEqual(self.data['phase'],'craft')
    def test_carried_shells_do_not_fake_new_material_acquisition(self):
        self.data.update(phase='outer',dragon={'dead_observed':True},gateway={'crossing_request_ids':['pearl']},outer_origin={'x':1000,'y':64,'z':0},shulkers_dead=['one'],initial_shells=2)
        with patch.object(self.runner,'frontier') as frontier:ex._outer_step(self.runner,sample(items=[('minecraft:shulker_shell',2)]))
        frontier.assert_called_once();self.assertEqual(self.data['phase'],'outer')
    def test_new_crystal_discovery_preempts_dragon_offense(self):
        crystal=entity('end_crystal','new');self.data['crystals']['new']={'removed':False}
        ex._dragon_step(self.runner,sample(entities=[crystal]))
        self.assertEqual(self.data['phase'],'crystals');self.assertFalse(self.runtime.commands)


class ShulkerStrategyTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.runtime=FakeRuntime(self.directory.name);self.data=data('outer')
        self.data.update(dragon={'dead_observed':True},gateway={'crossing_request_ids':['pearl']},
            outer_origin={'x':1000,'y':64,'z':0},shulker_target='one',shulker_entity_id=1)
        self.runner=ex._Runner(self.runtime,ex._path(self.runtime,'test'),self.data)
        self.shulker=entity('shulker',shell_open=False,line_of_sight=True)
        self.shulker.update(x=16.5,z=.5)
    def test_closed_shell_never_shot(self):
        ex._outer_step(self.runner,sample(entities=[self.shulker]))
        self.assertEqual(self.runtime.sleeps,[.1]);self.assertFalse(self.runtime.commands)
    def test_open_shell_uses_bow_outside_native_near_threat_radius(self):
        self.shulker['shell_open']=True;s=sample(entities=[self.shulker])
        outcome=Outcome('succeeded','damage',('shot',),dict(target_uuid='one',observed_health_loss=8),s)
        with patch.object(self.runner,'select') as select,patch.object(threats,'strike',return_value=outcome) as strike:
            ex._outer_step(self.runner,s)
        select.assert_called_once_with('minecraft:bow',0)
        self.assertTrue(strike.call_args.kwargs['ranged'])
        self.assertEqual(len(self.data['shulker_damage']),1)
    def test_projectile_tracking_preempts_bow_draw(self):
        self.shulker['shell_open']=True
        bullet=entity('shulker_bullet','bullet');bullet.update(x=8.5,y=65,z=.5,entity_id=2)
        with patch.object(threats,'strike') as strike:
            ex._outer_step(self.runner,sample(entities=[self.shulker,bullet]))
        strike.assert_not_called();self.assertEqual(self.runtime.sleeps,[.05])
    def test_missing_shell_or_visibility_fact_is_blocker(self):
        del self.shulker['shell_open']
        with self.assertRaisesRegex(SkillError,'visibility_and_shell'):ex._outer_step(self.runner,sample(entities=[self.shulker]))
        self.assertFalse(self.runtime.commands)


class ReserveTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.runtime=FakeRuntime(self.directory.name)
        self.data=data();self.data['settings']['max_actions']=4096
        self.data['settings']['max_walk_distance']=4096
        self.runner=ex._Runner(self.runtime,ex._path(self.runtime,'test'),self.data)
        self.sample=sample(items=[('minecraft:cobblestone',256),('minecraft:iron_pickaxe',1)])
        self.sample.player['inventory'][1].update(max_damage=250,damage=0)
    def test_full_round_trip_reserve_includes_bridge_and_durability(self):
        reserve=ex._reserve_tower(self.runner,self.sample,{'x':0,'y':64,'z':0},90,12)
        self.assertEqual(reserve['blocks'],40)
        self.assertGreater(reserve['return_actions'],26)
        self.sample.player['inventory'][1]['damage']=245
        with self.assertRaisesRegex(SkillError,'durability'):ex._reserve_tower(self.runner,self.sample,{'x':0,'y':64,'z':0},90,12)
    def test_material_reserve_before_any_ascent(self):
        self.sample.player['inventory'][0]['count']=32
        with self.assertRaisesRegex(SkillError,'material_reserve'):ex._reserve_tower(self.runner,self.sample,{'x':0,'y':64,'z':0},90,12)
        self.assertFalse(self.runtime.commands)
    def test_shorter_outer_scheduler_budget_is_authoritative(self):
        self.runtime.effective_remaining_budget=lambda:dict(remaining_actions=32,deadline_unix=time.time()+7200)
        with self.assertRaisesRegex(SkillError,'outer_scheduler_action'):ex._reserve_tower(self.runner,self.sample,{'x':0,'y':64,'z':0},90,12)
        self.runtime.effective_remaining_budget=lambda:dict(remaining_actions=4096,deadline_unix=time.time()+300)
        with self.assertRaisesRegex(SkillError,'outer_scheduler_deadline'):ex._reserve_tower(self.runner,self.sample,{'x':0,'y':64,'z':0},90,12)
    def test_gate_prethrow_requires_five_damage_plus_landing_health(self):
        self.data.update(phase='gateway',dragon={'dead_observed':True,'death_position':{'x':0,'y':64,'z':0}},dragon_damage=[{'observed_health_loss':10}])
        gate=dict(x=3,y=67,z=0,id='minecraft:end_gateway',properties={},loaded=True)
        self.sample.state['nearby']['end_gateways']=[gate];self.sample.player['health']=16
        ex._gateway_step(self.runner,self.sample)
        self.assertFalse(self.runtime.commands);self.assertIsNone(self.data['gateway'])
        self.assertIn('gateway_health_wait',self.data);self.assertEqual(self.runtime.sleeps,[.2])


class SafeHealthRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.runtime=FakeRuntime(self.directory.name);self.data=data('outer')
        self.runner=ex._Runner(self.runtime,ex._path(self.runtime,'test'),self.data)
    def test_food_then_observed_regeneration_requires_two_later_healthy_samples(self):
        first=sample(items=[('minecraft:bread',1)]);first.player.update(health=14,food=17)
        later=[sample(tick=2),sample(tick=3),sample(tick=4)]
        for item,hp in zip(later,(16,18,18)):item.player['health']=hp
        self.runtime.observations=later
        outcome=Outcome('succeeded','actual_food_delta',('eat',),{},first)
        with patch.object(ex.inventory,'consume',return_value=outcome) as consume:
            after=ex._restore_health(self.runner,first)
        consume.assert_called_once_with(self.runner,'minecraft:bread')
        self.assertEqual(after.tick,4);self.assertNotIn('health_recovery',self.data)
        self.assertEqual(self.data['last_health_recovery']['observed_health'],18)
    def test_unsafe_station_never_eats_while_hostile_near(self):
        hostile=entity('shulker');first=sample(entities=[hostile]);first.player['health']=14
        with patch.object(ex.inventory,'consume') as consume:
            with self.assertRaisesRegex(SkillError,'unthreatened'):ex._restore_health(self.runner,first)
        consume.assert_not_called()
    def test_no_food_does_not_invent_regeneration(self):
        first=sample();first.player.update(health=14,food=10)
        with self.assertRaisesRegex(SkillError,'observed_food_required'):ex._restore_health(self.runner,first)
        self.assertFalse(self.runtime.commands)
    def test_new_damage_stops_rest_without_other_action(self):
        first=sample();first.player['health']=14
        after=sample(tick=2);after.player['health']=13;self.runtime.observations=[after]
        with self.assertRaisesRegex(SkillError,'damage_during'):ex._restore_health(self.runner,first)
        self.assertFalse(self.runtime.commands)
    def test_actual_selected_worn_pickaxe_cannot_borrow_hidden_copy_durability(self):
        self.data['settings']['max_actions']=4096
        before=sample(items=[('minecraft:cobblestone',256),('minecraft:iron_pickaxe',1),('minecraft:iron_pickaxe',1)])
        before.player['inventory'][1].update(max_damage=250,damage=249)
        before.player['inventory'][2].update(slot=10,max_damage=250,damage=0)
        with self.assertRaisesRegex(SkillError,'durability'):ex._reserve_tower(self.runner,before,{'x':0,'y':64,'z':0},80,12)
        self.assertFalse(self.runtime.commands)


class ReturnFloorTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.runtime=FakeRuntime(self.directory.name);self.data=data()
        self.runner=ex._Runner(self.runtime,ex._path(self.runtime,'test'),self.data)
    def test_dragon_and_shulker_station_budget_abort_only_after_base(self):
        for key in ('dragon_tower','shulker_tower'):
            self.data[key]={'base':{'x':0,'y':64,'z':0},'reserve':{'return_actions':33,'return_seconds':10,'return_walk':5}}
            with self.assertRaisesRegex(SkillError,'stopped_with_return_reserve'):
                ex._abort_owned_tower_if_low(self.runner,sample(),key)
            self.assertIsNone(self.data[key]);self.assertFalse(self.runtime.commands)
    def test_column_change_does_not_guess_a_descent(self):
        self.data['dragon_tower']={'base':{'x':3,'y':64,'z':0},'reserve':{'return_actions':33,'return_seconds':10,'return_walk':5}}
        with self.assertRaisesRegex(SkillError,'column_changed'):
            ex._abort_owned_tower_if_low(self.runner,sample(), 'dragon_tower')
        self.assertFalse(self.runtime.commands)


class RealRuntimeCompositionTests(unittest.TestCase):
    """Actual Runtime journal/correlation/freshness composition, synthetic endpoint."""
    def setUp(self):
        from support_core import Client,Clock,NATIVE
        from mdc_skills.core import Runtime
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.clock=Clock();self.client=Client(self.clock)
        self.kind='ender_dragon'
        def patch_state(state):
            state['world']['dimension']=dimensions.END
            state['player'].update(dimension=dimensions.END,inventory_total=36,effects_truncated=False,effects=[],
                eye_position={'x':.5,'y':65.62,'z':.5},x=.5,y=64,z=.5,
                armor=[{'slot':'head','id':'minecraft:carved_pumpkin','count':1}],
                **{k:False for k in threats.ENVIRONMENT_FLAGS})
            state['player']['inventory'][0].update(id='minecraft:iron_sword',count=1,empty=False)
            mob=entity(self.kind,'dragon',0 if self.client.action_count else 20,
                       phase_id=6,dragon_parts=[{'name':'head','bounding_box':{'min':{'x':0,'y':65,'z':2},'max':{'x':1,'y':66,'z':3}}}])
            if self.kind=='shulker_bullet':
                mob['alive']=True;mob.update(x=.5,y=65.5,z=2.0)
            values=[] if self.kind=='shulker_bullet' and self.client.action_count else [mob]
            state['nearby']=dict(entities=values,truncated=False,total=len(values),returned=len(values),
                loaded_chunks=[{'x':0,'z':0,'loaded':True}])
            return state
        self.client.patch_state=patch_state
        self.runtime=Runtime(self.client,self.directory.name,clock=self.clock,sleeper=self.clock.sleep)
        self.addCleanup(self.runtime.close)
        self.data=data();self.data['context']=['world-one',dimensions.END,'player-one',NATIVE]
        self.data['owner']=self.runtime._owner
        self.runner=ex._Runner(self.runtime,ex._path(self.runtime,'test'),self.data)
    def test_perched_dragon_stage_uses_real_runtime_action_and_two_later_samples(self):
        before=self.runner.observe(entity_radius=128)
        self.data['dragon']={'uuid':'dragon','entity_id':1,'dead_observed':False}
        ex._dragon_step(self.runner,before)
        self.assertEqual(self.data['phase'],'gateway')
        self.assertEqual(self.data['actions_reserved'],1)
        self.assertTrue(self.data['dragon']['dead_observed'])
        mutation=[c for c,_ in self.client.calls if c['op']=='action']
        self.assertEqual(len(mutation),1);self.assertEqual(mutation[0]['action'],'attack_entity')
        self.assertTrue(mutation[0]['require_pumpkin'])
        journal=self.runtime._journal
        records=[r for r in journal['records'].values() if r['kind']=='mutation']
        self.assertEqual(records[0]['status'],'succeeded')
        self.assertEqual(len(records[0]['evidence']['stable_game_times']),2)
        self.assertIsNone(journal['pending']);self.assertIsNone(journal['semantic_pending'])
    def test_bullet_interception_real_runtime_does_not_claim_living_kill(self):
        self.kind='shulker_bullet'
        result=self.runner.step('intercept',lambda:ex.deflect_shulker_bullet(self.runner,'dragon'))
        self.assertIsNotNone(result)
        self.assertEqual(self.data['actions_reserved'],1)
        self.assertEqual(self.client.action_count,1)
        self.assertEqual(self.data['dragon_damage'],[])
    def test_unknown_real_action_receipt_never_dispatches_second_action(self):
        self.client.mode='pending'
        before=self.runner.observe(entity_radius=128)
        self.data['dragon']={'uuid':'dragon','entity_id':1,'dead_observed':False}
        with self.assertRaises(SkillError):ex._dragon_step(self.runner,before)
        self.assertEqual(self.client.action_count,1)
        self.assertTrue(self.runtime.has_unresolved_execution)
        with self.assertRaisesRegex(SkillError,'unresolved_execution'):
            self.runner.snapshot()
        self.assertEqual(self.client.action_count,1)


if __name__=='__main__':unittest.main()

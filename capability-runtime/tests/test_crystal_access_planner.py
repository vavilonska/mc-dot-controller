"""Production crystal planning on complete serialized synthetic tower worlds.

These are geometry/reserve contracts, not native actions or live End acceptance.
No fixture assigns a planner outcome or substitutes a mocked access planner.
"""
from copy import deepcopy
import gzip
import json
from pathlib import Path
import tempfile
import time
import unittest
from math import dist as math_dist, floor, hypot

from mdc_skills import expedition as ex, reach
from mdc_skills.core import SkillError, Outcome
from test_end_expedition import FakeRuntime, cell, data, sample

FIXTURE = Path(__file__).parent / 'fixtures' / 'crystal-tower-worlds.json.gz'


class SerializedWorld:
    def __init__(self, record):
        self.record = record
        self.cells = {(c['x'], c['y'], c['z']): deepcopy(c) for c in record['cells']}
        self.crystal = deepcopy(record['crystal'])
        self.tick = 0

    def observe(self, x, y=64, z=0, radius=4, vertical=4):
        self.tick += 1
        value = sample(tick=self.tick, x=x+.5, y=y, z=z+.5, entities=[deepcopy(self.crystal)],
                       items=[('minecraft:cobblestone',256),('minecraft:iron_pickaxe',1),
                              ('minecraft:bow',1),('minecraft:arrow',64)])
        value.player['block_interaction_range'] = 4.5
        for row in value.player['inventory']:
            if row['id'].endswith(('pickaxe', 'bow')):
                row.update(max_damage=250 if row['id'].endswith('pickaxe') else 384, damage=0)
        value.terrain['cells'] = [deepcopy(c) for (a,b,d),c in self.cells.items()
            if abs(a-x)<=radius and abs(b-y)<=vertical and abs(d-z)<=radius]
        # Incomplete source cells are deliberately not filled with synthetic air.
        value.terrain.update(origin={'x':x,'y':y,'z':z},radius=radius,vertical=vertical,
            source_tick=self.tick,last_tick=self.tick,scan_generation='tower-fixture-'+str(self.tick),
            capture_started_mono=time.monotonic())
        return value

    def set_block(self, x, y, z, kind):
        assert (x,y,z) in self.cells, 'outside serialized world'
        self.cells[x,y,z] = {**cell(x,y,z,kind != 'minecraft:air',kind),
                             'fluid_source':False,'hazards_exhaustive':False}

    def top_observation(self, plan):
        # Explicit setup state for cage-only planning; not a simulated ascent result.
        base, top = plan['base'], plan['height']
        for y in range(base['y'],top):
            self.set_block(base['x'], y, base['z'], 'minecraft:cobblestone')
        return self.observe(base['x'],top,base['z'],radius=8)


class ReturnGeometryRuntime(FakeRuntime):
    """Synthetic path endpoint adapter; actual mobility replans each local slice."""
    def __init__(self, root, world, position):
        super().__init__(root)
        self.world, self.position = world, dict(position)
        self.clock = time.monotonic

    def observe(self, **kwargs):
        position=self.position
        observation=self.world.observe(*(floor(position[k]) for k in ('x','y','z')),
            radius=kwargs.get('radius',4),vertical=kwargs.get('vertical',4))
        observation.player.update(position)
        observation.player.update(eye_position={**position,'y':position['y']+1.62},
                                  velocity={'x':0.,'y':0.,'z':0.})
        observation.player['armor'][0]['count']=1
        return observation

    def execute(self, skill, command, verify, **kwargs):
        assert command['action']=='follow_path', 'return must not mine, build or shoot'
        result=super().execute(skill,command,verify,**kwargs)
        for waypoint in command['waypoints']:
            point={k:floor(waypoint[k]) for k in ('x','y','z')}
            view=self.world.observe(point['x'],point['y'],point['z'])
            assert ex._standable(view,point), 'every simulated waypoint needs serialized support'
        self.position={k:command['waypoints'][-1][k] for k in ('x','y','z')}
        after=self.observe(terrain=True)
        assert verify(kwargs['before'],after), 'real semantic arrival predicate must pass'
        return Outcome(result.status,result.reason,result.request_ids,result.evidence,after)


class CrystalAccessPlannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(gzip.decompress(FIXTURE.read_bytes()))

    def world(self, index=2):
        return SerializedWorld(self.fixture['worlds'][index])

    def runner(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        runtime=FakeRuntime(directory.name)
        state=data('crystals');state['settings'].update(max_actions=4096,max_walk_distance=4096)
        return ex._Runner(runtime,ex._path(runtime,'test'),state)

    def plan(self, world):
        observation=world.observe(world.record['radius']+1)
        plans=ex._crystal_access_candidates(observation,world.crystal)
        self.assertTrue(plans)
        return observation, plans[0]

    def test_fixture_serializes_every_cell_in_its_declared_bounds(self):
        self.assertEqual(self.fixture['schema_version'],1)
        for record in self.fixture['worlds']:
            lo,hi=record['complete_bounds']['min'],record['complete_bounds']['max']
            expected={(x,y,z) for x in range(lo[0],hi[0]+1) for y in range(lo[1],hi[1]+1)
                              for z in range(lo[2],hi[2]+1)}
            actual={(c['x'],c['y'],c['z']) for c in record['cells']}
            self.assertEqual(actual,expected)
            self.assertEqual(len(actual),len(record['cells']))

    def test_real_planner_handles_varying_radius_height_and_cages(self):
        for index in range(3):
            with self.subTest(world=index):
                world=self.world(index);observation,plan=self.plan(world)
                base=plan['base']
                self.assertTrue(ex._standable(observation,base))
                self.assertGreater(base['x']**2+base['z']**2,world.record['radius']**2+1)
                self.assertEqual(plan['height'],world.crystal['y'])
                self.assertEqual(plan['source']['request_id'],observation.request_id)
                self.assertEqual(plan['source']['context'],list(observation.context))
                self.assertLessEqual(plan['bridge_length'],12)
                self.assertGreaterEqual(ex._horizontal({'x':plan['firing']['x']+.5,
                                                       'z':plan['firing']['z']+.5},world.crystal),14)
                self.assertEqual(plan['scope'],'observed_base_and_initial_ascent_only')

    def test_all_fixed_radius_three_columns_occupied_but_external_base_found(self):
        world=self.world();observation,plan=self.plan(world)
        for dx,dz in ex.CARDINAL:
            self.assertEqual(world.cells[dx*3,64,dz*3]['id'],'minecraft:obsidian')
        self.assertFalse(ex._base_candidates(observation,world.crystal))
        self.assertGreater(max(abs(plan['base']['x']),abs(plan['base']['z'])),3)

    def test_blocked_front_column_selects_an_observed_offset_or_other_face(self):
        world=self.world();_,first=self.plan(world);base=first['base']
        world.set_block(base['x'],base['y']+3,base['z'],'minecraft:obsidian')
        observation=world.observe(world.record['radius']+1)
        alternatives=ex._crystal_access_candidates(observation,world.crystal)
        self.assertTrue(alternatives)
        self.assertTrue(all(p['base']!=base for p in alternatives))
        self.assertTrue(all(ex._standable(observation,p['base']) for p in alternatives))

    def test_unloaded_support_and_unobserved_headroom_never_become_base(self):
        world=self.world();_,first=self.plan(world);base=first['base']
        for key in ((base['x'],base['y']-1,base['z']),(base['x'],base['y']+3,base['z'])):
            with self.subTest(key=key):
                changed=self.world();changed.cells[key]['known']=False
                observation=changed.observe(changed.record['radius']+1)
                self.assertTrue(all(p['base']!=base for p in ex._crystal_access_candidates(observation,changed.crystal)))

    def test_no_safe_base_is_explicit_before_any_mutation(self):
        world=self.world()
        for (x,y,z) in list(world.cells):
            if y==67:world.set_block(x,y,z,'minecraft:obsidian')
        observation=world.observe(5);runner=self.runner()
        runner.data['crystals'][world.crystal['uuid']]={'removed':False}
        self.assertFalse(ex._crystal_access_candidates(observation,world.crystal))
        with self.assertRaisesRegex(SkillError,'no_observed_safe_access_base'):
            ex._crystal_step(runner,observation)
        self.assertFalse(runner.runtime.commands)
        self.assertEqual(runner.data['actions_reserved'],0)

    def test_cage_bars_come_from_actual_trajectory_and_fresh_reachable_ray(self):
        for index in (1,2):
            with self.subTest(world=index):
                world=self.world(index);_,plan=self.plan(world)
                work={**plan,'bars_mined':[]}
                observation=world.top_observation(plan)
                initial=ex._crystal_cage_plan(observation,world.crystal,work)
                self.assertTrue(initial['bars']);self.assertIsNotNone(initial['next_bar'])
                for _ in range(ex.CRYSTAL_MAX_BARS):
                    lane=ex._crystal_cage_plan(observation,world.crystal,work)
                    if lane['next_bar'] is None:break
                    bar=lane['next_bar'];key=ex._point(bar)
                    self.assertEqual(world.cells[key]['id'],'minecraft:iron_bars')
                    eye=ex.threats.position(observation.player['eye_position'])
                    self.assertLess(math_dist(eye,tuple(v+.5 for v in key)),4.5)
                    # Independent geometry change, not a fabricated helper outcome.
                    world.set_block(*key,'minecraft:air');work['bars_mined'].append(bar)
                    observation=world.observe(plan['base']['x'],plan['height'],plan['base']['z'],radius=8)
                self.assertFalse(ex._crystal_cage_plan(observation,world.crystal,work)['bars'])
                self.assertLessEqual(len(work['bars_mined']),3)

    def test_uncaged_tower_requires_no_arbitrary_mining(self):
        world=self.world(0);_,plan=self.plan(world)
        lane=ex._crystal_cage_plan(world.top_observation(plan),world.crystal,{**plan,'bars_mined':[]})
        self.assertEqual(lane['bars'],[])

    def test_cage_lane_unknown_or_solid_obstruction_is_refused(self):
        for unknown in (False,True):
            world=self.world();_,plan=self.plan(world);work={**plan,'bars_mined':[]}
            observation=world.top_observation(plan)
            lane=ex._crystal_cage_plan(observation,world.crystal,work);key=ex._point(lane['next_bar'])
            if unknown:world.cells[key]['known']=False
            else:world.set_block(*key,'minecraft:obsidian')
            observation=world.observe(plan['base']['x'],plan['height'],plan['base']['z'],radius=8)
            with self.assertRaisesRegex(SkillError,'lane_unknown|unsupported_obstruction|no_observed_reachable_bar'):
                ex._crystal_cage_plan(observation,world.crystal,work)

    def test_cage_reach_is_actual_not_assumed(self):
        world=self.world();_,plan=self.plan(world);observation=world.top_observation(plan)
        observation.player['block_interaction_range']=1
        with self.assertRaisesRegex(SkillError,'no_observed_reachable_bar'):
            ex._crystal_cage_plan(observation,world.crystal,{**plan,'bars_mined':[]})

    def test_material_durability_inner_and_outer_budgets_remain_authoritative(self):
        world=self.world();observation,plan=self.plan(world);runner=self.runner()
        reserve=ex._reserve_crystal_access(runner,observation,plan)
        self.assertEqual(reserve['blocks'],plan['height']-plan['base']['y']+plan['bridge_length']+2)
        self.assertGreater(reserve['return_actions'],3*reserve['height']+8)
        before=deepcopy(runner.data)
        observation.player['inventory'][0]['count']=1
        with self.assertRaisesRegex(SkillError,'material_reserve'):ex._reserve_crystal_access(runner,observation,plan)
        observation.player['inventory'][0]['count']=256
        observation.player['inventory'][1]['damage']=249
        with self.assertRaisesRegex(SkillError,'durability'):ex._reserve_crystal_access(runner,observation,plan)
        observation.player['inventory'][1]['damage']=0
        runner.runtime.effective_remaining_budget=lambda:{'remaining_actions':2,'deadline_unix':time.time()+7000}
        with self.assertRaisesRegex(SkillError,'outer_scheduler_action'):ex._reserve_crystal_access(runner,observation,plan)
        del runner.runtime.effective_remaining_budget
        runner.data['settings']['max_walk_distance']=1
        with self.assertRaisesRegex(SkillError,'walk_reserve'):ex._reserve_crystal_access(runner,observation,plan)
        runner.data['settings']=before['settings']
        runner.data['deadline_unix']=time.time()+1
        with self.assertRaisesRegex(SkillError,'deadline_reserve'):ex._reserve_crystal_access(runner,observation,plan)
        self.assertEqual(runner.data['actions_reserved'],0);self.assertFalse(runner.runtime.commands)

    def test_new_ascent_obstruction_returns_before_another_mutation(self):
        world=self.world();_,plan=self.plan(world);runner=self.runner()
        observation=world.top_observation(plan)
        feet=dict(plan['base'],y=plan['height']-2)
        world.set_block(feet['x'],feet['y'],feet['z'],'minecraft:air')
        world.set_block(feet['x'],feet['y']+1,feet['z'],'minecraft:air')
        world.set_block(feet['x'],feet['y']+2,feet['z'],'minecraft:obsidian')
        observation=world.observe(feet['x'],feet['y'],feet['z'])
        work={**plan,'access_plan':plan,'uuid':world.crystal['uuid'],'entity_id':world.crystal['entity_id'],
              'stage':'ascend','bridge_cells':[],'bars_mined':[]}
        runner.data['crystal_work']=work
        ex._crystal_step(runner,observation)
        self.assertEqual(work['stage'],'descend')
        self.assertEqual(work['height'],feet['y'])
        self.assertIn('obstruction_or_unknown',work['abort_reason'])
        self.assertFalse(runner.runtime.commands)

    def test_new_bridge_obstruction_starts_reserved_return_without_replanning(self):
        world=self.world();ground,plan=self.plan(world);runner=self.runner()
        reserve=ex._reserve_crystal_access(runner,ground,plan)
        world.top_observation(plan)
        base,direction=plan['base'],plan['direction']
        world.set_block(base['x']+direction['x'],plan['height'],base['z']+direction['z'],'minecraft:obsidian')
        observation=world.observe(base['x'],plan['height'],base['z'])
        work={**plan,'access_plan':plan,'uuid':world.crystal['uuid'],'entity_id':world.crystal['entity_id'],
              'stage':'bridge','bridge_cells':[],'bars_mined':[],'reserve':reserve}
        runner.data['crystal_work']=work
        ex._crystal_step(runner,observation)
        self.assertEqual(work['stage'],'return')
        self.assertIn('obstruction_or_unknown',work['abort_reason'])
        self.assertEqual(work['firing'],plan['firing'])
        self.assertFalse(runner.runtime.commands)

    def test_original_return_reserve_stops_ascent_without_reset(self):
        world=self.world();ground,plan=self.plan(world);runner=self.runner()
        reserve=ex._reserve_crystal_access(runner,ground,plan)
        work={**plan,'access_plan':plan,'uuid':world.crystal['uuid'],'entity_id':world.crystal['entity_id'],
              'stage':'ascend','bridge_cells':[],'bars_mined':[],'reserve':reserve}
        runner.data['crystal_work']=work
        runner.data['settings']['max_actions']=reserve['return_actions']
        # Ground is already the original base, so no descent is necessary.
        base=plan['base'];observation=world.observe(base['x'],base['y'],base['z'])
        deadline=runner.data['deadline_unix']
        with self.assertRaisesRegex(SkillError,'stopped_with_return_reserve'):
            ex._crystal_step(runner,observation)
        self.assertIsNone(runner.data['crystal_work'])
        self.assertEqual(runner.data['deadline_unix'],deadline)
        self.assertFalse(runner.runtime.commands)

    def test_unknown_action_remains_fenced_before_any_new_crystal_step(self):
        world=self.world();ground,plan=self.plan(world);runner=self.runner()
        runner.data['inflight']={'label':'one_observed_pillar_ascent','reserved_actions':1,'status':'unknown'}
        runner.runtime.has_unresolved_execution=True
        with self.assertRaisesRegex(SkillError,'unresolved_execution_no_replay'):
            runner.observe(terrain=True)
        self.assertFalse(runner.runtime.commands)
        self.assertEqual(runner.data['inflight']['status'],'unknown')

    def test_cage_bar_budget_is_cumulative_across_observations(self):
        world=self.world();_,plan=self.plan(world);observation=world.top_observation(plan)
        with self.assertRaisesRegex(SkillError,'bar_budget_exhausted'):
            ex._crystal_cage_plan(observation,world.crystal,{**plan,'bars_mined':[{'x':1,'y':1,'z':1}]*3})

    def test_geometry_context_and_duplicate_cells_are_rejected(self):
        for mode in ('context','duplicate'):
            world=self.world();observation=world.observe(5)
            if mode=='context':observation.terrain['dimension']='minecraft:overworld'
            else:observation.terrain['cells'].append(deepcopy(observation.terrain['cells'][0]))
            with self.assertRaisesRegex(SkillError,'context_mismatch|duplicate_terrain_cell'):
                ex._crystal_access_candidates(observation,world.crystal)

    def test_legacy_access_checkpoint_cannot_issue_new_ascent(self):
        world=self.world();observation,plan=self.plan(world);runner=self.runner()
        runner.data['crystal_work']={'uuid':world.crystal['uuid'],'entity_id':world.crystal['entity_id'],
                                    'stage':'ascend','base':plan['base'],'height':plan['height']}
        with self.assertRaisesRegex(SkillError,'access_plan_required_no_legacy_replay'):
            ex._crystal_step(runner,observation)
        self.assertFalse(runner.runtime.commands)

    def test_firing_endpoint_covers_real_radial_arrival_tolerance_within_bridge_cap(self):
        world=self.world(0);observation=world.observe(3)
        plans=ex._crystal_access_candidates(observation,world.crystal)
        self.assertTrue(plans)
        # The frozen radius-two plan needs a thirteenth segment after adding
        # arrival margin, so this base must be rejected rather than extended.
        self.assertFalse(any(p['base']=={'x':2,'y':64,'z':-2} for p in plans))
        for plan in plans:
            self.assertLessEqual(plan['bridge_length'],12)
            goal={k:plan['firing'][k]+(.5 if k!='y' else 0) for k in ('x','y','z')}
            center_distance=ex._horizontal(goal,world.crystal)
            self.assertGreaterEqual(center_distance,14.25)
            # Worst inward radial arrival has the smallest possible clearance.
            dx,dz=world.crystal['x']-goal['x'],world.crystal['z']-goal['z']
            player={**goal,'x':goal['x']+.229999*dx/hypot(dx,dz),
                    'z':goal['z']+.229999*dz/hypot(dx,dz),
                    'on_ground':True,'velocity':{'x':0.,'z':0.}}
            self.assertTrue(reach._arrived(player,goal))
            self.assertGreater(ex._horizontal(player,world.crystal),14)
            # The actual predicate is radial: .20 on both axes is not admitted.
            diagonal={**player,'x':goal['x']+.20,'z':goal['z']+.20}
            self.assertFalse(reach._arrived(diagonal,goal))

    def test_exact_accepted_short_clearance_returns_by_real_loaded_route_without_extra_action(self):
        world=self.world(0);ground=world.observe(3)
        base={'x':2,'y':64,'z':-2};firing={'x':14,'y':73,'z':-2}
        # Preserve the exact frozen checkpoint geometry as regression input.
        old={'base':base,'height':73,'firing':firing,'direction':{'x':1,'z':0},
             'bridge_length':12,'approach_route':ex.observed_routes(ground)[ex._key(base)],
             'target':{'uuid':world.crystal['uuid'],'entity_id':world.crystal['entity_id'],
                       'position':{k:world.crystal[k] for k in ('x','y','z')}}}
        world.top_observation(old)
        for x in range(3,15):world.set_block(x,72,-2,'minecraft:cobblestone')
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        runtime=ReturnGeometryRuntime(directory.name,world,{'x':14.3,'y':73,'z':-1.5})
        state=data('crystals');state['settings'].update(max_actions=4096,max_walk_distance=4096)
        runner=ex._Runner(runtime,ex._path(runtime,'test'),state)
        reserve=ex._reserve_crystal_access(runner,ground,old)
        work={**old,'access_plan':old,'uuid':world.crystal['uuid'],'entity_id':world.crystal['entity_id'],
              'stage':'bridge','bridge_cells':[{'x':x,'y':73,'z':-2} for x in range(3,15)],
              'bars_mined':[],'reserve':reserve}
        runner.data['crystal_work']=work
        before=runtime.observe(terrain=True)
        self.assertTrue(reach._arrived(before.player,{'x':14.5,'y':73,'z':-1.5}))
        self.assertAlmostEqual(ex._horizontal(before.player,world.crystal),13.944174412684269)
        deadline=runner.data['deadline_unix'];original_reserve=deepcopy(reserve)
        ex._crystal_step(runner,before)
        self.assertEqual(work['stage'],'return')
        self.assertEqual(work['abort_reason'],'crystal_planned_blast_clearance_changed')
        self.assertFalse(runtime.commands)
        self.assertEqual(work['reserve'],original_reserve)
        self.assertEqual(len(work['bridge_cells']),12)
        # The next step exercises the actual mobility planner and semantic
        # arrival checks over the serialized supported corridor. Only endpoint
        # movement is simulated, not Minecraft/native execution or survival.
        ex._crystal_step(runner,runtime.observe(terrain=True))
        self.assertEqual(work['stage'],'descend')
        self.assertEqual(runtime.position,{'x':2.5,'y':73,'z':-1.5})
        self.assertTrue(runtime.commands)
        self.assertTrue(all(c['action']=='follow_path' for c in runtime.commands))
        points=[p for c in runtime.commands for p in c['waypoints']]
        self.assertTrue(all(2.5<=p['x']<=14.5 and p['y']==73 and p['z']==-1.5 for p in points))
        self.assertEqual(runner.data['deadline_unix'],deadline)
        self.assertEqual(work['reserve'],original_reserve)

    def test_descent_and_ground_closeout_reject_lateral_column_drift(self):
        for y in (73,64):
            with self.subTest(y=y):
                world=self.world(0);runner=self.runner()
                work={'uuid':world.crystal['uuid'],'entity_id':world.crystal['entity_id'],
                      'base':{'x':2,'y':64,'z':-2},'height':73,'stage':'descend'}
                runner.data['crystal_work']=work
                observation=world.observe(3,y,-2)  # Actual x=3.5, neighboring column.
                with self.assertRaisesRegex(SkillError,'return_column_changed_no_guessed_descent'):
                    ex._crystal_step(runner,observation)
                self.assertIs(runner.data['crystal_work'],work)
                self.assertFalse(runner.runtime.commands)

    def test_cage_falling_above_matches_mining_preflight_and_returns_before_dispatch(self):
        falling=('minecraft:sand','minecraft:red_sand','minecraft:gravel','minecraft:anvil',
                 'minecraft:chipped_anvil','minecraft:damaged_anvil','minecraft:blue_concrete_powder')
        for kind in falling:
            with self.subTest(kind=kind):
                world=self.world();ground,plan=self.plan(world);runner=self.runner()
                reserve=ex._reserve_crystal_access(runner,ground,plan)
                work={**plan,'access_plan':plan,'uuid':world.crystal['uuid'],
                      'entity_id':world.crystal['entity_id'],'stage':'cage',
                      'bridge_cells':[],'bars_mined':[],'reserve':reserve}
                before=world.top_observation(plan)
                bar=ex._crystal_cage_plan(before,world.crystal,work)['next_bar']
                self.assertEqual(bar,{'x':2,'y':86,'z':-1})
                world.set_block(bar['x'],bar['y']+1,bar['z'],kind)
                unsafe=world.observe(plan['base']['x'],plan['height'],plan['base']['z'],radius=8)
                # Both the actual resource helper and the access planner refuse
                # the same serialized, known falling block before any mutation.
                runner.runtime.observations=[unsafe]
                with self.assertRaisesRegex(SkillError,'resource_falling_or_fluid_above'):
                    ex.resources.mine(runner.runtime,bar)
                with self.assertRaisesRegex(SkillError,'no_observed_reachable_bar'):
                    ex._crystal_cage_plan(unsafe,world.crystal,work)
                runner.runtime.observations=[unsafe]
                runner.data['crystal_work']=work
                original=deepcopy(reserve);deadline=runner.data['deadline_unix']
                ex._crystal_step(runner,unsafe)
                self.assertEqual(work['stage'],'return')
                self.assertEqual(work['abort_reason'],'crystal_cage_no_observed_reachable_bar')
                self.assertEqual(work['reserve'],original)
                self.assertEqual(runner.data['deadline_unix'],deadline)
                self.assertIsNone(runner.data['inflight'])
                self.assertEqual(runner.data['actions_reserved'],0)
                self.assertFalse(runner.runtime.commands)

    def test_shoot_stage_rechecks_clearance_after_collateral_wait(self):
        world=self.world(0);ground,plan=self.plan(world);runner=self.runner()
        reserve=ex._reserve_crystal_access(runner,ground,plan)
        work={**plan,'access_plan':plan,'uuid':world.crystal['uuid'],'entity_id':world.crystal['entity_id'],
              'stage':'shoot','bridge_cells':[],'bars_mined':[],'reserve':reserve}
        runner.data['crystal_work']=work
        firing=plan['firing'];before=world.observe(firing['x'],firing['y'],firing['z'])
        collateral={'uuid':'collateral','entity_id':20,'type':'minecraft:cow','alive':True,'health':20,
                    'x':world.crystal['x']+1,'y':world.crystal['y'],'z':world.crystal['z']}
        before.state['nearby'].update(entities=[world.crystal,collateral],returned=2,total=2)
        ex._crystal_step(runner,before)
        self.assertEqual(work['stage'],'shoot');self.assertEqual(runner.runtime.sleeps,[.1])
        self.assertFalse(runner.runtime.commands)
        after=world.observe(firing['x'],firing['y'],firing['z'])
        dx,dz=after.player['x']-world.crystal['x'],after.player['z']-world.crystal['z']
        distance=hypot(dx,dz)
        after.player.update(x=world.crystal['x']+13.9*dx/distance,
                            z=world.crystal['z']+13.9*dz/distance)
        ex._crystal_step(runner,after)
        self.assertEqual(work['stage'],'return')
        self.assertEqual(work['abort_reason'],'crystal_planned_blast_clearance_changed')
        self.assertFalse(runner.runtime.commands)
        self.assertIsNone(runner.data['inflight'])
        self.assertEqual(runner.data['actions_reserved'],0)

    def test_ray_supercover_does_not_skip_thin_or_boundary_cells(self):
        crossed=ex._crystal_ray_cells((5.5,85.5,1.),(.5,85.5,1.))
        self.assertIn((2,85,0),crossed);self.assertIn((2,85,1),crossed)


if __name__=='__main__':unittest.main()

"""Geometry, fail-closed metadata, and actual read adapters; no real game/network."""
from copy import deepcopy
from dataclasses import replace
import math
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from mdc_skills.core import Observation, Runtime, SkillError
from mdc_skills.observation_profiles import _profile, observe_flat_segment
from mdc_skills import reach, mobility
from navigation_controller.fake import Block, FakeWorld
from resident_controller.controller import Resident
from resident_controller.ipc import QueueClient
from support_core import state
from test_gateway_integration import EndpointFixture
from test_observation_latency_adapter import PumpClock

WORLD = '11111111-2222-4333-8444-555555555555'


def observed(*, x=.5, y=64, z=.5, low=None, high=None, tick=100):
    s = state(tick, x)
    s['world']['world_generation'] = WORLD
    s['player'].update(y=y, z=z, on_ground=True)
    s['player']['bounding_box'] = {
        'min': dict(zip(('x','y','z'), low or (x-.3, y, z-.3))),
        'max': dict(zip(('x','y','z'), high or (x+.3, y+1.8, z+.3)))}
    context = (WORLD, s['world']['dimension'], s['player']['uuid'], s['client_action']['action_session'])
    return Observation(s, None, {'state': s}, tick, context, 100., str(tick))


def with_terrain(obs, radius, vertical):
    p = obs.player; origin = Block(*(math.floor(p[k]) for k in ('x','y','z')))
    world = FakeWorld(floor_y=origin.y-1); world.generation = obs.context[0]
    pages = world.pages(origin=origin, radius=radius, vertical=vertical, tick=obs.tick, limit=1024)
    terrain = {'complete': True, 'world_generation': obs.context[0], 'dimension': obs.context[1],
               'origin': vars(origin), 'radius': radius, 'vertical': vertical,
               'source_tick': obs.tick, 'last_tick': obs.tick, 'scan_generation': pages[0]['generation'],
               'capture_started_mono': 100., 'capture_finished_mono': 100.1,
               'cells': [c for page in pages for c in page['cells']]}
    return replace(obs, terrain=terrain, raw={'state': obs.state, 'terrain': terrain})


class ReadRuntime:
    max_age = .8
    def __init__(self, seed, fresh=None, mutate=None):
        self.seed, self.fresh, self.mutate = seed, fresh or deepcopy(seed), mutate
        self.calls = []; self.now = 100.1
    def clock(self): return self.now
    def observe(self, **options):
        self.calls.append(deepcopy(options))
        if len(self.calls) == 1: return self.seed
        self.result = with_terrain(self.fresh, options['radius'], options['vertical'])
        if self.mutate: self.mutate(self.result)
        return self.result
    def execute(self, *_args, **_kwargs):
        raise AssertionError('The profile helper must never mutate the game')


class ProfileGeometryTests(unittest.TestCase):
    def test_typical_one_cell_profile_is125_not729(self):
        obs = observed(); point = {'x':1.5,'y':64,'z':.5}
        profile = _profile(obs, point)
        self.assertEqual((profile.radius, profile.vertical), (2, 2))
        self.assertEqual((2*profile.radius+1)**2*(2*profile.vertical+1), 125)
        self.assertEqual((profile.minimum, profile.maximum), ((-1,63,-1), (2,65,1)))

    def test_negative_coordinates_use_floor_not_truncation(self):
        profile = _profile(observed(x=-.5, z=-.5), {'x':-1.5,'y':64,'z':-.5})
        self.assertEqual(profile.origin, (-1,64,-1))
        self.assertEqual(profile.minimum, (-3,63,-2))
        self.assertEqual(profile.maximum, (0,65,0))
        self.assertEqual(profile.radius, 2)

    def test_near_boundary_pose_requires_larger_profile(self):
        profile = _profile(observed(x=.99, z=.01), {'x':1.99,'y':64,'z':.01})
        self.assertEqual(profile.radius, 3)
        self.assertEqual(profile.maximum[0], 3)
        self.assertEqual(profile.minimum[2], -2)

    def test_actual_asymmetric_body_and_full_height_are_used(self):
        obs = observed(x=.12,z=.84,low=(-.71,64,.63),high=(.21,67.9,1.52))
        profile = _profile(obs, {'x':1.1,'y':64,'z':.7})
        self.assertEqual(profile.vertical, 3)
        self.assertEqual(profile.minimum[0], -2)
        self.assertEqual(profile.maximum[1], 67)
        self.assertEqual(profile.maximum[2], 2)

    def test_arrival_plus_coast_margin_changes_required_cells(self):
        obs = observed(x=.2, z=.5)
        profile = _profile(obs, {'x':1.2,'y':64,'z':.5})
        # .3 actual half-width + .56 native inflation alone reaches 2.06;
        # in the negative direction the extra .30 crosses an additional cell.
        self.assertIn((-1,63,0), set(profile.cells()))
        obs = observed(x=.1, z=.1)
        profile = _profile(obs, {'x':1.1,'y':64,'z':.1})
        self.assertEqual(profile.minimum[0], -2)
        self.assertEqual(profile.minimum[2], -2)
        self.assertGreaterEqual(obs.player['bounding_box']['min']['x']-.56, -1)

    def test_closed_integer_max_faces_are_included(self):
        obs = observed(x=.5,low=(.2,64,.2),high=(1.14,66,.8))
        profile = _profile(obs, {'x':1.5,'y':64,'z':.5})
        self.assertEqual(profile.maximum[0], 3)
        self.assertEqual(profile.maximum[1], 66)

    def test_seeded_swept_body_samples_fit_minimal_bounded_cube(self):
        rng = random.Random(634)
        for _ in range(120):
            x, z = rng.uniform(-20,20), rng.uniform(-20,20)
            direction = rng.choice(((1,0),(-1,0),(0,1),(0,-1)))
            target = (math.floor(x)+direction[0]+.5,64,math.floor(z)+direction[1]+.5)
            low = (x-rng.uniform(.1,1.2),64,z-rng.uniform(.1,1.2))
            high = (x+rng.uniform(.1,1.2),rng.uniform(65,68),z+rng.uniform(.1,1.2))
            obs = observed(x=x,z=z,low=low,high=high)
            profile = _profile(obs, dict(zip(('x','y','z'),target)))
            required = set(profile.cells())
            for t in (0,.07,.23,.5,.77,1):
                dx, dz = t*(target[0]-x), t*(target[2]-z)
                for px in (low[0]+dx-.86,high[0]+dx+.86):
                    for pz in (low[2]+dz-.86,high[2]+dz+.86):
                        for py in (63,64,high[1]):
                            self.assertIn((math.floor(px),math.floor(py),math.floor(pz)),required)
            extent = max(abs(bound[i]-profile.origin[i]) for bound in (profile.minimum,profile.maximum) for i in (0,2))
            self.assertEqual(profile.radius, max(1,extent))

    def test_diagonal_multicell_height_jump_and_excessive_body_fail(self):
        obs = observed()
        for point in ({'x':1.5,'y':64,'z':1.5}, {'x':2.5,'y':64,'z':.5},
                      {'x':1.5,'y':65,'z':.5}, {'x':1.5,'y':64,'z':.5,'jump':True}):
            with self.subTest(point=point), self.assertRaises(SkillError): _profile(obs,point)
        for body in ({'low':(-9,64,.2)}, {'high':(.8,73,.8)}):
            with self.subTest(body=body), self.assertRaisesRegex(SkillError,'bounds_exceeded'):
                _profile(observed(**body),{'x':1.5,'y':64,'z':.5})

    def test_unknown_malformed_nonfinite_body_is_not_assumed_default(self):
        for mutate in (lambda p:p.pop('bounding_box'), lambda p:p.update(bounding_box=None),
                       lambda p:p['bounding_box']['min'].update(x=True),
                       lambda p:p['bounding_box']['max'].update(y=float('nan')),
                       lambda p:p['bounding_box']['min'].update(x=2),
                       lambda p:p['bounding_box']['min'].update(y=63), lambda p:p.update(on_ground=False)):
            obs=observed();mutate(obs.player)
            with self.assertRaises(SkillError): _profile(obs,{'x':1.5,'y':64,'z':.5})


class ProfileReadTests(unittest.TestCase):
    point = {'x':1.5,'y':64,'z':.5}
    def test_only_second_observation_returned_and_raw_entities_preserved(self):
        seed,fresh=observed(),observed(tick=101)
        seed.state['nearby']={'entities':['proposal-only']}
        fresh.state['nearby']={'entities':['fresh-48'],'native_living_sample':'unchanged'}
        rt=ReadRuntime(seed,fresh);original=deepcopy(fresh)
        result=observe_flat_segment(rt,self.point)
        self.assertIs(result,rt.result);self.assertIsNot(result,seed)
        self.assertEqual(rt.calls,[{'terrain':False,'entity_radius':48},
            {'terrain':True,'radius':2,'vertical':2,'entity_radius':48}])
        self.assertEqual(result.state,original.state);self.assertEqual(result.captured_at,100)
        grid,stamp=reach._grid(result);grid.require_fresh(stamp,rt.clock())
        self.assertTrue(mobility.safe_edge(grid,Block(0,64,0),Block(1,64,0)))

    def test_fresh_pose_is_recomputed_not_trusted_from_seed(self):
        # Tiny same-cell drift makes a larger west/north footprint than the seed
        # but still fits its radius2 cube and is explicitly covered.
        rt=ReadRuntime(observed(),observed(x=.1,z=.1,tick=101))
        result=observe_flat_segment(rt,self.point)
        self.assertEqual(result.player['x'],.1)
        # Eastward boundary drift would need radius3, which the proposal omitted.
        rt=ReadRuntime(observed(),observed(x=.99,z=.5,high=(1.91,65.8,.8),tick=101))
        with self.assertRaisesRegex(SkillError,'fresh_envelope_outside_scan'):
            observe_flat_segment(rt,self.point)
        self.assertEqual(len(rt.calls),2)

    def test_context_epoch_and_body_changes_fail_without_retry(self):
        for mutate in (lambda o:o.state['world'].update(navigation_guard={}),
                       lambda o:o.state['world']['navigation_guard'].update(epoch=5),
                       lambda o:o.state['player'].update(uuid='other'),
                       lambda o:o.state['client_action'].update(action_session='other'),
                       lambda o:o.state['world'].update(world_generation='other'),
                       lambda o:o.state['player'].pop('bounding_box')):
            fresh=observed(tick=101);mutate(fresh);rt=ReadRuntime(observed(),fresh)
            with self.assertRaises(SkillError):observe_flat_segment(rt,self.point)
            self.assertEqual(len(rt.calls),2)

    def test_missing_duplicate_unloaded_and_incomplete_collision_fail(self):
        def required(o):return next(c for c in o.terrain['cells'] if (c['x'],c['y'],c['z'])==(2,63,1))
        variants=[lambda o:o.terrain['cells'].remove(required(o)),
                  lambda o:o.terrain['cells'].append(deepcopy(required(o))),
                  lambda o:required(o).update(status='unloaded',known=False),
                  lambda o:required(o).update(collision_known=False),
                  lambda o:required(o).pop('collision_bounds'),
                  lambda o:required(o).update(collision_bounds=[0,0,0,1,float('inf'),1]),
                  lambda o:required(o).update(properties_truncated=True),
                  lambda o:required(o).update(fluid_truncated=True),
                  lambda o:required(o).pop('hazards_exhaustive')]
        for mutate in variants:
            rt=ReadRuntime(observed(),mutate=mutate)
            with self.assertRaises(SkillError):observe_flat_segment(rt,self.point)
            self.assertEqual(len(rt.calls),2)

    def test_coverage_is_not_a_passage_certificate(self):
        def blocked(o):
            cell=next(c for c in o.terrain['cells'] if (c['x'],c['y'],c['z'])==(1,64,0))
            cell.update(id='minecraft:stone',air=False,collision_empty=False,full_top_support=True,
                        collision_bounds=[0,0,0,1,1,1])
        result=observe_flat_segment(ReadRuntime(observed(),mutate=blocked),self.point)
        grid,_=reach._grid(result)
        self.assertFalse(mobility.safe_edge(grid,Block(0,64,0),Block(1,64,0)))

    def test_terrain_profile_context_and_historical_mismatch_fail(self):
        for mutate in (lambda o:o.terrain.update(radius=4), lambda o:o.terrain.update(complete=False),
                       lambda o:o.terrain.update(world_generation='other'),
                       lambda o:o.terrain.update(historical_survey=True),
                       lambda o:o.terrain.update(origin={'x':10,'y':64,'z':0})):
            rt=ReadRuntime(observed(),mutate=mutate)
            with self.assertRaises(SkillError):observe_flat_segment(rt,self.point)

    def test_age_is_original_and_point8_remains_fail_closed(self):
        rt=ReadRuntime(observed());rt.now=100.801
        with self.assertRaisesRegex(SkillError,'observation_stale'):observe_flat_segment(rt,self.point)
        self.assertEqual(rt.result.captured_at,100.)
        for radius in (True,0,129,'48'):
            rt=ReadRuntime(observed())
            with self.assertRaises(SkillError):observe_flat_segment(rt,self.point,entity_radius=radius)
            self.assertEqual(rt.calls,[])


class ProfileActualAdapterTests(unittest.TestCase):
    def test_helper_uses_real_runtime_queue_resident_and125_cells(self):
        class BodyEndpoints(EndpointFixture):
            def snapshot(self):
                value=super().snapshot();p=value['player']
                p['bounding_box']={'min':{'x':p['x']-.3,'y':p['y'],'z':p['z']-.3},
                                   'max':{'x':p['x']+.3,'y':p['y']+1.8,'z':p['z']+.3}}
                return value
            def request(self,method,path,body=None):
                if method!='GET':raise AssertionError('Read profile must not mutate game')
                return super().request(method,path,body)
        with tempfile.TemporaryDirectory(prefix='offline-flat-profile-') as temp:
            clock=PumpClock();bridge=BodyEndpoints()
            with patch('time.monotonic',clock.monotonic),patch('time.sleep',clock.sleep):
                resident=Resident(bridge,Path(temp)/'resident');resident.start();clock.resident=resident
                runtime=Runtime(QueueClient(Path(temp)/'resident'),Path(temp)/'journal',
                                clock=clock.monotonic,sleeper=clock.sleep)
                try:
                    result=observe_flat_segment(runtime,{'x':1.5,'y':64,'z':.5})
                    self.assertEqual(len(result.terrain['cells']),125)
                    self.assertEqual((result.terrain['radius'],result.terrain['vertical']),(2,2))
                    self.assertEqual(result.state['nearby']['radius'],48)
                    self.assertEqual(bridge.state_paths,['/control/capability-snapshot?radius=48']*3)
                    self.assertEqual(len(bridge.terrain_responses),1)
                    self.assertEqual(bridge.terrain_responses[0]['page_limit'],1024)
                    self.assertEqual(bridge.posts,[])
                    self.assertEqual(runtime.max_age,.8)
                    self.assertIs(runtime._last,result)
                finally:runtime.close();resident.lock.close()


if __name__=='__main__':unittest.main()

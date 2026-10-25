"""Offline synthetic tests against exact C8 geometry, PLAN4 and admission gate.

Actual C8 fixture function bodies are reused via AST, without executing their
historical-ledger module initialization. No game, HTTP, Controller or ledger is
constructed; the fixture identities and all terrain below are synthetic.
"""
import ast
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
C8 = Path(os.environ.get('MDC_C8_SOURCE', str(HERE.parent / 'MDC-RECOVERY-RESTORED-F1220-20261022T1433Z/C8-source')))
sys.path.insert(0, str(C8 / 'survival6-controller'))
from survival6_controller import Plan
from survival6_controller.legacy import PROFILE, Refused, encode
from survival6_controller.policy import gate
from terrain_planner import TerrainPlanner, manual_target

_fixture_path = C8 / 'survival6-controller/tests/fixtures.py'
_fixture_tree = ast.parse(_fixture_path.read_text())
_fixture_functions = ast.Module(body=[n for n in _fixture_tree.body if isinstance(n, ast.FunctionDef) and n.name in ('base_observation', 'observation')], type_ignores=[])
_fixture_env = dict(PROFILE=PROFILE, SESSION='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaa60',
                    WORLD='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbb60',
                    PLAYER='cccccccc-cccc-4ccc-8ccc-cccccccccc60',
                    OWNER='ffffffff-ffff-4fff-8fff-ffffffffff60',
                    OBS='dddddddd-dddd-4ddd-8ddd-dddddddddd60',
                    TARGET='eeeeeeee-eeee-4eee-8eee-eeeeeeeeee60')
exec(compile(_fixture_functions, str(_fixture_path), 'exec'), _fixture_env)


def observation(x=.5, z=.5, *, y=48., yaw=90., pitch=0., heights=None):
    o = _fixture_env['observation']()
    o['pose'] = dict(x=x, y=y, z=z, yaw=yaw, pitch=pitch)
    o['player_bbox'] = dict(min_x=x-.3, max_x=x+.3, min_y=y, max_y=y+1.8,
                            min_z=z-.3, max_z=z+.3)
    o['velocity'] = dict(x=0., y=-.0784, z=0.)
    o['nearby_living'] = []
    o['survival']['entity_hit'] = None
    o['local_blocks'] = []
    for dx in range(-2, 3):
        for dy in range(-2, 4):
            for dz in range(-2, 3):
                key = (math.floor(x)+dx, math.floor(z)+dz)
                height = 48. if heights is None else heights.get(key)
                solid = height is not None and math.floor(y)+dy < height
                o['local_blocks'].append(dict(
                    dx=dx, dy=dy, dz=dz, loaded=True,
                    id='minecraft:stone' if solid else 'minecraft:air',
                    collision=solid, fluid='minecraft:empty',
                    collision_boxes=[[0., 0., 0., 1., 1., 1.]] if solid else []))
    return o


def cell(o, dx, dy, dz):
    return next(c for c in o['local_blocks'] if (c['dx'], c['dy'], c['dz']) == (dx, dy, dz))


def solid(c, boxes=None):
    c.update(id='minecraft:stone', collision=True,
             collision_boxes=boxes or [[0., 0., 0., 1., 1., 1.]])


def production_gate(o, stage):
    context = {k: o['bound_owner_id' if k == 'owner_id' else k]
               for k in ('session', 'world_generation', 'player_uuid', 'owner_id')}
    data = dict(version=4, kind='survival', context=context,
                navigation=[stage], survival=[])
    raw = encode(data)
    plan = Plan(raw, hashlib.sha256(raw).hexdigest())
    q = {k: o[k] for k in ('session', 'world_generation', 'player_uuid',
                           'owner_generation', 'observation_id')}
    q.update(schema_version=1, profile=PROFILE, kind='move',
             id='11111111-1111-4111-8111-111111111111', owner_id=o['bound_owner_id'],
             ttl_ms=1000, plan_version=4, plan_sha256=plan.sha256,
             stage_id=stage['id'], forward=stage['forward'], strafe=stage['strafe'],
             jump_first=stage['jump_first'], samples=stage['max_samples'])
    return gate(o, q, o['bound_owner_id'], {}, plan)


class TerrainTests(unittest.TestCase):
    def planner(self):
        return TerrainPlanner(stop_x=-100.)

    def test_flat_cardinal_actual_yaw_and_production_gate(self):
        for yaw in (-180., -135., -90., -33.25, 0., 44.5, 90., 179.99):
            with self.subTest(yaw=yaw):
                o = observation(yaw=yaw, pitch=21.)
                stage = self.planner().choose(o, 'west')
                self.assertEqual(stage['target'], dict(x=-1.5, y=48., z=.5))
                self.assertEqual((stage['yaw'], stage['pitch']), (yaw, 21.))
                a = math.radians(yaw)
                self.assertAlmostEqual(stage['strafe']*math.cos(a)-stage['forward']*math.sin(a), -1.)
                self.assertAlmostEqual(stage['forward']*math.cos(a)+stage['strafe']*math.sin(a), 0.)
                self.assertEqual((stage['max_samples'], stage['max_moves'], stage['max_looks']), (8, 8, 0))
                self.assertFalse(stage['jump_first'])
                self.assertEqual(production_gate(o, stage)['stage_id'], 'west')

    def test_one_block_ascent_original_gate_and_one_shot_budget(self):
        o = observation(heights={(0, 0): 48, (-1, 0): 49})
        stage = self.planner().choose(o, 'up')
        self.assertEqual(stage['target'], dict(x=-.5, y=49., z=.5))
        self.assertEqual((stage['jump_first'], stage['max_samples'], stage['max_moves']), (True, 8, 1))
        production_gate(o, stage)
        with self.assertRaisesRegex(Refused, 'step height'):
            manual_target(o, 'no-jump-up', stage['target'])

    def test_downstep_nojump_y_minus_one_is_valid(self):
        o = observation(heights={(0, 0): 48, (-1, 0): 47})
        stage = self.planner().choose(o, 'down')
        self.assertEqual(stage['target'], dict(x=-.5, y=47., z=.5))
        self.assertFalse(stage['jump_first'])
        production_gate(o, stage)

    def test_no_arbitrary_jump_apex_margin(self):
        o = observation(heights={(0, 0): 48, (-1, 0): 49})
        # Actual body and landing fit under a 2.9m ceiling. Do not invent a
        # higher apex requirement than C8's body/landing/support admission.
        for dx in (0, -1):
            solid(cell(o, dx, 2, 0), [[0., .9, 0., 1., 1., 1.]])
        stage = self.planner().choose(o, 'bounded-up')
        self.assertTrue(stage['jump_first'])
        production_gate(o, stage)

    def test_solid_low_ceiling_rejected_by_actual_landing_body(self):
        o = observation(heights={(0, 0): 48, (-1, 0): 49})
        target = dict(x=-.5, y=49., z=.5)
        admitted_stage = manual_target(o, 'before-ceiling', target, jump=True)
        solid(cell(o, -1, 2, 0))
        with self.assertRaisesRegex(Refused, 'body intersects'):
            production_gate(o, admitted_stage)
        with self.assertRaisesRegex(Refused, 'body intersects'):
            manual_target(o, 'low', target, jump=True)
        self.assertIsNone(self.planner().choose(o, 'blocked-low'))

    def test_unsupported_gap_not_traversed_even_with_jump(self):
        o = observation(heights={(0, 0): 48, (-2, 0): 48})
        self.assertIsNone(self.planner().choose(o, 'no-neighbor'))
        for jump in (False, True):
            with self.assertRaisesRegex(Refused, 'support'):
                manual_target(o, 'gap', dict(x=-1.5, y=48., z=.5), jump=jump)

    def test_high_difference_checkpoints_before_long_backtrack(self):
        h = {(0, 0): 48, (-1, 0): 48, (-2, 0): 50}
        p = self.planner()
        first = p.choose(observation(heights=h), 'first')
        p.arrived(first)
        self.assertIsNone(p.choose(observation(x=-.5, heights=h), 'boundary'))
        self.assertEqual(p.reason, 'high_difference_boundary_checkpoint')
        self.assertEqual(p.boundaries[0]['height_delta'], 2.)
        self.assertEqual(len(p.arrivals), 1)

    def test_finite_supported_component_backtracks_then_terminates(self):
        cells = {(0, 0), (-1, 0), (0, -1), (0, -2), (1, -1)}
        heights = {n: 48 for n in cells}
        p, x, z, stages = self.planner(), .5, .5, []
        for i in range(30):
            o = observation(x, z, heights=heights)
            stage = p.choose(o, 'walk-%s' % i)
            if stage is None:
                break
            production_gate(o, stage)
            stages.append(stage)
            p.arrived(stage)
            x, z = stage['target']['x'], stage['target']['z']
        else:
            self.fail('finite component did not terminate')
        self.assertEqual(p.visited, {(x, 48, z) for x, z in cells})
        self.assertLessEqual(len(stages), 2*(len(cells)-1))
        self.assertEqual(p.reason, 'explored_graph_exhausted')

    def test_pending_immutable_no_automatic_arrival(self):
        p = self.planner()
        stage = p.choose(observation(), 'original')
        self.assertEqual(p.choose(observation(x=-.5), 'replacement'), stage)
        self.assertEqual(p.visited, {(0, 48, 0)})
        self.assertEqual(p.arrivals, [])
        changed = copy.deepcopy(stage)
        changed['target']['x'] -= .25
        with self.assertRaises(Refused):
            p.arrived(changed)
        p.arrived(stage)
        self.assertIn((-2, 48, 0), p.visited)
        with self.assertRaises(Refused):
            p.arrived(stage)

    def test_blocked_edge_no_retry_or_fake_arrival(self):
        p = self.planner()
        stage = p.choose(observation(), 'blocked')
        p.blocked(stage)
        next_stage = p.choose(observation(), 'detour')
        self.assertEqual(next_stage['target'], dict(x=-.5, y=48., z=.5))
        self.assertNotEqual(next_stage['target'], stage['target'])
        self.assertEqual(p.arrivals, [])
        self.assertNotIn((-1, 48, 0), p.visited)

    def test_partial_abandonment_records_actual_source_only(self):
        p = self.planner()
        stage = p.choose(observation(), 'partial')
        p.blocked(stage)
        p.choose(observation(x=-.1), 'fresh')
        self.assertNotIn((-1, 48, 0), p.visited)
        self.assertIn((-1, 48, 0), p.observed_sources)

    def test_residual_preserves_orthogonal_position_and_feet_bounds(self):
        o = observation(x=.73, z=.61)
        stage = self.planner().choose(o, 'residual')
        self.assertEqual(stage['target'], dict(x=-.5, y=48., z=.61))
        self.assertAlmostEqual(stage['source_bounds']['min_x'], -.8)
        self.assertAlmostEqual(stage['source_bounds']['max_x'], 1.03)
        self.assertEqual((stage['source_bounds']['min_y'], stage['source_bounds']['max_y']), (47.95, 48.05))
        production_gate(o, stage)

    def test_no_full_health_or_inventory_invariant(self):
        o = observation()
        o['health'], o['selected_slot'], o['hotbar'][1]['count'] = 3., 3, 1
        o['nearby_living'] = [dict(id=9, type='minecraft:blaze', x=2., y=48., z=.5, alive=True)]
        stage = self.planner().choose(o, 'hurt')
        production_gate(o, stage)
        o['nearby_living'][0]['x'] = .5
        with self.assertRaisesRegex(Refused, 'immediate nearby'):
            production_gate(o, stage)

    def test_missing_unloaded_invalid_current_reject(self):
        for mode in ('missing', 'unloaded', 'body', 'support', 'bbox', 'speed'):
            with self.subTest(mode=mode):
                o = observation()
                if mode == 'missing':
                    o['local_blocks'].pop()
                elif mode == 'unloaded':
                    cell(o, -1, 0, 0).update(loaded=False, id=None, fluid=None, collision=None, collision_boxes=None)
                    o.update(ready=False, collision_boxes_complete=False)
                elif mode == 'body':
                    solid(cell(o, 0, 1, 0))
                elif mode == 'support':
                    cell(o, 0, -1, 0).update(id='minecraft:air', collision=False, collision_boxes=[])
                elif mode == 'bbox':
                    o['player_bbox']['min_x'] += .1
                else:
                    o['velocity']['x'] = .031
                with self.assertRaises(Refused):
                    self.planner().choose(o, mode)

    def test_manual_closed_finite_cardinal_local_target_and_id(self):
        o = observation()
        invalid = [dict(x=-.5, y=48., z=.5, yaw=0), dict(x=float('nan'), y=48., z=.5),
                   dict(x=True, y=48., z=.5), dict(x=-.5, y=48., z=-.5),
                   dict(x=-.5, y=46., z=.5), dict(x=-10., y=48., z=.5)]
        for target in invalid:
            with self.subTest(target=target), self.assertRaises(Refused):
                manual_target(o, 'bad-target', target)
        for sid in ('', 'has spaces', 'x'*65):
            with self.assertRaises(Refused):
                manual_target(o, sid, dict(x=-.5, y=48., z=.5))
        stage = manual_target(o, 'x'*64, dict(x=-.5, y=48., z=.5), max_moves=2)
        self.assertEqual(stage['max_moves'], 2)
        production_gate(o, stage)

    def test_snapshot_json_roundtrip_preserves_pending_and_no_reissue(self):
        p = self.planner()
        stage = p.choose(observation(), 'pending')
        state = json.loads(json.dumps(p.snapshot(), allow_nan=False))
        restored = TerrainPlanner.restore(state)
        self.assertEqual(restored.snapshot(), state)
        self.assertEqual(restored.choose(observation(), 'replacement'), stage)
        restored.blocked(stage)
        with self.assertRaises(Refused):
            restored.choose(observation(), 'pending')
        next_stage = restored.choose(observation(), 'next')
        restored.arrived(next_stage)
        again = TerrainPlanner.restore(json.loads(json.dumps(restored.snapshot())))
        self.assertEqual(again.snapshot(), restored.snapshot())

    def test_corrupt_snapshot_rejected(self):
        p = self.planner()
        p.choose(observation(), 'pending')
        for mode in ('extra', 'nonfinite', 'budget', 'dest', 'seen'):
            state = p.snapshot()
            if mode == 'extra': state['extra'] = True
            elif mode == 'nonfinite': state['stop_x'] = float('nan')
            elif mode == 'budget': state['pending']['max_moves'] = 9
            elif mode == 'dest': state['pending_info']['dest'] = [99, 48, 0]
            else: state['seen'] = []
            with self.subTest(mode=mode), self.assertRaises(Refused):
                TerrainPlanner.restore(state)

    def test_default_stop_no_mutation_and_reused_stage_id(self):
        o = observation(x=-635.1)
        before = copy.deepcopy(o)
        p = TerrainPlanner()
        self.assertIsNone(p.choose(o, 'stop'))
        self.assertEqual(p.reason, 'goal_reached')
        self.assertEqual(o, before)
        p = self.planner()
        s = p.choose(observation(), 'used')
        p.blocked(s)
        with self.assertRaises(Refused):
            p.choose(observation(), 'used')


if __name__ == '__main__':
    unittest.main(verbosity=2)

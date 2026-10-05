"""Independent offline robustness checks; no game, input, or network adapters."""
from copy import deepcopy
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from building_controller.__main__ import main
from building_controller.model import Blueprint, PlanError
from building_controller.planner import plan
from building_controller.terrain import Cell, Terrain, parse_inventory

WORLD = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
SCAN = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'


def cell(x, y, z, block='minecraft:air'):
    air = block == 'minecraft:air'
    value = dict(x=x, y=y, z=z, status='loaded', known=True, id=block,
                 id_truncated=False, air=air, properties={}, properties_truncated=False,
                 fluid='minecraft:empty', fluid_truncated=False, fluid_source=False,
                 hazards=[], hazards_exhaustive=False, collision_known=True,
                 collision_empty=air, full_top_support=not air)
    if not air:
        value['collision_bounds'] = [0, 0, 0, 1, 1, 1]
    return value


def pages(*, origin_y=0, ground=True):
    radius = vertical = 3
    cells = [cell(x, y, z, 'minecraft:stone' if ground and y == origin_y - 1 else 'minecraft:air')
             for y in range(origin_y - vertical, origin_y + vertical + 1)
             for z in range(-radius, radius + 1) for x in range(-radius, radius + 1)]
    result = []
    for start in range(0, len(cells), 128):
        batch = cells[start:start + 128]
        end = start + len(batch)
        complete = end == len(cells)
        result.append(dict(ok=True, protocol='mineclient-bridge', schema_version=2,
                           terrain_schema_version=1, consistency='live_pages',
                           order='x_then_z_then_y', read_only=True, loaded_chunks_only=True,
                           world_generation=WORLD, generation=SCAN, dimension='minecraft:overworld',
                           origin=dict(x=0, y=origin_y, z=0), radius=radius, vertical=vertical,
                           total_cells=len(cells), game_time=100, response_game_time=100,
                           offset=start, returned=len(batch), next_offset=end, complete=complete,
                           next_cursor=None if complete else f'{SCAN}:{end}', budget_exhausted=False,
                           read_elapsed_micros=100, unknown_cells=0, cells=batch))
    return result


def replace_cell(values, pos, block):
    for page in values:
        for i, raw in enumerate(page['cells']):
            if (raw['x'], raw['y'], raw['z']) == pos:
                page['cells'][i] = cell(*pos, block)
                return page['cells'][i]
    raise AssertionError('position not in fixture')


def state(y=0):
    inventory = [dict(slot=i, count=0, empty=True, id='') for i in range(36)]
    inventory[0] = dict(slot=0, count=64, empty=False, id='minecraft:oak_planks')
    return dict(ok=True, protocol='mineclient-bridge', schema_version=2,
                world=dict(world_generation=WORLD, dimension='minecraft:overworld', game_time=100),
                player=dict(dimension='minecraft:overworld', gamemode='survival', x=4, y=y, z=0,
                            inventory_total=36, inventory_truncated=False, inventory=inventory),
                nearby=dict(radius=16, total=0, returned=0, truncated=False, entities=[]))


def blueprint(width=1, extent=1, template='floor', y=0):
    return Blueprint.parse(dict(schema_version=1, template=template,
                               origin=dict(x=0, y=y, z=0),
                               region=dict(min=dict(x=0, y=y, z=0), max=dict(x=width-1, y=y+extent-1 if template=='wall' else y, z=extent-1 if template=='floor' else 0)),
                               size=dict(width=width, extent=extent), axis='x',
                               palette=dict(primary='minecraft:oak_planks', accent='minecraft:stone_bricks'),
                               pattern='solid'))


class IndependentReviewTests(unittest.TestCase):
    def run_plan(self, bp=None, terrain=None, snapshot=None):
        return plan(bp or blueprint(), Terrain.parse(terrain or pages()), snapshot or state())

    def assert_blocked(self, result):
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['proposed_placements'], [])
        self.assertIs(result['executable'], False)
        self.assertIs(result['execution_enabled'], False)

    def test_baseline_is_non_executable(self):
        result = self.run_plan()
        self.assertEqual(result['status'], 'provisional_plan')
        self.assertEqual(len(result['proposed_placements']), 1)
        self.assertIs(result['executable'], False)
        self.assertIs(result['execution_enabled'], False)

    def test_horizontal_support_dependency_is_prior_and_rooted(self):
        terrain = pages(ground=False)
        replace_cell(terrain, (-1, 0, 0), 'minecraft:stone')
        result = self.run_plan(blueprint(width=3), terrain)
        self.assertEqual(result['status'], 'provisional_plan')
        self.assertEqual(len(result['proposed_placements']), 3)
        for p in result['proposed_placements']:
            if p['index']:
                self.assertLess(p['anchor']['depends_on_index'], p['index'])
            else:
                self.assertEqual(p['anchor']['source'], 'observed_full_cube')

    def test_vertical_wall_is_bottom_up(self):
        result = self.run_plan(blueprint(extent=3, template='wall'))
        self.assertEqual(result['status'], 'provisional_plan')
        self.assertEqual([p['position']['y'] for p in result['proposed_placements']], [0, 1, 2])
        self.assertEqual([p['anchor']['source'] for p in result['proposed_placements']],
                         ['observed_full_cube', 'earlier_proposed_block', 'earlier_proposed_block'])

    def test_floating_cycles_do_not_support_each_other(self):
        self.assert_blocked(self.run_plan(blueprint(width=2), pages(ground=False)))

    def test_single_conflict_suppresses_entire_plan(self):
        terrain = pages()
        replace_cell(terrain, (1, 0, 0), 'minecraft:stone')
        result = self.run_plan(blueprint(width=2), terrain)
        self.assert_blocked(result)
        self.assertEqual(result['summary']['known_air_candidates'], 1)

    def test_existing_correct_not_charged(self):
        terrain = pages()
        replace_cell(terrain, (1, 0, 0), 'minecraft:oak_planks')
        material = self.run_plan(blueprint(width=2), terrain)['materials'][0]
        self.assertEqual(material['blueprint_total'], 2)
        self.assertEqual(material['already_correct'], 1)
        self.assertEqual(material['remaining_upper_bound'], 1)

    def test_offhand_not_credited(self):
        snapshot = state()
        snapshot['player']['inventory'][0] = dict(slot=0, count=0, empty=True, id='')
        snapshot['player']['offhand'] = dict(count=64, empty=False, id='minecraft:oak_planks')
        self.assert_blocked(self.run_plan(snapshot=snapshot))

    def test_duplicate_inventory_slots_fail(self):
        snapshot = state()
        snapshot['player']['inventory'][1]['slot'] = 0
        with self.assertRaises(PlanError):
            parse_inventory(snapshot)

    def test_inventory_total_requires_integer_schema_type(self):
        snapshot = state()
        snapshot['player']['inventory_total'] = 36.0
        with self.assertRaises(PlanError):
            parse_inventory(snapshot)

    def test_empty_entity_scan_needs_geometric_coverage(self):
        snapshot = state()
        snapshot['nearby']['radius'] = 0
        self.assert_blocked(self.run_plan(snapshot=snapshot))

    def test_truncated_empty_entity_scan_blocks(self):
        snapshot = state()
        snapshot['nearby']['truncated'] = True
        self.assert_blocked(self.run_plan(snapshot=snapshot))

    def test_player_overlap_blocks(self):
        snapshot = state()
        snapshot['player']['x'] = snapshot['player']['z'] = 0.5
        self.assert_blocked(self.run_plan(snapshot=snapshot))

    def test_neighbor_hazard_blocks_whole_plan(self):
        terrain = pages()
        raw = replace_cell(terrain, (1, 0, 0), 'minecraft:air')
        raw['hazards'] = ['lava']
        self.assert_blocked(self.run_plan(terrain=terrain))

    def test_mixed_generation_is_rejected(self):
        terrain = pages()
        terrain[1]['world_generation'] = SCAN
        with self.assertRaises(PlanError):
            Terrain.parse(terrain)

    def test_duplicate_page_is_rejected(self):
        terrain = pages()
        with self.assertRaises(PlanError):
            Terrain.parse([terrain[0], terrain[0], *terrain[1:]])

    def test_contradictory_air_collision_bounds_cannot_be_clear(self):
        raw = cell(0, 0, 0)
        raw['collision_bounds'] = [0, 0, 0, 1, 1, 1]
        self.assertNotEqual(Cell.parse(raw).kind, 'clear')

    def test_loaded_out_of_world_support_cannot_enable_plan(self):
        # A vanilla Overworld placement at -64 cannot anchor to a loaded block at -65.
        try:
            result = self.run_plan(blueprint(y=-64), pages(origin_y=-64), state(y=-64))
        except PlanError:
            return
        self.assert_blocked(result)

    def test_huge_numeric_json_is_structured_failure(self):
        snapshot = state()
        snapshot['player']['x'] = 10 ** 1000
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            for name, value in [('blueprint', blueprint().spec()), ('terrain', pages()), ('state', snapshot)]:
                (folder / (name + '.json')).write_text(json.dumps(value))
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = main(['plan', '--blueprint', str(folder/'blueprint.json'),
                             '--terrain', str(folder/'terrain.json'), '--state', str(folder/'state.json')])
            self.assertIn(code, (2, 3))
            result = json.loads(stderr.getvalue() if code == 2 else stdout.getvalue())
            self.assertEqual(result['proposed_placements'], [])
            self.assertIs(result['executable'], False)


if __name__ == '__main__':
    unittest.main()

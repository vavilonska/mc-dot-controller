"""Offline regression against sanitized, genuinely captured terrain responses.

No network or game calls. Synthetic monotonic receipt times test parsing only;
there is no claim that a historical file is currently fresh enough for actions.
"""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import unittest
from navigation_controller.executor import in_corridor
from navigation_controller.observation import Position
from navigation_controller.planner import plan
from navigation_controller.terrain import Block, TerrainAssembler, TerrainError, WorldStamp


class CapturedTerrainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.capture = json.loads((Path(__file__).parent / 'fixtures' / 'captured_terrain_schema1.json').read_text())

    def assemble(self, group):
        before = WorldStamp.parse(self.capture['world_before'])
        after = WorldStamp.parse(self.capture['world_after'])
        scan = TerrainAssembler(before, now=100)
        for page in self.capture[group]:
            scan.add(page, now=101)
        return scan.finish(after, now=101)

    def test_all_actual_response_shapes_parse(self):
        for group, count in (('one', 1), ('cube', 27), ('paging', 27), ('boundary', 17)):
            with self.subTest(group=group):
                self.assertEqual(len(self.assemble(group).cells), count)

    def test_actual_order_metadata_matches_coordinates(self):
        for group in ('one', 'cube', 'paging', 'boundary'):
            for page in self.capture[group]:
                self.assertEqual(page['order'], 'x_then_z_then_y')
                width = 2 * page['radius'] + 1
                origin = Block.parse(page['origin'])
                for offset, cell in enumerate(page['cells'], page['offset']):
                    self.assertEqual(Block.parse(cell), Block(
                        origin.x - page['radius'] + offset % width,
                        origin.y - page['vertical'] + offset // (width * width),
                        origin.z - page['radius'] + (offset // width) % width))

    def test_actual_cube_has_grass_floor_and_air_headroom(self):
        cells = self.capture['cube'][0]['cells']
        self.assertEqual(Counter(c['id'] for c in cells), {'minecraft:grass_block': 9, 'minecraft:air': 18})
        grid = self.assemble('cube')
        for x in (-1, 0, 1):
            for z in (-1, 0, 1):
                self.assertTrue(grid.standable(Block(x, -60, z)))

    def test_actual_seven_pages_equal_single_cube(self):
        self.assertEqual([p['returned'] for p in self.capture['paging']], [4, 4, 4, 4, 4, 4, 3])
        cells = [c for p in self.capture['paging'] for c in p['cells']]
        self.assertEqual(cells, self.capture['cube'][0]['cells'])
        self.assertEqual(self.assemble('paging').cells, self.assemble('cube').cells)

    def test_actual_cube_and_pages_plan_same_cardinal_path(self):
        for group in ('cube', 'paging'):
            grid = self.assemble(group)
            target = grid.origin.offset(x=1)
            result = plan(grid, grid.origin, target, WorldStamp.parse(self.capture['world_after']), now=101)
            self.assertEqual(result.reason, 'path_found')
            self.assertEqual(result.route.nodes, (grid.origin, target))

    def test_actual_cube_and_pages_plan_safe_diagonal(self):
        for group in ('cube', 'paging'):
            grid = self.assemble(group)
            target = grid.origin.offset(x=1, z=1)
            result = plan(grid, grid.origin, target, WorldStamp.parse(self.capture['world_after']), now=101)
            self.assertEqual(result.reason, 'path_found')
            self.assertAlmostEqual(result.route.cost, 2**.5)

    def test_actual_boundary_unknowns_remain_blocked(self):
        page = self.capture['boundary'][0]
        self.assertEqual(page['unknown_cells'], 4)
        grid = self.assemble('boundary')
        unknowns = [c for c in page['cells'] if c['known'] is False]
        self.assertEqual([c['y'] for c in unknowns], [-68, -67, -66, -65])
        for cell in unknowns:
            self.assertEqual(cell['status'], 'out_of_world')
            self.assertNotIn('id', cell)
            pos = Block.parse(cell)
            self.assertFalse(grid.clear(pos))
            self.assertFalse(grid.support(pos))

    def test_boundary_scan_cannot_infer_adjacent_column(self):
        grid = self.assemble('boundary')
        result = plan(grid, grid.origin, grid.origin.offset(x=1), WorldStamp.parse(self.capture['world_after']), now=101)
        self.assertEqual(result.reason, 'target_or_start_out_of_bounds')

    def test_captured_scan_not_fresh_enough_for_final_state_action(self):
        after = WorldStamp.parse(self.capture['world_after'])
        for group, expected_age in (('cube', 16), ('paging', 14)):
            grid = self.assemble(group)
            self.assertEqual(after.tick - grid.first_tick, expected_age)
            with self.assertRaisesRegex(TerrainError, 'stale_terrain_ticks'):
                grid.require_fresh(after, now=101, max_age_ticks=2, max_wall_age=2)

    def test_capture_is_not_a_complete_execution_observation(self):
        self.assertEqual(self.capture['player_before'], self.capture['player_after'])
        self.assertEqual(self.capture['nearby']['radius'], 0)
        position = Position.parse(self.capture['player_after'])
        self.assertFalse(in_corridor(position, position.block(), position.block()))
        # There are no status samples here; no fabricated live observation is made.

    def test_reordered_captured_cells_are_rejected(self):
        page = deepcopy(self.capture['cube'][0])
        page['cells'][0], page['cells'][1] = page['cells'][1], page['cells'][0]
        scan = TerrainAssembler(WorldStamp.parse(self.capture['world_before']), now=100)
        with self.assertRaises(TerrainError):
            scan.add(page, now=101)

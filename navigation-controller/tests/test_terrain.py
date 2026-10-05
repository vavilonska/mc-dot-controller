from copy import deepcopy
from dataclasses import replace
import unittest
from navigation_controller.fake import FakeClock, FakeWorld, WORLD_ID
from navigation_controller.terrain import Block, Cell, TerrainAssembler, TerrainError, WorldStamp
from navigation_controller.reader import collect_terrain


class TerrainTests(unittest.TestCase):
    def setUp(self):
        self.world = FakeWorld()
        self.stamp = WorldStamp(WORLD_ID, 'minecraft:overworld', 100)

    def assemble(self, pages):
        scan = TerrainAssembler(self.stamp, 100)
        for page in pages:
            scan.add(page, 100)
        return scan.finish(self.stamp, 100)

    def test_actual_schema_paged_complete_coverage(self):
        pages = self.world.pages()
        self.assertEqual(len(pages), 4)
        grid = self.assemble(pages)
        self.assertEqual(len(grid.cells), 405)
        self.assertTrue(grid.standable(Block(0, 64, 0)))

    def test_final_cursor_absent_or_null(self):
        for explicit in (False, True):
            pages = self.world.pages()
            if explicit:
                pages[-1]['next_cursor'] = None
            self.assertTrue(self.assemble(pages).complete)

    def test_unknown_cells_never_air_or_support(self):
        for status in ('unloaded', 'read_failed', 'out_of_world'):
            self.world.unknown(Block(1, 64, 0), status)
            grid = self.assemble(self.world.pages())
            self.assertFalse(grid.clear(Block(1, 64, 0)))
            self.assertFalse(grid.standable(Block(1, 64, 0)))

    def test_incomplete_scan_rejected(self):
        scan = TerrainAssembler(self.stamp, 100)
        scan.add(self.world.pages()[0], 100)
        with self.assertRaises(TerrainError):
            scan.finish(self.stamp, 100)

    def test_world_reset_poisoned_scan(self):
        pages = self.world.pages()
        scan = TerrainAssembler(self.stamp, 100)
        scan.add(pages[0], 100)
        pages[1]['world_generation'] = '00000000-0000-4000-8000-000000000099'
        with self.assertRaises(TerrainError):
            scan.add(pages[1], 100)
        self.assertFalse(scan.cells)
        with self.assertRaises(TerrainError):
            scan.add(self.world.pages()[1], 100)

    def test_scan_generation_changed(self):
        pages = self.world.pages()
        pages[1]['generation'] = '00000000-0000-4000-8000-000000000099'
        with self.assertRaises(TerrainError):
            self.assemble(pages)

    def test_reordered_or_duplicate_page_rejected(self):
        pages = self.world.pages()
        for altered in ([pages[1], pages[0]], [pages[0], pages[0]]):
            with self.assertRaises(TerrainError):
                self.assemble(altered)

    def test_forged_metadata_rejected(self):
        mutations = {'schema_version': True, 'terrain_schema_version': True, 'read_only': False,
                     'loaded_chunks_only': False, 'consistency': 'atomic', 'order': 'other',
                     'radius': 17, 'vertical': 9, 'total_cells': 1, 'returned': 999,
                     'offset': 1, 'next_offset': 1, 'complete': True, 'next_cursor': 'arbitrary',
                     'unknown_cells': 1, 'response_game_time': 99, 'game_time': 99}
        for key, value in mutations.items():
            with self.subTest(key=key):
                pages = self.world.pages()
                pages[0][key] = value
                with self.assertRaises(TerrainError):
                    self.assemble(pages)

    def test_duplicate_cell_rejected(self):
        pages = self.world.pages()
        pages[0]['cells'][1] = deepcopy(pages[0]['cells'][0])
        with self.assertRaises(TerrainError):
            self.assemble(pages)

    def test_capped_page_budget_can_continue(self):
        pages = self.world.pages(limit=16)
        for p in pages:
            p['budget_exhausted'] = not p['complete']
        self.assertTrue(self.assemble(pages).complete)

    def test_max_pages_budget(self):
        scan = TerrainAssembler(self.stamp, 100, max_pages=1)
        scan.add(self.world.pages()[0], 100)
        with self.assertRaises(TerrainError):
            scan.add(self.world.pages()[1], 100)

    def test_wall_budget(self):
        scan = TerrainAssembler(self.stamp, 100)
        with self.assertRaises(TerrainError):
            scan.add(self.world.pages()[0], 104)

    def test_tick_budget(self):
        pages = self.world.pages(tick_per_page=20)
        with self.assertRaises(TerrainError):
            self.assemble(pages)

    def test_tick_reversal(self):
        pages = self.world.pages(tick_per_page=1)
        pages[2]['game_time'] = pages[2]['response_game_time'] = 100
        with self.assertRaises(TerrainError):
            self.assemble(pages)

    def test_stale_finished_grid(self):
        grid = self.world.grid()
        for stamp, now in ((replace(self.stamp, tick=141), 100), (self.stamp, 104), (self.stamp, 99)):
            with self.assertRaises(TerrainError):
                grid.require_fresh(stamp, now)

    def test_new_world_invalidates_finished_grid(self):
        with self.assertRaises(TerrainError):
            self.world.grid().require_fresh(replace(self.stamp, generation='00000000-0000-4000-8000-000000000099'), 100)

    def test_future_grid_rejected(self):
        with self.assertRaises(TerrainError):
            self.world.grid().require_fresh(replace(self.stamp, tick=99), 100)

    def test_grid_cells_immutable(self):
        grid = self.world.grid()
        with self.assertRaises(TypeError):
            grid.cells[Block(0, 64, 0)] = None

    def test_uncertain_cell_flags_block(self):
        mutations = {'collision_known': False, 'id_truncated': True, 'fluid_truncated': True,
                     'properties_truncated': True, 'hazards': ['water'], 'fluid': 'minecraft:water',
                     'fluid_source': True, 'properties': None, 'id': 'example:air', 'air': False,
                     'hazards_exhaustive': True, 'collision_empty': False}
        for key, value in mutations.items():
            with self.subTest(key=key):
                raw = self.world.get(Block(0, 64, 0))
                raw[key] = value
                self.assertFalse(Cell.parse(raw).clear)

    def test_unallowlisted_slabs_falling_and_damage_blocks_block(self):
        for kind in ('sand', 'gravel', 'magma_block', 'oak_slab', 'ice', 'powder_snow', 'cactus'):
            self.world.set(Block(0, 63, 0), kind)
            self.assertFalse(self.world.grid().standable(Block(0, 64, 0)))

    def test_non_cube_support_blocked(self):
        for bounds in ([0, 0, 0, 1, 0.5, 1], [0, 0, 0, 1, 2, 1], [0, 0, 0, 1, float('nan'), 1]):
            self.world.set(Block(0, 63, 0), collision_bounds=bounds)
            self.assertFalse(self.world.grid().standable(Block(0, 64, 0)))

    def test_nether_not_supported(self):
        with self.assertRaises(TerrainError):
            WorldStamp(WORLD_ID, 'minecraft:the_nether', 100)

    def test_boolean_coordinate_rejected(self):
        with self.assertRaises(TerrainError):
            Block(True, 64, 0)

    def test_reader_uses_bounded_get_paths_and_pacing(self):
        clock = FakeClock()
        pages = iter(self.world.pages(tick_per_page=1))
        paths = []
        def fetch(path):
            paths.append(path)
            return next(pages)
        def stamp():
            return replace(self.stamp, tick=100 + int(round((clock.now - 100) * 20)))
        grid = collect_terrain(fetch, stamp, clock)
        self.assertTrue(grid.complete)
        self.assertEqual(paths[0], '/control/terrain?radius=4&vertical=2&limit=128')
        self.assertEqual(len(paths), 4)
        self.assertAlmostEqual(clock.now, 100.15)
        self.assertTrue(all(p.startswith('/control/terrain?cursor=') for p in paths[1:]))

    def test_reader_aborts_without_retries_on_error(self):
        calls = []
        def fetch(path):
            calls.append(path)
            raise RuntimeError('fake 409')
        with self.assertRaises(RuntimeError):
            collect_terrain(fetch, lambda: self.stamp, FakeClock())
        self.assertEqual(len(calls), 1)

    def test_reader_stops_before_fetch_when_sleep_expires_budget(self):
        calls = []
        pages = iter(self.world.pages())
        def fetch(path):
            calls.append(path)
            return next(pages)
        with self.assertRaises(TerrainError):
            collect_terrain(fetch, lambda: self.stamp, FakeClock(), max_seconds=.025)
        self.assertEqual(len(calls), 1)

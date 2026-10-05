from dataclasses import replace
import unittest
from navigation_controller.fake import FakeWorld, WORLD_ID
from navigation_controller.terrain import Block, WorldStamp
from navigation_controller.planner import PlanConfig, plan, safe_edge


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.world = FakeWorld()
        self.stamp = WorldStamp(WORLD_ID, 'minecraft:overworld', 100)
        self.start = Block(0, 64, 0)

    def plan(self, target=Block(3, 64, 0), **kwargs):
        return plan(self.world.grid(), self.start, target, self.stamp, 100, **kwargs)

    def test_flat_path(self):
        result = self.plan()
        self.assertEqual(result.reason, 'path_found')
        self.assertEqual(result.route.nodes, tuple(Block(x, 64, 0) for x in range(4)))
        self.assertEqual(result.route.cost, 3)

    def test_diagonal_path(self):
        result = self.plan(Block(3, 64, 3))
        self.assertEqual(len(result.route.nodes), 4)
        self.assertAlmostEqual(result.route.cost, 3 * 2**0.5)

    def test_disable_diagonals(self):
        result = self.plan(Block(3, 64, 3), config=PlanConfig(diagonals=False))
        self.assertEqual(len(result.route.nodes), 7)

    def test_obstacle_detour(self):
        self.world.set(Block(1, 64, 0))
        result = self.plan()
        self.assertIsNotNone(result.route)
        self.assertNotIn(Block(1, 64, 0), result.route.nodes)
        self.assertGreater(result.route.cost, 3)

    def test_headroom_obstacle_detour(self):
        self.world.set(Block(1, 65, 0))
        self.assertNotIn(Block(1, 64, 0), self.plan().route.nodes)

    def test_diagonal_corner_cut_prevented(self):
        self.world.set(Block(1, 64, 0))
        grid = self.world.grid()
        self.assertFalse(safe_edge(grid, self.start, Block(1, 64, 1)))
        self.assertGreater(len(self.plan(Block(1, 64, 1)).route.nodes), 2)

    def test_diagonal_unknown_corner_prevented(self):
        self.world.unknown(Block(1, 63, 0))
        self.assertFalse(safe_edge(self.world.grid(), self.start, Block(1, 64, 1)))

    def test_ledge_two_blocks_never_traversed(self):
        for x in range(1, 5):
            for z in range(-4, 5):
                self.world.set(Block(x, 63, z), 'air')
                self.world.set(Block(x, 62, z), 'air')
        result = self.plan(Block(2, 64, 0))
        self.assertIsNone(result.route)

    def test_one_block_step_down_planned(self):
        self.world.set(Block(1, 63, 0), 'air')
        result = self.plan(Block(1, 63, 0))
        self.assertEqual(result.reason, 'path_found')
        self.assertEqual(result.route.nodes, (self.start, Block(1, 63, 0)))

    def test_step_down_old_head_height_required(self):
        self.world.set(Block(1, 63, 0), 'air')
        self.world.set(Block(1, 65, 0))
        self.assertFalse(safe_edge(self.world.grid(), self.start, Block(1, 63, 0)))

    def test_step_down_can_be_disabled(self):
        self.world.set(Block(1, 63, 0), 'air')
        self.assertIsNone(self.plan(Block(1, 63, 0), config=PlanConfig(step_down=False)).route)

    def test_no_diagonal_step_down(self):
        self.world.set(Block(1, 63, 1), 'air')
        self.assertFalse(safe_edge(self.world.grid(), self.start, Block(1, 63, 1)))

    def test_ascent_jump_deferred(self):
        self.world.set(Block(1, 64, 0))
        self.assertEqual(self.plan(Block(1, 65, 0)).reason, 'jump_required_unsupported')

    def test_unknown_barrier_no_path(self):
        for z in range(-4, 5):
            self.world.unknown(Block(1, 64, z))
        self.assertEqual(self.plan().reason, 'no_path_within_budget')

    def test_hazard_barrier_no_path(self):
        for z in range(-4, 5):
            self.world.set(Block(1, 63, z), 'magma_block', hazards=['contact_damage'])
        self.assertIsNone(self.plan().route)

    def test_missing_support_detour(self):
        self.world.set(Block(1, 63, 0), 'air')
        self.assertNotIn(Block(1, 64, 0), self.plan().route.nodes)

    def test_target_out_of_bounds(self):
        self.assertEqual(self.plan(Block(5, 64, 0)).reason, 'target_or_start_out_of_bounds')

    def test_stale_snapshot_rejected(self):
        self.stamp = replace(self.stamp, tick=141)
        self.assertEqual(self.plan().reason, 'stale_terrain_ticks')

    def test_generation_reset_rejected(self):
        self.stamp = replace(self.stamp, generation='00000000-0000-4000-8000-000000000099')
        self.assertEqual(self.plan().reason, 'world_generation_changed')

    def test_expansion_budget(self):
        self.assertEqual(self.plan(config=PlanConfig(max_expansions=1)).reason, 'expansion_budget_exhausted')

    def test_frontier_budget(self):
        self.assertEqual(self.plan(config=PlanConfig(max_frontier=1)).reason, 'frontier_budget_exhausted')

    def test_time_budget(self):
        ticks = iter([0, 1])
        self.assertEqual(self.plan(clock=lambda: next(ticks)).reason, 'time_budget_exhausted')

    def test_path_length_budget(self):
        self.assertIsNone(self.plan(config=PlanConfig(max_path_steps=1)).route)

    def test_start_equals_target(self):
        self.assertEqual(self.plan(self.start).route.nodes, (self.start,))

    def test_unknown_start_rejected(self):
        self.world.unknown(self.start)
        self.assertEqual(self.plan().reason, 'start_not_supported_or_unknown')

    def test_cost_depth_labels_preserve_bounded_detour(self):
        rows = (
            'S..........###.#..#', '..##.#..#...#......', '............#......',
            '.#.#.#....#......##', '#..#..#.#..#.#.#.#.', '..##.........#....#',
            '...#....#.......#..', '............#....#.', '#......#...#.#...#.',
            '......#...#.#..##..', '........##.......#.', '............#...#..',
            '.#....#.#..........', '#....#.#.#.........', '#..##..#....#....##',
            '##.#...........#...', '...#....#......##..', '..#..#.#...##......',
            '......#.#.#.......T',
        )
        world = FakeWorld(floor_y=-1)
        for z, row in enumerate(rows):
            for x, symbol in enumerate(row):
                if symbol == '#':
                    world.set(Block(x, 0, z))
        grid = world.grid(origin=Block(9, 0, 9), radius=9, vertical=1)
        result = plan(grid, Block(0, 0, 0), Block(18, 0, 18), self.stamp, 100,
                      config=PlanConfig(step_down=False, max_path_steps=27), clock=lambda: 0)
        self.assertEqual(result.reason, 'path_found')
        self.assertLessEqual(len(result.route.nodes)-1, 27)
        self.assertTrue(all(safe_edge(grid, a, b) for a, b in zip(result.route.nodes, result.route.nodes[1:])))

    def test_seeded_maps_match_bfs_feasibility_with_edge_budget(self):
        from collections import deque
        import random
        from navigation_controller.planner import neighbors
        randomizer = random.Random(726)
        config = PlanConfig(step_down=False, max_path_steps=7)
        for _ in range(50):
            world = FakeWorld()
            target = Block(3, 64, 3)
            for x in range(-4, 5):
                for z in range(-4, 5):
                    pos = Block(x, 64, z)
                    if pos not in (self.start, target) and randomizer.random() < .24:
                        world.set(pos)
            grid = world.grid()
            queue = deque([(self.start, 0)])
            seen, feasible = {self.start}, False
            while queue:
                pos, depth = queue.popleft()
                if pos == target:
                    feasible = True
                    break
                if depth == config.max_path_steps:
                    continue
                for candidate, _ in neighbors(grid, pos, config):
                    if candidate not in seen:
                        seen.add(candidate)
                        queue.append((candidate, depth+1))
            result = plan(grid, self.start, target, self.stamp, 100, config=config, clock=lambda: 0)
            self.assertEqual(result.route is not None, feasible)
            if result.route:
                self.assertLessEqual(len(result.route.nodes)-1, config.max_path_steps)
                self.assertTrue(all(safe_edge(grid, a, b) for a, b in zip(result.route.nodes, result.route.nodes[1:])))

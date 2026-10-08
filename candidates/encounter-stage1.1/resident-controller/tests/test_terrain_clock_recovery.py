"""Synthetic client-clock correction; no live evidence, transport or gameplay."""
import unittest

from test_terrain_diagnostics import run_scan, world, G2


def rewind(page, bridge):
    page.update(game_time=100 + bridge.pages - 2,
                response_game_time=100 + bridge.pages - 2)


class TerrainClockRecoveryTests(unittest.TestCase):
    def test_correction_discards_batch_and_starts_fresh_scan(self):
        evidence, cache, bridge = run_scan(world, frozen_tick=False,
            faults={('page', 3): rewind})
        self.assertEqual(evidence[0][0], 'ok')
        self.assertEqual(cache.terrain_read['outcome'], 'recovered')
        self.assertEqual(cache.grid.scan_generation, G2)
        d = cache.terrain_read['diagnostics']
        self.assertEqual(d['actual_attempts'], 2)
        self.assertEqual(d['total_budget_ms'], 3000)
        self.assertLess(d['attempts'][1]['assembler_budget_ms'], 3000)
        self.assertEqual(d['attempts'][0]['original_rejection']['detail'], 'terrain_page_tick_reversed')
        self.assertTrue(d['attempts'][0]['original_rejection']['refreshable'])
        self.assertEqual(sum('limit=128' in path for _, path in bridge.calls), 2)
        # The accepted grid is entirely the second generation, starting after
        # the discarded third page; no cells/age from the poisoned batch survive.
        self.assertEqual(cache.grid.first_tick, 104)
        self.assertEqual(cache.grid.last_tick, 108)
        self.assertEqual(len(cache.grid.cells), 567)

    def test_repeated_correction_exhausts_existing_two_attempts(self):
        evidence, cache, bridge = run_scan(world, frozen_tick=False,
            faults={('page', 3): rewind, ('page', 6): rewind})
        self.assertEqual(evidence[0][0], 'error')
        self.assertIn('terrain_refresh_exhausted_terrain_page_tick_reversed', evidence[0][-1])
        self.assertEqual(cache.terrain_read['attempts'], 2)
        self.assertEqual(bridge.attempt, 2)
        self.assertIsNone(cache.grid)
        self.assertEqual(cache.cells, {})

    def test_recovery_keeps_original_deadline(self):
        evidence, cache, bridge = run_scan(world, frozen_tick=False, page_delay=.45,
            faults={('page', 3): rewind})
        self.assertEqual(evidence[0][0], 'error')
        self.assertIn('stale_terrain_clock', evidence[0][-1])
        d = cache.terrain_read['diagnostics']
        self.assertEqual(d['total_budget_ms'], 3000)
        self.assertEqual(bridge.attempt, 2)
        self.assertLess(d['attempts'][1]['assembler_budget_ms'], 1600)
        self.assertIsNone(cache.grid)
        self.assertEqual(cache.cells, {})

    def test_no_remaining_budget_means_no_second_scan(self):
        evidence, cache, bridge = run_scan(world, frozen_tick=False, page_delay=.96,
            faults={('page', 3): rewind})
        self.assertEqual(evidence[0][0], 'error')
        self.assertEqual(bridge.attempt, 1)
        self.assertIsNone(cache.grid)

    def test_malformed_rewound_page_is_not_refreshable(self):
        def corrupt(page, bridge):
            rewind(page, bridge)
            page['offset'] = 0
        evidence, cache, bridge = run_scan(world, frozen_tick=False,
            faults={('page', 3): corrupt})
        self.assertEqual(evidence[0][-1], 'invalid_terrain_page_noncontiguous_page')
        self.assertEqual(bridge.attempt, 1)
        self.assertIsNone(cache.grid)

    def test_changed_world_during_refresh_is_still_rejected(self):
        def changed(state, bridge):
            state['world']['world_generation'] = G2
        evidence, cache, bridge = run_scan(world, frozen_tick=False,
            faults={('page', 3): rewind, ('state', 2): changed})
        self.assertEqual(evidence[0][-1], 'terrain_refresh_context_changed')
        self.assertEqual(bridge.attempt, 1)  # No new terrain GET in the other world.
        self.assertIsNone(cache.grid)

    def test_state_clock_before_original_baseline_still_rejected(self):
        def changed(state, bridge):
            state['world']['game_time'] = 99
        evidence, cache, bridge = run_scan(world, frozen_tick=False,
            faults={('page', 3): rewind, ('state', 2): changed})
        self.assertEqual(evidence[0][-1], 'terrain_state_tick_reversed')
        self.assertEqual(bridge.attempt, 1)
        self.assertIsNone(cache.grid)


if __name__ == '__main__':
    unittest.main()

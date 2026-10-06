"""Offline paginated-read regressions. No sockets, credentials or live queue."""
import copy
import unittest
from unittest.mock import patch

from resident_controller.world import WorldCache
from resident_controller.transport import BridgeError
from navigation_controller.fake import FakeClock, FakeWorld, WORLD_ID
from navigation_controller.terrain import Block, TerrainAssembler, TerrainError, TerrainPageError, WorldStamp
import test_native_combat as combat_tests


SCAN_TWO = '00000000-0000-4000-8000-000000000009'


class ScriptedBridge:
    def __init__(self, clock, scripts):
        self.clock, self.scripts = clock, scripts
        self.calls, self.scan_count, self.page_count, self.state_reads = [], 0, 0, 0
        self.pages = iter(())
        self.state_hook = self.page_hook = self.before_read = None

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        assert method == 'GET' and body is None
        if self.before_read:
            self.before_read()
        if path.startswith('/control/state?'):
            self.state_reads += 1
            state = {'world': {'world_generation': WORLD_ID, 'dimension': 'minecraft:overworld',
                              'game_time': 100 + int(round((self.clock.now - 100) * 20))},
                     'player': {'uuid': 'synthetic-player', 'x': .5, 'y': 64, 'z': .5},
                     'client_action': {'action_session': 'synthetic-session'}}
            if self.state_hook:
                self.state_hook(self.state_reads, state)
            return state
        if path.startswith('/control/terrain?radius='):
            script = self.scripts[self.scan_count]
            self.scan_count += 1
            self.pages = iter(script(self) if callable(script) else script)
        else:
            assert path.startswith('/control/terrain?cursor=')
        value = next(self.pages)
        self.page_count += 1
        if self.page_hook:
            self.page_hook(self.page_count)
        if isinstance(value, Exception):
            raise value
        return copy.deepcopy(value)


def fresh(bridge, **kwargs):
    return FakeWorld().pages(radius=3, tick=100 + int(round((bridge.clock.now - 100) * 20)),
                             scan_id=SCAN_TWO, **kwargs)


class TerrainRecoveryChecks(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.monotonic = patch('time.monotonic', self.clock.monotonic)
        self.sleep = patch('time.sleep', self.clock.sleep)
        self.monotonic.start(); self.sleep.start()
        self.addCleanup(self.monotonic.stop); self.addCleanup(self.sleep.stop)
        self.cache = WorldCache()

    def scan(self, scripts, **kwargs):
        self.bridge = ScriptedBridge(self.clock, scripts)
        for key, value in kwargs.items():
            setattr(self.bridge, key, value)
        return self.cache.scan(self.bridge, radius=3, vertical=2)

    def empty_cache(self):
        self.assertIsNone(self.cache.grid)
        self.assertEqual(self.cache.cells, {})
        self.assertEqual(self.cache.terrain_received_at, 0)

    def old(self):
        return FakeWorld().pages(radius=3, tick=99)

    def test_valid_aged_page_starts_new_scan_and_publishes_only_new_generation(self):
        result = self.scan([self.old(), fresh])
        self.assertTrue(result['complete'])
        self.assertEqual(self.bridge.scan_count, 2)
        self.assertEqual(self.cache.grid.scan_generation, SCAN_TWO)
        self.assertEqual(self.cache.terrain_read['outcome'], 'recovered')
        self.assertEqual(self.cache.terrain_read['last_rejection'], 'stale_terrain_page_ticks')
        self.assertNotIn('00000000-0000-4000-8000-000000000002:',
                         ' '.join(path for _, path, _ in self.bridge.calls))

    def test_failed_partial_scan_is_discarded_before_new_initial_request(self):
        pages = FakeWorld().pages(radius=3)
        pages[1]['game_time'] = pages[1]['response_game_time'] = 141
        self.scan([pages, fresh])
        terrain_paths = [p for _, p, _ in self.bridge.calls if '/terrain?' in p]
        self.assertEqual(['cursor=' in p for p in terrain_paths], [False, True, False, True])
        self.assertEqual(len(self.cache.cells), 245)

    def test_persistent_expiry_is_bounded_to_two_attempts_and_no_success(self):
        with self.assertRaisesRegex(TerrainError, 'terrain_refresh_exhausted_stale_terrain_page_ticks'):
            self.scan([self.old(), self.old()])
        self.assertEqual(self.bridge.scan_count, 2)
        self.assertEqual(self.bridge.page_count, 2)
        self.empty_cache()
        self.assertEqual(self.cache.terrain_read['outcome'], 'failed')

    def test_old_cache_cleared_before_first_read_and_on_failure(self):
        self.cache.grid = FakeWorld().grid()
        self.cache.cells = {(0, 63, 0): {'old': True}}
        self.cache.terrain_received_at = 100
        with self.assertRaisesRegex(BridgeError, 'transport_failed'):
            self.scan([[BridgeError('transport_failed')]], before_read=self.empty_cache)
        self.empty_cache()

    def test_corrupt_expired_page_is_integrity_failure_without_retry(self):
        pages = self.old()
        pages[0]['next_cursor'] = 'malformed'
        with self.assertRaisesRegex(TerrainError, 'invalid_terrain_page_invalid_cursor'):
            self.scan([pages, fresh])
        self.assertEqual(self.bridge.scan_count, 1)
        self.empty_cache()

    def test_mixed_scan_world_reordered_and_bad_cell_count_never_retry(self):
        mutations = [('generation', SCAN_TWO), ('world_generation', SCAN_TWO),
                     ('offset', 0), ('returned', 1), ('game_time', 99)]
        for key, value in mutations:
            with self.subTest(key=key):
                self.clock.now = 100
                pages = FakeWorld().pages(radius=3)
                pages[1][key] = value
                with self.assertRaises(TerrainError):
                    self.scan([pages, fresh])
                self.assertEqual(self.bridge.scan_count, 1)
                self.empty_cache()

    def test_stale_cursor_and_rate_limit_retry_only_read_initial_request(self):
        for code, status in [('stale_terrain_cursor', 409), ('terrain_rate_limited', 429)]:
            with self.subTest(code=code):
                self.clock.now = 100
                self.scan([[BridgeError(code, status=status)], fresh])
                self.assertEqual(self.bridge.scan_count, 2)
                self.assertEqual(self.cache.terrain_read['outcome'], 'recovered')
                self.assertTrue(all(method == 'GET' for method, _, _ in self.bridge.calls))

    def test_wrong_status_auth_transport_uncertainty_and_busy_are_not_retried(self):
        failures = [BridgeError('stale_terrain_cursor', status=401),
                    BridgeError('terrain_rate_limited', status=500),
                    BridgeError('terrain_rate_limited', status=429, uncertain=True),
                    BridgeError('unauthorized', status=401), BridgeError('transport_failed'),
                    BridgeError('terrain_busy', status=429)]
        for failure in failures:
            with self.subTest(code=failure.code, status=failure.status):
                self.clock.now = 100
                with self.assertRaises(BridgeError):
                    self.scan([[failure], fresh])
                self.assertEqual(self.bridge.scan_count, 1)
                self.empty_cache()

    def test_world_or_player_or_action_session_changes_do_not_restart_in_new_context(self):
        for section, field in [('world', 'world_generation'), ('player', 'uuid'),
                               ('client_action', 'action_session')]:
            with self.subTest(field=field):
                self.clock.now = 100
                def change(read, state):
                    if read == 2:
                        state[section][field] = SCAN_TWO
                with self.assertRaisesRegex(TerrainError, 'terrain_refresh_context_changed'):
                    self.scan([self.old(), fresh], state_hook=change)
                self.assertEqual(self.bridge.scan_count, 1)
                self.empty_cache()

    def test_context_change_at_final_state_does_not_publish_grid(self):
        def change(read, state):
            if read == 2:
                state['client_action']['action_session'] = 'replacement'
        with self.assertRaisesRegex(TerrainError, 'terrain_refresh_context_changed'):
            self.scan([fresh], state_hook=change)
        self.empty_cache()

    def test_malformed_or_missing_initial_and_final_identity_fails_without_retry(self):
        for read_number in (1, 2):
            for section in ('player', 'client_action'):
                for value in (None, [], 'bad', {}, {'uuid': '', 'action_session': 1}):
                    with self.subTest(read=read_number, section=section, value=value):
                        self.clock.now = 100
                        def corrupt(read, state):
                            if read == read_number:
                                state[section] = value
                        with self.assertRaisesRegex(TerrainError, 'invalid_terrain_state_context'):
                            self.scan([fresh, fresh], state_hook=corrupt)
                        self.assertLessEqual(self.bridge.scan_count, 1)
                        self.assertEqual(self.cache.terrain_read['outcome'], 'failed')
                        self.empty_cache()

    def test_malformed_world_state_is_controlled_failure_without_retry(self):
        for read_number in (1, 2):
            self.clock.now = 100
            def corrupt(read, state):
                if read == read_number:
                    state['world'] = None
            with self.assertRaisesRegex(TerrainError, 'invalid_terrain_state_world'):
                self.scan([fresh, fresh], state_hook=corrupt)
            self.assertEqual(self.cache.terrain_read['outcome'], 'failed')
            self.assertLessEqual(self.bridge.scan_count, 1)
            self.empty_cache()

    def test_clock_budget_includes_initial_state_and_does_not_fetch_after_deadline(self):
        def slow_state(read, state):
            self.clock.now += 3.1
        with self.assertRaisesRegex(TerrainError, 'terrain_refresh_exhausted_stale_terrain_clock'):
            self.scan([fresh], state_hook=slow_state)
        self.assertEqual(self.bridge.page_count, 0)
        self.empty_cache()

    def test_slow_read_response_never_gets_fresh_arrival_stamp(self):
        def delay(read):
            self.clock.now += 3.1
        with self.assertRaisesRegex(TerrainError, 'terrain_refresh_exhausted_stale_terrain_clock'):
            self.scan([fresh], page_hook=delay)
        self.assertEqual(self.bridge.page_count, 1)
        self.empty_cache()

    def test_page_count_budget_stops_before_request_33(self):
        with self.assertRaisesRegex(TerrainError, 'scan_page_budget'):
            self.scan([lambda b: fresh(b, limit=1)])
        self.assertEqual(self.bridge.page_count, 32)
        self.assertEqual(self.bridge.scan_count, 1)
        self.empty_cache()

    def test_overslept_retry_does_not_start_another_state_read(self):
        with patch('time.sleep', lambda seconds: self.clock.sleep(3.1)):
            with self.assertRaisesRegex(TerrainError, 'terrain_refresh_exhausted_stale_terrain_clock'):
                self.scan([self.old(), fresh])
        self.assertEqual(self.bridge.state_reads, 1)
        self.assertEqual(self.bridge.page_count, 1)
        self.empty_cache()

    def test_expired_after_validation_does_not_start_final_state_read(self):
        original = TerrainAssembler.add
        def slow_validation(assembler, page, now):
            original(assembler, page, now)
            if assembler.complete:
                self.clock.now += 3.1
        with patch.object(TerrainAssembler, 'add', slow_validation):
            with self.assertRaisesRegex(TerrainError, 'terrain_refresh_exhausted_stale_terrain_clock'):
                self.scan([fresh])
        self.assertEqual(self.bridge.state_reads, 1)
        self.empty_cache()

    def test_last_state_aged_ticks_can_refresh_but_future_or_reversed_cannot(self):
        def jump_once(read, state):
            if read == 2:
                self.clock.now = 102.25
                state['world']['game_time'] = 145
        self.scan([fresh, fresh], state_hook=jump_once)
        self.assertEqual(self.bridge.scan_count, 2)
        self.clock.now = 100
        def reverse(read, state):
            if read == 2:
                state['world']['game_time'] = 99
        with self.assertRaisesRegex(TerrainError, 'terrain_state_tick_reversed'):
            self.scan([fresh, fresh], state_hook=reverse)
        self.assertEqual(self.bridge.scan_count, 1)
        self.empty_cache()

    def test_tick_reversal_after_aged_last_state_does_not_restart(self):
        def jump_and_reverse(read, state):
            if read == 2:
                state['world']['game_time'] = 145
        with self.assertRaisesRegex(TerrainError, 'terrain_state_tick_reversed'):
            self.scan([fresh, fresh], state_hook=jump_and_reverse)
        self.assertEqual(self.bridge.scan_count, 1)
        self.empty_cache()

    def test_cache_age_is_attempt_start_not_completion(self):
        self.scan([fresh])
        self.assertEqual(self.cache.terrain_received_at, 100)
        self.assertGreater(self.clock.now, self.cache.terrain_received_at)

    def test_route_uses_new_grid_and_changed_block_instead_of_old_partial(self):
        def blocked(bridge):
            world = FakeWorld()
            world.set(Block(1, 64, 0), 'stone')
            return world.pages(radius=3, tick=101, scan_id=SCAN_TWO)
        bridge = ScriptedBridge(self.clock, [self.old(), blocked])
        with self.assertRaisesRegex(ValueError, 'path_'):
            self.cache.route(bridge, {'x': 1, 'y': 64, 'z': 0}, radius=3)
        self.assertFalse(self.cache.grid.clear(Block(1, 64, 0)))
        self.assertEqual(self.cache.grid.scan_generation, SCAN_TWO)

    def test_assembler_legacy_message_has_machine_cause_and_poisoned_cells(self):
        assembler = TerrainAssembler(WorldStamp(WORLD_ID, 'minecraft:overworld', 100), 100)
        with self.assertRaises(TerrainPageError) as caught:
            assembler.add(self.old()[0], 100)
        self.assertEqual(str(caught.exception), 'invalid_or_stale_terrain_page')
        self.assertEqual(caught.exception.detail, 'stale_terrain_page_ticks')
        self.assertTrue(caught.exception.refreshable)
        self.assertTrue(assembler.failed)
        self.assertEqual(assembler.cells, {})


class CombatTerrainRecoveryChecks(unittest.TestCase):
    setUp = combat_tests.CombatChecks.setUp
    tearDown = combat_tests.CombatChecks.tearDown
    command = combat_tests.CombatChecks.command
    start = combat_tests.CombatChecks.start
    step = combat_tests.CombatChecks.step
    keys = combat_tests.CombatChecks.keys
    target = combat_tests.CombatChecks.target
    far_target = combat_tests.CombatChecks.far_target

    def terrain_bridge(self, broken=False):
        self.bridge.state['world'].update(world_generation=WORLD_ID, dimension='minecraft:overworld')
        self.far_target()
        self.start(approach=True)
        original = self.bridge.request
        self.scans = 0
        pages = iter(())
        def request(method, path, body=None):
            nonlocal pages
            if '/control/terrain?' not in path:
                return original(method, path, body)
            self.assertNotIn('key.forward', self.bridge.held)
            self.bridge.calls.append((method, path, body))
            if '?radius=' in path:
                self.scans += 1
                tick = self.bridge.state['world']['game_time']
                if self.scans == 1 or broken:
                    tick -= 1
                pages = iter(FakeWorld().pages(radius=3, tick=tick))
            return next(pages)
        self.bridge.request = request

    def test_successful_refresh_keeps_combat_active_but_reobserves_before_forward(self):
        self.terrain_bridge()
        with patch('time.sleep', lambda duration: setattr(self, 'now', self.now + duration)):
            self.step()
        self.assertEqual(self.scans, 2)
        self.assertTrue(self.resident.combat.active)
        self.assertEqual(self.resident.combat.phase, 'refreshing_approach')
        self.assertFalse(any(k['action'] == 'down' for k in self.keys('key.forward')))
        self.assertEqual(self.keys('key.attack'), [])
        self.step(.05)
        self.assertTrue(self.resident.combat.active)
        self.assertTrue(any(k['action'] == 'down' for k in self.keys('key.forward')))

    def test_exhausted_refresh_stops_and_releases_without_attack_or_false_success(self):
        self.terrain_bridge(broken=True)
        with patch('time.sleep', lambda duration: setattr(self, 'now', self.now + duration)):
            self.step()
        self.assertEqual(self.scans, 2)
        self.assertFalse(self.resident.combat.active)
        self.assertEqual(self.bridge.held, set())
        self.assertTrue(self.resident.combat.reason.startswith('terrain_refresh_exhausted_'))
        self.assertEqual(self.keys('key.attack'), [])
        self.assertEqual(self.resident.cache.cells, {})

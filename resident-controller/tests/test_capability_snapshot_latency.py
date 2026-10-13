"""Actual snapshot/scan code with deterministic endpoint latency, no game or sockets."""
import copy
import tempfile
import unittest
from unittest.mock import patch

from resident_controller.controller import Resident
from resident_controller.world import WorldCache
from resident_controller.transport import BridgeError
from navigation_controller.fake import FakeClock, FakeWorld, Block
from navigation_controller.terrain import CapabilityWorldStamp, TerrainAssembler, TerrainError
from test_navigation_snapshot import SnapshotBridge
from test_navigation_binding_producers import state
from test_terrain_recovery import ScriptedBridge
from capability_fixtures import native_bundle


def pages(*, limit=512, **options):
    result = FakeWorld().pages(limit=limit, **options)
    for page in result:
        page.update(capability_page_schema_version=1, page_limit=1024)
    return result


class TimedSnapshotBridge(SnapshotBridge):
    def __init__(self, clock, states, terrain_pages):
        super().__init__(states)
        self.clock = clock
        # Replace the default radius-one scripted page completely.
        from collections import deque
        self.reads.pages = deque(copy.deepcopy(terrain_pages))
        self.delay = .03
        self.bundle_delay = 0

    def request(self, method, path, body=None):
        self.clock.now += self.bundle_delay + self.delay if '/capability-snapshot?' in path else self.delay
        if '/capability-snapshot?' in path:
            from urllib.parse import parse_qs, urlsplit
            self.calls.append((method, path, copy.deepcopy(body)))
            return native_bundle(self.reads.states.popleft(), int(parse_qs(urlsplit(path).query)['radius'][0]))
        return super().request(method, path, body)


class CapabilitySnapshotLatencyTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        for target, replacement in [('time.monotonic', self.clock.monotonic), ('time.sleep', self.clock.sleep)]:
            context = patch(target, replacement); context.start(); self.addCleanup(context.stop)

    def resident(self, states, terrain_pages):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        bridge = TimedSnapshotBridge(self.clock, states, terrain_pages)
        resident = Resident(bridge, temp.name); resident.start(); self.addCleanup(resident.lock.close)
        bridge.calls.clear()
        return resident, bridge

    def test_fresh_snapshot_reuses_only_current_a_and_keeps_complete_c(self):
        a, c = state(), state(tick=101)
        a.update(capability_guard={'source_tick': 100}, nearby={'entities': [{'uuid': 'old'}]}, native_living={'sample': 'old'})
        c.update(capability_guard={'source_tick': 101}, nearby={'entities': [{'uuid': 'fresh-48'}]}, native_living={'sample': 'fresh'})
        resident, bridge = self.resident([a, c], pages(radius=4, vertical=4))
        started = self.clock.now
        result = resident.snapshot({'terrain': True, 'radius': 4, 'vertical': 4,
                                    'capability_observation': True, 'entity_radius': 48})
        self.assertEqual(result['state'], native_bundle(c)['state'])
        self.assertEqual(len(result['terrain']['cells']), 729)
        self.assertAlmostEqual(self.clock.now - started, .17)
        self.assertAlmostEqual(result['terrain']['capture_started_mono'], started)
        paths = [path for _, path, _ in bridge.calls]
        self.assertEqual([p for p in paths if '/capability-snapshot?' in p], ['/control/capability-snapshot?radius=48'] * 2)
        self.assertEqual([p for p in paths if '/terrain?' in p][0],
                         '/control/terrain?radius=4&vertical=4&limit=1024&capability=1')
        self.assertEqual(sum('/terrain?' in p for p in paths), 2)
        diagnostic = result['terrain_read']['diagnostics']['attempts'][0]
        self.assertTrue(diagnostic['initial_state_reused'])
        self.assertFalse(diagnostic['initial_state_requested'])
        self.assertEqual(diagnostic['initial_state_capture']['entity_radius'], 48)

    def test_legacy_keeps_three_state_reads_and_six_pages(self):
        resident, bridge = self.resident([state()] * 3, FakeWorld().pages(radius=4, vertical=4))
        resident.snapshot({'terrain': True, 'radius': 4, 'vertical': 4})
        paths = [p for _, p, _ in bridge.calls]
        self.assertEqual(sum('/state?' in p for p in paths), 3)
        self.assertEqual(sum('/terrain?' in p for p in paths), 6)
        self.assertIn('/control/terrain?radius=4&vertical=4&limit=128', paths)

    def test_final_context_and_epoch_changes_are_nonretryable(self):
        variants = [('world', 'world_generation'), ('world', 'dimension'), ('player', 'uuid'),
                    ('client_action', 'action_session'), ('epoch', 'epoch')]
        for section, key in variants:
            with self.subTest(section=section, key=key):
                a, c = state(), state()
                if section == 'epoch': c['world']['navigation_guard']['epoch'] += 1
                elif key == 'dimension': c['world'][key] = c['player'][key] = 'minecraft:the_end'
                elif key == 'world_generation': c['world'][key] = '00000000-0000-4000-8000-000000000099'
                else: c[section][key] = 'replaced'
                resident, bridge = self.resident([a, c], pages(radius=1, vertical=2))
                with self.assertRaises(TerrainError):
                    resident.snapshot({'terrain': True, 'radius': 1, 'vertical': 2,
                                       'capability_observation': True, 'entity_radius': 48})
                self.assertIsNone(resident.cache.grid)
                self.assertEqual(sum('/terrain?' in p for _, p, _ in bridge.calls), 1)

    def test_delayed_bundle_does_not_restamp_a_or_read_after_deadline(self):
        resident, bridge = self.resident([state()], pages(radius=1, vertical=2))
        bridge.bundle_delay = 3.01
        with self.assertRaisesRegex(TerrainError, 'terrain_refresh_exhausted_stale_terrain_clock'):
            resident.snapshot({'terrain': True, 'radius': 1, 'vertical': 2,
                               'capability_observation': True, 'entity_radius': 48})
        self.assertFalse(any('/terrain?' in p for _, p, _ in bridge.calls))
        self.assertIsNone(resident.cache.grid)

    def test_partial_failure_never_leaves_old_or_partial_cells(self):
        chunks = pages(radius=4, vertical=4)
        chunks[1]['page_limit'] = 128
        resident, bridge = self.resident([state()], chunks)
        resident.cache.grid = object(); resident.cache.cells = {'old': 'old'}
        with self.assertRaisesRegex(TerrainError, 'invalid_capability_page_profile'):
            resident.snapshot({'terrain': True, 'radius': 4, 'vertical': 4,
                               'capability_observation': True, 'entity_radius': 48})
        self.assertIsNone(resident.cache.grid); self.assertEqual(resident.cache.cells, {})
        self.assertEqual(sum('/capability-snapshot?' in p for _, p, _ in bridge.calls), 1)
        self.assertEqual(resident.cache.terrain_read['attempts'], 1)

    def test_requested_region_cannot_be_substituted(self):
        for options in ({'radius': 2}, {'vertical': 3}, {'origin': Block(1, 64, 0)}):
            with self.subTest(options=options):
                chunks = pages(**{'radius': 1, 'vertical': 2, **options})
                resident, _ = self.resident([state()], chunks)
                with self.assertRaisesRegex(TerrainError, 'terrain_requested_region_changed'):
                    resident.snapshot({'terrain': True, 'radius': 1, 'vertical': 2,
                                       'capability_observation': True, 'entity_radius': 48})
                self.assertIsNone(resident.cache.grid)

    def test_seed_is_one_use_owner_radius_state_and_clock_bound(self):
        for variant in ('consumed', 'other_cache', 'intervening_read', 'radius', 'mutated', 'clock_reversed'):
            with self.subTest(variant=variant):
                cache = WorldCache()
                bridge = ScriptedBridge(self.clock, [pages(radius=1)])
                _state, token = cache.observe_scan_start(bridge, entity_radius=48)
                if variant == 'consumed':
                    cache.scan(bridge, 1, 2, capability=True, entity_radius=48, _initial_observation=token)
                elif variant == 'other_cache': cache = WorldCache()
                elif variant == 'intervening_read': cache.observe(bridge, entity_radius=48)
                elif variant == 'mutated': _state['player']['x'] = 12
                elif variant == 'clock_reversed': self.clock.now -= .01
                calls = len(bridge.calls)
                with self.assertRaisesRegex(TerrainError, 'invalid_terrain_initial_observation'):
                    cache.scan(bridge, 1, 2, capability=True, entity_radius=8 if variant == 'radius' else 48,
                               _initial_observation=token)
                self.assertEqual(len(bridge.calls), calls)
                self.assertIsNone(cache.grid)
                self.clock.now = 100

    def test_read_retry_acquires_new_a_and_preserves_profile(self):
        def new_pages(bridge):
            return pages(radius=3, tick=100 + int(round((self.clock.now-100)*20)))
        bridge = ScriptedBridge(self.clock, [[BridgeError('stale_terrain_cursor', status=409)], new_pages])
        cache = WorldCache(); _, token = cache.observe_scan_start(bridge, entity_radius=48)
        cache.scan(bridge, 3, 2, capability=True, entity_radius=48, _initial_observation=token)
        self.assertEqual(bridge.state_reads, 3)  # current A, new attempt A, final C
        starts = [p for _, p, _ in bridge.calls if '/terrain?radius=' in p]
        self.assertEqual(starts, ['/control/terrain?radius=3&vertical=2&limit=1024&capability=1'] * 2)
        self.assertTrue(all(method == 'GET' for method, _, _ in bridge.calls))
        self.assertEqual(cache.terrain_read['outcome'], 'recovered')
        self.assertGreater(cache.grid.received_at, token.started)

    def test_large_slow_page_remains_bounded_and_never_published(self):
        bridge = ScriptedBridge(self.clock, [pages(radius=4, vertical=4)])
        bridge.page_hook = lambda _: self.clock.sleep(3.01)
        cache = WorldCache()
        with self.assertRaisesRegex(TerrainError, 'stale_terrain_clock'):
            cache.scan(bridge, 4, 4, capability=True, entity_radius=48)
        self.assertEqual(bridge.page_count, 1)
        self.assertIsNone(cache.grid); self.assertEqual(cache.cells, {})


class CapabilityPageProfileTests(unittest.TestCase):
    def assembler(self, **options):
        stamp = CapabilityWorldStamp(FakeWorld().generation, 'minecraft:overworld', 100)
        return TerrainAssembler(stamp, 100, **options)

    def test_large_pages_require_optin_and_keep_raw_fields_and_unknowns(self):
        chunks = pages(radius=4, vertical=4)
        original = copy.deepcopy(chunks)
        with self.assertRaises(TerrainError): self.assembler().add(chunks[0], 100)
        scan = self.assembler(capability_page_limit=1024)
        for chunk in chunks: scan.add(chunk, 100)
        self.assertEqual(len(scan.finish(scan.world, 100).cells), 729)
        self.assertEqual(chunks, original)
        world = FakeWorld(); world.unknown(Block(0, 64, 0))
        chunk = world.pages(radius=1)[0]; chunk.update(capability_page_schema_version=1, page_limit=1024)
        scan = self.assembler(capability_page_limit=1024); scan.add(chunk, 100)
        self.assertFalse(scan.finish(scan.world, 100).clear(Block(0, 64, 0)))

    def test_bad_profile_on_every_page_poisons_scan_without_refresh(self):
        mutations = [('capability_page_schema_version', None), ('capability_page_schema_version', True),
                     ('capability_page_schema_version', 2), ('page_limit', None), ('page_limit', True),
                     ('page_limit', '1024'), ('page_limit', 128), ('page_limit', 1025)]
        for index in (0, 1):
            for key, value in mutations:
                with self.subTest(index=index, key=key, value=value):
                    chunks = pages(radius=4, vertical=4); chunks[index][key] = value
                    scan = self.assembler(capability_page_limit=1024)
                    for chunk in chunks[:index]: scan.add(chunk, 100)
                    with self.assertRaises(TerrainError) as caught: scan.add(chunks[index], 100)
                    self.assertFalse(caught.exception.refreshable)
                    self.assertEqual(scan.cells, {})

    def test_explicit_optin_still_rejects_1025_cells_and_bad_limits(self):
        for limit in (True, 0, 1025, '1024', 1024.):
            with self.subTest(limit=limit), self.assertRaises(TerrainError):
                self.assembler(capability_page_limit=limit)
        chunk = pages(limit=1025, radius=5, vertical=4)[0]
        with self.assertRaises(TerrainError): self.assembler(capability_page_limit=1024).add(chunk, 100)

    def test_large_page_integrity_checks_are_not_relaxed(self):
        mutations = [lambda p: p.update(returned=511),
                     lambda p: p.update(next_cursor='untrusted'),
                     lambda p: p.update(offset=1),
                     lambda p: p['cells'].__setitem__(1, copy.deepcopy(p['cells'][0])),
                     lambda p: p.update(unknown_cells=1),
                     lambda p: p.update(complete=True),
                     lambda p: p.update(world_generation='00000000-0000-4000-8000-000000000099')]
        for mutate in mutations:
            chunk = pages(radius=4, vertical=4)[0]; mutate(chunk)
            scan = self.assembler(capability_page_limit=1024)
            with self.assertRaises(TerrainError) as caught: scan.add(chunk, 100)
            self.assertFalse(caught.exception.refreshable)
            self.assertEqual(scan.cells, {})

    def test_byte_limited_short_pages_need_not_report_time_budget_exhaustion(self):
        scan = self.assembler(capability_page_limit=1024)
        for chunk in pages(limit=217, radius=4, vertical=4):
            self.assertFalse(chunk['budget_exhausted'])
            chunk['payload_budget_exhausted'] = not chunk['complete']
            scan.add(chunk, 100)
        self.assertEqual(len(scan.finish(scan.world, 100).cells), 729)


if __name__ == '__main__': unittest.main()

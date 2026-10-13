"""Deterministic real Runtime -> QueueClient -> Resident read-only regression.

The mailbox, journal, serialization and adapters are real. Only native endpoint
responses and elapsed endpoint/storage timings are synthetic; no network/game.
"""
from copy import deepcopy
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from resident_controller.controller import Resident
from resident_controller.ipc import QueueClient
from navigation_controller.fake import FakeWorld
from mdc_skills import core
from mdc_skills.core import Runtime, SkillError
from test_gateway_integration import EndpointFixture


class PumpClock:
    def __init__(self):
        self.now = 100.
        self.resident = None
        self.pumping = False
    def monotonic(self): return self.now
    def sleep(self, seconds):
        self.now += seconds
        if self.resident is not None and not self.pumping:
            self.pumping = True
            try: self.resident.tick()
            finally: self.pumping = False


class TimedEndpoints(EndpointFixture):
    def __init__(self, clock, *, page_size=512, delay=.03, wire_pages=None):
        super().__init__()
        self.clock, self.page_size, self.delay = clock, page_size, delay
        self.wire_pages = deepcopy(wire_pages)
        if wire_pages is not None: self.tick = wire_pages[0]['game_time'] - 1
        self.reads = []
        self.state_reads = []
    def snapshot(self):
        value = super().snapshot()
        if self.wire_pages is not None:
            page = self.wire_pages[0]
            value['world']['world_generation'] = page['world_generation']
            value['world']['dimension'] = value['player']['dimension'] = page['dimension']
            value['player'].update(x=page['origin']['x']+.5, y=page['origin']['y'], z=page['origin']['z']+.5)
        return value
    def request(self, method, path, body=None):
        self.clock.now += self.delay
        if method != 'GET': raise AssertionError('Observation regression permits no game mutation')
        self.reads.append(path)
        if path.startswith('/control/terrain?'):
            from urllib.parse import parse_qs, urlsplit
            query = parse_qs(urlsplit(path).query)
            if 'radius' in query:
                world = FakeWorld(); world.generation = '11111111-2222-4333-8444-555555555555'
                pages = world.pages(radius=int(query['radius'][0]), vertical=int(query['vertical'][0]),
                                    tick=self.tick, limit=self.page_size)
                for page in pages:
                    page.update(capability_page_schema_version=1, page_limit=1024)
                self.terrain_pages = iter(deepcopy(self.wire_pages) if self.wire_pages is not None else pages)
            return next(self.terrain_pages)
        value = super().request(method, path, body)
        if path.startswith(('/control/state?', '/control/capability-snapshot?')):
            observed = value['state'] if 'capability_snapshot_schema_version' in value else value
            self.state_reads.append(deepcopy(observed))
        return value


class ActualReadAdapterLatencyTests(unittest.TestCase):
    def run_adapter(self, *, page_size=512, delay=.03, archive_delay=.2, old_read_shape=False, wire_pages=None):
        """Retain A+B+C only to replay the prior measured read schedule in a control."""
        with tempfile.TemporaryDirectory(prefix='offline-read-latency-') as directory:
            root = Path(directory); clock = PumpClock(); bridge = TimedEndpoints(clock, page_size=page_size, delay=delay, wire_pages=wire_pages)
            with patch('time.monotonic', clock.monotonic), patch('time.sleep', clock.sleep):
                resident = Resident(bridge, root / 'resident'); resident.start(); clock.resident = resident
                if old_read_shape:
                    scan = resident.cache.scan
                    def separate_initial_read(*args, **kwargs):
                        kwargs.pop('_initial_observation', None)
                        return scan(*args, **kwargs)
                    resident.cache.scan = separate_initial_read
                bridge.reads.clear(); bridge.state_reads.clear()
                runtime = Runtime(QueueClient(root / 'resident'), root / 'journal', clock=clock.monotonic,
                                  sleeper=clock.sleep, wait_timeout=4)
                original = core._atomic_bytes
                def archive_with_latency(path, data, *args, **kwargs):
                    # Actual durable evidence bytes are still written. This delay
                    # remains inside Runtime acquisition, rather than restamping.
                    if Path(path).name.startswith('receipt-'): clock.now += archive_delay
                    return original(path, data, *args, **kwargs)
                captured = clock.now
                try:
                    with patch.object(core, '_atomic_bytes', archive_with_latency):
                        try:
                            result = runtime.observe(terrain=True, radius=4, vertical=4, entity_radius=48)
                            error = None
                        except SkillError as exc:
                            result, error = None, exc.reason
                    return {'result': result, 'error': error, 'elapsed': clock.now-captured,
                            'reads': list(bridge.reads), 'states': deepcopy(bridge.state_reads),
                            'terrain_read': deepcopy(resident.cache.terrain_read),
                            'journal': deepcopy(runtime._journal), 'posts': list(bridge.posts)}
                finally:
                    runtime.close(); resident.lock.close()

    def test_actual_adapter_729_cells_two_pages_two_states_passes_point8(self):
        outcome = self.run_adapter()
        self.assertIsNone(outcome['error'], outcome)
        observed = outcome['result']
        self.assertLess(outcome['elapsed'], .8)
        self.assertEqual(len(observed.terrain['cells']), 729)
        self.assertEqual(observed.state, outcome['states'][-1])
        self.assertEqual([s['nearby']['radius'] for s in outcome['states']], [48, 48])
        self.assertEqual(sum('/terrain?' in p for p in outcome['reads']), 2)
        self.assertEqual(outcome['posts'], [])
        self.assertGreater(outcome['elapsed'], .2)  # archived evidence was not excluded
        self.assertLess(observed.captured_at, observed.terrain['capture_started_mono'])

    def test_actual_adapter_accepts_exact_java_scan_reader_http_pages(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures' / 'native-capability-terrain-pages.json').read_text())
        self.assertIs(fixture['synthetic_input_not_live_evidence'], True)
        self.assertIs(fixture['actual_production_scan_reader_http_codec'], True)
        pages = fixture['pages']
        original = deepcopy(pages)
        outcome = self.run_adapter(wire_pages=pages)
        self.assertIsNone(outcome['error'], outcome)
        self.assertLess(outcome['elapsed'], .8)
        self.assertEqual(outcome['result'].terrain['cells'], [cell for page in pages for cell in page['cells']])
        self.assertEqual(outcome['result'].state, outcome['states'][-1])
        self.assertEqual(pages, original)
        self.assertEqual(len(pages), 2)
        self.assertTrue(pages[0]['payload_budget_exhausted'])
        self.assertTrue(all(page['page_limit'] == 1024 for page in pages))
        self.assertEqual(outcome['posts'], [])

    def test_prior_six_page_three_state_read_schedule_crosses_unchanged_fence(self):
        outcome = self.run_adapter(page_size=128, old_read_shape=True)
        self.assertEqual(outcome['error'], 'observation_acquisition_stale')
        self.assertGreater(outcome['elapsed'], .8)
        self.assertEqual(len(outcome['states']), 3)
        self.assertEqual(sum('/terrain?' in p for p in outcome['reads']), 6)
        self.assertEqual(outcome['posts'], [])

    def test_extra_storage_latency_remains_stale_despite_larger_pages(self):
        outcome = self.run_adapter(archive_delay=.65)
        self.assertEqual(outcome['error'], 'observation_acquisition_stale')
        self.assertEqual(sum('/terrain?' in p for p in outcome['reads']), 2)
        self.assertEqual(outcome['posts'], [])
        self.assertIsNone(outcome['result'])
        records = list(outcome['journal']['records'].values())
        self.assertEqual(records[-1]['status'], 'blocked')
        self.assertEqual(records[-1]['reason'], 'observation_acquisition_stale')


if __name__ == '__main__': unittest.main()

import copy
from dataclasses import replace
import json
import tempfile
import unittest

from mdcoord import Acquisition, Coordinator, Rejected
from mdcoord.schema import loads
from mdcoord.snapshots import sanitize
from support import CONTEXT, Clock, grant, player, proposal, publish, sections


class SnapshotChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.clock = Clock()
        self.owner = Coordinator(self.tmp.name, clock=self.clock)
        self.owner.activate(grant())
        self.data = sections()
        self.original = publish(self.owner)

    def tearDown(self):
        self.owner.close(); self.tmp.cleanup()

    def test_per_section_revision_and_original_source_stamps(self):
        self.clock.step(.5)
        publish(self.owner, 'obs2', {'player': player(1.5)}, tick=11)
        result = self.owner.snapshots.read()
        self.assertEqual(result['sections']['terrain'], self.original['sections']['terrain'])
        self.assertGreater(result['sections']['player']['revision'], self.original['sections']['player']['revision'])
        terrain = result['sections']['terrain']
        self.assertEqual(terrain['source_tick'], 10)
        self.assertEqual(terrain['source_tick_clock'], 'native_game_tick')
        self.assertEqual(terrain['source_time_ms'], 1_700_000_000_000)
        self.assertEqual(terrain['expires_mono'], 103)

    def test_expiry_does_not_refresh_on_read(self):
        self.clock.step(3.1)
        first = self.owner.snapshots.read()
        for _ in range(10):
            self.assertEqual(first, self.owner.snapshots.read())
        self.assertEqual(first['sections']['player']['freshness'], 'stale')
        self.assertEqual(first['sections']['terrain']['freshness'], 'stale')

    def test_duplicate_observation_cannot_refresh_ttl(self):
        self.clock.step(2)
        acquisition = Acquisition(self.owner.snapshots.epoch, 100.0, 100.0, 1_700_000_000_000, 10)
        again = publish(self.owner, capture=acquisition)
        self.assertEqual(again['sections']['player']['expires_mono'], 103)
        self.assertEqual(self.owner.metrics.snapshot()['counts']['duplicate_scans'], 1)
        self.clock.step(2)
        self.assertEqual(self.owner.snapshots.read()['sections']['player']['freshness'], 'stale')

    def test_duplicate_source_identity_payload_change_rejected(self):
        changed = sections(); changed['player']['x'] = 1.5
        with self.assertRaisesRegex(Rejected, 'source_id_payload_conflict'):
            publish(self.owner, data=changed)
        self.assertEqual(self.owner.snapshots.read(), self.original)

    def test_unrelated_process_monotonic_clock_rejected(self):
        with self.assertRaisesRegex(Rejected, 'foreign_monotonic_clock'):
            publish(self.owner, 'foreign', capture=Acquisition('other-owner', 100, 100, 0, 1))

    def test_import_without_original_capture_remains_unknown(self):
        publish(self.owner, 'recorded', capture=Acquisition(self.owner.snapshots.epoch, None, None, 0, 10, 'unknown'))
        value = self.owner.snapshots.read()['sections']['terrain']
        self.assertEqual(value['freshness'], 'unknown')
        self.assertIsNone(value['expires_mono'])

    def test_future_or_reversed_capture_rejected(self):
        for a in (Acquisition(self.owner.snapshots.epoch, 101, 101, 0, 10),
                  Acquisition(self.owner.snapshots.epoch, 100, 99, 0, 10)):
            with self.subTest(a=a), self.assertRaises(Rejected):
                publish(self.owner, 'bad', capture=a)

    def test_regressed_tick_rejected_without_partial_update(self):
        # First entry would have been changed before an error in the second in a non-atomic implementation.
        data = {'scan': {'scan_id': 'scan1', 'status': 'succeeded', 'tested_positions': 1, 'complete': True},
                'terrain': self.data['terrain']}
        with self.assertRaisesRegex(Rejected, 'source_tick_reversed'):
            publish(self.owner, 'regression', data, tick=9)
        self.assertEqual(self.owner.snapshots.read(), self.original)

    def test_world_change_invalidates_old_sections(self):
        publish(self.owner, 'other-world', {'player': player()}, context=replace(CONTEXT, world_generation='world2'))
        result = self.owner.snapshots.read()
        self.assertEqual(set(result['sections']), {'player'})
        self.assertIn('terrain', result['missing_sections'])

    def test_unknown_truncated_and_missing_never_become_fresh(self):
        cases = [({'cells': self.data['terrain']['cells'], 'complete': False}, 'truncated'),
                 ({'cells': [{}], 'complete': True}, 'unknown'),
                 ({'cells': [{'x': 0, 'y': 64, 'z': 0, 'loaded': False}], 'complete': True}, 'unknown'),
                 ({'cells': self.data['terrain']['cells'] * 6, 'complete': True}, 'unknown')]
        for index, (terrain, expected) in enumerate(cases):
            publish(self.owner, 'test' + str(index), {'terrain': terrain})
            self.assertEqual(self.owner.snapshots.read()['sections']['terrain']['freshness'], expected)

    def test_secrets_chat_and_config_are_not_recursively_mirrored(self):
        data = sections()
        for raw in data.values():
            raw.update(chat='SYNTHETIC_SECRET_CHAT', token='SYNTHETIC_SECRET_TOKEN',
                       auth={'password': 'SYNTHETIC_SECRET_PASSWORD'}, config={'url': 'SYNTHETIC_SECRET_URL'},
                       shell='SYNTHETIC_SECRET_SHELL')
        for cell in data['terrain']['cells']:
            cell['display_name'] = 'SYNTHETIC_SECRET_CELL_TEXT'
        data['inventory']['slots'][0]['nbt'] = 'SYNTHETIC_SECRET_ITEM_DATA'
        data['entities']['entities'][0]['name'] = 'SYNTHETIC_SECRET_NAME'
        publish(self.owner, 'clean', data)
        self.assertNotIn('SYNTHETIC_SECRET', json.dumps(self.owner.snapshots.read()))

    def test_invalid_numeric_values_and_bool_as_number_rejected_for_safety(self):
        for number in (float('nan'), float('inf'), True, '20'):
            bad = player(); bad['health'] = number
            data, quality = sanitize('player', bad)
            self.assertEqual(quality, 'unknown')
            self.assertIsNone(data['health'])

    def test_snapshot_and_events_are_copy_isolated(self):
        first = self.owner.snapshots.read(); first['sections']['player']['data']['health'] = -1
        self.assertEqual(self.owner.snapshots.read()['sections']['player']['data']['health'], 20)
        sub = self.owner.snapshots.subscribe()
        publish(self.owner, 'obs2'); events = self.owner.snapshots.poll(sub)
        events['events'][0]['sections'].append('evil')
        self.assertEqual(self.owner.snapshots.poll(sub)['events'], [])

    def test_subscription_backpressure_bounded_drop_oldest_requires_resync(self):
        sub = self.owner.snapshots.subscribe(capacity=2)
        for i in range(5):
            publish(self.owner, 'event-' + str(i))
        events = self.owner.snapshots.poll(sub)
        self.assertEqual(len(events['events']), 2)
        self.assertEqual(events['dropped'], 3)
        self.assertTrue(events['resync_required'])
        self.assertFalse(self.owner.snapshots.poll(sub)['resync_required'])

    def test_subscription_limit_and_unsubscribe(self):
        ids = [self.owner.snapshots.subscribe() for _ in range(32)]
        with self.assertRaisesRegex(Rejected, 'subscriber_capacity'):
            self.owner.snapshots.subscribe()
        self.owner.snapshots.unsubscribe(ids[0]); self.owner.snapshots.subscribe()
        with self.assertRaisesRegex(Rejected, 'unknown_subscription'):
            self.owner.snapshots.poll(ids[0])

    def test_metrics_do_not_mix_clocks_or_invent_model_latency(self):
        metrics = self.owner.metrics
        with self.assertRaisesRegex(Rejected, 'incomparable_clock'):
            metrics.duration('observation', 100, 1000, clock_domain='native_tick')
        self.assertFalse(metrics.snapshot()['model_wait_available'])
        self.assertIsNone(metrics.snapshot()['native_execution_ms'])
        self.assertIsNone(metrics.snapshot()['speedup_claim'])
        metrics.model_start('model1'); self.clock.step(.125); metrics.model_end('model1')
        self.assertEqual(metrics.snapshot()['durations']['model_wait'], [125])
        with self.assertRaisesRegex(Rejected, 'missing_model_start'):
            metrics.model_end('missing')

    def test_json_duplicates_and_nonfinite_are_rejected(self):
        for raw in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}'):
            with self.assertRaises(Rejected):
                loads(raw)


class TerrainSafetyChecks(unittest.TestCase):
    setUp = SnapshotChecks.setUp
    tearDown = SnapshotChecks.tearDown
    def test_unchecked_route_fails_for_each_missing_or_unsafe_fact(self):
        for i, field in enumerate(('loaded', 'passable', 'hazard', 'fluid')):
            data = sections()
            target = next(c for c in data['terrain']['cells'] if (c['x'], c['y']) == (1, 64))
            target[field] = field in ('hazard', 'fluid')
            publish(self.owner, 'unsafe-' + field, data)
            p = proposal(self.owner, pid='unsafe-' + field)
            self.owner.propose(p); self.owner.advance()
            self.assertEqual(self.owner.result(p['proposal_id'])['status'], 'rejected')
        self.assertFalse(self.owner.executor.dispatches)

    def test_floor_and_head_clearance_both_checked(self):
        for y in (63, 65):
            data = sections()
            cell = next(c for c in data['terrain']['cells'] if (c['x'], c['y']) == (1, y))
            cell['full_support'] = False; cell['passable'] = False
            publish(self.owner, 'bad' + str(y), data)
            p = proposal(self.owner, pid='bad' + str(y)); self.owner.propose(p); self.owner.advance()
            self.assertEqual(self.owner.result(p['proposal_id'])['reason'], 'blocked_corridor')
        self.assertFalse(self.owner.executor.dispatches)

    def test_diagonal_jump_drop_skip_and_unknown_route_rejected(self):
        for index, waypoint in enumerate(({'x': 1.5, 'y': 64, 'z': 1.5}, {'x': 1.5, 'y': 65, 'z': .5},
                                           {'x': 1.5, 'y': 63, 'z': .5}, {'x': 10.5, 'y': 64, 'z': .5})):
            p = proposal(self.owner, pid='bad-route-' + str(index)); p['intent']['waypoints'] = [waypoint]
            self.owner.propose(p); self.owner.advance()
            self.assertEqual(self.owner.result(p['proposal_id'])['status'], 'rejected')
        self.assertFalse(self.owner.executor.dispatches)

    def test_missing_player_flags_block(self):
        for index, field in enumerate(('alive', 'grounded', 'screen_closed')):
            data = sections(); data['player'][field] = False
            publish(self.owner, 'player-' + field, data)
            p = proposal(self.owner, pid='player-' + field); self.owner.propose(p); self.owner.advance()
            self.assertEqual(self.owner.result(p['proposal_id'])['reason'], 'precondition_failed')
        self.assertFalse(self.owner.executor.dispatches)

    def test_unknown_scan_status_is_never_fresh(self):
        _, quality = sanitize('scan', {'scan_id': 'scan1', 'status': 'not_a_status',
                                       'tested_positions': 1, 'complete': True})
        self.assertEqual(quality, 'unknown')

    def test_running_action_without_id_is_unknown(self):
        _, quality = sanitize('action', {'status': 'running', 'input_released': False})
        self.assertEqual(quality, 'unknown')

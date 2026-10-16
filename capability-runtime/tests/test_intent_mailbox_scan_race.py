"""Bounded read-only inbox rescans; no original unknown job is retried.

The admission predicate has always counted only inbox work. The real daemon
serializes the separately claimed working owner and enforces post-action reads.
Only native Bridge responses in the integration fixture are synthetic.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import intent_client
from intent_client import IntentClient
from mdc_skills.core import Runtime, SkillError
from support_core import Clock, Client, SESSION, arrived, move
import test_capability_ownership as owners


class InboxScanRaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='offline-inbox-scan-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in ('inbox', 'working', 'results'):
            (self.root / name).mkdir()
        self.session = {'implementation': 'native-defense-watchdog-v5',
            'updated_at': time.time(), 'state': 'ready', 'session_id': SESSION, 'pending': 0}
        (self.root / 'state.json').write_text(json.dumps(self.session))
        self.client = IntentClient(self.root)

    def entry(self, name, op='capability_heartbeat', *, raw=None):
        path = self.root / 'inbox' / (name + '.json')
        path.write_text(json.dumps({'op': op}) if raw is None else raw)
        return path

    @contextmanager
    def schedule(self, moving=(), *, read_error=None):
        original_glob, original_read = Path.glob, Path.read_text
        scans, reads = [], []
        moving = set(moving)
        def glob(path, pattern):
            values = list(original_glob(path, pattern))
            if path == self.root / 'inbox' and pattern == '*.json':
                values.sort()
                scans.append([p.name for p in values])
            return iter(values)
        def read(path, *args, **kwargs):
            if path.parent == self.root / 'inbox':
                reads.append(path.name)
                if read_error is not None:
                    raise read_error
                if path in moving:
                    path.rename(self.root / 'working' / path.name)
            return original_read(path, *args, **kwargs)
        with patch.object(Path, 'glob', glob), patch.object(Path, 'read_text', read), \
                patch.object(intent_client, 'write_json', wraps=intent_client.write_json) as writes, \
                patch.object(intent_client.time, 'sleep', side_effect=AssertionError('scan must not sleep')), \
                patch.object(intent_client.time, 'monotonic', side_effect=AssertionError('scan must not reset a deadline')):
            yield scans, reads, writes

    def test_control_rename_restarts_whole_scan_then_writes_original_id_once(self):
        moving = self.entry('a-heartbeat')
        with self.schedule([moving]) as (scans, reads, writes):
            self.assertEqual(self.client.submit({'op': 'observe'}, request_id='new-observation'), 'new-observation')
            self.assertEqual(scans, [['a-heartbeat.json'], []])
            self.assertEqual(reads, ['a-heartbeat.json'])
            self.assertEqual(writes.call_count, 1)
            self.assertEqual(writes.call_args.args[0], self.root / 'inbox' / 'new-observation.json')
        self.assertEqual(json.loads((self.root / 'inbox' / 'new-observation.json').read_text())['op'], 'observe')

    def test_moved_ordinary_still_rescans_and_refuses_other_pending_ordinary(self):
        moving = self.entry('a-moving', 'observe')
        self.entry('b-still-pending', 'observe')
        with self.schedule([moving]) as (scans, reads, writes):
            with self.assertRaisesRegex(ValueError, '^one_pending_owner_intent_only$'):
                self.client.submit({'op': 'observe'}, request_id='new-observation')
            self.assertEqual(scans, [['a-moving.json', 'b-still-pending.json'], ['b-still-pending.json']])
            self.assertEqual(reads, ['a-moving.json', 'b-still-pending.json'])
            self.assertEqual(writes.call_count, 0)

    def test_three_rename_races_exhaust_before_write_with_original_error(self):
        moving = [self.entry('race-' + str(i)) for i in range(3)]
        with self.schedule(moving) as (scans, reads, writes):
            with self.assertRaises(FileNotFoundError) as caught:
                self.client.submit({'op': 'observe'}, request_id='new-observation')
            self.assertEqual(len(scans), 3)
            self.assertEqual(reads, [p.name for p in moving])
            self.assertEqual(caught.exception.filename, str(moving[-1]))
            self.assertEqual(writes.call_count, 0)

    def test_malformed_or_nonobject_entry_never_rescans_or_writes(self):
        for raw, error in [('{', json.JSONDecodeError), ('[]', AttributeError)]:
            with self.subTest(raw=raw):
                path = self.entry('malformed', raw=raw)
                with self.schedule() as (scans, reads, writes):
                    with self.assertRaises(error):
                        self.client.submit({'op': 'observe'}, request_id='new-observation')
                    self.assertEqual(len(scans), 1)
                    self.assertEqual(writes.call_count, 0)
                path.unlink()

    def test_permission_error_never_rescans_or_writes(self):
        self.entry('denied')
        error = PermissionError('synthetic mailbox read denied')
        with self.schedule(read_error=error) as (scans, reads, writes):
            with self.assertRaises(PermissionError) as caught:
                self.client.submit({'op': 'observe'}, request_id='new-observation')
            self.assertIs(caught.exception, error)
            self.assertEqual(len(scans), 1)
            self.assertEqual(writes.call_count, 0)

    def test_write_file_not_found_is_not_retried(self):
        error = FileNotFoundError('synthetic write boundary failure')
        with patch.object(intent_client, 'write_json', side_effect=error) as writes:
            with self.assertRaises(FileNotFoundError) as caught:
                self.client.submit({'op': 'observe'}, request_id='new-observation')
            self.assertIs(caught.exception, error)
            self.assertEqual(writes.call_count, 1)

    def test_existing_identity_and_control_submission_do_not_rescan(self):
        for folder in ('inbox', 'working', 'results'):
            with self.subTest(folder=folder):
                path = self.root / folder / 'existing.json'
                path.write_text('{}')
                with patch.object(intent_client, '_pending_owner_intent', side_effect=AssertionError('unexpected scan')), \
                        patch.object(intent_client, 'write_json') as writes:
                    self.assertEqual(self.client.submit({'op': 'observe'}, request_id='existing'), 'existing')
                    self.assertEqual(writes.call_count, 0)
                path.unlink()
        with patch.object(intent_client, '_pending_owner_intent', side_effect=AssertionError('unexpected scan')):
            self.assertEqual(self.client.submit({'op': 'capability_heartbeat'}, request_id='control'), 'control')

    def test_exhausted_mutation_stays_unknown_and_cannot_replay(self):
        clock = Clock()
        fake = Client(clock)
        runtime = Runtime(fake, self.root / 'runtime', clock=clock, sleeper=clock.sleep)
        self.addCleanup(runtime.close)
        before = runtime.observe()
        runtime.client = self.client
        moving = [self.entry('race-' + str(i)) for i in range(3)]
        with self.schedule(moving) as (scans, reads, writes):
            outcome = runtime.execute('walk', move(), arrived, before=before)
            self.assertEqual(outcome.status, 'unknown')
            self.assertEqual(outcome.reason, 'queue_exchange_unknown:FileNotFoundError')
            original_id = runtime.pending_request_id
            self.assertIn(original_id, outcome.request_ids)
            self.assertEqual(len(scans), 3)
            self.assertEqual(writes.call_count, 0)
            later = runtime.execute('walk', move(), arrived, before=before)
            self.assertFalse(later.ok)
            self.assertEqual(runtime.pending_request_id, original_id)
            self.assertEqual(len(scans), 3)
            self.assertEqual(writes.call_count, 0)
            self.assertEqual(clock(), before.captured_at + .001)
        record = json.loads((self.root / 'runtime' / 'execution.json').read_text())['records'][original_id]
        self.assertEqual(record['kind'], 'mutation')
        self.assertEqual(record['status'], 'unknown')
        self.assertFalse(any((self.root / folder / (original_id + '.json')).exists()
                             for folder in ('inbox', 'working', 'results')))


class GatewayScanSerializationTests(unittest.TestCase):
    setUp = owners.ActualGatewayOwnershipTests.setUp
    tearDown = owners.ActualGatewayOwnershipTests.tearDown
    until = owners.ActualGatewayOwnershipTests.until
    claim = owners.ActualGatewayOwnershipTests.claim
    read = owners.ActualGatewayOwnershipTests.read
    command = owners.ActualGatewayOwnershipTests.command
    action = owners.ActualGatewayOwnershipTests.action

    def evidence(self, stage):
        destination = os.environ.get('MDC_MAILBOX_SCAN_TEST_RESULTS')
        if not destination:
            return
        output = Path(destination) / self._testMethodName / stage
        output.mkdir(parents=True, exist_ok=True)
        mailbox = self.root / 'watchdog'
        proof = {'synthetic_native': True, 'stage': stage,
            'state': self.client.session(), 'posts': self.bridge.posts,
            'owner': self.dog.owner,
            'inbox': sorted(p.name for p in (mailbox / 'inbox').glob('*.json')),
            'working': sorted(p.name for p in (mailbox / 'working').glob('*.json'))}
        (output / 'proof.json').write_text(json.dumps(proof, indent=2) + '\n')
        for path in (mailbox / 'results').glob('*.json'):
            (output / path.name).write_bytes(path.read_bytes())

    @contextmanager
    def stale_directory_entry(self, request_id):
        # A directory snapshot can contain a name already claimed into working
        # or completed into results before open. Reproduce exactly that window.
        inbox = self.root / 'watchdog' / 'inbox'
        stale = inbox / (request_id + '.json')
        original_glob = Path.glob
        caller = threading.get_ident()
        snapshots = []
        def glob(path, pattern):
            if path == inbox and pattern == '*.json' and threading.get_ident() == caller:
                snapshots.append(True)
                if len(snapshots) == 1:
                    return iter([stale])
            return original_glob(path, pattern)
        with patch.object(Path, 'glob', glob):
            yield snapshots

    def test_claimed_work_is_serialized_and_second_mutation_requires_post_read(self):
        self.claim()
        source = self.read()
        self.bridge.hold = True
        first = self.action('follow_path', source, waypoints=[{'x': 1.5, 'y': 64, 'z': .5}])
        self.until(lambda: self.bridge.action['status'] == 'running'
                   and (self.root / 'watchdog' / 'working' / (first + '.json')).exists())
        with self.stale_directory_entry(first) as snapshots:
            second = self.action('select_hotbar', source)
            self.assertEqual(len(snapshots), 2)
        # The existing inbox-only rule allows one pending item behind an active
        # owner. It does not grant a second simultaneous resident/native owner.
        time.sleep(.15)
        self.assertEqual(self.dog.owner['id'], first)
        self.assertTrue((self.root / 'watchdog' / 'inbox' / (second + '.json')).exists())
        self.assertIsNone(self.client.result(second))
        self.assertEqual(len([p for p, b in self.bridge.posts if p == '/control/action']), 1)
        self.evidence('first-working-second-pending')
        self.bridge.hold = False
        self.assertEqual(self.client.wait(first, timeout=3)['status'], 'succeeded')
        denied = self.client.wait(second, timeout=3)
        self.assertEqual(denied['reason'], 'capability_command_out_of_scope')
        self.assertIsNone(denied['queue_request_id'])
        self.assertEqual(len([p for p, b in self.bridge.posts if p == '/control/action']), 1)
        self.evidence('second-denied-no-concurrent-native-action')
        self.read()
        self.assertEqual(self.client.release_capability(self.owner)['status'], 'succeeded')

    def test_completed_entry_rescan_allows_fresh_observation_with_same_lease(self):
        self.claim()
        first = self.action('select_hotbar', self.read())
        self.assertEqual(self.client.wait(first, timeout=3)['status'], 'succeeded')
        self.until(lambda: not (self.root / 'watchdog' / 'working' / (first + '.json')).exists())
        with self.stale_directory_entry(first) as snapshots:
            observed = self.read()
            self.assertEqual(len(snapshots), 2)
        self.assertEqual(observed['client_action']['status'], 'succeeded')
        self.assertEqual(self.client.session()['capability_lease']['owner_id'], self.owner)
        self.assertEqual(len([p for p, b in self.bridge.posts if p == '/control/action']), 1)
        self.evidence('completed-first-fresh-observation')
        self.assertEqual(self.client.release_capability(self.owner)['status'], 'succeeded')


if __name__ == '__main__':
    unittest.main()

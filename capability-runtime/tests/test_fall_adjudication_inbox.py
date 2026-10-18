"""Deterministic control arrival after the production loop's control scan."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import base_watchdog
import test_fall_adjudication_owner_chain as chain


class CancellationLaneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='offline-control-arrival-')
        self.root = Path(self.temp.name)
        for name in ('inbox', 'working', 'results'):
            (self.root / name).mkdir()
        self.dog = SimpleNamespace(armed=False, owner=None, completed=[],
                                   session_id='same-session', defense_epoch=1)

    def tearDown(self):
        self.temp.cleanup()

    def put(self, name, body):
        path = self.root / 'inbox' / (name + '.json')
        path.write_text(json.dumps(body))
        return path

    def test_all_supported_controls_survive_late_arrival_without_admission(self):
        paths = [self.put(op, {'op': op, '_watchdog_session_id': 'same-session'})
                 for op in base_watchdog.CONTROL_OPS]
        base_watchdog.cancel_waiting_intents(self.root, self.dog)
        self.assertTrue(all(p.exists() for p in paths))
        self.assertEqual(list((self.root / 'working').iterdir()), [])
        self.assertEqual(list((self.root / 'results').iterdir()), [])

    def test_stale_control_is_left_for_existing_session_validator(self):
        path = self.put('stale', {'op': 'capability_fall_adjudicate',
                                  '_watchdog_session_id': 'foreign'})
        base_watchdog.cancel_waiting_intents(self.root, self.dog)
        self.assertTrue(path.exists())
        self.assertEqual(list((self.root / 'results').iterdir()), [])

    def test_ordinary_and_unsupported_gameplay_still_cancelled(self):
        for op in ('action', 'walk_to', 'fall_rescue_control', 'unknown_control'):
            self.put(op, {'op': op, '_watchdog_session_id': 'same-session'})
        base_watchdog.cancel_waiting_intents(self.root, self.dog)
        self.assertEqual(list((self.root / 'inbox').iterdir()), [])
        for path in (self.root / 'results').iterdir():
            result = json.loads(path.read_text())
            self.assertEqual(result['status'], 'cancelled')
            self.assertEqual(result['reason'], 'watchdog_interrupted_replan_required')


class FullOwnerLaneTests(unittest.TestCase):
    def run_boundary(self, stop=False):
        t = chain.AdjudicationTests()
        t.setUp()
        entered = threading.Event()
        release = threading.Event()
        returned = []
        errors = []
        worker = None
        real = base_watchdog.cancel_waiting_intents
        try:
            original = t.unknown()
            original_receipt = deepcopy(t.runtime._journal['records'][t.runtime.pending_request_id])

            def boundary(directory, dog):
                if dog is t.dog and not entered.is_set():
                    entered.set()
                    if not release.wait(3):
                        raise RuntimeError('offline_late_arrival_gate_timeout')
                return real(directory, dog)

            def call():
                try:
                    returned.append(t.adjudicate(original))
                except BaseException as exc:
                    errors.append(exc)

            with patch.object(base_watchdog, 'cancel_waiting_intents', side_effect=boundary):
                self.assertTrue(entered.wait(3))
                worker = threading.Thread(target=call)
                worker.start()
                inbox = t.root / 'watchdog' / 'inbox'
                t.until(lambda: any(json.loads(p.read_text()).get('op') == 'capability_fall_adjudicate'
                                    for p in inbox.glob('*.json')))
                ordinary = inbox / 'late-gameplay.json'
                base_watchdog.write_json(ordinary, {'op': 'action', 'action': 'use_item',
                                                    '_watchdog_session_id': t.dog.session_id})
                if stop:
                    t.dog.stop()  # Production stop flag, before next admission.
                release.set()
                worker.join(5)
                self.assertFalse(worker.is_alive())
                self.assertEqual(errors, [])
            reply = returned[0]['adjudication']
            self.assertEqual(reply['authority_released'], not stop, returned[0])
            posts = sum(m == 'POST' for m, p, b in t.bridge.adjudication_calls)
            self.assertEqual(posts, 0 if stop else 1)
            control = t.runtime._journal['fall_adjudications']['adjudication-one']['controls'][0]
            control_receipt = t.client.result(control['id'])
            if stop:
                self.assertIn('fall_adjudication_gateway_original_scope_changed',
                              control_receipt['reason'])
                self.assertIsNotNone(t.dog.capability_lease)
            else:
                self.assertTrue(control_receipt['gateway_authority_released'])
            cancelled = json.loads((t.root / 'watchdog' / 'results' / 'late-gameplay.json').read_text())
            self.assertEqual(cancelled['status'], 'cancelled')
            kept = t.runtime._journal['records'][original_receipt['request_id']]
            self.assertEqual(kept['status'], 'unknown')
            self.assertEqual(kept['receipt_ref'], original_receipt['receipt_ref'])
        finally:
            release.set()
            if worker is not None:
                worker.join(5)
            t.tearDown()

    def test_late_control_succeeds_but_late_gameplay_is_cancelled(self):
        self.run_boundary()

    def test_explicit_stop_still_refuses_preserved_control_before_native_write(self):
        self.run_boundary(stop=True)


if __name__ == '__main__':
    unittest.main()

"""Real watchdog run-loop + IntentClient, isolated temp files and fake resident.

WATCHDOG_CANDIDATE=/path/to/watchdog/source enables this test. It never opens a
live queue, socket, auth file, process, or Minecraft client. In particular this
tests state.json as published by base_watchdog.run(), not status() alone.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from crafting_helper import CraftStopped, craft_once
from test_crafting_helper import FakeQueueClient

CANDIDATE = os.environ.get('WATCHDOG_CANDIDATE')
if CANDIDATE:
    sys.path.insert(0, CANDIDATE)
    import base_watchdog
    from watchdog import Watchdog
    from intent_client import IntentClient


class FakeResident(FakeQueueClient):
    def snapshot(self):
        state = super().snapshot()
        state.update(screen_open=False, paused=False, nearby={'entities': []})
        state['player'].update(alive=True, x=.5, y=64, z=.5, on_ground=True)
        state['world']['dimension'] = 'minecraft:overworld'
        return state

    def submit(self, command, request_id=None):
        request_id = request_id or 'fake-resident-' + str(len(self.commands))
        if command['op'] == 'cancel':
            self.commands.append(deepcopy(command))
            self.results[request_id] = {'request_id': request_id, 'session_id': self.session_id,
                                        'status': 'succeeded', 'result': {'ok': True}}
            return request_id
        return super().submit(command, request_id=request_id)

    def result(self, request_id):
        return deepcopy(self.results.get(request_id))


@unittest.skipUnless(CANDIDATE, 'set WATCHDOG_CANDIDATE for the actual v5.1-compatible run-loop contract')
class GatewayPublicationChecks(unittest.TestCase):
    def test_real_run_publishes_idle_pending_and_crafting_uses_real_admission(self):
        resident = FakeResident(width=2)
        errors, dogs, publications = [], [], []
        with tempfile.TemporaryDirectory(prefix='offline-craft-gateway-') as directory:
            root = Path(directory)
            original_write = base_watchdog.write_json
            def record_write(path, data):
                if path.name == 'state.json':
                    publications.append(deepcopy(data))
                return original_write(path, data)
            def make_watchdog(queue):
                dog = Watchdog(queue)
                dogs.append(dog)
                return dog
            def run():
                try:
                    base_watchdog.run('never-opened-offline-fake', root, watchdog_class=make_watchdog)
                except BaseException as exc:
                    errors.append(exc)
            with patch.object(base_watchdog, 'QueueClient', return_value=resident), \
                    patch.object(base_watchdog, 'write_json', side_effect=record_write):
                worker = threading.Thread(target=run, daemon=True)
                worker.start()
                try:
                    client = IntentClient(root)
                    deadline = time.monotonic() + 3
                    while True:
                        self.assertFalse(errors, errors)
                        if (root/'state.json').exists():
                            session = client.session()
                            if session['state'] == 'ready' and session.get('pending') == 0:
                                break
                        self.assertLess(time.monotonic(), deadline, 'fake watchdog never published idle')
                        time.sleep(.01)
                    self.assertEqual(type(session['pending']), int)
                    # The status method alone intentionally has no pending count;
                    # publication adds the observed inbox count. Do not default it.
                    self.assertNotIn('pending', dogs[0].status())
                    result = craft_once(client, 'stick', settle_timeout=3, wait_timeout=3)
                    self.assertEqual(result['added'], 4)
                    self.assertEqual(result['evidence'], 'client_observed_stable')
                    self.assertEqual(resident.quick_moves, 1)
                    self.assertGreater(result['stable_game_times'][1], result['stable_game_times'][0])
                    self.assertFalse(result['server_confirmed'])
                    self.assertTrue(all(type(s.get('pending')) is int for s in publications))
                    self.assertTrue(any(s['state'] == 'ready' and s['pending'] == 0 for s in publications))
                    # Actual wrapper preserves gateway and backing resident IDs.
                    completed = client.result(result['request_ids'][-1])
                    self.assertEqual(completed['session_id'], session['session_id'])
                    self.assertEqual(completed['queue_session_id'], resident.session_id)
                    self.assertTrue(completed['queue_request_id'].startswith('fake-resident-'))
                finally:
                    (root/'STOP').write_text('offline test teardown')
                    worker.join(timeout=3)
                self.assertFalse(worker.is_alive(), 'fake watchdog did not stop')
                self.assertFalse(errors, errors)


if __name__ == '__main__':
    unittest.main()

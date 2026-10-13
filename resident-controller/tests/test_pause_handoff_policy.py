"""Pause producer through actual mailbox and watchdog policy; native I/O is synthetic."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'defense-watchdog'))
from watchdog import Watchdog
from resident_controller.controller import Resident
from resident_controller.ipc import QueueClient
from test_encounter_pause import PauseBridge, acknowledgement, pause_body
from test_encounter_contract import body, receipt


class PausePolicy(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.bridge = PauseBridge()
        self.resident = Resident(self.bridge, self.temp.name)
        self.resident.start()
        self.queue = QueueClient(self.temp.name)

    def tearDown(self):
        self.resident.lock.close()
        self.temp.cleanup()

    def start(self):
        rid = self.queue.submit(dict(body(), op='action'))
        self.resident.tick()
        return rid, self.bridge.accepted['action_id']

    def pause(self, action_id):
        rid = self.queue.submit(dict(op='encounter_pause', expected_resident_session=self.resident.session_id,
                                     body=pause_body(action_id)))
        self.resident.tick()
        return rid

    def poll(self):
        if self.resident.active:
            self.resident.active.wake_at = 0
        self.resident.tick()

    def fresh_dog(self):
        dog = Watchdog(self.queue)
        for _ in range(6):
            dog.tick()
            self.resident.read_commands()
        return dog

    def posts(self):
        return [call for call in self.bridge.calls if call[0] == 'POST']

    def test_policy_is_published_before_the_only_pause_post(self):
        original, action_id = self.start()
        request = self.bridge.request
        observed = []
        def intercept(method, path, payload=None):
            if path == '/control/pause':
                observed.append(copy.deepcopy(self.queue.session()['resident_policy']))
            return request(method, path, payload)
        self.bridge.request = intercept
        self.bridge.calls.clear()
        pause_id = self.pause(action_id)
        self.assertEqual([dict(schema_version=1, requires_handoff=True, input_release_unconfirmed=False)], observed)
        self.assertEqual('succeeded', self.queue.result(pause_id)['status'])
        self.assertEqual(['/control/pause'], [p for _, p, _ in self.posts()])
        self.assertIsNone(self.queue.result(original))

    def test_undispatched_pause_holds_exact_pending_command_for_fresh_watchdog(self):
        command = dict(body(), op='action', request_id='pending-pause', session_id=self.resident.session_id)
        self.resident.command(command)
        native_id = uuid.uuid5(uuid.UUID(self.resident.session_id), 'pending-pause:1').hex
        self.bridge.calls.clear()
        self.pause(native_id)
        dog = self.fresh_dog()
        self.assertTrue(dog.handoff_latched)
        self.assertEqual([command], list(self.resident.pending))
        self.assertIsNone(self.queue.result('pending-pause'))
        self.assertEqual(['/control/pause'], [p for _, p, _ in self.posts()])

    def test_unknown_pause_keeps_original_body_and_uncertain_envelope(self):
        original, native_id = self.start()
        accepted = copy.deepcopy(self.bridge.accepted)
        self.bridge.pause_failure = 'unknown'
        self.bridge.bad_read = True
        self.bridge.calls.clear()
        paused = self.pause(native_id)
        before = copy.deepcopy(self.queue.result(paused))
        dog = self.fresh_dog()
        for _ in range(3): self.poll()
        self.assertTrue(dog.handoff_latched)
        self.assertEqual(accepted, self.bridge.accepted)
        self.assertIsNone(self.queue.result(original))
        self.assertEqual(native_id, self.resident.active.action_id)
        self.bridge.bad_read = False
        self.poll()
        self.assertEqual(before, self.queue.result(paused))
        self.assertEqual('uncertain', before['status'])
        self.assertEqual(native_id, self.queue.result(original)['action']['action_id'])
        self.assertEqual(['/control/pause'], [p for _, p, _ in self.posts()])

    def test_bound_release_false_keeps_raw_terminal_and_release_priority(self):
        original, native_id = self.start()
        terminal = receipt(self.bridge.accepted, 'failed', 'input_release_unconfirmed')
        terminal['result']['input_release_confirmed'] = False
        self.bridge.action = copy.deepcopy(terminal)
        self.bridge.calls.clear()
        self.pause(native_id)
        self.assertTrue(self.queue.session()['resident_policy']['input_release_unconfirmed'])
        self.poll()
        self.assertEqual(terminal, self.queue.result(original)['action'])
        self.assertTrue(self.queue.session()['resident_policy']['input_release_unconfirmed'])
        dog = self.fresh_dog()
        self.assertTrue(dog.input_release_latched)
        self.assertEqual('owner_input_release_unconfirmed', dog.reason)
        self.assertEqual(['/control/pause'], [p for _, p, _ in self.posts()])

    def test_successful_read_reconciliation_keeps_main_client_observed_evidence(self):
        original, native_id = self.start()
        self.bridge.action = receipt(self.bridge.accepted, 'succeeded')
        self.bridge.calls.clear()
        self.pause(native_id)
        self.poll()
        result = self.queue.result(original)
        self.assertEqual('succeeded', result['status'])
        self.assertEqual(native_id, result['result']['action']['action_id'])
        self.assertFalse(result['result']['server_confirmed'])
        self.assertEqual(dict(level='client_observed', stable=False,
                              later_state_game_time=result['result']['state']['world'].get('game_time')),
                         result['result']['evidence'])
        self.assertEqual(['/control/pause'], [p for _, p, _ in self.posts()])

    def test_unknown_pause_preserves_preexisting_release_policy_without_replay(self):
        original, native_id = self.start()
        self.bridge.action = receipt(self.bridge.accepted, 'failed', 'input_release_unconfirmed')
        self.bridge.action['result']['input_release_confirmed'] = False
        self.poll()
        before = copy.deepcopy(self.queue.result(original))
        self.bridge.pause_failure = 'unknown'
        self.bridge.calls.clear()
        paused = self.pause(native_id)
        self.assertEqual('uncertain', self.queue.result(paused)['status'])
        self.assertEqual('input_release_unconfirmed', self.resident.reason)
        self.assertTrue(self.queue.session()['resident_policy']['input_release_unconfirmed'])
        dog = self.fresh_dog()
        self.assertTrue(dog.input_release_latched)
        self.assertEqual(before, self.queue.result(original))
        self.assertEqual(['/control/pause'], [p for _, p, _ in self.posts()])

    def test_old_cleanup_failure_cannot_be_erased_by_pause_acknowledgement(self):
        original, native_id = self.start()
        self.bridge.action = receipt(self.bridge.accepted, 'failed', 'input_release_unconfirmed')
        self.bridge.action['result']['input_release_confirmed'] = False
        self.poll()
        before = copy.deepcopy(self.queue.result(original))
        self.assertTrue(self.resident.observation_policy()['input_release_unconfirmed'])
        self.bridge.calls.clear()
        self.pause(native_id)
        self.assertTrue(self.queue.session()['resident_policy']['input_release_unconfirmed'])
        self.assertEqual(before, self.queue.result(original))
        dog = self.fresh_dog()
        self.assertTrue(dog.input_release_latched)
        self.assertEqual(['/control/pause'], [p for _, p, _ in self.posts()])
        resume = self.queue.submit({'op': 'resume'})
        self.resident.tick()
        self.assertEqual('succeeded', self.queue.result(resume)['status'])
        self.assertEqual(dict(schema_version=1, requires_handoff=False, input_release_unconfirmed=False),
                         self.queue.session()['resident_policy'])

if __name__ == '__main__':
    unittest.main()

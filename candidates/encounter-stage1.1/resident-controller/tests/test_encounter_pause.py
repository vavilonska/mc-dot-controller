"""One pause POST and read-only reconciliation; fakes do not prove world pause."""
import copy
import tempfile
import unittest
import uuid

from resident_controller.controller import Resident
from resident_controller.ipc import QueueClient
from resident_controller.pause_contract import validate_pause_request, validate_pause_receipt
from resident_controller.transport import BridgeError, DIRECT, WRITES
from test_encounter_contract import EncounterBridge, body, receipt, U


def pause_body(action_id):
    return dict(pause_schema_version=1, expected_action_session=U, expected_world_generation=U,
                expected_player_uuid=U, expected_action_id=action_id)


def acknowledgement(request, action):
    return dict(ok=True, protocol='mineclient-bridge', schema_version=2, pause_schema_version=1,
                action='ensure_paused', pause_requested=True, pause_screen_installed=True,
                already_pause_screen=False, client_paused_observed=False,
                pause_effect_confirmed=False, server_confirmed=False, action_session=U,
                world_generation=U, player_uuid=U, expected_action_id=request['expected_action_id'],
                expected_action_present=action is not None, client_action=copy.deepcopy(action),
                input_release_confirmed=None if action is None else action['result']['input_release_confirmed'])


class PauseBridge(EncounterBridge):
    def __init__(self):
        super().__init__()
        self.pause_failure = None
        self.corrupt_pause = None
        self.bad_read = False
    def request(self, method, path, payload=None):
        if path == '/control/pause':
            self.calls.append((method, path, copy.deepcopy(payload)))
            if self.pause_failure == 'rejected':
                raise BridgeError('pause_foreign_action_owner', status=409)
            if self.action.get('action_id') == payload['expected_action_id']:
                if self.action['status'] == 'running':
                    self.action = receipt(self.accepted, 'cancelled', 'encounter_paused_risk_remaining')
                value = acknowledgement(payload, self.action)
            else:
                value = acknowledgement(payload, None)
            if self.pause_failure == 'unknown':
                raise BridgeError('transport_failed', uncertain=True)
            if self.corrupt_pause:
                self.corrupt_pause(value)
            return value
        if self.bad_read and path.startswith('/control/action/status?'):
            self.calls.append((method, path, copy.deepcopy(payload)))
            return {'action_id': 'foreign', 'status': 'cancelled'}
        return super().request(method, path, payload)


class PauseContract(unittest.TestCase):
    def test_strict_request_and_no_direct_takeover_route(self):
        request = pause_body('known-action')
        self.assertEqual(request, validate_pause_request(request))
        self.assertIn('/control/pause', WRITES)
        self.assertNotIn('pause', DIRECT)
        for key, value in [('pause_schema_version', True), ('expected_action_session', 'bad'),
                           ('expected_world_generation', None), ('expected_player_uuid', U.upper()),
                           ('expected_action_id', 'bad/action'), ('extra', 1)]:
            # U consists of digits, so use a noncanonical UUID for that mutation.
            if key == 'expected_player_uuid': value = 'A0000000-0000-4000-8000-000000000001'
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_pause_request(dict(request, **{key: value}))
    def test_missing_action_is_explicit_null_not_an_admission_decision(self):
        request = pause_body('absent')
        value = acknowledgement(request, None)
        self.assertIsNone(validate_pause_receipt(value, request)['client_action'])
        for key in ('client_action', 'input_release_confirmed'):
            bad = copy.deepcopy(value); del bad[key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_pause_receipt(bad, request)
        value['input_release_confirmed'] = True
        with self.assertRaises(ValueError): validate_pause_receipt(value, request)
    def test_installed_screen_does_not_promote_pause_or_release_claims(self):
        request = pause_body('known-action'); native = receipt(dict(body(), action_id='known-action'), 'cancelled', 'encounter_paused_risk_remaining')
        value = acknowledgement(request, native)
        self.assertFalse(validate_pause_receipt(value, request, body())['pause_effect_confirmed'])
        for key, invalid in [('pause_effect_confirmed', True), ('pause_requested', 1),
                             ('expected_action_present', 1), ('input_release_confirmed', False),
                             ('world_generation', 'other'), ('client_paused_observed', None)]:
            bad = copy.deepcopy(value); bad[key] = invalid
            with self.subTest(key=key), self.assertRaises(ValueError): validate_pause_receipt(bad, request, body())


class PauseRelay(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bridge = PauseBridge()
        self.resident = Resident(self.bridge, self.tmp.name); self.resident.start()
        self.client = QueueClient(self.tmp.name)
    def tearDown(self):
        self.resident.lock.close(); self.tmp.cleanup()
    def start_encounter(self):
        rid = self.client.submit(dict(body(), op='action')); self.resident.tick()
        return rid, self.bridge.accepted['action_id']
    def pause(self, action_id, **changes):
        command = dict(op='encounter_pause', expected_resident_session=self.resident.session_id,
                       body=pause_body(action_id)); command.update(changes)
        rid = self.client.submit(command); self.resident.tick(); return rid
    def posts(self):
        return [(p, b) for m, p, b in self.bridge.calls if m == 'POST']
    def poll(self):
        if self.resident.active: self.resident.active.wake_at = 0
        self.resident.tick()
    def test_matching_running_pause_uses_one_post_then_reads_original(self):
        original, action_id = self.start_encounter(); self.bridge.calls.clear()
        rid = self.pause(action_id)
        self.assertEqual(('POST', '/control/pause'), self.bridge.calls[0][:2])
        response = self.client.result(rid)
        self.assertEqual('succeeded', response['status'])
        self.assertFalse(response['gameplay_effect_confirmed'])
        self.assertFalse(response['result']['client_paused_observed'])
        for _ in range(3): self.poll()
        result = self.client.result(original)
        self.assertEqual('cancelled', result['status'])
        self.assertEqual('encounter_paused_risk_remaining', result['reason'])
        self.assertEqual(action_id, result['action']['action_id'])
        self.assertEqual(['/control/pause'], [p for p, _ in self.posts()])
        self.assertTrue(self.resident.paused)
    def test_unknown_pause_keeps_its_uncertain_result_and_only_reads_original(self):
        original, action_id = self.start_encounter(); self.bridge.pause_failure = 'unknown'; self.bridge.bad_read = True
        self.bridge.calls.clear(); rid = self.pause(action_id)
        self.assertEqual('uncertain', self.client.result(rid)['status'])
        for _ in range(3): self.poll()
        self.assertIsNone(self.client.result(original)); self.assertIsNotNone(self.resident.active)
        self.assertEqual(['/control/pause'], [p for p, _ in self.posts()])
        self.bridge.bad_read = False; self.poll()
        self.assertEqual('cancelled', self.client.result(original)['status'])
        self.assertEqual('uncertain', self.client.result(rid)['status'])
    def test_invalid_success_body_becomes_unknown_without_second_write(self):
        original, action_id = self.start_encounter(); self.bridge.corrupt_pause = lambda v: v.update(world_generation='foreign')
        self.bridge.calls.clear(); rid = self.pause(action_id); self.poll()
        self.assertEqual('uncertain', self.client.result(rid)['status'])
        self.assertEqual('cancelled', self.client.result(original)['status'])
        self.assertEqual(['/control/pause'], [p for p, _ in self.posts()])
    def test_original_uncertain_envelope_is_never_promoted_by_pause_terminal(self):
        self.bridge.post_failure = 'timeout'
        original = self.client.submit(dict(body(), op='action')); self.resident.tick()
        before = self.client.result(original); self.assertEqual('uncertain', before['status'])
        action_id = self.bridge.accepted['action_id']; self.bridge.calls.clear()
        rid = self.pause(action_id)
        self.assertEqual('succeeded', self.client.result(rid)['status'])
        self.assertEqual(before, self.client.result(original)); self.assertIsNone(self.resident.active)
        self.assertEqual(['/control/pause'], [p for p, _ in self.posts()])
    def test_existing_known_failed_envelope_is_not_rewritten(self):
        original, action_id = self.start_encounter()
        self.bridge.action = receipt(self.bridge.accepted, 'failed', 'retreat_budget_risk_remaining'); self.poll()
        before = self.client.result(original); self.bridge.calls.clear(); self.pause(action_id)
        self.assertEqual(before, self.client.result(original))
        self.assertEqual(['/control/pause'], [p for p, _ in self.posts()])
    def test_missing_native_action_ack_cannot_finish_unresolved_original(self):
        original, action_id = self.start_encounter(); self.bridge.action = {'status':'idle', 'action_id':None}; self.bridge.calls.clear()
        rid = self.pause(action_id); self.poll()
        self.assertIsNone(self.client.result(rid)['result']['client_action'])
        self.assertIsNone(self.client.result(original)); self.assertIsNotNone(self.resident.active)
        resume = self.client.submit({'op':'resume'}); self.resident.tick()
        self.assertEqual('failed', self.client.result(resume)['status'])
        self.assertEqual(['/control/pause'], [p for p, _ in self.posts()])
    def test_foreign_resident_owner_refuses_before_any_write(self):
        original, _ = self.start_encounter(); self.bridge.calls.clear(); rid = self.pause('foreign-action')
        self.assertEqual('failed', self.client.result(rid)['status']); self.assertFalse(self.posts())
        self.assertIsNone(self.client.result(original)); self.assertFalse(self.resident.paused)
    def test_matching_undispatched_pending_stays_held_and_is_never_replayed(self):
        rid = 'not-yet-dispatched'; command = dict(body(), op='action', request_id=rid, session_id=self.resident.session_id)
        self.resident.command(command)
        action_id = uuid.uuid5(uuid.UUID(self.resident.session_id), rid + ':1').hex
        self.bridge.calls.clear(); pause_id = self.pause(action_id)
        self.assertEqual('succeeded', self.client.result(pause_id)['status'])
        for _ in range(3): self.poll()
        self.assertEqual([command], list(self.resident.pending)); self.assertIsNone(self.client.result(rid))
        resume = self.client.submit({'op':'resume'}); self.resident.tick()
        self.assertEqual('failed', self.client.result(resume)['status'])
        self.assertEqual(['/control/pause'], [p for p, _ in self.posts()])
    def test_foreign_pending_work_refuses_without_consuming_or_cancelling_it(self):
        pending = dict(body(), op='action', request_id='other-pending', session_id=self.resident.session_id)
        self.resident.command(pending); self.bridge.calls.clear()
        with self.assertRaisesRegex(ValueError, 'foreign_pending'):
            self.resident.command(dict(op='encounter_pause', expected_resident_session=self.resident.session_id,
                                      body=pause_body('different')))
        self.assertEqual([pending], list(self.resident.pending)); self.assertFalse(self.bridge.calls)
    def test_native_rejection_does_not_trigger_cancel_fallback(self):
        original, action_id = self.start_encounter(); self.bridge.pause_failure = 'rejected'; self.bridge.calls.clear()
        rid = self.pause(action_id)
        for _ in range(3): self.poll()
        self.assertEqual('failed', self.client.result(rid)['status']); self.assertIsNone(self.client.result(original))
        self.assertEqual(['/control/pause'], [p for p, _ in self.posts()])
    def test_wrong_resident_binding_refuses_before_native_post(self):
        _, action_id = self.start_encounter(); self.bridge.calls.clear()
        rid = self.pause(action_id, expected_resident_session='other')
        self.assertEqual('failed', self.client.result(rid)['status']); self.assertFalse(self.posts())


if __name__ == '__main__': unittest.main()

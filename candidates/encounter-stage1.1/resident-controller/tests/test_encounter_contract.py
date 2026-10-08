"""Synthetic encounter receipts and queue files only; no game, sockets or real IPC."""
import copy
import tempfile
import unittest
from unittest.mock import patch

from resident_controller.controller import Resident
from resident_controller.encounter_contract import (MODE, OUTCOME_SCOPE,
    validate_encounter_request, validate_encounter_receipt)
from resident_controller.ipc import QueueClient, atomic_json
from resident_controller.tasks import basic
from resident_controller.transport import BridgeError
from test_controller import FakeBridge

U = '00000000-0000-0000-0000-000000000001'
V = '00000000-0000-0000-0000-000000000002'
W = '00000000-0000-0000-0000-000000000003'


def body():
    return dict(action='combat_entity', timeout_ms=15000,
                expected_world_generation=U, expected_player_uuid=U, expected_action_session=U,
                target_entity_id=1, target_uuid=V, target_type='minecraft:zombie',
                approach=False, shield=False, encounter_mode=MODE,
                encounter_scope=[dict(entity_id=1, uuid=V, type='minecraft:zombie'),
                                 dict(entity_id=2, uuid=W, type='minecraft:zombie')])


def receipt(request=None, status='running', reason=None):
    request = request or body()
    reason = reason or ('encounter_clearance_observed' if status == 'succeeded' else
                        'accepted' if status == 'running' else 'encounter_scope_missing_risk_remaining')
    encounter = dict(encounter_schema_version=1, encounter_mode=MODE,
                     encounter_scope=copy.deepcopy(request['encounter_scope']), offense_disabled=True,
                     risk_remaining=True, requires_handoff=True, safety_assured=False,
                     outcome_scope=OUTCOME_SCOPE if status == 'succeeded' else None,
                     clearance_observations=3 if status == 'succeeded' else 0, danger_radius=8.0,
                     scoped_living_threats=[dict(x, known=True, alive=True, clearance=9.0)
                                           for x in request['encounter_scope']])
    if status != 'running':
        encounter.update(terminal_status=status, terminal_reason=reason)
    combat = dict(encounter=encounter, target_entity_id=request['target_entity_id'],
                  target_uuid=request['target_uuid'], target_type=request['target_type'],
                  attack_dispatches=0, attack_completed=False, target_dead_observed=False,
                  hits_confirmed=False, server_confirmed=False, risk_remaining=True, safety_assured=False)
    return dict(ok=True, action_schema_version=1, action='combat_entity', action_session=U,
                action_id=request.get('action_id', 'synthetic-action'), status=status, reason=reason,
                server_confirmed=False, result=dict(world_generation=U, combat=combat,
                                                    input_release_confirmed=status != 'running'))


class EncounterBridge(FakeBridge):
    def __init__(self):
        super().__init__()
        self.action['action_session'] = U
        self.post_failure = None
        self.cancel_corruption = None
        self.accepted = None
    def request(self, method, path, payload=None):
        if path == '/control/action':
            self.calls.append((method, path, copy.deepcopy(payload)))
            if self.post_failure == 'disabled':
                raise BridgeError('encounter_stage1_disabled', status=409)
            self.accepted = copy.deepcopy(payload)
            self.action = receipt(payload)
            if self.post_failure == 'timeout':
                raise BridgeError('transport_failed', uncertain=True)
            if self.post_failure == 'malformed':
                return {'action_schema_version': 1}
            return copy.deepcopy(self.action)
        if path == '/control/action/cancel':
            self.calls.append((method, path, copy.deepcopy(payload)))
            if self.action['status'] == 'running':
                self.action = receipt(self.accepted, 'cancelled', 'cancel_requested')
            result = copy.deepcopy(self.action)
            if self.cancel_corruption:
                self.cancel_corruption(result)
            return result
        result = super().request(method, path, payload)
        if path == '/control/status':
            result['world'] = {'world_generation': U}
            result['player'] = {'uuid': U}
        if path == '/control/state?radius=8':
            result['world']['world_generation'] = U
        return result


class EntryContract(unittest.TestCase):
    def test_new_mode_preserves_exact_scope_and_owns_copy(self):
        b = body()
        validated = validate_encounter_request(b)
        self.assertEqual(validated, b)
        b['encounter_scope'][0]['entity_id'] = 7
        self.assertEqual(validated['encounter_scope'][0]['entity_id'], 1)
    def test_old_combat_without_new_fields_is_untouched(self):
        self.assertIsNone(validate_encounter_request({'action': 'combat_entity', 'target_uuid': 'legacy'}))
    def test_scope_only_and_other_action_are_invalid(self):
        for change in ({'encounter_mode': None}, {'encounter_mode': 'future'}, {'action': 'follow_path'}):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    validate_encounter_request(dict(body(), **change))
        b = body(); del b['encounter_mode']
        with self.assertRaises(ValueError): validate_encounter_request(b)
    def test_exact_two_distinct_canonical_zombies_contain_target(self):
        for change in ([body()['encounter_scope'][0]], body()['encounter_scope'] * 2,
                       [body()['encounter_scope'][0]] * 2,
                       [dict(entity_id=1, uuid=V, type='minecraft:zombie'), dict(entity_id=1, uuid=W, type='minecraft:zombie')],
                       [dict(entity_id=1, uuid=V, type='minecraft:zombie'), dict(entity_id=2, uuid=V, type='minecraft:zombie')]):
            with self.subTest(scope=change), self.assertRaises(ValueError):
                validate_encounter_request(dict(body(), encounter_scope=change))
        for key, value in [('entity_id', True), ('entity_id', -1), ('entity_id', 1.0), ('entity_id', 2147483648),
                           ('uuid', 'A0000000-0000-0000-0000-000000000001'), ('uuid', '1-1-1-1-1'),
                           ('type', 'minecraft:skeleton'), ('extra', 1)]:
            b = body(); b['encounter_scope'][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError): validate_encounter_request(b)
        b = body(); b['target_uuid'] = U
        with self.assertRaises(ValueError): validate_encounter_request(b)
    def test_unsafe_fields_even_false_or_null_and_implicit_options_rejected(self):
        for key in ['hotbar_slot', 'jump', 'sneak', 'sprint', 'unknown']:
            for value in (False, None, 0):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    validate_encounter_request(dict(body(), **{key: value}))
        for key in ('approach', 'shield'):
            for value in (True, 0, None):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    validate_encounter_request(dict(body(), **{key: value}))
            b = body(); del b[key]
            with self.assertRaises(ValueError): validate_encounter_request(b)
    def test_mode_identity_time_and_navigation_strictness(self):
        for key, value in [('expected_world_generation', None), ('expected_player_uuid', 'x'),
                           ('expected_action_session', 'x'), ('timeout_ms', True), ('timeout_ms', 30001),
                           ('target_entity_id', True), ('target_type', 'minecraft:husk'),
                           ('expected_origin', {'x': 0, 'y': 0, 'z': 0})]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_encounter_request(dict(body(), **{key: value}))
        b = dict(body(), expected_navigation_epoch=3, expected_origin={'x': 0, 'y': 64, 'z': 0})
        self.assertEqual(validate_encounter_request(b), b)
    def test_basic_recipe_validates_before_yield_and_terminal_after_yield(self):
        b = dict(body(), op='action', jump=False)
        with self.assertRaises(ValueError): next(basic(b))
        recipe = basic(dict(body(), op='action'))
        self.assertEqual(next(recipe)['body'], body())
        invalid = receipt(status='succeeded'); invalid['result']['combat']['encounter']['clearance_observations'] = 2
        with self.assertRaises(ValueError): recipe.send(invalid)
        for status in ('running', 'failed', 'cancelled'):
            recipe = basic(dict(body(), op='action')); next(recipe)
            with self.subTest(status=status), self.assertRaises(ValueError):
                recipe.send(receipt(status=status))


class ReceiptContract(unittest.TestCase):
    def test_running_failure_cancel_and_bounded_success_keep_risk(self):
        for status in ('running', 'failed', 'cancelled', 'succeeded'):
            with self.subTest(status=status): validate_encounter_receipt(receipt(status=status), body())
    def test_invalid_or_missing_receipts_cannot_claim_success(self):
        patches = [('encounter_schema_version', True), ('encounter_mode', 'other'), ('encounter_scope', []),
                   ('offense_disabled', False), ('risk_remaining', False), ('requires_handoff', False),
                   ('safety_assured', True), ('danger_radius', True), ('danger_radius', 7.9),
                   ('clearance_observations', 2), ('clearance_observations', True),
                   ('clearance_observations', 4), ('terminal_reason', 'target_dead_observed'),
                   ('terminal_status', 'failed'), ('outcome_scope', None), ('scoped_living_threats', [])]
        for key, value in patches:
            r = receipt(status='succeeded'); r['result']['combat']['encounter'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): validate_encounter_receipt(r, body())
    def test_missing_dead_unknown_changed_or_near_scope_is_not_clearance(self):
        for key, value in [('known', False), ('alive', False), ('clearance', 8), ('clearance', float('nan')),
                           ('clearance', float('inf')), ('clearance', True), ('entity_id', True),
                           ('entity_id', 8), ('uuid', U), ('type', 'minecraft:husk')]:
            r = receipt(status='succeeded'); r['result']['combat']['encounter']['scoped_living_threats'][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError): validate_encounter_receipt(r, body())
    def test_clearance_never_equals_attack_or_safety_success(self):
        for key, value in [('attack_completed', True), ('attack_dispatches', 1), ('attack_dispatches', False),
                           ('target_dead_observed', True), ('hits_confirmed', True), ('server_confirmed', True),
                           ('risk_remaining', False), ('safety_assured', True), ('target_entity_id', 2)]:
            r = receipt(status='succeeded'); r['result']['combat'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): validate_encounter_receipt(r, body())
        for reason in ('target_dead_observed', 'retreat_segment_completed', 'path_reached'):
            with self.subTest(reason=reason), self.assertRaises(ValueError):
                validate_encounter_receipt(receipt(status='succeeded', reason=reason), body())
    def test_failed_or_running_receipt_cannot_borrow_previous_success(self):
        for status in ('failed', 'cancelled', 'running'):
            r = receipt(status=status); r['result']['combat']['encounter']['outcome_scope'] = OUTCOME_SCOPE
            with self.subTest(status=status), self.assertRaises(ValueError): validate_encounter_receipt(r, body())
    def test_release_failure_does_not_validate_success(self):
        r = receipt(status='succeeded'); r['result']['input_release_confirmed'] = False
        with self.assertRaises(ValueError): validate_encounter_receipt(r, body())


class ResidentEncounterContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bridge = EncounterBridge()
        self.resident = Resident(self.bridge, self.tmp.name)
        self.resident.start()
        self.client = QueueClient(self.tmp.name)
    def tearDown(self):
        self.resident.lock.close(); self.tmp.cleanup()
    def submit(self, request=None, request_id=None):
        rid = self.client.submit(dict(request or body(), op='action'), request_id=request_id)
        self.resident.tick()
        return rid
    def tick(self):
        if self.resident.active: self.resident.active.wake_at = 0
        self.resident.tick()
    def posts(self):
        return [b for m, p, b in self.bridge.calls if m == 'POST' and p == '/control/action']
    def test_invalid_entry_before_any_bridge_read_or_takeover(self):
        for patch_value in ({'shield': True}, {'jump': False}, {'encounter_scope': []}, {'encounter_mode': None}):
            before = len(self.bridge.calls)
            rid = self.submit(dict(body(), **patch_value))
            result = self.client.result(rid)
            self.assertEqual(result['status'], 'failed')
            self.assertTrue(result['requires_handoff']); self.assertTrue(result['risk_remaining'])
            self.assertEqual(len(self.bridge.calls), before)
    def test_dispatch_revalidates_custom_recipe_before_post(self):
        def invalid_recipe(*args):
            yield {'step': 'action', 'body': dict(body(), jump=False)}
        with patch('resident_controller.controller.make_task', side_effect=invalid_recipe):
            rid = self.submit()
        self.assertEqual(self.client.result(rid)['status'], 'failed')
        self.assertEqual(self.posts(), [])
    def test_one_native_action_multiple_status_reads_then_bounded_completion(self):
        rid = self.submit()
        for _ in range(3): self.tick()
        self.assertEqual(len(self.posts()), 1)
        self.assertEqual(self.posts()[0]['encounter_scope'], body()['encounter_scope'])
        self.bridge.action = receipt(self.bridge.accepted, 'succeeded')
        for _ in range(3): self.tick()
        result = self.client.result(rid)
        self.assertEqual(result['status'], 'succeeded')
        self.assertTrue(result['risk_remaining']); self.assertTrue(result['requires_handoff'])
        self.assertFalse(result['safety_assured'])
        self.assertEqual(len(self.posts()), 1)
    def test_terminal_failure_cancels_pending_not_reposts(self):
        rid = self.submit(); waiting = self.submit()
        self.bridge.action = receipt(self.bridge.accepted, 'failed', 'encounter_scope_missing_risk_remaining')
        self.tick(); self.tick()
        result = self.client.result(rid)
        self.assertEqual(result['status'], 'failed')
        self.assertTrue(result['requires_handoff'])
        self.assertEqual(self.client.result(waiting)['status'], 'cancelled')
        self.assertEqual(len(self.posts()), 1)
    def test_disabled_gate_definite_409_has_no_cancel_or_retry(self):
        self.bridge.post_failure = 'disabled'; rid = self.submit()
        for _ in range(4): self.tick()
        result = self.client.result(rid)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['reason'], 'encounter_stage1_disabled')
        self.assertTrue(result['requires_handoff'])
        self.assertEqual(len(self.posts()), 1)
        self.assertFalse(any(p == '/control/action/cancel' for _, p, _ in self.bridge.calls))
    def test_timeout_and_malformed_acceptance_never_replay(self):
        for mode in ('timeout', 'malformed'):
            self.bridge.post_failure = mode
            self.resident.paused = False
            before = len(self.posts()); rid = self.submit()
            for _ in range(4): self.tick()
            result = self.client.result(rid)
            self.assertEqual(result['status'], 'uncertain')
            self.assertTrue(result['requires_handoff']); self.assertFalse(result['task_completed'])
            self.assertEqual(len(self.posts()) - before, 1)
            cancellations = [b for _, p, b in self.bridge.calls if p == '/control/action/cancel']
            self.assertEqual(cancellations[-1]['expected_action_session'], U)
    def test_mutated_scope_terminal_and_cancel_receipt_are_untrusted(self):
        rid = self.submit()
        self.bridge.action = receipt(self.bridge.accepted, 'succeeded')
        self.bridge.action['result']['combat']['encounter']['encounter_scope'].reverse()
        self.tick()
        result = self.client.result(rid)
        self.assertEqual(result['status'], 'uncertain')
        self.assertIsNone(result['resolved_action'])
        self.assertEqual(result['action_outcome'], 'unresolved')
        self.assertEqual(len(self.posts()), 1)
    def test_duplicate_consumed_queue_request_cannot_replay(self):
        self.bridge.post_failure = 'disabled'; rid = self.submit(request_id='same-request')
        self.client.submit(dict(body(), op='action'), request_id=rid)
        for _ in range(3): self.tick()
        self.assertEqual(len(self.posts()), 1)
        (self.resident.root / 'results' / (rid + '.json')).unlink()
        atomic_json(self.resident.root / 'inbox' / (rid + '.json'),
                    dict(body(), op='action', request_id=rid, session_id=self.resident.session_id))
        self.tick()
        self.assertEqual(self.client.result(rid)['reason'], 'request_id_already_consumed_result_expired')
        self.assertEqual(len(self.posts()), 1)


if __name__ == '__main__': unittest.main()

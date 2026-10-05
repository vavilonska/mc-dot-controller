import copy
import json
import unittest
from dataclasses import replace
from unittest.mock import patch

from combat_controller.core import ActionContext, HOSTILE_TYPES
from combat_controller.bridge import (BridgeError, ConnectionConfig, HttpTransport, MineClientBridge,
                                      validate_guarded_capabilities, validate_guarded_request)
from combat_controller.fake import FakeClock
from tests.test_bridge import fixtures, FakeTransport, PROTOCOL, IDENTITY, PLAYER, TARGET, WORLD


def capabilities(**changes):
    guard = {'schema_version': 1, 'enabled': True, 'max_ttl_ms': 250, 'max_range': 2.75,
             'max_yaw_step': 30.0, 'max_pitch_step': 20.0, 'local_unpublished_survival_only': True,
             'single_flight': True, 'synchronous_attack_attempt': True, 'held_input': False, 'unenchanted_axe_only': True,
             'allowed_target_types': sorted(HOSTILE_TYPES)}
    guard.update(changes)
    return dict(PROTOCOL, guarded_actions=guard)


def request(action='attack', **changes):
    body = {'guard_schema_version': 1, 'action': action, 'expected_world_generation': WORLD,
            'expected_player_uuid': PLAYER, 'expected_target_uuid': TARGET,
            'expected_crosshair_uuid': TARGET, 'ttl_ms': 150}
    if action == 'look':
        body.update(yaw=10.0, pitch=5.0)
    body.update(changes)
    return body


def outcome(action='attack', **changes):
    result = dict(PROTOCOL, guard_schema_version=1, action=action, dispatched=True,
                  damage_confirmed=False, world_generation=WORLD, player_uuid=PLAYER,
                  target_uuid=TARGET, yaw=0.0, pitch=0.0)
    if action == 'look':
        result.update(yaw=10.0, pitch=5.0)
    result.update(changes)
    return result


class GuardedAdapterTests(unittest.TestCase):
    def prepare(self, result=None, changes=None):
        clock = FakeClock()
        status, terrain, state = fixtures()
        if changes:
            changes(state)
        transport = FakeTransport([capabilities(), status, terrain, state, status,
                                   outcome() if result is None else result])
        bridge = MineClientBridge(transport, IDENTITY, clock)
        bridge.prepare_guarded()
        snapshot = bridge.observe()
        context = ActionContext(snapshot, snapshot.entities[0], clock.now + 0.5)
        return bridge, transport, clock, context

    def test_attack_emits_only_guarded_context_bound_schema(self):
        bridge, transport, _, context = self.prepare()
        bridge.attack(context)
        self.assertEqual(('POST', '/control/guarded-action', request()), transport.calls[-1])
        self.assertFalse(any(path in ('/control/key', '/control/look', '/control/mouse') for _, path, _ in transport.calls))

    def test_look_accepts_null_crosshair_for_acquisition(self):
        def miss(state):
            state['crosshair'] = {'type': 'miss'}
        bridge, transport, _, context = self.prepare(outcome('look'), miss)
        bridge.look(10, 5, context)
        self.assertEqual(('POST', '/control/guarded-action', request('look', expected_crosshair_uuid=None)), transport.calls[-1])

    def test_no_legacy_mod_event_ack_is_required(self):
        bridge, _, _, context = self.prepare()
        bridge.attack(context)  # Synchronous startAttack, not a key event.

    def test_unprepared_adapter_never_posts(self):
        transport = FakeTransport([])
        bridge = MineClientBridge(transport, IDENTITY)
        with self.assertRaisesRegex(BridgeError, 'guarded_preflight_required'):
            bridge.attack(None)
        self.assertEqual([], transport.calls)

    def test_missing_or_disabled_guard_capability_rejected(self):
        for data in (PROTOCOL, capabilities(enabled=False), capabilities(single_flight=False)):
            with self.subTest(data=data):
                transport = FakeTransport([data])
                with self.assertRaises(BridgeError):
                    MineClientBridge(transport, IDENTITY).prepare_guarded()
                self.assertEqual(1, len(transport.calls))

    def test_wrong_or_missing_response_identity_is_not_success(self):
        for changes in ({'target_uuid': PLAYER}, {'world_generation': PLAYER}, {'player_uuid': TARGET},
                        {'action': 'look'}, {'guard_schema_version': 2}, {'dispatched': False},
                        {'damage_confirmed': True}, {'damage_confirmed': 0}):
            with self.subTest(changes=changes):
                bridge, transport, _, context = self.prepare(outcome(**changes))
                with self.assertRaisesRegex(BridgeError, 'guarded_response_mismatch'):
                    bridge.attack(context)
                self.assertEqual(1, sum(m == 'POST' for m, _, _ in transport.calls))

    def test_failed_response_consumes_snapshot_no_replay(self):
        bridge, transport, _, context = self.prepare(BridgeError('http_status_500'))
        with self.assertRaises(BridgeError):
            bridge.attack(context)
        with self.assertRaisesRegex(BridgeError, 'unrecognized_action_snapshot'):
            bridge.attack(context)
        self.assertEqual(1, sum(m == 'POST' for m, _, _ in transport.calls))

    def test_successful_response_also_consumes_snapshot(self):
        bridge, transport, _, context = self.prepare()
        bridge.attack(context)
        with self.assertRaisesRegex(BridgeError, 'unrecognized_action_snapshot'):
            bridge.attack(context)
        self.assertEqual(1, sum(m == 'POST' for m, _, _ in transport.calls))

    def test_expired_session_or_stale_context_never_posts(self):
        for advance in (0.6, 0.8):
            with self.subTest(advance=advance):
                bridge, transport, clock, context = self.prepare()
                clock.sleep(advance)
                with self.assertRaisesRegex(BridgeError, 'expired_action_context'):
                    bridge.attack(context)
                self.assertFalse(any(m == 'POST' for m, _, _ in transport.calls))

    def test_ttl_respects_remaining_local_deadline(self):
        bridge, transport, clock, context = self.prepare()
        context = replace(context, deadline=clock.now + 0.075)
        bridge.attack(context)
        ttl = transport.calls[-1][2]['ttl_ms']
        self.assertGreaterEqual(ttl, 74)
        self.assertLessEqual(ttl, 75)

    def test_forged_or_old_snapshot_rejected(self):
        bridge, _, _, context = self.prepare()
        context = replace(context, snapshot=replace(context.snapshot, tick=99))
        with self.assertRaisesRegex(BridgeError, 'unrecognized_action_snapshot'):
            bridge.attack(context)

    def test_foreign_or_protected_target_rejected(self):
        bridge, _, _, context = self.prepare()
        context = replace(context, target=replace(context.target, kind='minecraft:player'))
        with self.assertRaisesRegex(BridgeError, 'invalid_action_target'):
            bridge.attack(context)

    def test_sword_cannot_use_guarded_adapter(self):
        def sword(state):
            state['player']['inventory'][0]['id'] = 'minecraft:iron_sword'
        bridge, transport, _, context = self.prepare(changes=sword)
        with self.assertRaisesRegex(BridgeError, 'guarded_action_requires_vanilla_axe'):
            bridge.attack(context)
        self.assertFalse(any(m == 'POST' for m, _, _ in transport.calls))

    def test_attack_missing_crosshair_rejected(self):
        bridge, _, _, context = self.prepare(changes=lambda s: s.update(crosshair={'type': 'miss'}))
        with self.assertRaisesRegex(BridgeError, 'guarded_attack_requires_target_crosshair'):
            bridge.attack(context)

    def test_look_step_is_limited_against_observed_rotation(self):
        bridge, transport, _, context = self.prepare(outcome('look'))
        with self.assertRaisesRegex(BridgeError, 'guarded_look_step_too_large'):
            bridge.look(90, 5, context)
        self.assertFalse(any(m == 'POST' for m, _, _ in transport.calls))

    def test_attack_response_accepts_finite_unwrapped_live_yaw(self):
        bridge, transport, _, context = self.prepare(outcome(yaw=540.0))
        bridge.attack(context)
        self.assertEqual(1, sum(m == 'POST' for m, _, _ in transport.calls))

    def test_look_response_tolerates_java_float_rounding_at_180(self):
        def near_wrap(state):
            state['player']['yaw'] = 179.0
        bridge, _, _, context = self.prepare(outcome('look', yaw=180.0), near_wrap)
        bridge.look(179.999999, 5.0, context)

    def test_look_response_must_match_requested_angles(self):
        bridge, _, _, context = self.prepare(outcome('look', yaw=9.0))
        with self.assertRaisesRegex(BridgeError, 'guarded_look_result_mismatch'):
            bridge.look(10, 5, context)

    def test_cleanup_never_uses_unguarded_release(self):
        status, _, _ = fixtures()
        transport = FakeTransport([status])
        bridge = MineClientBridge(transport, IDENTITY)
        self.assertTrue(bridge.release_all())
        self.assertEqual([('GET', '/control/status', None)], transport.calls)


class GuardedSchemaTests(unittest.TestCase):
    def test_valid_attack_and_look(self):
        validate_guarded_request(request())
        validate_guarded_request(request('look', expected_crosshair_uuid=None))

    def test_invalid_fields_uuid_ttl_and_actions_rejected(self):
        cases = [dict(button=0), dict(ttl_ms=0), dict(ttl_ms=251), dict(ttl_ms=True),
                 dict(expected_player_uuid='bad'), dict(expected_world_generation='BAD'),
                 dict(expected_crosshair_uuid=None), dict(expected_crosshair_uuid=PLAYER),
                 dict(action='command'), dict(guard_schema_version=True), dict(yaw=0)]
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(BridgeError):
                validate_guarded_request(request(**changes))

    def test_look_angles_must_be_finite_and_normalized(self):
        for changes in ({'yaw': 180}, {'yaw': float('nan')}, {'pitch': 91}, {'pitch': True}):
            with self.subTest(changes=changes), self.assertRaises(BridgeError):
                validate_guarded_request(request('look', **changes))

    def test_capability_contract_is_narrow(self):
        validate_guarded_capabilities(capabilities())
        for changes in ({'enabled': False}, {'max_ttl_ms': 999}, {'held_input': True},
                        {'local_unpublished_survival_only': False}, {'max_range': 4.5},
                        {'synchronous_attack_attempt': False}, {'unenchanted_axe_only': False}, {'schema_version': True}, {'allowed_target_types': ['minecraft:player']}):
            with self.subTest(changes=changes), self.assertRaises(BridgeError):
                validate_guarded_capabilities(capabilities(**changes))


class GuardedTransportTests(unittest.TestCase):
    def config(self, **changes):
        return ConnectionConfig(**dict(dict(token='offline-fake-token', expected_identity=IDENTITY), **changes))

    def test_default_blocks_guarded_write_without_socket(self):
        with patch('http.client.HTTPConnection') as ctor:
            with self.assertRaisesRegex(BridgeError, 'adapter_disabled'):
                HttpTransport(self.config()).request('POST', '/control/guarded-action', request())
            ctor.assert_not_called()

    def test_enable_without_acceptance_verification_blocks(self):
        with patch('http.client.HTTPConnection') as ctor:
            with self.assertRaisesRegex(BridgeError, 'local_acceptance_not_verified'):
                HttpTransport(self.config(enabled=True)).request('POST', '/control/guarded-action', request())
            ctor.assert_not_called()

    def test_no_capability_negotiation_blocks(self):
        with patch('http.client.HTTPConnection') as ctor:
            with self.assertRaisesRegex(BridgeError, 'guarded_capabilities_not_negotiated'):
                HttpTransport(self.config(enabled=True, acceptance_verified=True)).request('POST', '/control/guarded-action', request())
            ctor.assert_not_called()

    def test_negotiated_guarded_wire_schema_uses_fake_http_only(self):
        with patch('http.client.HTTPConnection') as ctor:
            response = ctor.return_value.getresponse.return_value
            response.status = 200
            response.getheader.return_value = 'application/json'
            response.read.side_effect = [json.dumps(capabilities()).encode(), json.dumps(outcome()).encode()]
            transport = HttpTransport(self.config(enabled=True, acceptance_verified=True))
            transport.request('GET', '/control/capabilities')
            transport.request('POST', '/control/guarded-action', request())
            call = ctor.return_value.request.call_args
            self.assertEqual(('POST', '/control/guarded-action'), call.args)
            self.assertEqual(request(), json.loads(call.kwargs['body']))
            self.assertEqual(2, ctor.call_count)

    def test_server_rejection_never_falls_back_or_retries(self):
        for status in (408, 409, 429, 500, 503):
            with self.subTest(status=status), patch('http.client.HTTPConnection') as ctor:
                response = ctor.return_value.getresponse.return_value
                response.status = 200
                response.getheader.return_value = 'application/json'
                response.read.return_value = json.dumps(capabilities()).encode()
                transport = HttpTransport(self.config(enabled=True, acceptance_verified=True))
                transport.request('GET', '/control/capabilities')
                response.status = status
                with self.assertRaisesRegex(BridgeError, 'http_status_'+str(status)):
                    transport.request('POST', '/control/guarded-action', request())
                self.assertEqual(2, ctor.call_count)
                self.assertEqual(('/control/guarded-action'), ctor.return_value.request.call_args.args[1])


if __name__ == '__main__':
    unittest.main()

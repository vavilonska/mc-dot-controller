"""Real public owner/Intent/Watchdog/Resident chain; only native endpoint is modeled."""
from copy import deepcopy
import time
import unittest
from unittest.mock import patch
import test_capability_ownership as owners
import base_watchdog
from mdc_skills.core import Runtime
from mdc_toolbox import ToolboxService
from mdc_toolbox.runtime_adapter import OwnerRuntimeBackend
from resident_controller.transport import BridgeError
from resident_controller.fall_rescue_control import validate, validate_status


class Endpoint(owners.CombatEndpoint):
    def __init__(self):
        super().__init__()
        self.fall = None
        self.fall_calls = []
        self.lose_arm = False
        self.external_unknown = False
        self.no_bucket = False
        self.bad_status = False
        self.stop_native = False
        self.proof_sequence = []
    def snapshot(self):
        s = super().snapshot()
        s['player']['inventory'][1].update(id='minecraft:stone' if self.no_bucket else 'minecraft:water_bucket',count=1,empty=False)
        s['native_fall_rescue'] = {'schema_version': 1, 'native_fences_ready': True,
            'external_controller_unknown': self.external_unknown, 'private_integrated_server_only': True}
        # Native capabilities and native status are distinct objects. A missing
        # status must fail closed under the integrated navigation owner fence.
        s['native_fall_rescue_status'] = deepcopy(self.fall) if self.fall is not None else {
            'fall_rescue_schema_version': 1, 'status': 'disarmed', 'reason': 'not_armed',
            'armed': False, 'input_owned': False, 'automation_blocked': False,
            'unknown_outcome_quarantined': False, 'arm_revision': 0, 'episodes_used': 0,
            'no_auto_resume': True, 'remaining_ms': 0}
        return s
    def request(self, method, path, body=None):
        if path.startswith('/control/fall-rescue/'):
            operation = path.rsplit('/', 1)[1]
            self.fall_calls.append((operation, deepcopy(body)))
            if operation == 'arm':
                self.fall = {'fall_rescue_schema_version': 1, 'status': 'armed', 'reason': 'synthetic_monitoring',
                    'armed': True, 'input_owned': False, 'automation_blocked': False, 'episodes_used': 0, 'unknown_outcome_quarantined': False, 'no_auto_resume': True,
                    'arm_revision': 1, 'remaining_ms': 5000, 'arm_id': body['arm_id'], 'owner_id': body['owner_id'],
                    'action_session': body['expected_action_session'], 'world_generation': body['expected_world_generation'],
                    'player_uuid': body['expected_player_uuid']}
                if self.lose_arm:
                    raise BridgeError('synthetic_lost_arm_response', uncertain=True)
            elif operation == 'renew':
                assert self.fall['arm_revision'] == body['expected_arm_revision']
                self.fall['arm_revision'] += 1
            elif operation == 'disarm':
                self.fall.update(status='disarmed', armed=False, input_owned=False, remaining_ms=0)
            if operation == 'status' and self.proof_sequence:
                update = deepcopy(self.proof_sequence.pop(0))
                for key in ('arm_id','owner_id','action_session','world_generation','player_uuid'):
                    update[key] = self.fall[key]
                for key in ('episode','last_episode'):
                    if key in update:
                        update[key]['episode_id'] = self.fall['arm_id'] + ':1'
                self.fall = update
            if operation == 'status' and self.bad_status:
                return {**deepcopy(self.fall), 'owner_id': 'different-owner'}
            if operation == 'status' and self.stop_native:
                self.fall.update(armed=False,status='disarmed',reason='explicit_pause',remaining_ms=0)
            return deepcopy(self.fall)
        return super().request(method, path, body)


class FallOwnerChainTests(unittest.TestCase):
    until = owners.ActualGatewayOwnershipTests.until
    def setUp(self):
        original_run = base_watchdog.run
        def request_only(*args, **kwargs):
            return original_run(*args, **{**kwargs, 'execution_policy': 'request_only'})
        with patch.object(owners, 'CombatEndpoint', Endpoint), patch.object(base_watchdog, 'run', request_only):
            owners.ActualGatewayOwnershipTests.setUp(self)
        self.runtime = Runtime(self.client, self.root / 'fall-runtime', wait_timeout=2)
        self.backend = OwnerRuntimeBackend(self.runtime)
        self.service = ToolboxService(self.backend, self.root / 'jobs')
    def tearDown(self):
        self.service.close()
        self.runtime.close()
        owners.ActualGatewayOwnershipTests.tearDown(self)
    def submit(self, request_id='guard-one', duration_ms=1000):
        d = self.backend.describe()
        return self.service.call('mdc_job', {'api_version': 'mdc.toolbox/1', 'operation': 'submit',
            'request_id': request_id, 'session_ref': d['session_ref'], 'expected_context_ref': d['context_ref'],
            'capability': 'fall_rescue_guard', 'capability_version': 1, 'arguments': {'duration_ms': duration_ms},
            'policy': {'version': 1, 'execution_mode': 'request_only', 'reactions': 'stop'},
            'budgets': {'max_actions': 16, 'max_observations': 64, 'deadline_seconds': 20}, 'wait_ms': 0})
    def finish(self, first):
        self.assertIn('job_id', first, first)
        def terminal():
            self.result = self.service.call('mdc_job', {'api_version': 'mdc.toolbox/1', 'operation': 'status',
                'job_id': first['job_id'], 'session_ref': first['session_ref']})
            return self.result['state'] not in ('accepted', 'running', 'stopping')
        self.until(terminal, timeout=12)
        return self.result
    def test_public_forged_server_confirmation_is_unknown(self):
        from test_fall_rescue_evidence import ROWS
        forged=deepcopy(ROWS[-1]);forged['last_episode']['dispatch_attempted']=False
        self.bridge.proof_sequence=[forged]
        result=self.finish(self.submit())
        self.assertEqual(result['state'],'unknown',result)
        self.assertNotIn('disarm',[op for op,_ in self.bridge.fall_calls])
        self.assertEqual(sum(op=='arm' for op,_ in self.bridge.fall_calls),1)

    def test_public_attempt_regression_cannot_release_or_become_no_effect(self):
        from test_fall_rescue_evidence import ROWS
        self.bridge.proof_sequence=[deepcopy(ROWS[2]),deepcopy(ROWS[0])]
        result=self.finish(self.submit())
        self.assertEqual(result['state'],'unknown',result)
        self.assertEqual(result['effect_certainty'],'unknown',result)
        self.assertNotIn('disarm',[op for op,_ in self.bridge.fall_calls])
        self.assertIsNotNone(self.client.session()['capability_lease'])

    def test_public_guard_owns_chain_and_deduplicates(self):
        d = self.backend.describe()
        self.assertIn('fall_rescue_guard', d['supported_capabilities'], d)
        first = self.submit()
        result = self.finish(first)
        self.assertEqual(result['state'], 'succeeded', result)
        self.assertEqual(result['cleanup_certainty'], 'confirmed', result)
        self.assertEqual(result['effect_certainty'], 'none_proven', result)
        ops = [op for op, body in self.bridge.fall_calls]
        self.assertEqual(ops.count('arm'), 1)
        self.assertEqual(ops.count('disarm'), 1)
        self.assertGreater(ops.count('status'), 0)
        self.assertEqual(self.bridge.fall_calls[0][1]['permitted_action_ids'], [])
        self.assertIsNone(self.client.session()['capability_lease'])
        again = self.submit()
        self.assertEqual(again['job_id'], first['job_id'])
        self.assertEqual([x[0] for x in self.bridge.fall_calls].count('arm'), 1)
    def test_cancel_disarms_exact_original_without_resume(self):
        first = self.submit(duration_ms=4000)
        self.until(lambda: any(op == 'arm' for op, _ in self.bridge.fall_calls))
        other = self.submit('duplicate-owner', 1000)
        self.assertIn('error', other)
        self.service.call('mdc_job', {'api_version': 'mdc.toolbox/1', 'operation': 'cancel',
            'job_id': first['job_id'], 'session_ref': first['session_ref'], 'cancel_request_id': 'stop-guard', 'wait_ms': 0})
        result = self.finish(first)
        self.assertEqual(result['state'], 'cancelled', result)
        self.assertEqual(result['cleanup_certainty'], 'confirmed', result)
        self.assertEqual([x[0] for x in self.bridge.fall_calls].count('disarm'), 1)
        self.assertFalse(self.bridge.fall['armed'])
    def test_unknown_arm_never_replays_or_new_owner(self):
        self.bridge.lose_arm = True
        result = self.finish(self.submit())
        self.assertEqual(result['state'], 'unknown', result)
        again = self.submit('new-guard')
        self.assertIn('error', again)
        self.assertEqual([x[0] for x in self.bridge.fall_calls], ['arm'])
    def test_renew_runs_on_same_owner_and_revision(self):
        result = self.finish(self.submit(duration_ms=2200))
        self.assertEqual(result['state'], 'succeeded', result)
        writes = [(op, b) for op, b in self.bridge.fall_calls if op != 'status']
        self.assertGreaterEqual(sum(op == 'renew' for op, _ in writes), 1)
        self.assertEqual(len({b['owner_id'] for _, b in writes}), 1)
        self.assertEqual(len({b['arm_id'] for _, b in writes}), 1)
    def test_stop_during_reservation_never_arms(self):
        reserve = self.runtime._reserve
        def cancel_after_reserve(kind, command, **kwargs):
            record = reserve(kind, command, **kwargs)
            if command.get('op') == 'fall_rescue_control' and command.get('operation') == 'arm':
                self.runtime._job_control.request_cancel('stop-during-persist')
            return record
        self.runtime._reserve = cancel_after_reserve
        result = self.finish(self.submit())
        self.assertEqual(result['state'], 'cancelled', result)
        self.assertEqual(result['cleanup_certainty'], 'confirmed', result)
        self.assertEqual(self.bridge.fall_calls, [])
    def test_missing_bucket_known_blocked_before_arm(self):
        self.bridge.no_bucket = True
        result = self.finish(self.submit())
        self.assertEqual(result['state'], 'blocked', result)
        self.assertEqual(result['result']['reason'], 'fall_rescue_water_bucket_required_in_hotbar')
        self.assertEqual(self.bridge.fall_calls, [])
    def test_unknown_status_freezes_original_without_disarm_or_replay(self):
        self.bridge.bad_status = True
        result = self.finish(self.submit())
        self.assertEqual(result['state'], 'unknown', result)
        self.assertEqual([op for op, _ in self.bridge.fall_calls], ['arm', 'status'])
        self.assertIn('error', self.submit('not-a-retry'))
    def test_native_pause_never_renews_or_claims_full_window(self):
        self.bridge.stop_native = True
        result = self.finish(self.submit(duration_ms=4000))
        self.assertEqual(result['state'], 'interrupted', result)
        self.assertEqual(result['cleanup_certainty'], 'confirmed', result)
        self.assertNotIn('renew', [op for op, _ in self.bridge.fall_calls])
        self.assertEqual(result['result']['reason'], 'native_guard_disarmed_before_window_end')
    def test_unowned_gateway_control_rejected_before_native(self):
        rid = self.client.submit({'op': 'fall_rescue_control', 'operation': 'arm'})
        result = self.client.wait(rid, timeout=3)
        self.assertEqual(result['status'], 'cancelled', result)
        self.assertEqual(self.bridge.fall_calls, [])


class FallControlContractTests(unittest.TestCase):
    def body(self):
        return {'op': 'fall_rescue_control', 'operation': 'arm', 'arm_id': 'a'*32, 'ttl_ms': 5000,
            'control_owner': {'owner_id': 'b'*32, 'owner_generation': 1, 'job_id': 'job-a'},
            'expected_context': dict(world_generation='world', dimension='minecraft:overworld', player_uuid='player', action_session='session')}
    def test_closed_schema_and_no_preemption_override(self):
        body = self.body()
        validate(body)
        for k, v in [('permitted_action_ids', ['foreign']), ('owner_id', 'forged'), ('ttl_ms', 60000),
                     ('operation', 'takeover'), ('expected_arm_revision', 1)]:
            with self.subTest(k=k):
                with self.assertRaises(ValueError):
                    validate({**body, k: v})
        for k in ('owner_id', 'owner_generation', 'job_id'):
            changed = deepcopy(body);changed['control_owner'][k] = None
            with self.assertRaises(ValueError):validate(changed)

if __name__ == '__main__': unittest.main()

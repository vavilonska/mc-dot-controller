"""Explicit noncombat policy through the real local mailbox adapters.

IntentClient -> Watchdog -> QueueClient -> Resident is real; only the Bridge
endpoint is synthetic. No game, GUI, network, credentials or live queue is used.
"""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import uuid
from unittest.mock import patch

import base_watchdog
import watchdog
from intent_client import IntentClient
from resident_controller.controller import Resident
from mdc_skills.core import Runtime
import test_capability_ownership as ownership
from test_watchdog import Queue as LegacyQueue


class NoncombatEndpoint(ownership.CombatEndpoint):
    def __init__(self):
        super().__init__()
        self.hazards = {}
        self.focused = True
        self.position = None
        self.next_position = None

    def snapshot(self):
        value = super().snapshot()
        value['focused'] = self.focused
        value['player'].update(self.hazards)
        if self.position:
            value['player'].update(self.position)
        return value

    def request(self, method, path, body=None):
        if path == '/control/action' and body.get('action') == 'follow_path':
            self.next_position = deepcopy(body['waypoints'][-1])
        value = super().request(method, path, body)
        if (path.startswith('/control/action/status') and self.action['status'] == 'succeeded'
                and self.next_position):
            self.position, self.next_position = self.next_position, None
        return value


class NoncombatGatewayTests(unittest.TestCase):
    until = ownership.ActualGatewayOwnershipTests.until
    claim = ownership.ActualGatewayOwnershipTests.claim
    command = ownership.ActualGatewayOwnershipTests.command
    read = ownership.ActualGatewayOwnershipTests.read
    action = ownership.ActualGatewayOwnershipTests.action
    hostile = ownership.ActualGatewayOwnershipTests.hostile
    tearDown = ownership.ActualGatewayOwnershipTests.tearDown

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='offline-noncombat-watchdog-')
        self.root = Path(self.temp.name)
        self.bridge = NoncombatEndpoint()
        self.hostile('zombie')  # Present before either process starts.
        self.bridge.hazards = {'in_water': True, 'eye_in_water': True, 'on_fire': True}
        self.resident = Resident(self.bridge, self.root / 'resident')
        self.resident.start()
        self.finished, self.resident_paused = threading.Event(), threading.Event()
        self.errors, self.queue_calls = [], []
        self.dog = None
        outer = self

        class CapturedWatchdog(watchdog.Watchdog):
            def __init__(dog, q, **kwargs):
                original = q.submit
                def submit(command, request_id=None):
                    result = original(command, request_id=request_id)
                    outer.queue_calls.append((result, deepcopy(command)))
                    return result
                q.submit = submit
                super().__init__(q, **kwargs)
                outer.dog = dog

        def resident_loop():
            try:
                while not self.finished.is_set():
                    if not self.resident_paused.is_set():
                        self.resident.tick()
                    time.sleep(.005)
            except BaseException as exc:
                self.errors.append(exc)

        def watchdog_loop():
            try:
                base_watchdog.run(self.root / 'resident', self.root / 'watchdog',
                    watchdog_class=CapturedWatchdog, execution_policy='noncombat')
            except BaseException as exc:
                self.errors.append(exc)

        self.watchdog_loop = watchdog_loop
        self.threads = [threading.Thread(target=resident_loop, daemon=True),
                        threading.Thread(target=watchdog_loop, daemon=True)]
        for thread in self.threads:
            thread.start()
        self.client = IntentClient(self.root / 'watchdog')
        self.until(lambda: self.client.session()['state'] == 'ready'
                   and self.client.session().get('capability_context') is not None)
        self.owner = uuid.uuid4().hex
        self.epoch = self.client.session()['defense_epoch']

    def mutations(self):
        return [(rid, body) for rid, body in self.queue_calls if body.get('op') != 'observe']

    def assert_no_legacy(self, permitted=0):
        self.assertEqual(len(self.mutations()), permitted, self.mutations())
        self.assertFalse(self.resident.combat.active)
        self.assertFalse(self.dog.environment.active)
        self.assertIsNone(self.dog.ranged_move)
        self.assertEqual(self.dog.defense_epoch, self.epoch)
        self.assertTrue(self.dog.armed)
        self.assertFalse([p for p, _ in self.bridge.posts
                          if p in ('/control/action/cancel', '/control/release-all')])

    def assert_rejected(self, result):
        self.assertEqual(result['status'], 'cancelled', result)
        self.assertEqual(result['reason'], 'noncombat_execution_policy')
        self.assertIsNone(result['queue_request_id'])
        self.assertFalse(result['gameplay_effect_confirmed'])
        self.assertEqual(result['policy_rejection'],
            {'schema_version': 1, 'execution_policy': 'noncombat', 'dispatched': False})
        self.assertTrue(Runtime._no_effect(result))

    def test_hostile_and_hazards_before_acquire_between_actions_and_after_release(self):
        session = self.client.session()
        self.assertEqual(session['execution_policy_schema_version'], 1)
        self.assertEqual(session['execution_policy'], 'noncombat')
        tick = self.bridge.tick
        self.until(lambda: self.bridge.tick >= tick + 2)
        self.assert_no_legacy()
        self.claim()
        source = self.read()
        self.assertTrue(source['player']['in_water'])
        self.assertEqual(source['nearby']['entities'][0]['type'], 'minecraft:zombie')
        # Do not send ordinary movement while wet. Hazard handling above remains
        # observable and read-only; the explicit native action keeps its guards.
        self.bridge.hazards = {}
        self.read()
        self.bridge.health = 16
        time.sleep(1.1)  # Idle planning gap; the owner heartbeat remains real.
        self.assert_no_legacy()
        self.read()
        self.assertEqual(self.client.release_capability(self.owner)['status'], 'succeeded')
        self.bridge.hazards = {'in_lava': True, 'in_powder_snow': True, 'on_fire': True}
        tick = self.bridge.tick
        self.until(lambda: self.bridge.tick >= tick + 2)
        self.assert_no_legacy()
        self.assertIsNone(self.client.session()['capability_lease'])

    def test_acquisition_with_read_in_flight_does_not_start_legacy_mutation(self):
        self.resident_paused.set()
        self.dog.next_observe = 0
        self.until(lambda: self.dog.rpc is not None and self.dog.rpc['kind'] == 'observe')
        self.claim()
        self.assertIsNotNone(self.dog.rpc)
        self.assert_no_legacy()
        self.resident_paused.clear()
        self.read()
        self.assert_no_legacy()

    def test_legacy_direct_and_combat_intents_are_proven_local_no_effect(self):
        for command in (
            {'op': 'action', 'action': 'combat_entity'},
            {'op': 'action', 'action': 'attack_entity'},
            {'op': 'action', 'action': 'shoot_entity'},
            {'op': 'direct', 'endpoint': 'attack', 'body': {}},
            {'op': 'direct', 'endpoint': 'raw-key', 'body': {'key': 'key.mouse.left', 'action': 'press'}},
            {'op': 'action', 'action': 'recover_environment', 'waypoints': []},
            {'op': 'action', 'action': 'follow_path', 'waypoints': []},
            {'op': 'walk_to', 'x': 1, 'y': 64, 'z': 0},
        ):
            with self.subTest(command=command):
                rid = self.client.submit(command)
                self.assert_rejected(self.client.wait(rid, timeout=3))
        self.assert_no_legacy()
        self.assertFalse(self.bridge.posts)

    def test_leased_combat_and_environment_actions_are_rejected_before_queue(self):
        self.claim()
        source = self.read()
        for name in ('combat_entity', 'attack_entity', 'shoot_entity', 'recover_environment', 'future_action'):
            with self.subTest(action=name):
                rid = self.action(name, source)
                self.assert_rejected(self.client.wait(rid, timeout=3))
                self.assertFalse(self.dog.capability_lease['post_observation_required'])
        self.assert_no_legacy()
        self.assertFalse(self.bridge.posts)
        self.read()
        self.assertEqual(self.client.release_capability(self.owner)['status'], 'succeeded')

    def test_allowed_action_requires_real_active_exact_nonempty_owner_and_guard(self):
        for leased in (False, True):
            if leased:
                self.claim()
                self.read()
            for owner in (None, '', uuid.uuid4().hex, self.owner) if not leased else (None, '', uuid.uuid4().hex):
                with self.subTest(leased=leased, owner=owner):
                    rid = self.client.submit({'op': 'action', 'action': 'select_hotbar', 'hotbar_slot': 0,
                        '_capability_owner_id': owner, '_navigation_defense_epoch': self.epoch})
                    self.assert_rejected(self.client.wait(rid, timeout=3))
                    self.assertFalse(self.mutations())
        missing_guard = self.client.submit(self.command({'op': 'action', 'action': 'select_hotbar', 'hotbar_slot': 0}))
        self.assertEqual(self.client.wait(missing_guard, timeout=3)['reason'], 'capability_command_out_of_scope')
        stale_epoch = self.client.submit({**self.command({'op': 'action', 'action': 'select_hotbar', 'hotbar_slot': 0}),
                                         '_navigation_defense_epoch': self.epoch + 1})
        self.assertEqual(self.client.wait(stale_epoch, timeout=3)['reason'], 'capability_defense_epoch_changed')
        self.assert_no_legacy()
        self.assertFalse(self.bridge.posts)

    def test_runtime_select_move_semantic_samples_and_local_rejection_keep_lease(self):
        self.bridge.hazards = {}
        runtime = Runtime(self.client, self.root / 'runtime', wait_timeout=3,
                          required_execution_policy='noncombat')
        try:
            rejected = runtime.execute('forbidden', {'op': 'action', 'action': 'attack_entity',
                'timeout_ms': 1000}, lambda before, after: True)
            self.assertEqual(rejected.status, 'blocked', rejected)
            self.assertEqual(rejected.reason, 'noncombat_execution_policy')
            self.assertIsNone(runtime.pending_request_id)
            first = runtime.execute('select', {'op': 'action', 'action': 'select_hotbar',
                'hotbar_slot': 1, 'timeout_ms': 1000}, lambda before, after: after.player['selected_slot'] == 1)
            self.assertTrue(first.ok, first)
            self.bridge.health = 14
            time.sleep(.7)
            moved = runtime.execute('move', {'op': 'action', 'action': 'follow_path', 'hotbar_slot': 0,
                'waypoints': [{'x': 1.5, 'y': 64, 'z': .5}], 'timeout_ms': 1000},
                lambda before, after: after.player['x'] == 1.5)
            self.assertTrue(moved.ok, moved)
            self.assertFalse(runtime.has_unresolved_execution)
            self.assert_no_legacy(permitted=2)
            self.assertEqual([b['action'] for p, b in self.bridge.posts if p == '/control/action'],
                             ['select_hotbar', 'follow_path'])
            for outcome in (first, moved):
                receipt = self.client.result(outcome.request_ids[0])
                self.assertNotEqual(receipt['request_id'], receipt['queue_request_id'])
                self.assertEqual(receipt['queue_session_id'], self.resident.session_id)
        finally:
            runtime.close()
        self.assertIsNone(self.client.session()['capability_lease'])
        tick = self.bridge.tick
        self.until(lambda: self.bridge.tick >= tick + 2)
        self.assert_no_legacy(permitted=2)

    def test_stop_overrides_pending_owner_exactly_once(self):
        self.bridge.hazards = {}
        ownership.ActualGatewayOwnershipTests.test_stop_overrides_pending_owner_exactly_once(self)
        self.assertEqual([body['op'] for _, body in self.mutations()], ['action', 'cancel'])

    def test_unknown_receipt_retains_exact_owner_without_watchdog_cancel_or_replay(self):
        self.bridge.hazards = {}
        ownership.ActualGatewayOwnershipTests.test_unknown_receipt_retains_owner_without_extra_cancel_or_replay(self)
        self.assertEqual([body['op'] for _, body in self.mutations()], ['action'])
        marker = json.loads((self.root / 'watchdog' / 'capability-owner.json').read_text())
        self.assertTrue(marker['active'])
        self.assertEqual(marker['active_request_id'], self.dog.owner['id'])

    def test_restart_keeps_durable_owner_quarantine(self):
        ownership.ActualGatewayOwnershipTests.test_restart_quarantines_durable_owner_even_after_explicit_stop(self)
        self.assertEqual(self.dog.status()['execution_policy'], 'noncombat')

    def test_noncombat_directory_refuses_default_restart_before_queue_access(self):
        stop = self.root / 'watchdog' / 'STOP'
        stop.write_text('fixture operator stop')
        self.threads[1].join(timeout=3)
        self.assertTrue(self.dog.stopped)
        stop.unlink()
        posts = len(self.bridge.posts)
        with patch.object(base_watchdog, 'QueueClient', side_effect=AssertionError('queue access forbidden')):
            with self.assertRaisesRegex(ValueError, 'execution_policy_pinned_noncombat_requires_explicit_flag'):
                base_watchdog.run(self.root / 'resident', self.root / 'watchdog')
        self.assertEqual(len(self.bridge.posts), posts)

    def test_focus_loss_before_acquire_pauses_without_input_mutation(self):
        self.bridge.focused = False
        self.until(lambda: not self.dog.armed)
        self.assertEqual(self.dog.reason, 'noncombat_observation_not_safe_idle')
        # The client observes the published state, not the daemon's in-memory
        # armed flag. Wait for that publication before expecting client refusal.
        self.until(lambda: self.client.session()['state'] == 'paused')
        self.assertFalse(self.bridge.posts)
        self.assertFalse(self.mutations())
        with self.assertRaisesRegex(ValueError, 'watchdog_not_accepting_intents'):
            self.client.acquire_capability(self.owner)
        self.assertFalse(self.bridge.posts)
        self.assertFalse(self.mutations())
        self.assertIsNone(self.dog.capability_lease)
        self.assertIsNone(self.client._capability_owner)

    def test_focus_loss_stale_publication_refuses_lease_without_input_mutation(self):
        paused_write = threading.Event()
        publish = threading.Event()
        real_write = base_watchdog.write_json
        outcome = []
        def hold_first_paused_publication(path, value):
            if (Path(path).name == 'state.json' and value.get('state') == 'paused'
                    and not paused_write.is_set()):
                paused_write.set()
                if not publish.wait(3):
                    raise AssertionError('test_paused_publication_not_released')
            return real_write(path, value)
        def acquire():
            try:
                self.client.acquire_capability(self.owner, timeout=3)
                outcome.append(None)
            except Exception as exc:
                outcome.append(exc)
        worker = None
        with patch.object(base_watchdog, 'write_json', hold_first_paused_publication):
            try:
                self.bridge.focused = False
                self.assertTrue(paused_write.wait(2))
                self.assertFalse(self.dog.armed)
                self.assertEqual(self.client.session()['state'], 'ready')
                worker = threading.Thread(target=acquire, daemon=True)
                worker.start()
                # Prove the stale client enqueued exactly a lease control before
                # releasing publication. No resident/gameplay request is sent.
                self.until(lambda: any(json.loads(path.read_text()).get('op') == 'capability_acquire'
                    for path in (self.root / 'watchdog' / 'inbox').glob('*.json')))
            finally:
                publish.set()
                if worker is not None:
                    worker.join(timeout=4)
        self.assertIsNotNone(worker)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(outcome), 1)
        self.assertIsInstance(outcome[0], ValueError)
        self.assertEqual(str(outcome[0]), 'capability_control_unconfirmed:capability_owner_requires_handoff')
        self.assertFalse(self.bridge.posts)
        self.assertFalse(self.mutations())
        self.assertIsNone(self.dog.capability_lease)
        self.assertIsNone(self.client._capability_owner)
        controls = [json.loads(path.read_text()) for path in (self.root / 'watchdog' / 'results').glob('*.json')]
        self.assertEqual(len(controls), 1)
        self.assertEqual(controls[0]['result']['status'], 'failed')
        self.assertEqual(controls[0]['result']['reason'], 'capability_owner_requires_handoff')
        self.assertFalse(controls[0]['result']['gameplay_effect_confirmed'])
        self.assertIsNone(controls[0]['queue_request_id'])

    def test_focus_loss_under_lease_preserves_handoff_without_mutation(self):
        self.claim()
        self.read()
        self.bridge.focused = False
        self.read()
        self.until(lambda: self.dog.handoff_latched)
        self.assertEqual(self.dog.reason, 'capability_observation_not_safe_idle')
        self.assertFalse(self.mutations())
        self.assertFalse(self.bridge.posts)

    def test_dead_observation_pauses_without_automatic_cancel(self):
        self.bridge.health = 0
        self.until(lambda: not self.dog.armed)
        self.assertEqual(self.dog.reason, 'player_dead_or_unavailable')
        self.assertFalse(self.mutations())
        self.assertFalse(self.bridge.posts)

    def test_delayed_observation_pauses_without_automatic_cancel(self):
        self.resident_paused.set()
        self.dog.next_observe = 0
        self.until(lambda: self.dog.rpc is not None)
        self.until(lambda: not self.dog.armed)
        self.assertEqual(self.dog.reason, 'noncombat_observation_delayed_no_cancel')
        self.assertFalse(self.dog.recover_observation)
        self.assertFalse(self.mutations())
        self.assertFalse(self.bridge.posts)

    def test_second_mutation_still_requires_semantic_post_observation(self):
        self.bridge.hazards = {}
        ownership.ActualGatewayOwnershipTests.test_second_mutation_cannot_reuse_pre_action_observation(self)

    def test_release_still_requires_fresh_neutral_post_observation(self):
        self.bridge.hazards = {}
        ownership.ActualGatewayOwnershipTests.test_release_requires_new_neutral_post_observation(self)

    def test_context_change_under_lease_preserves_pause(self):
        ownership.ActualGatewayOwnershipTests.test_unrequested_player_context_change_pauses(self)
        self.assertFalse(self.mutations())

    def test_expired_lease_never_releases_into_legacy_defense(self):
        self.bridge.hazards = {}
        ownership.ActualGatewayOwnershipTests.test_original_budget_expiry_cannot_start_legacy_combat(self)
        self.assertEqual([body['op'] for _, body in self.mutations()], ['action'])


class NoncombatPolicyUnitTests(unittest.TestCase):
    def test_handoff_dominates_local_policy_denial_without_changing_pending_owner(self):
        q = LegacyQueue()
        dog = watchdog.Watchdog(q, execution_policy='noncombat')
        dog.owner = {'id': 'original-intent', 'request_id': 'original-queue'}
        dog.capability_lease = {'state': 'paused', 'owner_id': uuid.uuid4().hex}
        dog.handoff_latched = True
        for release_unconfirmed in (False, True):
            dog.input_release_latched = release_unconfirmed
            original = deepcopy(dog.owner)
            self.assertTrue(dog.submit_owner('forbidden-after-unknown', {'op': 'action', 'action': 'attack_entity'}))
            denial = dog.completed[-1]['result']
            self.assertTrue(denial['requires_handoff'])
            self.assertNotIn('policy_rejection', denial)
            self.assertFalse(Runtime._no_effect(denial))
            self.assertEqual(dog.owner, original)
        self.assertFalse(q.calls)

    def test_default_preserves_legacy_hostile_response(self):
        q = LegacyQueue()
        q.obs['state']['nearby']['entities'] = [{'uuid': '22222222-2222-4222-8222-222222222222',
            'type': 'minecraft:zombie', 'alive': True, 'health': 20, 'distance': 2}]
        now = [0.0]
        dog = watchdog.Watchdog(q, clock=lambda: now[0])
        for _ in range(8):
            dog.tick()
            now[0] += .1
        self.assertEqual(dog.status()['execution_policy'], 'standard')
        self.assertEqual([c['op'] for _, c in q.calls][:4], ['observe', 'cancel', 'observe', 'combat_start'])

    def test_automatic_mutation_gate_preserves_explicit_stop_only(self):
        q = LegacyQueue()
        dog = watchdog.Watchdog(q, execution_policy='noncombat')
        for kind, command in (
            ('start_combat', {'op': 'combat_start'}), ('ranged_cancel', {'op': 'cancel'}),
            ('attention_cancel', {'op': 'cancel'}), ('env_cancel', {'op': 'cancel'}),
            ('stop_cancel', {'op': 'cancel'}),
        ):
            dog.send(kind, command)
        self.assertFalse(q.calls)
        dog.stop()
        dog.tick()
        dog.tick()
        self.assertTrue(dog.stopped)
        self.assertTrue(dog.cancel_confirmed)
        self.assertEqual([c['op'] for _, c in q.calls], ['cancel'])

    def test_missing_or_corrupt_pin_cannot_silently_reenable_defense(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base_watchdog.enforce_execution_policy(root, 'standard')
            self.assertFalse((root / 'execution-policy.json').exists())
            (root / 'state.json').write_text(json.dumps({'execution_policy': 'noncombat'}))
            for mode in ('standard', 'noncombat'):
                with self.assertRaisesRegex(ValueError, 'published_noncombat_pin_missing'):
                    base_watchdog.enforce_execution_policy(root, mode)
            (root / 'state.json').unlink()
            base_watchdog.enforce_execution_policy(root, 'noncombat')
            pin = root / 'execution-policy.json'
            self.assertEqual(json.loads(pin.read_text()), {'schema_version': 1, 'execution_policy': 'noncombat'})
            pin.write_text('{broken')
            for mode in ('standard', 'noncombat'):
                with self.assertRaisesRegex(ValueError, 'checkpoint_unconfirmed'):
                    base_watchdog.enforce_execution_policy(root, mode)

    def test_policy_pin_symlink_nonfile_and_oversized_content_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pin = root / 'execution-policy.json'
            target = root / 'target.json'
            target.write_text(json.dumps({'schema_version': 1, 'execution_policy': 'noncombat'}))
            pin.symlink_to(target)
            with self.assertRaisesRegex(ValueError, 'checkpoint_unconfirmed'):
                base_watchdog.enforce_execution_policy(root, 'noncombat')
            pin.unlink()
            pin.mkdir()
            with self.assertRaisesRegex(ValueError, 'checkpoint_unconfirmed'):
                base_watchdog.enforce_execution_policy(root, 'noncombat')
            pin.rmdir()
            pin.write_text(' ' * 1025)
            with self.assertRaisesRegex(ValueError, 'checkpoint_unconfirmed'):
                base_watchdog.enforce_execution_policy(root, 'noncombat')

    def test_cli_explicit_mode_and_default(self):
        for arguments, expected in (([], 'standard'), (['--execution-policy', 'noncombat'], 'noncombat')):
            with patch('sys.argv', ['watchdog.py', 'run', '--queue', '/unused/q', '--control', '/unused/c', *arguments]):
                with patch.object(base_watchdog, 'run') as run:
                    watchdog.main()
                    self.assertEqual(run.call_args.kwargs['execution_policy'], expected)


if __name__ == '__main__':
    unittest.main()

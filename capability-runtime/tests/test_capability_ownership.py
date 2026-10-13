"""Real local IntentClient/Watchdog/QueueClient/Resident arbitration.

Only the Bridge endpoint is synthetic. Tests never connect to a game/server.
"""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import uuid

import base_watchdog
from watchdog import Watchdog
from intent_client import IntentClient
from resident_controller.controller import Resident
from resident_controller.navigation_binding import NativeBindingContext
from test_gateway_integration import EndpointFixture
from mdc_skills.core import Runtime


class CombatEndpoint(EndpointFixture):
    def __init__(self):
        super().__init__()
        self.entities = []
        self.health = 20
        self.hold = False
        self.destination = None
        self.other_player = False
        self.transition_cancel = False
        self.integrated_server_instance = '33333333-3333-4333-8333-333333333333'
    def snapshot(self):
        value = super().snapshot()
        value['player']['uuid'] = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
        value['world']['integrated_server_instance'] = self.integrated_server_instance
        value['player']['health'] = self.health
        value['player']['inventory'][0].update(id='minecraft:iron_axe', count=1, empty=False)
        value['nearby'] = {'entities': deepcopy(self.entities), 'truncated': False,
                           'returned': len(self.entities), 'total': len(self.entities)}
        if self.destination and self.action['status'] in ('succeeded', 'cancelled'):
            value['world']['world_generation'] = '22222222-2222-4333-8444-555555555555'
            value['world']['dimension'] = value['player']['dimension'] = self.destination
        if self.other_player:
            value['player']['uuid'] = 'different-player'
        return value
    def request(self, method, path, body=None):
        if path.startswith('/control/action/status') and self.transition_cancel and self.action['status'] == 'running':
            self.action.update(status='cancelled', reason='world_transition')
        if path.startswith('/control/action/status') and self.hold and self.action['status'] == 'running':
            return deepcopy(self.action)
        return super().request(method, path, body)


class ActualGatewayOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='offline-capability-lease-')
        self.root = Path(self.temp.name)
        self.bridge = CombatEndpoint()
        self.resident = Resident(self.bridge, self.root / 'resident')
        self.resident.start()
        self.finished = threading.Event()
        self.resident_paused = threading.Event()
        self.errors = []
        self.dog = None
        outer = self
        class CapturedWatchdog(Watchdog):
            def __init__(dog, *args, **kwargs):
                super().__init__(*args, **kwargs)
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
                base_watchdog.run(self.root / 'resident', self.root / 'watchdog', watchdog_class=CapturedWatchdog)
            except BaseException as exc:
                self.errors.append(exc)
        self.watchdog_loop = watchdog_loop
        self.threads = [threading.Thread(target=resident_loop, daemon=True),
                        threading.Thread(target=watchdog_loop, daemon=True)]
        for thread in self.threads:
            thread.start()
        self.client = IntentClient(self.root / 'watchdog')
        self.until(lambda: self.client.session()['state'] == 'ready' and self.client.session().get('capability_context') is not None)
        self.owner = uuid.uuid4().hex
        self.epoch = self.client.session()['defense_epoch']
    def tearDown(self):
        self.client.close_capability()
        self.resident_paused.clear()
        (self.root / 'watchdog' / 'STOP').write_text('offline teardown')
        self.threads[1].join(timeout=5)
        self.finished.set()
        self.threads[0].join(timeout=2)
        self.resident.lock.close()
        self.assertFalse(self.errors, self.errors)
        self.assertFalse(any(t.is_alive() for t in self.threads))
        self.temp.cleanup()
    def until(self, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.assertFalse(self.errors, self.errors)
            try:
                if predicate():
                    return
            except (OSError, ValueError):
                pass
            time.sleep(.01)
        self.fail('offline adapter condition timed out')
    def claim(self, duration_ms=10000):
        result = self.client.acquire_capability(self.owner, duration_ms=duration_ms)
        self.assertEqual(result['status'], 'succeeded')
        return result
    def command(self, body):
        return {**body, '_capability_owner_id': self.owner, '_navigation_defense_epoch': self.epoch}
    def read(self):
        rid = self.client.submit(self.command({'op': 'observe', 'capability_observation': True, 'entity_radius': 48}))
        result = self.client.wait(rid, timeout=3)
        self.assertEqual(result['status'], 'succeeded', result)
        return result['result']['state']
    def action(self, name, source, **extra):
        body = {'op': 'action', 'action': name, 'hotbar_slot': 0, 'timeout_ms': 1000,
            'capability_guard': deepcopy(source['capability_guard']),
            'expected_world_generation': source['world']['world_generation'],
            'expected_dimension': source['world']['dimension'],
            'expected_player_uuid': source['player']['uuid'],
            'expected_action_session': source['client_action']['action_session'],
            'expected_hotbar_slot': source['player']['selected_slot'],
            'expected_held_item': source['player']['inventory'][0], **extra}
        if name == 'follow_path':
            body = NativeBindingContext().bind(body, source)
        return self.client.submit(self.command(body))
    def hostile(self, kind='ender_dragon'):
        self.bridge.entities = [{'uuid': '22222222-2222-4222-8222-222222222222', 'entity_id': 42,
            'type': 'minecraft:' + kind, 'alive': True, 'health': 200, 'distance': 2,
            'x': 2.5, 'y': 64, 'z': .5,
            'bounding_box': {'min': {'x': 2, 'y': 64, 'z': 0}, 'max': {'x': 3, 'y': 67, 'z': 1}}}]
    def assert_no_legacy_attack(self):
        self.assertFalse(self.resident.combat.active)
        self.assertEqual(self.dog.defense_epoch, self.epoch)
        self.assertFalse([p for p,b in self.bridge.posts if p in ('/control/action/cancel', '/control/release-all')])
    def test_nearby_dragon_guarded_attack_and_post_sample_keep_owner(self):
        self.claim()
        self.hostile()
        source = self.read()
        rid = self.action('attack_entity', source, target_uuid=self.bridge.entities[0]['uuid'],
                          target_type='minecraft:ender_dragon', target_entity_id=42, expected_dragon_phase=6)
        result = self.client.wait(rid, timeout=3)
        self.assertEqual(result['status'], 'succeeded', result)
        self.assertEqual(self.read()['nearby']['entities'][0]['distance'], 2)
        self.assert_no_legacy_attack()
        posts = [b for p,b in self.bridge.posts if p == '/control/action']
        self.assertEqual(len(posts), 1)
        self.assertFalse(any(k.startswith('_capability') for k in posts[0]))
        self.assertEqual(self.client.release_capability(self.owner)['status'], 'succeeded')
    def test_shulker_damage_and_idle_planning_gap_do_not_preempt_guarded_path(self):
        self.claim()
        self.hostile('shulker')
        source = self.read()
        self.bridge.hold = True
        rid = self.action('follow_path', source, waypoints=[{'x': 1.5, 'y': 64, 'z': .5}])
        self.until(lambda: self.bridge.action['status'] == 'running')
        self.bridge.health = 14
        time.sleep(3.2)  # Beyond heartbeat TTL; daemon controls retain original owner.
        self.assertEqual(self.client.session()['capability_lease']['state'], 'active')
        self.assert_no_legacy_attack()
        self.bridge.hold = False
        self.assertEqual(self.client.wait(rid, timeout=3)['status'], 'succeeded')
        self.assertEqual(self.read()['player']['health'], 14)
        time.sleep(1.1)  # Between semantic sample and next skill action.
        source = self.read()
        second = self.action('select_hotbar', source)
        self.assertEqual(self.client.wait(second, timeout=3)['status'], 'succeeded')
        self.read()
        self.assert_no_legacy_attack()
    def test_original_budget_expiry_cannot_start_legacy_combat(self):
        self.claim(duration_ms=1700)
        self.hostile()
        source = self.read()
        self.bridge.hold = True
        rid = self.action('select_hotbar', source)
        self.until(lambda: self.bridge.action['status'] == 'running')
        self.until(lambda: self.dog.handoff_latched)
        self.assertEqual(self.dog.reason, 'capability_deadline_expired')
        self.assertEqual(self.dog.owner['id'], rid)
        self.assertFalse(self.resident.combat.active)
        self.assertFalse([p for p,b in self.bridge.posts if p == '/control/action/cancel'])
        self.assertEqual(len([p for p,b in self.bridge.posts if p == '/control/action']), 1)
    def test_owner_process_heartbeat_loss_pauses_without_takeover(self):
        self.claim()
        self.hostile()
        self.read()
        self.client.close_capability()
        self.until(lambda: self.dog.handoff_latched)
        self.assertEqual(self.dog.reason, 'capability_heartbeat_expired')
        self.assertFalse(self.resident.combat.active)
        self.assertFalse(self.bridge.posts)
    def test_stop_overrides_pending_owner_exactly_once(self):
        self.claim()
        self.hostile()
        self.bridge.hold = True
        rid = self.action('select_hotbar', self.read())
        self.until(lambda: self.bridge.action['status'] == 'running')
        (self.root / 'watchdog' / 'STOP').write_text('explicit offline stop')
        self.until(lambda: self.dog.stopped)
        self.assertTrue(self.dog.cancel_confirmed)
        self.assertEqual(len([p for p,b in self.bridge.posts if p == '/control/release-all']), 1)
        self.assertEqual(len([p for p,b in self.bridge.posts if p == '/control/action']), 1)
        self.assertFalse(self.resident.combat.active)
    def test_unknown_receipt_retains_owner_without_extra_cancel_or_replay(self):
        self.claim()
        self.hostile()
        self.bridge.mode = 'unknown'
        rid = self.action('select_hotbar', self.read())
        result = self.client.wait(rid, timeout=3)
        self.assertEqual(result['status'], 'uncertain')
        self.until(lambda: self.dog.handoff_latched)
        self.assertEqual(self.dog.owner['id'], rid)
        self.assertEqual(self.dog.owner['request_id'], result['queue_request_id'])
        time.sleep(.3)
        self.assertEqual(len([p for p,b in self.bridge.posts if p == '/control/action']), 1)
        # The existing Resident performs its one correlated cancellation; the
        # watchdog adds no cancel or combat takeover after the unknown receipt.
        self.assertEqual(len([p for p,b in self.bridge.posts if p == '/control/action/cancel']), 1)
        self.assertFalse(self.resident.combat.active)
    def test_wrong_owner_and_stale_epoch_are_consumed_without_queue_write(self):
        self.claim()
        base = {'op': 'observe', 'capability_observation': True}
        for update in ({'_capability_owner_id': uuid.uuid4().hex}, {'_navigation_defense_epoch': self.epoch + 1}):
            rid = self.client.submit({**self.command(base), **update})
            result = self.client.wait(rid, timeout=3)
            self.assertEqual(result['status'], 'cancelled')
            self.assertIsNone(result['queue_request_id'])
        self.assertFalse(self.bridge.posts)
    def test_release_requires_new_neutral_post_observation(self):
        self.claim()
        rid = self.action('select_hotbar', self.read())
        self.assertEqual(self.client.wait(rid, timeout=3)['status'], 'succeeded')
        release = self.client.submit({'op': 'capability_release', 'owner_id': self.owner,
                                     'expected_defense_epoch': self.epoch})
        self.assertEqual(self.client.wait(release, timeout=3)['reason'], 'capability_release_needs_fresh_idle_observation')
        self.read()
        self.assertEqual(self.client.release_capability(self.owner)['status'], 'succeeded')
    def test_expected_dimension_transition_rebinds_once_without_releasing_lease(self):
        self.claim()
        source = self.read()
        self.bridge.destination = 'minecraft:the_nether'
        rid = self.action('follow_path', source, waypoints=[{'x':1.5,'y':64,'z':.5}],
                          _capability_expected_dimension='minecraft:the_nether')
        self.assertEqual(self.client.wait(rid, timeout=3)['status'], 'succeeded')
        after = self.read()
        self.assertEqual(after['world']['dimension'], 'minecraft:the_nether')
        lease = self.client.session()['capability_lease']
        self.assertEqual(lease['context']['dimension'], 'minecraft:the_nether')
        self.assertEqual(lease['owner_id'], self.owner)
        self.assert_no_legacy_attack()
    def test_expected_transition_cancel_with_confirmed_release_allows_one_destination_read(self):
        self.claim()
        source = self.read()
        self.bridge.destination = 'minecraft:the_nether'
        self.bridge.transition_cancel = True
        rid = self.action('follow_path', source, waypoints=[{'x':1.5,'y':64,'z':.5}],
                          _capability_expected_dimension='minecraft:the_nether')
        result = self.client.wait(rid, timeout=3)
        self.assertEqual(result['status'], 'cancelled', result)
        self.assertEqual(self.read()['world']['dimension'], 'minecraft:the_nether')
        self.assertEqual(self.client.session()['capability_lease']['context']['dimension'], 'minecraft:the_nether')
        self.assert_no_legacy_attack()

    def test_unrequested_player_context_change_pauses(self):
        self.claim()
        self.bridge.other_player = True
        self.read()
        self.until(lambda: self.dog.handoff_latched)
        self.assertEqual(self.dog.reason, 'capability_observation_context_changed')
        self.assertFalse(self.bridge.posts)

    def test_second_mutation_cannot_reuse_pre_action_observation(self):
        self.claim()
        source = self.read()
        first = self.action('select_hotbar', source)
        self.assertEqual(self.client.wait(first, timeout=3)['status'], 'succeeded')
        second = self.action('select_hotbar', source)
        denied = self.client.wait(second, timeout=3)
        self.assertEqual(denied['reason'], 'capability_command_out_of_scope')
        self.assertIsNone(denied['queue_request_id'])
        self.assertEqual(len([p for p,b in self.bridge.posts if p == '/control/action']), 1)
    def policy_refusal(self, policy):
        self.claim()
        source = self.read()
        self.resident_paused.set()
        time.sleep(.02)
        session_path = self.root / 'resident' / 'session.json'
        session = json.loads(session_path.read_text())
        if policy is None:
            session.pop('resident_policy', None)
        else:
            session['resident_policy'] = policy
        base_watchdog.write_json(session_path, session)
        rid = self.action('select_hotbar', source)
        result = self.client.wait(rid, timeout=3)
        self.assertEqual(result['reason'], 'capability_resident_session_or_policy_changed')
        self.assertIsNone(result['queue_request_id'])
        self.assertFalse(self.bridge.posts)
        self.assertTrue(self.dog.handoff_latched)
    def test_missing_current_resident_policy_blocks_native_dispatch(self):
        self.policy_refusal(None)
    def test_malformed_current_resident_policy_blocks_native_dispatch(self):
        self.policy_refusal({'schema_version': True, 'requires_handoff': False, 'input_release_unconfirmed': False})
    def test_acquisition_marker_is_persisted_before_ack_and_tombstoned_on_release(self):
        receipt = self.claim()
        marker = json.loads((self.root / 'watchdog' / 'capability-owner.json').read_text())
        self.assertTrue(marker['active'])
        self.assertEqual(marker['owner_id'], self.owner)
        self.assertEqual(self.client.session()['capability_lease']['owner_id'], self.owner)
        self.read()
        self.client.release_capability(self.owner)
        marker = json.loads((self.root / 'watchdog' / 'capability-owner.json').read_text())
        self.assertFalse(marker['active'])
        self.assertIsNone(self.client.session()['capability_lease'])
    def test_restart_quarantines_durable_owner_even_after_explicit_stop(self):
        self.claim()
        self.client.close_capability()
        old = self.dog
        stop = self.root / 'watchdog' / 'STOP'
        stop.write_text('fixture operator stop')
        self.threads[1].join(timeout=3)
        self.assertTrue(old.stopped)
        self.assertTrue(old.cancel_confirmed)
        stop.unlink()
        posts = len(self.bridge.posts)
        self.threads[1] = threading.Thread(target=self.watchdog_loop, daemon=True)
        self.threads[1].start()
        self.until(lambda: self.dog is not old and self.dog.handoff_latched)
        self.assertEqual(self.dog.reason, 'previous_capability_owner_requires_reconciliation')
        time.sleep(.15)
        self.assertEqual(len(self.bridge.posts), posts)
    def test_queued_heartbeat_is_counted_separately_from_gameplay_intents(self):
        self.claim()
        # Exercise the actual publisher's count logic deterministically, without
        # relying on the daemon's scheduling against the 50ms gateway loop.
        with tempfile.TemporaryDirectory(prefix='offline-pending-counts-') as directory:
            root = Path(directory)
            (root / 'inbox').mkdir()
            base_watchdog.write_json(root / 'inbox' / 'heartbeat.json',
                {'op': 'capability_heartbeat', 'owner_id': self.owner,
                 'expected_defense_epoch': self.epoch})
            self.assertEqual(base_watchdog.pending_intent_counts(root),
                             {'pending': 0, 'pending_capability_controls': 1})
            base_watchdog.write_json(root / 'inbox' / 'action.json', {'op': 'action'})
            self.assertEqual(base_watchdog.pending_intent_counts(root),
                             {'pending': 1, 'pending_capability_controls': 1})

    def test_runtime_composition_keeps_nearby_dragon_and_damage_under_one_lease(self):
        runtime = Runtime(self.client, self.root / 'runtime', wait_timeout=3)
        try:
            runtime.observe()  # Acquire before the fixture introduces its threat.
            self.hostile()
            for name in ('attack_entity', 'select_hotbar'):
                self.bridge.health -= 2
                result = runtime.execute(name, {'op': 'action', 'action': name,
                    'hotbar_slot': 0, 'timeout_ms': 1000,
                    **({'target_uuid': self.bridge.entities[0]['uuid'], 'target_entity_id': 42,
                        'target_type': 'minecraft:ender_dragon', 'expected_dragon_phase': 6}
                       if name == 'attack_entity' else {})}, lambda before, after: after.player['health'] > 0)
                self.assertTrue(result.ok, result)
            self.assert_no_legacy_attack()
            self.assertFalse(runtime.has_unresolved_execution)
        finally:
            runtime.close()
        self.assertIsNone(self.client.session()['capability_lease'])
    def test_runtime_composition_unknown_keeps_exact_pending_action_and_does_not_release(self):
        runtime = Runtime(self.client, self.root / 'runtime', wait_timeout=3)
        try:
            runtime.observe()
            self.hostile('shulker')
            self.bridge.mode = 'unknown'
            result = runtime.execute('select', {'op': 'action', 'action': 'select_hotbar',
                'hotbar_slot': 0, 'timeout_ms': 1000}, lambda before, after: True)
            self.assertEqual(result.status, 'unknown', result)
            original = runtime.pending_request_id
            self.assertIsNotNone(original)
            self.assertEqual(self.dog.owner['id'], original)
            self.assertEqual(len([p for p,b in self.bridge.posts if p == '/control/action']), 1)
        finally:
            runtime.close()
        self.assertTrue(json.loads((self.root / 'watchdog' / 'capability-owner.json').read_text())['active'])
        self.assertTrue(self.dog.handoff_latched)


if __name__ == '__main__':
    unittest.main()

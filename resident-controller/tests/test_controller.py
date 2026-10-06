"""Focused protocol tests only. FakeBridge is not a Minecraft simulation."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from resident_controller.controller import Resident
from resident_controller.ipc import QueueClient, atomic_json
from resident_controller.tasks import basic, craft_planks
from resident_controller.transport import Bridge, BridgeError


class FakeBridge:
    base_url = 'http://127.0.0.1:12345'
    def __init__(self):
        self.calls = []
        self.action = {'ok': True, 'action_schema_version': 1, 'action_session': 'test-session', 'status': 'idle', 'action_id': None}
        self.fail_post = False
    def request(self, method, path, body=None):
        self.calls.append((method, path, copy.deepcopy(body)))
        if path == '/control/status':
            return {'protocol': 'mineclient-bridge', 'schema_version': 2, 'run_id': 'test-run',
                    'process_id': 1234, 'in_world': True, 'client_action': copy.deepcopy(self.action)}
        if path == '/control/state?radius=8':
            return {'world': {'world_generation': 'w'}, 'player': {'inventory': []}}
        if path.startswith('/control/action/status'):
            return copy.deepcopy(self.action)
        if path == '/control/action':
            self.action = {'ok': True, 'action_schema_version': 1, 'action_session': 'test-session', 'action_id': body['action_id'],
                           'action': body['action'], 'status': 'running'}
            if self.fail_post:
                raise BridgeError('transport_failed', uncertain=True)
            return copy.deepcopy(self.action)
        if path == '/control/action/cancel':
            self.action.update(status='cancelled', reason='cancel_requested')
            return copy.deepcopy(self.action)
        if method == 'POST':
            self.action.update(status='cancelled', reason='direct_takeover')
            return {'ok': True}
        if path == '/control/screen':
            return {'ok': True, 'open': False}
        raise AssertionError((method, path, body))


class ControllerChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bridge = FakeBridge()
        self.resident = Resident(self.bridge, self.tmp.name)
        self.resident.start()
        self.client = QueueClient(self.tmp.name)
    def tearDown(self):
        if self.resident.lock:
            self.resident.lock.close()
        self.tmp.cleanup()
    def test_semantic_action_has_one_post_then_status_poll(self):
        rid = self.client.submit({'op': 'action', 'action': 'break_block', 'target': {'x': 1, 'y': 64, 'z': 2}})
        self.resident.tick()
        self.resident.active.wake_at = 0
        self.resident.tick()
        self.bridge.action.update(status='succeeded', reason='block_changed', server_confirmed=False)
        self.resident.active.wake_at = 0
        self.resident.tick()
        self.resident.tick()
        posts = [x for x in self.bridge.calls if x[0] == 'POST' and x[1] == '/control/action']
        self.assertEqual(len(posts), 1)
        self.assertEqual(self.client.result(rid)['status'], 'succeeded')
        self.assertFalse(self.client.result(rid)['result']['server_confirmed'])
    def test_direct_takeover_clears_tasks_and_sends_once(self):
        first = self.client.submit({'op': 'action', 'action': 'follow_path', 'waypoints': [{'x': 1, 'y': 64, 'z': 1}]})
        self.resident.tick()
        second = self.client.submit({'op': 'action', 'action': 'break_block', 'target': {'x': 2, 'y': 64, 'z': 1}})
        direct = self.client.submit({'op': 'direct', 'endpoint': 'key', 'body': {'mapping': 'key.forward', 'action': 'down'}})
        self.resident.tick()
        self.assertEqual(self.client.result(first)['status'], 'cancelled')
        self.assertEqual(self.client.result(second)['status'], 'cancelled')
        self.assertEqual(self.client.result(direct)['status'], 'succeeded')
        writes = [x[1] for x in self.bridge.calls if x[0] == 'POST']
        self.assertEqual(writes, ['/control/action', '/control/key'])
    def test_uncertain_post_is_not_retried(self):
        self.bridge.fail_post = True
        rid = self.client.submit({'op': 'action', 'action': 'break_block', 'target': {'x': 1, 'y': 64, 'z': 2}})
        self.resident.tick()
        for _ in range(3):
            self.resident.tick()
        self.assertTrue(self.resident.paused)
        self.assertEqual(self.client.result(rid)['status'], 'uncertain')
        self.assertEqual(sum(path == '/control/action' for _, path, _ in self.bridge.calls), 1)
        self.assertNotIn('/control/close', [path for _, path, _ in self.bridge.calls])
    def test_controller_restart_does_not_replay_old_mail(self):
        rid = self.client.submit({'op': 'action', 'action': 'break_block', 'target': {}})
        self.resident.lock.close()
        new = Resident(self.bridge, self.tmp.name)
        new.start()
        self.resident = new
        self.assertEqual(self.client.result(rid)['reason'], 'previous_session_not_replayed')
        self.assertFalse(any(method == 'POST' for method, _, _ in self.bridge.calls))
    def test_repeated_request_id_reads_existing_result(self):
        rid = self.client.submit({'op': 'cancel'}, 'same-id')
        self.resident.tick()
        self.client.submit({'op': 'cancel'}, 'same-id')
        self.resident.tick()
        self.assertEqual(sum(path == '/control/release-all' for _, path, _ in self.bridge.calls), 1)
    def test_expired_result_does_not_reenable_consumed_id(self):
        rid = self.client.submit({'op': 'cancel'}, 'consumed-id')
        self.resident.tick()
        (Path(self.tmp.name) / 'results' / (rid + '.json')).unlink()
        self.client.submit({'op': 'cancel'}, rid)
        self.resident.tick()
        self.assertEqual(sum(path == '/control/release-all' for _, path, _ in self.bridge.calls), 1)
        self.assertEqual(self.client.result(rid)['reason'], 'request_id_already_consumed_result_expired')
    def test_changed_action_session_does_not_run_queue(self):
        rid = self.client.submit({'op': 'action', 'action': 'break_block', 'target': {}})
        self.bridge.action['action_session'] = 'new-jvm-session'
        self.resident.tick()
        self.assertEqual(self.client.result(rid)['status'], 'failed')
        self.assertTrue(self.resident.paused)
        self.assertFalse(any(method == 'POST' for method, _, _ in self.bridge.calls))
    def test_shutdown_does_not_execute_later_command(self):
        stop = self.client.submit({'op': 'shutdown'})
        late = self.client.submit({'op': 'direct', 'endpoint': 'key', 'body': {'mapping': 'key.forward', 'action': 'down'}})
        self.resident.tick()
        self.assertFalse(self.resident.running)
        self.assertEqual(self.client.result(late)['status'], 'cancelled')
        self.assertEqual([p for m, p, _ in self.bridge.calls if m == 'POST'], ['/control/release-all'])
    def test_owner_lock_is_singleton(self):
        with self.assertRaisesRegex(ValueError, 'already_running'):
            other = Resident(self.bridge, self.tmp.name)
            try:
                other.start()
            finally:
                if other.lock:
                    other.lock.close()
    def test_loopback_only_constructor_no_network(self):
        for url in ('https://127.0.0.1:1', 'http://example.com:1', 'http://127.0.0.1:1/x', 'http://127.0.0.1:65536'):
            with self.assertRaises(ValueError):
                Bridge(url, 'test-token')
        with patch('http.client.HTTPConnection') as connect:
            Bridge('http://127.0.0.1:38121', 'test-token')
            connect.assert_not_called()


def item(name='', count=0):
    return {'id': name, 'count': count, 'empty': count == 0}


def craft_state(source=3, carried=0, grid=0, output=0, planks=0, game_time=100):
    log, plank = 'minecraft:oak_log', 'minecraft:oak_planks'
    slots = [{'menu_index': i, 'item': item(log, grid) if i == 1 and grid else item(plank, output) if i == 0 and output else item(),
              'player_inventory': False} for i in range(5)]
    slots.append({'menu_index': 36, 'player_inventory': True, 'inventory_index': 0, 'item': item(log, source)})
    return {'world': {'game_time': game_time, 'world_generation': 'craft-test-world'},
            'menu': {'menu_class': 'net.minecraft.world.inventory.InventoryMenu', 'container_id': 0,
                     'carried': item(log, carried), 'slots': slots, 'slots_truncated': False},
            'player': {'uuid': 'craft-test-player', 'dimension': 'minecraft:overworld',
                       'inventory': [{'slot': 0, **item(log, source)}, {'slot': 1, **item(plank, planks)}]}}


class CraftChecks(unittest.TestCase):
    def final_confirmation(self):
        recipe = craft_planks({'op': 'craft_planks'})
        self.assertEqual(next(recipe)['step'], 'observe')
        clicks = []
        for state in (craft_state(), craft_state(source=0, carried=3),
                      craft_state(source=0, carried=2, grid=1, output=4),
                      craft_state(source=2, grid=1, output=4)):
            step = recipe.send(state)
            self.assertEqual(step['step'], 'action')
            clicks.append(step['body'])
            self.assertEqual(recipe.send({'status': 'succeeded'})['step'], 'observe')
        self.assertEqual(sum(c.get('click_type') == 'quick_move' for c in clicks), 1)
        return recipe

    def test_one_log_recipe_uses_actual_output_and_inventory_delta(self):
        recipe = craft_planks({'op': 'craft_planks'})
        self.assertEqual(next(recipe)['step'], 'observe')
        click = recipe.send(craft_state())
        self.assertEqual(click['body']['slot'], 36)
        self.assertEqual(recipe.send({'status': 'succeeded'})['step'], 'observe')
        click = recipe.send(craft_state(source=0, carried=3))
        self.assertEqual((click['body']['slot'], click['body']['button']), (1, 1))
        recipe.send({'status': 'succeeded'})
        click = recipe.send(craft_state(source=0, carried=2, grid=1, output=4))
        self.assertEqual(click['body']['slot'], 36)
        recipe.send({'status': 'succeeded'})
        click = recipe.send(craft_state(source=2, grid=1, output=4))
        self.assertEqual((click['body']['slot'], click['body']['click_type']), (0, 'quick_move'))
        recipe.send({'status': 'succeeded'})
        self.assertEqual(recipe.send(craft_state(source=2, planks=4, game_time=101))['step'], 'wait')
        self.assertEqual(recipe.send(None)['step'], 'observe')
        with self.assertRaises(StopIteration) as done:
            recipe.send(craft_state(source=2, planks=4, game_time=102))
        self.assertEqual(done.exception.value['planks_added'], 4)
        self.assertEqual(done.exception.value['stable_game_times'], [101, 102])
    def test_nonempty_cursor_blocks_before_click(self):
        recipe = craft_planks({'op': 'craft_planks'})
        next(recipe)
        with self.assertRaisesRegex(ValueError, 'cursor_not_empty'):
            recipe.send(craft_state(carried=1))

    def test_duplicate_ticks_do_not_count_as_later_stable_samples(self):
        recipe = self.final_confirmation()
        for tick in (100, 101, 101):
            self.assertEqual(recipe.send(craft_state(source=2, planks=4, game_time=tick))['step'], 'wait')
            self.assertEqual(recipe.send(None)['step'], 'observe')
        with self.assertRaises(StopIteration) as done:
            recipe.send(craft_state(source=2, planks=4, game_time=102))
        self.assertEqual(done.exception.value['stable_game_times'], [101, 102])

    def test_rollback_resets_stability_without_another_output_click(self):
        recipe = self.final_confirmation()
        for tick, planks in ((101, 4), (102, 0), (103, 4)):
            self.assertEqual(recipe.send(craft_state(source=2, planks=planks, game_time=tick))['step'], 'wait')
            self.assertEqual(recipe.send(None)['step'], 'observe')
        with self.assertRaises(StopIteration) as done:
            recipe.send(craft_state(source=2, planks=4, game_time=104))
        self.assertEqual(done.exception.value['stable_game_times'], [103, 104])

    def test_game_time_regression_rejects_after_output_without_replay(self):
        recipe = self.final_confirmation()
        with self.assertRaisesRegex(ValueError, 'game_time_regressed'):
            recipe.send(craft_state(source=2, planks=4, game_time=99))

    def test_missing_game_time_rejects_before_click(self):
        recipe = craft_planks({'op': 'craft_planks'})
        next(recipe)
        state = craft_state()
        state['world'].pop('game_time')
        with self.assertRaisesRegex(ValueError, 'fresh_game_time_required'):
            recipe.send(state)

    def test_nonempty_output_is_not_claimed_as_completed_craft(self):
        recipe = self.final_confirmation()
        self.assertEqual(recipe.send(craft_state(source=2, planks=4, output=4, game_time=101))['step'], 'wait')

    def test_stability_never_spans_world_or_player_change(self):
        for category, field in (('world', 'world_generation'), ('player', 'uuid'), ('player', 'dimension')):
            recipe = self.final_confirmation()
            changed = craft_state(source=2, planks=4, game_time=101)
            changed[category][field] = 'different-context'
            with self.assertRaisesRegex(ValueError, 'craft_world_or_player_changed'):
                recipe.send(changed)


class BasicEvidenceChecks(unittest.TestCase):
    def finish(self, reason):
        task = basic({'op': 'action', 'action': 'break_block', 'target': {'x': 1, 'y': 64, 'z': 1}})
        self.assertEqual(next(task)['step'], 'action')
        self.assertEqual(task.send({'status': 'succeeded', 'reason': reason})['step'], 'observe')
        with self.assertRaises(StopIteration) as done:
            task.send({'world': {'game_time': 20}, 'player': {'inventory': []}})
        return done.exception.value

    def test_block_broken_does_not_mean_drops_collected(self):
        result = self.finish('block_broken_observed')
        self.assertTrue(result['mining']['block_broken_observed'])
        self.assertFalse(result['mining']['drops_collected_confirmed'])
        self.assertIn('collection_unverified', result['reason'])
        self.assertFalse(result['evidence']['stable'])
        self.assertFalse(result['server_confirmed'])

    def test_already_absent_is_not_claimed_as_mined(self):
        result = self.finish('block_absent')
        self.assertFalse(result['mining']['block_broken_observed'])
        self.assertTrue(result['mining']['block_absent_observed'])
        self.assertFalse(result['mining']['drops_collected_confirmed'])

    def test_unrecognized_reason_does_not_invent_mining_evidence(self):
        result = self.finish('block_changed')
        self.assertFalse(any(result['mining'].values()))


if __name__ == '__main__':
    unittest.main()

"""Actual IntentClient -> Watchdog -> QueueClient -> Resident -> fake Bridge.

Only endpoint responses are synthetic. No real game, network or auth is used.
"""
from copy import deepcopy
import importlib.util
from pathlib import Path
import tempfile
import threading
import time
import unittest

import base_watchdog
from watchdog import Watchdog
from intent_client import IntentClient
from resident_controller.controller import Resident
from resident_controller.transport import BridgeError
from mdc_skills.core import Runtime
from support_core import state, NATIVE

_fixture_path = Path(__file__).resolve().parents[2] / 'resident-controller/tests/capability_fixtures.py'
_fixture_spec = importlib.util.spec_from_file_location('mdc_offline_capability_fixtures', _fixture_path)
_fixture_module = importlib.util.module_from_spec(_fixture_spec)
_fixture_spec.loader.exec_module(_fixture_module)
native_bundle = _fixture_module.native_bundle


class EndpointFixture:
    base_url = 'http://127.0.0.1:1'
    def __init__(self, mode='success', action='select_hotbar'):
        self.mode = mode
        self.requested_action = action
        self.teleported = False
        self.terrain_pages = iter(())
        self.terrain_responses = []
        self.state_paths = []
        self.posts = []
        self.tick = 200
        self.selected = 0
        self.action = {'action_schema_version': 1, 'action_session': NATIVE, 'action_id': None, 'status': 'idle'}
    def snapshot(self):
        self.tick += 1
        value = state(self.tick)
        value['world']['world_generation'] = '11111111-2222-4333-8444-555555555555'
        value['player'].update(selected_slot=self.selected, on_ground=True, food=20, air=300,
            yaw=0, pitch=0, eye_position={'x': .5, 'y': 65.62, 'z': .5},
            in_water=False, eye_in_water=False, in_lava=False, in_powder_snow=False,
            on_fire=False, frozen_ticks=0, environment_schema_version=1, velocity={'x': 0, 'y': 0, 'z': 0})
        if self.requested_action == 'gateway_pearl':
            value['world']['dimension'] = value['player']['dimension'] = 'minecraft:the_end'
            if self.teleported: value['player']['x'] = 1024.5
        value['nearby'] = {'entities': [], 'truncated': False, 'total': 0, 'returned': 0}
        value['client_action'] = deepcopy(self.action)
        return value
    def request(self, method, path, body=None):
        if method == 'POST':
            self.posts.append((path, deepcopy(body)))
        if path == '/control/status':
            return {'protocol': 'mineclient-bridge', 'schema_version': 2, 'run_id': 'fixture', 'process_id': 123,
                    'in_world': True, 'held_mappings': [], 'client_action': deepcopy(self.action)}
        if path.startswith('/control/state?'):
            self.state_paths.append(path)
            value = self.snapshot()
            value['nearby']['radius'] = int(path.split('radius=')[1].split('&')[0])
            return value
        if path.startswith('/control/capability-snapshot?'):
            self.state_paths.append(path)
            radius = int(path.split('radius=')[1].split('&')[0])
            value = self.snapshot()
            value['nearby']['radius'] = radius
            if 'movement_budget' in value:
                value['client_action']['movement_budget'] = deepcopy(value['movement_budget'])
            return native_bundle(value, radius, run_id='fixture', process_id=123)
        if path.startswith('/control/terrain?'):
            from navigation_controller.fake import FakeWorld
            from urllib.parse import parse_qs, urlsplit
            query = parse_qs(urlsplit(path).query)
            if 'radius' in query:
                world = FakeWorld(); world.generation = '11111111-2222-4333-8444-555555555555'
                pages = world.pages(radius=int(query['radius'][0]), vertical=int(query['vertical'][0]), tick=self.tick,
                                    limit=min(int(query.get('limit', ['128'])[0]), 512))
                if query.get('capability') == ['1']:
                    for page in pages:
                        page.update(capability_page_schema_version=1, page_limit=int(query['limit'][0]))
                self.terrain_pages = iter(pages)
            value = next(self.terrain_pages)
            self.terrain_responses.append(deepcopy(value))
            return value
        if path == '/control/screen': return {'ok': True, 'open': False}
        if path.startswith('/control/action/status'):
            if self.action['status'] == 'running': self.action['status'] = 'succeeded'
            return deepcopy(self.action)
        if path == '/control/action':
            if self.mode == 'reject':
                raise BridgeError('capability_source_expired', status=409, uncertain=False)
            self.selected = body['hotbar_slot']
            self.teleported = body['action'] == 'gateway_pearl'
            self.action = {'action_schema_version': 1, 'action_session': NATIVE, 'action_id': body['action_id'],
                'action': body['action'], 'status': 'running', 'reason': 'hotbar_selected',
                'result': {'input_release_confirmed': True}, 'server_confirmed': False}
            if self.mode == 'unknown': raise BridgeError('transport_failed', uncertain=True)
            return deepcopy(self.action)
        if path == '/control/action/cancel':
            self.action.update(status='cancelled', reason='cancel_requested')
            return deepcopy(self.action)
        if path == '/control/release-all':
            return {'ok': True}
        raise AssertionError((method, path, body))


class GatewayChainTests(unittest.TestCase):
    def run_chain(self, mode, action="select_hotbar", *, terrain=False, bridge=None, resident_interval=.005):
        with tempfile.TemporaryDirectory(prefix='offline-capability-chain-') as directory:
            root = Path(directory)
            bridge = bridge if bridge is not None else EndpointFixture(mode, action)
            resident = Resident(bridge, root / 'resident')
            resident.start()
            stopped, errors = threading.Event(), []
            def tick_resident():
                try:
                    while not stopped.is_set():
                        resident.tick()
                        time.sleep(resident_interval)
                except BaseException as exc: errors.append(exc)
            def tick_watchdog():
                try:
                    base_watchdog.run(root / 'resident', root / 'watchdog', watchdog_class=Watchdog)
                except BaseException as exc: errors.append(exc)
            rt = None
            threads = [threading.Thread(target=tick_resident, daemon=True), threading.Thread(target=tick_watchdog, daemon=True)]
            for thread in threads: thread.start()
            client = IntentClient(root / 'watchdog')
            try:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    self.assertFalse(errors, errors)
                    try:
                        info = client.session()
                        if info['state'] == 'ready' and info['pending'] == 0 and info.get('capability_context') is not None: break
                    except (FileNotFoundError, ValueError): pass
                    time.sleep(.01)
                else: self.fail('actual watchdog did not become ready')
                rt = Runtime(client, root / 'capability', wait_timeout=3)
                if action == 'survey':
                    survey = rt.survey(radius=3, vertical=2, entity_radius=48)
                    self.assertTrue(survey.terrain['historical_survey'])
                    self.assertEqual(len(survey.terrain['source_pages']), 1)
                    self.assertEqual(sum(page['returned'] for page in survey.terrain['source_pages']), 245)
                    self.assertEqual(len(survey.terrain['cells']), 245)
                    self.assertIsNone(resident.cache.grid)
                    self.assertFalse([p for p,b in bridge.posts if p == '/control/action'])
                    self.assertIsNone(rt._preflight_request_id)
                    return
                command = {'op':'action','action':action,'hotbar_slot':1,'timeout_ms':1000}
                if terrain: command['entity_radius'] = 48
                if action == 'gateway_pearl':
                    command.update(target={'x':3,'y':65,'z':0},expected_block_id='minecraft:end_gateway',expected_block_properties={},min_health=12)
                before = rt.observe(terrain=True, radius=4, vertical=4, entity_radius=48) if terrain else None
                if terrain:
                    self.assertEqual(len(before.terrain['cells']), 729)
                    self.assertEqual(before.state['nearby']['radius'], 48)
                result = rt.execute(action, command, lambda a,b: b.player['x'] == 1024.5 if action == 'gateway_pearl' else b.player['selected_slot'] == 1, before=before)
                if mode == 'success':
                    self.assertTrue(result.ok, result)
                    receipt = client.result(result.request_ids[0])
                    self.assertEqual(receipt['queue_session_id'], resident.session_id)
                    self.assertNotEqual(receipt['queue_request_id'], result.request_ids[0])
                    self.assertFalse(result.evidence['server_confirmed'])
                    if terrain:
                        self.assertEqual(len(result.last_observation.terrain['cells']), 729)
                        self.assertEqual(result.last_observation.state['nearby']['radius'], 48)
                        self.assertEqual(result.last_observation.player['selected_slot'], 1)
                        self.assertEqual(len(bridge.terrain_responses), 6)
                        self.assertEqual([page['returned'] for page in bridge.terrain_responses], [512, 217] * 3)
                        self.assertTrue(all(page['page_limit'] == 1024 and page['capability_page_schema_version'] == 1
                                            for page in bridge.terrain_responses))
                        self.assertEqual(bridge.state_paths.count('/control/capability-snapshot?radius=48'), 6)
                elif mode == 'reject':
                    self.assertEqual(result.status, 'blocked', result)
                    self.assertEqual(result.reason, 'capability_source_expired')
                    self.assertIsNone(rt.pending_request_id)
                else:
                    self.assertEqual(result.status, 'unknown', result)
                    again = rt.execute('select', {'op': 'action', 'action': 'select_hotbar', 'hotbar_slot': 1,
                        'timeout_ms': 1000}, lambda a, b: True)
                    self.assertFalse(again.ok)
                native_posts = [body for path, body in bridge.posts if path == '/control/action']
                self.assertEqual(len(native_posts), 1)
                self.assertEqual(native_posts[0]['action'], action)
                self.assertEqual(native_posts[0]['capability_guard']['schema_version'], 1)
                self.assertIn('expected_held_item', native_posts[0])
                self.assertNotIn('_navigation_defense_epoch', native_posts[0])
            finally:
                if rt: rt.close()
                (root / 'watchdog' / 'STOP').write_text('offline fixture teardown')
                threads[1].join(timeout=5)
                stopped.set(); threads[0].join(timeout=2)
                resident.lock.close()
            self.assertFalse(any(t.is_alive() for t in threads), 'offline adapter loop failed to stop')
            self.assertFalse(errors, errors)
            return result
    def test_gateway_pearl_uses_actual_full_adapter_chain(self): self.run_chain('success', 'gateway_pearl')
    def test_gateway_pearl_unknown_does_not_replay(self): self.run_chain('unknown', 'gateway_pearl')
    def test_historical_survey_uses_actual_full_adapter_chain(self): self.run_chain('success', 'survey')
    def test_actual_adapter_chain_success(self): self.run_chain('success')
    def test_large_terrain_preflight_and_two_postsamples_through_full_chain(self):
        self.run_chain('success', terrain=True)
    def test_actual_adapter_chain_no_effect(self): self.run_chain('reject')
    def test_actual_adapter_chain_unknown_no_repeat(self): self.run_chain('unknown')

if __name__ == '__main__': unittest.main()

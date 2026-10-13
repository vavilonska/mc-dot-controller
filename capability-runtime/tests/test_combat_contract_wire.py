"""Real Python adapter path with synthetic endpoint responses, never a live game.

MDC_COMBAT_COMMAND_CAPTURE optionally records the exact native POST bodies for
independent production Java parser tests. It does not grant execution authority.
"""
from contextlib import contextmanager
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest

import base_watchdog
from intent_client import IntentClient
from watchdog import Watchdog
from resident_controller.controller import Resident
from resident_controller.transport import BridgeError
from mdc_skills import combat_goals as goals, threats
from mdc_skills.core import Runtime, SkillError
from support_core import NATIVE
from test_combat_contract_alignment import CAPABILITIES
from test_combat_goals import mob, shield_stack
from test_gateway_integration import EndpointFixture
from test_reach_inventory_resources import stack


TARGET_UUID = '53c2bc82-f76d-4a70-81bc-8e379d2f7bb7'
PLAYER_UUID = '4a2869ac-6f33-4df4-a908-c55d00c32615'


class CombatEndpoint(EndpointFixture):
    """The native/game endpoint is the only synthetic layer in this wire test."""
    def __init__(self, kind=None, *, x=2.5, shield=False, support=True, mode='success'):
        super().__init__(mode)
        self.active = False
        self.target = mob(kind, uid=TARGET_UUID, x=x, shell_open=True) if kind else None
        self.shield_mode, self.support = shield, support
        self.position = dict(x=.5, y=64, z=.5)

    def snapshot(self):
        value = super().snapshot()
        value['player'].update(uuid=PLAYER_UUID, **self.position, effects=[], effects_truncated=False,
            offhand=shield_stack() if self.shield_mode else stack(), armor=[],
            enderman_shelter={'schema_version': 1, 'safe': True, 'roof_y': 66})
        if self.target and self.target['type'] == 'minecraft:blaze' and not self.shield_mode:
            value['player']['effects'] = [{'id': 'minecraft:fire_resistance', 'duration_ticks': 600}]
        ranged = self.target and self.target['type'] in ('minecraft:blaze', 'minecraft:creeper', 'minecraft:cave_spider')
        value['player']['inventory'][0].update(stack('minecraft:bow' if ranged else 'minecraft:iron_sword', 1))
        value['player']['inventory'][1].update(stack('minecraft:arrow', 32))
        value['player']['mainhand'] = deepcopy(value['player']['inventory'][self.selected])
        value['player']['inventory_total'] = 36
        value['player']['eye_position'] = dict(x=self.position['x'], y=65.62, z=self.position['z'])
        rows = [deepcopy(self.target)] if self.active and self.target else []
        value['nearby'].update(entities=rows, total=len(rows), returned=len(rows))
        if self.support:
            value['combat_capabilities'] = deepcopy(CAPABILITIES)
        return value

    def request(self, method, path, body=None):
        if path.startswith('/control/terrain?'):
            from navigation_controller.fake import FakeWorld
            from navigation_controller.terrain import Block
            from urllib.parse import parse_qs, urlsplit
            query = parse_qs(urlsplit(path).query)
            if 'radius' in query:
                world = FakeWorld()
                world.generation = '11111111-2222-4333-8444-555555555555'
                origin = Block(*(math.floor(self.position[key]) for key in ('x', 'y', 'z')))
                pages = world.pages(origin=origin, radius=int(query['radius'][0]),
                    vertical=int(query['vertical'][0]), tick=self.tick,
                    limit=min(int(query.get('limit', ['128'])[0]), 512))
                if query.get('capability') == ['1']:
                    for page in pages:
                        page.update(capability_page_schema_version=1, page_limit=int(query['limit'][0]))
                self.terrain_pages = iter(pages)
            value = next(self.terrain_pages)
            self.terrain_responses.append(deepcopy(value))
            return value
        if path != '/control/action':
            return super().request(method, path, body)
        self.posts.append((path, deepcopy(body)))
        if self.mode == 'unknown':
            raise BridgeError('combat_wire_transport_unknown', uncertain=True)
        action = body['action']
        result = {'input_release_confirmed': True}
        if action == 'follow_path':
            self.position.update({key: body['waypoints'][-1][key] for key in ('x', 'y', 'z')})
        elif action in ('attack_entity', 'shoot_entity', 'combat_entity'):
            target = self.target
            initial = target['health']
            target.update(alive=False, health=0)
            proof = dict(target_uuid=target['uuid'], target_entity_id=target['entity_id'],
                target_type=target['type'], target_initial_health=initial,
                target_min_observed_health=0, target_dead_observed=True, observation_tick=self.tick)
            if body.get('blaze_safety_mode') == 'shield_window':
                proof.update(shield_window=True, pre_cover_saw_charge=True, pre_cover_complete=True,
                    shield_raised=True, shield_released=True, shield_blocking_observed=True,
                    cover_ticks=20, risk_remaining=False)
            result['combat' if action == 'combat_entity' else 'target_action'] = proof
        else:
            raise AssertionError('unmodeled combat wire action: ' + action)
        self.action = dict(action_schema_version=1, action_session=NATIVE, action_id=body['action_id'],
            action=action, status='running', reason='synthetic_semantic_change',
            result=result, server_confirmed=False)
        return deepcopy(self.action)


class CombatWireTests(unittest.TestCase):
    commands = []

    @classmethod
    def tearDownClass(cls):
        destination = os.environ.get('MDC_COMBAT_COMMAND_CAPTURE')
        if destination:
            path = Path(destination)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({'commands': cls.commands}, indent=2) + '\n')

    @contextmanager
    def chain(self, endpoint):
        with tempfile.TemporaryDirectory(prefix='offline-combat-contract-wire-') as directory:
            root = Path(directory)
            resident = Resident(endpoint, root / 'resident')
            resident.start()
            stopped, errors = threading.Event(), []
            def tick_resident():
                try:
                    while not stopped.is_set():
                        resident.tick()
                        time.sleep(.005)
                except BaseException as exc:
                    errors.append(exc)
            def tick_watchdog():
                try:
                    base_watchdog.run(root / 'resident', root / 'watchdog', watchdog_class=Watchdog)
                except BaseException as exc:
                    errors.append(exc)
            threads = [threading.Thread(target=tick_resident, daemon=True),
                       threading.Thread(target=tick_watchdog, daemon=True)]
            for thread in threads:
                thread.start()
            runtime = None
            client = IntentClient(root / 'watchdog')
            try:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    self.assertFalse(errors, errors)
                    try:
                        info = client.session()
                        if info['state'] == 'ready' and info['pending'] == 0 and info.get('capability_context'):
                            break
                    except (FileNotFoundError, ValueError):
                        pass
                    time.sleep(.01)
                else:
                    self.fail('actual watchdog did not become ready')
                runtime = Runtime(client, root / 'capability', wait_timeout=3)
                # Establish exclusive capability ownership in the empty fixture;
                # the synthetic target then appears before the actual skill read.
                runtime.observe(entity_radius=48)
                endpoint.active = True
                yield runtime, client
            finally:
                endpoint.active = False
                if runtime:
                    runtime.close()
                (root / 'watchdog' / 'STOP').write_text('offline fixture teardown')
                threads[1].join(timeout=5)
                stopped.set()
                threads[0].join(timeout=2)
                resident.lock.close()
            self.assertFalse(any(thread.is_alive() for thread in threads), 'offline adapter loop failed to stop')
            self.assertFalse(errors, errors)

    def native_posts(self, endpoint):
        return [body for path, body in endpoint.posts if path == '/control/action']

    def capture(self, endpoint):
        commands = self.native_posts(endpoint)
        self.assertTrue(commands)
        for command in commands:
            self.assertEqual(command['capability_guard']['schema_version'], 1)
            self.assertEqual(set(command['capability_guard']), {'schema_version', 'source_tick', 'source_nano'})
            self.assertEqual(command['expected_player_uuid'], PLAYER_UUID)
            self.assertEqual(command['expected_action_session'], NATIVE)
            self.assertNotIn('_capability_owner_id', command)
        self.commands.extend(deepcopy(commands))
        return commands

    def test_real_wire_direct_species_reserves_and_mode_defaults(self):
        for kind, x, shield, minimum, timeout in (
                ('enderman', 2.5, False, 12, 5000), ('creeper', 13.5, False, 12, 5000),
                ('cave_spider', 9.5, False, 12, 5000), ('blaze', 13.5, False, 12, 5000),
                ('blaze', 17.5, True, 18, 20000), ('shulker', 2.5, False, 10, 5000)):
            with self.subTest(kind=kind, shield=shield):
                endpoint = CombatEndpoint(kind, x=x, shield=shield)
                with self.chain(endpoint) as (runtime, client):
                    result = threats.strike(runtime, TARGET_UUID,
                        ranged=kind in ('blaze', 'creeper', 'cave_spider'))
                    self.assertTrue(result.ok, result)
                    receipt = client.result(result.request_ids[0])
                    self.assertNotEqual(receipt['queue_request_id'], result.request_ids[0])
                    command, = self.capture(endpoint)
                    self.assertEqual(command['min_health'], minimum)
                    self.assertEqual(command['timeout_ms'], timeout)

    def test_real_wire_higher_bounded_combat_reserve(self):
        endpoint = CombatEndpoint('zombie')
        with self.chain(endpoint) as (runtime, _):
            result = threats.engage(runtime, TARGET_UUID, min_health=18)
            self.assertTrue(result.ok, result)
            command, = self.capture(endpoint)
            self.assertEqual(command['action'], 'combat_entity')
            self.assertEqual(command['min_health'], 18)

    def test_real_wire_search_and_bound_approach_routes(self):
        for target in (None, 'spider'):
            endpoint = CombatEndpoint(target, x=4.5)
            with self.chain(endpoint) as (runtime, _):
                result = goals.defeat_nearby(runtime, 'minecraft:spider', max_search_steps=1)
                if target:
                    self.assertTrue(result.ok, result)
                else:
                    self.assertEqual(result.reason, 'mob_loaded_search_budget_exhausted')
                commands = self.capture(endpoint)
                routes = [command for command in commands if command['action'] == 'follow_path']
                self.assertTrue(routes)
                expected = {'schema_version': 1}
                if target:
                    expected.update(target_uuid=TARGET_UUID, target_entity_id=7, target_type='minecraft:spider')
                self.assertTrue(all(command['encounter_route_guard'] == expected for command in routes))

    def test_real_wire_missing_feature_and_fresh_closed_shell_send_no_action(self):
        for kind, support in ((None, False), ('shulker', False), ('shulker', True), ('zombie', False)):
            endpoint = CombatEndpoint(kind, support=support)
            if support:
                endpoint.target['shell_open'] = False
            with self.chain(endpoint) as (runtime, _):
                if kind is None:
                    result = goals.defeat_nearby(runtime, 'minecraft:spider')
                    self.assertEqual(result.reason, 'native_encounter_route_guard_schema_version_required')
                else:
                    with self.assertRaises(SkillError):
                        if kind == 'zombie':
                            threats.engage(runtime, TARGET_UUID, min_health=18)
                        else:
                            threats.strike(runtime, TARGET_UUID)
                self.assertFalse(self.native_posts(endpoint))

    def test_real_wire_unknown_route_does_not_replay(self):
        endpoint = CombatEndpoint(mode='unknown')
        with self.chain(endpoint) as (runtime, _):
            result = goals.defeat_nearby(runtime, 'minecraft:spider', max_search_steps=10)
            self.assertEqual(result.status, 'unknown', result)
            self.assertEqual(len(self.native_posts(endpoint)), 1)
            self.assertIn('encounter_route_guard', self.native_posts(endpoint)[0])


if __name__ == '__main__':
    unittest.main()

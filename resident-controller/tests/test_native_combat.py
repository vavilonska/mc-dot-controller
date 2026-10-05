"""Offline fake-protocol checks. No Minecraft, socket, credentials or real IPC."""
import copy
import tempfile
import unittest
from unittest.mock import patch

from resident_controller.controller import Resident
from resident_controller.ipc import QueueClient
from resident_controller.native_combat import NativeCombat, flat_corridor_clear, sweep_near_protected
from resident_controller.transport import BridgeError
from test_entity_aim_lock import AimBridge, state as aim_state, TARGET, OTHER


def state():
    s = aim_state()
    s['player'].update(x=0.5, y=64, z=0.5, on_ground=True, selected_slot=0,
                       inventory=[{'slot': 0, 'id': 'minecraft:iron_sword', 'count': 1}],
                       offhand={'id': 'minecraft:shield', 'count': 1})
    s['player']['eye_position'] = {'x': .5, 'y': 65.62, 'z': .5}
    e = s['nearby']['entities'][0]
    e.update(type='minecraft:zombie', x=.5, y=64, z=2.5, distance=2,
             bounding_box={'min': {'x': .2, 'y': 64, 'z': 2.2},
                           'max': {'x': .8, 'y': 65.95, 'z': 2.8}})
    s['crosshair'].update(entity_id=e['entity_id'], entity_type=e['type'], distance_euclidean=1.8, location={'x':.5,'y':65.0,'z':2.2})
    return s


def cells():
    result = {}
    for x in range(-4, 5):
        for z in range(-4, 9):
            for y in (63, 64, 65):
                result[x, y, z] = {'status': 'loaded', 'known': True, 'collision_known': True,
                                  'fluid': 'minecraft:empty', 'hazards': [],
                                  'full_top_support': y == 63, 'collision_empty': y != 63}
    return result


class CombatBridge(AimBridge):
    def __init__(self):
        super().__init__()
        self.state = state()
        self.input_failure = None
        self.invalid_attack_ack = False
    def request(self, method, path, body=None):
        if method == 'POST' and path == '/control/key':
            if self.input_failure and self.input_failure[0] == body['mapping']:
                self.calls.append((method, path, copy.deepcopy(body)))
                raise self.input_failure[1]
            if body['mapping'].startswith('key.hotbar.'):
                self.state['player']['selected_slot'] = int(body['mapping'].split('.')[-1]) - 1
            if self.invalid_attack_ack and body['mapping'] == 'key.attack':
                self.calls.append((method, path, copy.deepcopy(body)))
                return {}
        return super().request(method, path, body)


class CombatChecks(unittest.TestCase):
    def setUp(self):
        self.now = 10.0
        self.clock = patch('time.monotonic', side_effect=lambda: self.now)
        self.clock.start()
        self.tmp = tempfile.TemporaryDirectory()
        self.bridge = CombatBridge()
        self.resident = Resident(self.bridge, self.tmp.name)
        self.resident.start()
        self.client = QueueClient(self.tmp.name)
    def tearDown(self):
        self.resident.lock.close()
        self.tmp.cleanup()
        self.clock.stop()
    def command(self, cmd):
        rid = self.client.submit(cmd)
        self.resident.tick()
        return self.client.result(rid)
    def start(self, **options):
        result = self.command({'op': 'combat_start', **options})
        self.assertEqual(result['status'], 'succeeded', result)
        return result
    def step(self, seconds=.1):
        self.now += seconds
        self.bridge.state['world']['game_time'] += 1
        self.resident.aim.next_update = self.resident.combat.next_update = 0
        self.resident.tick()
    def keys(self, mapping=None):
        return [b for m, p, b in self.bridge.calls if m == 'POST' and p == '/control/key'
                and (mapping is None or b['mapping'] == mapping)]
    def target(self):
        return self.bridge.state['nearby']['entities'][0]
    def far_target(self):
        e = self.target()
        e.update(z=5, distance=4.5)
        e['bounding_box']['min']['z'] = 4.7
        e['bounding_box']['max']['z'] = 5.3
        self.bridge.state['crosshair'] = {'type': 'miss'}
    def ready_terrain(self):
        self.resident.cache.state = copy.deepcopy(self.bridge.state)
        self.resident.cache.cells = cells()
        self.resident.cache.received_at = self.now
        self.resident.cache.terrain_received_at = self.now

    def test_disabled_until_explicit_start(self):
        self.step()
        self.assertFalse(self.resident.combat.active)
        self.assertEqual(self.keys(), [])
    def test_multiplayer_state_is_not_restricted_to_integrated_server(self):
        self.bridge.state['world']['multiplayer'] = True
        result = self.start()
        self.assertFalse(result['gameplay_effect_confirmed'])
        self.assertTrue(self.resident.combat.active)
    def test_start_releases_preexisting_holds_and_locks_exact_target(self):
        self.bridge.held.update(('key.attack', 'key.forward'))
        self.start()
        self.assertEqual(self.bridge.held, set())
        self.assertEqual(self.resident.aim.target_uuid, TARGET)
        self.assertEqual(self.keys('key.attack'), [])
    def test_selects_nearest_hostile_not_near_player(self):
        player = copy.deepcopy(self.target())
        player.update(uuid=OTHER, entity_id=99, type='minecraft:player', distance=.1)
        self.bridge.state['nearby']['entities'].append(player)
        self.start()
        self.assertEqual(self.resident.combat.target_uuid, TARGET)
    def test_neutral_species_players_pets_and_unknown_are_not_targets(self):
        for entity_type in ('minecraft:player', 'minecraft:wolf', 'minecraft:cat', 'minecraft:spider',
                            'minecraft:enderman', 'minecraft:piglin', 'minecraft:iron_golem', 'custom:monster'):
            with self.subTest(entity_type=entity_type):
                self.target()['type'] = entity_type
                before = len(self.bridge.calls)
                result = self.command({'op': 'combat_start', 'target_uuid': TARGET})
                self.assertEqual(result['reason'], 'combat_target_not_observed_hostile')
                self.assertFalse(any(m == 'POST' for m, _, _ in self.bridge.calls[before:]))
    def test_missing_candidate_mod_rejected_before_inputs(self):
        del self.bridge.state['aim_view_guard_schema_version']
        result = self.command({'op': 'combat_start'})
        self.assertEqual(result['reason'], 'aim_view_guard_mod_required')
        self.assertFalse(any(m == 'POST' for m, _, _ in self.bridge.calls))
    def test_duplicate_start_does_not_stop_running_session(self):
        first = self.start()
        second = self.command({'op': 'combat_start'})
        self.assertEqual(second['reason'], 'combat_already_active_stop_first')
        self.assertTrue(self.resident.combat.active)
        self.assertEqual(self.resident.combat.request_id, first['request_id'])
    def test_no_attack_without_new_world_tick(self):
        self.start()
        self.now += 1
        self.resident.combat.next_update = 0
        self.resident.tick()
        self.assertEqual(self.keys('key.attack'), [])
    def test_sword_cadence_and_shield_lower_before_next_attack(self):
        self.start()
        self.step()
        self.assertEqual(len(self.keys('key.attack')), 1)
        self.step()
        self.assertIn('key.use', self.bridge.held)
        self.step(.6)
        self.assertEqual(self.resident.combat.phase, 'lowering_shield')
        self.assertEqual(len(self.keys('key.attack')), 1)
        self.step()
        self.assertEqual(len(self.keys('key.attack')), 2)
        self.assertNotIn('key.use', self.bridge.held)
        self.assertTrue(all(k['action'] == 'click' for k in self.keys('key.attack')))
    def test_axe_uses_slower_pacing(self):
        self.bridge.state['player']['inventory'][0]['id'] = 'minecraft:iron_axe'
        self.start(shield=False)
        self.step()
        self.step(.8)
        self.assertEqual(len(self.keys('key.attack')), 1)
        self.step(.6)
        self.assertEqual(len(self.keys('key.attack')), 2)
    def test_attack_counts_are_not_hits_or_kills(self):
        self.start(shield=False)
        self.step()
        s = self.resident.combat.status()
        self.assertEqual(s['attack_attempts'], 1)
        self.assertEqual(s['attack_dispatches'], 1)
        self.assertEqual(s['observed_target_health'], 10)
        self.assertIsNone(s['hits_confirmed'])
        self.assertIsNone(s['kills_confirmed'])
        self.assertFalse(s['server_confirmed'])
    def test_never_clicks_attack_for_wrong_or_missing_crosshair(self):
        self.start(shield=False)
        for crosshair in ({'type': 'miss'}, {'type': 'block'},
                          {'type': 'entity', 'uuid': OTHER, 'entity_id': 9, 'entity_type': 'minecraft:player', 'distance_euclidean': 2},
                          {'type': 'entity', 'uuid': TARGET, 'entity_id': 4, 'entity_type': 'minecraft:zombie'},
                          {'type': 'entity', 'uuid': TARGET, 'entity_id': 4, 'entity_type': 'minecraft:zombie', 'distance_euclidean': 4}):
            self.bridge.state['crosshair'] = crosshair
            self.step(1)
        self.assertTrue(self.resident.combat.active)
        self.assertEqual(self.keys('key.attack'), [])
    def test_sword_near_player_switches_to_observed_axe_before_attacking(self):
        protected = copy.deepcopy(self.target())
        protected.update(uuid=OTHER, entity_id=6, type='minecraft:player')
        self.bridge.state['nearby']['entities'].append(protected)
        self.bridge.state['player']['inventory'].append({'slot': 2, 'id': 'minecraft:iron_axe', 'count': 1})
        self.start(shield=False)
        self.step()
        self.assertEqual(self.keys()[-1]['mapping'], 'key.hotbar.3')
        self.assertEqual(self.keys('key.attack'), [])
        self.step()
        self.assertEqual(len(self.keys('key.attack')), 1)
    def test_sword_near_pet_without_axe_stops_without_attack(self):
        pet = copy.deepcopy(self.target())
        pet.update(uuid=OTHER, entity_id=6, type='minecraft:wolf')
        self.bridge.state['nearby']['entities'].append(pet)
        self.start()
        self.step()
        self.assertFalse(self.resident.combat.active)
        self.assertEqual(self.resident.combat.reason, 'combat_sweep_near_protected_entity')
        self.assertEqual(self.keys('key.attack'), [])
    def test_selected_hotbar_weapon_is_verified_in_new_state(self):
        self.bridge.state['player']['selected_slot'] = 5
        self.start(shield=False)
        self.step()
        self.assertEqual(self.keys()[0]['mapping'], 'key.hotbar.1')
        self.assertEqual(self.keys('key.attack'), [])
        self.step()
        self.assertEqual(len(self.keys('key.attack')), 1)
    def test_direct_key_takes_over_once_and_remains_down(self):
        self.far_target()
        self.start()
        self.ready_terrain()
        self.step()
        self.assertIn('key.forward', self.bridge.held)
        result = self.command({'op': 'direct', 'endpoint': 'key',
                               'body': {'mapping': 'key.forward', 'action': 'down'}})
        self.assertEqual(result['status'], 'succeeded')
        self.assertFalse(self.resident.combat.active)
        self.assertFalse(self.resident.aim.active)
        self.assertEqual([k['action'] for k in self.keys('key.forward')], ['down', 'up', 'down'])
        self.assertEqual(self.bridge.held, {'key.forward'})
        self.step()
        self.assertEqual(self.bridge.held, {'key.forward'})
    def test_manual_view_stops_and_releases_owned_shield(self):
        self.start()
        self.step()
        self.step()
        self.bridge.state['player']['yaw'] += 3
        self.step()
        self.assertFalse(self.resident.combat.active)
        self.assertEqual(self.bridge.held, set())
        self.assertIn('manual_view_changed', self.resident.combat.reason)
    def test_target_lost_does_not_retarget_or_claim_kill(self):
        self.start()
        self.target()['uuid'] = OTHER
        self.step()
        self.assertFalse(self.resident.combat.active)
        self.assertEqual(self.resident.combat.target_uuid, TARGET)
        self.assertIsNone(self.resident.combat.status()['kills_confirmed'])
        self.assertEqual(self.keys('key.attack'), [])
    def test_target_death_stops(self):
        self.start()
        self.target().update(alive=False, health=0)
        self.step()
        self.assertFalse(self.resident.combat.active)
        self.assertIn('target_dead', self.resident.combat.reason)
    def test_explicit_stop_releases_combat_only_not_future_direct_control(self):
        self.start()
        self.step()
        self.step()
        result = self.command({'op': 'combat_stop'})
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(self.bridge.held, set())
        self.command({'op': 'aim_lock', 'target_uuid': TARGET})
        self.command({'op': 'combat_stop'})
        self.assertTrue(self.resident.aim.active)  # Standalone aim stays independent.
    def test_flat_approach_holds_forward_then_stops_at_reach(self):
        self.far_target()
        self.start()
        self.ready_terrain()
        self.step()
        self.assertEqual(self.bridge.held, {'key.forward', 'key.use'})
        self.target()['bounding_box'] = state()['nearby']['entities'][0]['bounding_box']
        self.target().update(z=2.5, distance=2)
        self.bridge.state['crosshair'] = state()['crosshair']
        self.step()
        self.assertNotIn('key.forward', self.bridge.held)
        self.assertEqual(self.resident.combat.phase, 'lowering_shield')
    def test_terrain_refresh_releases_forward_before_blocking_read(self):
        self.far_target()
        self.start()
        self.ready_terrain()
        self.step()
        def scan(*args, **kwargs):
            self.assertNotIn('key.forward', self.bridge.held)
            self.ready_terrain()
        with patch.object(self.resident.cache, 'scan', side_effect=scan) as mocked:
            self.step(.3)
            mocked.assert_called_once()
        self.assertEqual(self.resident.combat.phase, 'refreshing_approach')
    def test_no_approach_option_does_not_scan_or_move(self):
        self.far_target()
        self.start(approach=False)
        with patch.object(self.resident.cache, 'scan') as mocked:
            self.step()
            mocked.assert_not_called()
        self.assertNotIn('key.forward', self.bridge.held)
        self.assertIn('key.use', self.bridge.held)
    def test_drop_or_unknown_corridor_stops_instead_of_walking(self):
        self.far_target()
        self.start()
        self.ready_terrain()
        del self.resident.cache.cells[0, 63, 1]
        self.step()
        self.assertEqual(self.resident.combat.reason, 'combat_flat_approach_blocked')
        self.assertEqual(self.bridge.held, set())
    def test_uncertain_attack_is_never_replayed(self):
        self.start()
        self.bridge.input_failure = ('key.attack', BridgeError('transport_failed', uncertain=True))
        self.step()
        self.step(2)
        self.assertEqual(len(self.keys('key.attack')), 1)
        self.assertEqual(self.resident.combat.attack_attempts, 1)
        self.assertEqual(self.resident.combat.attack_dispatches, 0)
        self.assertTrue(self.resident.paused)
    def test_invalid_attack_response_is_uncertain(self):
        self.start()
        self.bridge.invalid_attack_ack = True
        self.step()
        self.assertTrue(self.resident.paused)
        self.assertEqual(self.resident.combat.reason, 'combat_input_response_invalid')
    def test_screen_world_player_pause_stop_before_attack(self):
        for key, value in (('screen_open', True), ('paused', True)):
            with self.subTest(key=key):
                self.bridge.state = state()
                self.start()
                self.bridge.state[key] = value
                self.step()
                self.assertFalse(self.resident.combat.active)
        self.assertEqual(self.keys('key.attack'), [])
    def test_observation_and_session_expose_combat_status(self):
        self.start()
        result = self.command({'op': 'observe'})
        self.assertTrue(result['result']['combat']['active'])
        self.assertEqual(self.client.session()['combat']['target_uuid'], TARGET)
    def test_bridge_session_change_does_not_release_into_new_client(self):
        self.far_target()
        self.start()
        self.ready_terrain()
        self.step()
        before = len(self.keys())
        self.bridge.state['client_action']['action_session'] = 'new-session'
        self.step()
        self.assertFalse(self.resident.combat.active)
        self.assertEqual(len(self.keys()), before)
        self.assertFalse(self.resident.combat.release_confirmed)
    def test_stop_read_failure_never_resumes_combat(self):
        self.start()
        original = self.bridge.request
        def request(method, path, body=None):
            if path == '/control/status':
                raise BridgeError('transport_failed')
            return original(method, path, body)
        with patch.object(self.bridge, 'request', side_effect=request):
            result = self.command({'op': 'combat_stop'})
        self.assertEqual(result['status'], 'failed')
        self.step()
        self.assertFalse(self.resident.combat.active)
        self.assertEqual(self.keys('key.attack'), [])
    def test_successful_cancel_forgets_failed_owned_key_releases(self):
        self.start()
        self.step()
        self.step()
        self.bridge.input_failure = ('key.use', BridgeError('transport_failed', uncertain=True))
        result = self.command({'op': 'cancel'})
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(self.resident.combat.held, set())
        self.bridge.input_failure = None
        self.start()
    def test_direct_takeover_resolves_failed_cleanup_before_owner_down(self):
        self.far_target()
        self.start()
        self.ready_terrain()
        self.step()
        original = self.bridge.request
        def request(method, path, body=None):
            if path == '/control/key' and body['action'] == 'up':
                raise BridgeError('transport_failed', uncertain=True)
            return original(method, path, body)
        with patch.object(self.bridge, 'request', side_effect=request):
            result = self.command({'op': 'direct', 'endpoint': 'key',
                                   'body': {'mapping': 'key.forward', 'action': 'down'}})
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(self.resident.combat.held, set())
        self.assertEqual(self.bridge.held, {'key.forward'})
        self.command({'op': 'observe'})
        self.assertEqual(self.bridge.held, {'key.forward'})
    def test_state_only_observe_does_not_refresh_terrain_timestamp(self):
        self.ready_terrain()
        old = self.resident.cache.terrain_received_at
        self.now += 100
        self.resident.cache.observe(self.bridge)
        self.assertEqual(self.resident.cache.received_at, self.now)
        self.assertEqual(self.resident.cache.terrain_received_at, old)
    def test_small_target_radius_still_reads_full_sweep_neighborhood(self):
        self.target()['distance'] = 1
        self.start(radius=1)
        self.assertEqual(self.resident.combat.target_radius, 1)
        self.assertEqual(self.resident.combat.radius, 5)
        self.assertTrue(any(p == '/control/state?radius=5' for _, p, _ in self.bridge.calls))
    def test_small_target_radius_does_not_select_outside_requested_distance(self):
        result = self.command({'op': 'combat_start', 'radius': 1})
        self.assertEqual(result['reason'], 'combat_no_observed_hostile')
    def test_slow_forward_release_does_not_attack_from_old_crosshair(self):
        self.start(shield=False)
        self.resident.combat.held.add('key.forward')
        original = self.bridge.request
        def request(method, path, body=None):
            if path == '/control/key' and body == {'mapping': 'key.forward', 'action': 'up'}:
                self.now += 1
            return original(method, path, body)
        with patch.object(self.bridge, 'request', side_effect=request):
            self.step()
        self.assertEqual(self.resident.combat.reason, 'stale_combat_observation')
        self.assertEqual(self.keys('key.attack'), [])
    def test_external_semantic_action_is_not_cancelled_by_old_combat_cleanup(self):
        self.start()
        self.step()
        self.step()
        before = len(self.keys())
        self.bridge.state['client_action']['status'] = 'running'
        self.step()
        self.assertFalse(self.resident.combat.active)
        self.assertEqual(self.resident.combat.held, set())
        self.assertEqual(len(self.keys()), before)
    def test_mouse_bound_shield_releases_across_menu_via_real_mouse_route(self):
        self.start()
        original = self.bridge.request
        def request(method, path, body=None):
            if path == '/control/key' and body['mapping'] == 'key.use':
                if self.bridge.state['screen_open']:
                    raise BridgeError('mouse_mapping_requires_no_screen', status=409)
                result = original(method, path, body)
                return {**result, 'key_type': 'mouse', 'button': 1}
            if path == '/control/mouse' and body == {'button': 1, 'action': 'up'}:
                self.bridge.held.discard('key.use')
            return original(method, path, body)
        with patch.object(self.bridge, 'request', side_effect=request):
            self.step()
            self.step()
            self.bridge.state['screen_open'] = True
            self.step()
        self.assertEqual(self.bridge.held, set())
        self.assertEqual(self.resident.combat.held, set())
        self.assertTrue(any(p == '/control/mouse' for _, p, _ in self.bridge.calls))
    def test_unconfirmed_cleanup_after_menu_pauses_and_reports(self):
        self.start()
        self.step()
        self.step()
        self.bridge.state['screen_open'] = True
        self.bridge.input_failure = ('key.use', BridgeError('mouse_mapping_requires_no_screen', status=409))
        self.step()
        self.assertFalse(self.resident.combat.active)
        self.assertTrue(self.resident.paused)
        self.assertFalse(self.resident.combat.status()['input_release_confirmed'])
    def test_shield_does_not_right_click_blocks_or_other_entities(self):
        self.start()
        self.step()
        for crosshair in ({'type': 'block', 'id': 'minecraft:chest'},
                          {'type': 'entity', 'uuid': OTHER, 'entity_type': 'minecraft:villager'}):
            self.bridge.state['crosshair'] = crosshair
            self.step(.1)
            self.assertNotIn('key.use', self.bridge.held)
        self.assertEqual(self.keys('key.use'), [])
    def test_final_cleanup_verifies_identity_before_old_key_releases(self):
        self.start()
        self.resident.combat.held.add('key.use')
        self.resident.combat.release_confirmed = False
        self.bridge.action['action_session'] = 'replacement-session'
        before = len(self.keys())
        with patch.object(self.resident, 'start'), patch.object(self.resident, 'tick', side_effect=KeyboardInterrupt):
            self.resident.serve()
        self.assertEqual(len(self.keys()), before)
        self.assertFalse(self.resident.combat.release_confirmed)
    def test_immediate_stop_after_external_action_does_not_cancel_new_owner(self):
        self.start()
        self.step()
        self.step()
        self.bridge.action.update(status='running', action_id='external-new-action')
        before = len(self.keys())
        result = self.command({'op': 'combat_stop'})
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(self.bridge.action['status'], 'running')
        self.assertEqual(len(self.keys()), before)
        self.assertEqual(self.resident.combat.held, set())
    def test_unexpected_exit_cleanup_does_not_cancel_external_action(self):
        self.start()
        self.resident.combat.held.add('key.use')
        self.bridge.action.update(status='running', action_id='external-new-action')
        before = len(self.keys())
        with patch.object(self.resident, 'start'), patch.object(self.resident, 'tick', side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                self.resident.serve()
        self.assertEqual(len(self.keys()), before)
        self.assertEqual(self.bridge.action['status'], 'running')
    def test_semantic_task_preempts_combat_before_dispatch(self):
        self.start()
        self.step()
        self.step()
        result = self.command({'op': 'action', 'action': 'break_block', 'target': {'x': 2, 'y': 64, 'z': 2}})
        self.assertIsNone(result)  # Semantic action remains running in fake bridge.
        self.assertFalse(self.resident.combat.active)
        self.assertEqual(self.bridge.held, set())
        self.assertIsNotNone(self.resident.active)


class CorridorChecks(unittest.TestCase):
    def test_any_observed_full_solid_support_not_old_block_allowlist(self):
        s, terrain = state(), cells()
        for c in terrain.values():
            c['id'] = 'minecraft:packed_mud'
        self.assertTrue(flat_corridor_clear(s, s['nearby']['entities'][0], terrain))
    def test_fluid_collision_and_hazard_block_corridor(self):
        s = state()
        for key, value in (('fluid', 'minecraft:water'), ('hazards', ['fire']), ('collision_empty', False)):
            terrain = cells()
            terrain[0, 64, 1][key] = value
            self.assertFalse(flat_corridor_clear(s, s['nearby']['entities'][0], terrain))
    def test_truncated_entity_list_is_not_safe_for_sword_sweep(self):
        s = state()
        s['nearby']['truncated'] = True
        self.assertTrue(sweep_near_protected(s, s['nearby']['entities'][0]))


if __name__ == '__main__':
    unittest.main()

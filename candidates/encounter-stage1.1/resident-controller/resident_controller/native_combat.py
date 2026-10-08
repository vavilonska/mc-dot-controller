"""Small external melee loop using the existing real-client input and aim contracts.

No socket, game process or credential access happens at import/construction. The
resident owns transport, queue arbitration and the exact-entity view lock.
"""
from __future__ import annotations

import math
import time

from .entity_aim_lock import canonical_uuid, number, MAX_SAMPLE_SECONDS
from .transport import BridgeError

# Intentionally omit players, villagers, pets and conditionally neutral species
# (including spiders, endermen, piglins, wolves, bees and iron golems).
HOSTILES = frozenset('minecraft:' + name for name in (
    'zombie', 'husk', 'drowned', 'zombie_villager', 'skeleton', 'stray', 'bogged',
    'wither_skeleton', 'creeper', 'slime', 'magma_cube', 'silverfish', 'endermite',
    'witch', 'pillager', 'vindicator', 'evoker', 'vex', 'ravager', 'phantom',
    'blaze', 'ghast', 'guardian', 'elder_guardian', 'shulker', 'hoglin', 'zoglin',
    'piglin_brute', 'wither', 'ender_dragon', 'warden',
))
MATERIALS = ('wooden', 'stone', 'iron', 'golden', 'diamond', 'netherite')
SWORDS = frozenset(f'minecraft:{m}_sword' for m in MATERIALS)
AXES = frozenset(f'minecraft:{m}_axe' for m in MATERIALS)
WEAPONS = SWORDS | AXES
INTERVAL = 0.1
MELEE_REACH = 3.0  # Upper bound for ordinary vanilla survival reach, not a hit claim.
TERRAIN_AGE = 0.25


def living_hostile(entity):
    return (entity.get('type') in HOSTILES and entity.get('alive') is True
            and ('health' not in entity or number(entity['health']) > 0))


def hotbar_weapons(state):
    return {item['slot']: item['id'] for item in state['player']['inventory']
            if type(item.get('slot')) is int and 0 <= item['slot'] <= 8
            and item.get('id') in WEAPONS and item.get('count', 0) > 0}


def box_distance(eye, entity):
    box = entity['bounding_box']
    result = 0.0
    for axis in ('x', 'y', 'z'):
        low, high = number(box['min'][axis]), number(box['max'][axis])
        if low > high:
            raise ValueError('invalid_entity_bounding_box')
        p = number(eye[axis])
        result += max(low - p, 0, p - high) ** 2
    return math.sqrt(result)


def crosshair_target_in_reach(state, target_uuid, entity_id, entity_type):
    """Minecraft 1.21.1 entity picking measures from the eye, not player feet."""
    hit = state.get('crosshair', {})
    if (hit.get('type') != 'entity' or hit.get('uuid') != target_uuid
            or hit.get('entity_id') != entity_id or hit.get('entity_type') != entity_type):
        return False
    try:
        eye, point = state['player']['eye_position'], hit['location']
        distance = math.sqrt(sum((number(eye[k]) - number(point[k])) ** 2 for k in ('x', 'y', 'z')))
    except (KeyError, TypeError, ValueError):
        return False
    try:
        reach = (min(MELEE_REACH, number(state['player']['entity_interaction_range']))
                 if state.get('combat_observation_schema_version') == 1 else MELEE_REACH)
    except (KeyError, TypeError, ValueError):
        return False
    return 0 < reach and distance <= reach


def sweep_near_protected(state, target):
    """Observed sword-sweep overlap precaution, not an atomic protection guarantee."""
    if state['nearby'].get('truncated') is not False:
        return True
    box = target['bounding_box']
    for other in state['nearby']['entities']:
        if other.get('uuid') == target['uuid'] or other.get('alive') is not True or living_hostile(other):
            continue
        other_box = other.get('bounding_box')
        if not other_box:
            return True
        if all(number(other_box['max'][k]) >= number(box['min'][k]) - pad
               and number(other_box['min'][k]) <= number(box['max'][k]) + pad
               for k, pad in (('x', 1.0), ('y', 0.25), ('z', 1.0))):
            return True
    return False


def flat_corridor_clear(state, target, cells):
    """Check the next 1.6 blocks of actual flat collision/support, not block names.

    This is close-range forward approach only, not a pathfinder, jump planner,
    terrain simulator, or guarantee against changing terrain/knockback.
    """
    p = state['player']
    if p.get('on_ground') is not True:
        return False
    x, y, z = (number(p[k]) for k in ('x', 'y', 'z'))
    if abs(y - round(y)) > 0.05:
        return False
    dx, dz = number(target['x']) - x, number(target['z']) - z
    distance = math.hypot(dx, dz)
    if distance < 0.01:
        return False
    travel = min(distance, 1.6)
    end_x, end_z = x + dx / distance * travel, z + dz / distance * travel
    # Cover the full swept rectangle. Point samples can miss a corner column
    # between simultaneous X/Z grid crossings, including an unknown/lava cell.
    for cell_x in range(math.floor(min(x, end_x) - .31), math.floor(max(x, end_x) + .31) + 1):
        for cell_z in range(math.floor(min(z, end_z) - .31), math.floor(max(z, end_z) + .31) + 1):
            for offset in (-1, 0, 1):
                cell = cells.get((cell_x, round(y) + offset, cell_z))
                if (not cell or cell.get('status') != 'loaded' or cell.get('known') is not True
                        or cell.get('collision_known') is not True
                        or cell.get('fluid') != 'minecraft:empty' or cell.get('hazards') != []):
                    return False
                if offset == -1:
                    if cell.get('full_top_support') is not True:
                        return False
                elif cell.get('collision_empty') is not True:
                    return False
    return True


class NativeCombat:
    """One hostile target per start. All writes go through the resident's bridge."""
    def __init__(self):
        self.active = False
        self.reason = 'not_started'
        self.phase = 'idle'
        self.target_uuid = None
        self.target_id = None
        self.target_type = None
        self.request_id = None
        self.held = set()
        self.releases = {}
        self.radius = 12
        self.target_radius = 12
        self.approach = True
        self.shield = True
        self.next_update = 0.0
        self.next_attack = 0.0
        self.attack_attempts = 0
        self.attack_dispatches = 0
        self.last_tick = -1
        self.shield_released_tick = None
        self.weapon_selected_tick = None
        self.requested_slot = None
        self.initial_target_health = None
        self.observed_target_health = None
        self.release_confirmed = True
        self.cadence_source = 'fixed_weapon_pacing_not_observed_cooldown'
        self.blocking_observed = None

    def status(self):
        return {'schema_version': 1, 'melee_closing_schema_version': 2,
                'active': self.active, 'phase': self.phase,
                'request_id': self.request_id,
                'target_radius': self.target_radius, 'observation_radius': self.radius,
                'reason': self.reason, 'target_uuid': self.target_uuid,
                'target_entity_id': self.target_id, 'target_type': self.target_type,
                'attack_attempts': self.attack_attempts, 'attack_dispatches': self.attack_dispatches,
                'initial_target_health': self.initial_target_health,
                'observed_target_health': self.observed_target_health,
                'held_mappings': sorted(self.held), 'input_release_confirmed': self.release_confirmed,
                'cadence_source': self.cadence_source, 'blocking_observed': self.blocking_observed,
                'server_confirmed': False, 'hits_confirmed': None, 'kills_confirmed': None}

    def prepare(self, command, state):
        """Validate a start without writes or replacing an existing session."""
        radius = command.get('radius', 12)
        if type(radius) is not int or not 1 <= radius <= 32:
            raise ValueError('combat_radius_1_to_32')
        approach, shield = command.get('approach', True), command.get('shield', True)
        if type(approach) is not bool or type(shield) is not bool:
            raise ValueError('combat_options_must_be_boolean')
        requested = command.get('target_uuid')
        if requested is not None:
            requested = canonical_uuid(requested)
        entities = [e for e in state['nearby']['entities']
                    if living_hostile(e) and number(e['distance']) <= radius]
        if requested:
            entity = next((e for e in entities if e.get('uuid') == requested), None)
            if entity is None:
                raise ValueError('combat_target_not_observed_hostile')
        else:
            entity = min(entities, key=lambda e: number(e['distance']), default=None)
            if entity is None:
                raise ValueError('combat_no_observed_hostile')
        if not hotbar_weapons(state):
            raise ValueError('combat_requires_sword_or_axe_in_hotbar')
        candidate = NativeCombat()
        candidate.request_id = command.get('request_id')
        candidate.target_uuid = canonical_uuid(entity['uuid'])
        candidate.target_id = entity['entity_id']
        candidate.target_type = entity['type']
        candidate.radius, candidate.target_radius = max(5, radius), radius
        candidate.approach, candidate.shield = approach, shield
        candidate.initial_target_health = candidate.observed_target_health = entity.get('health')
        candidate.active, candidate.reason, candidate.phase = True, 'tracking_hostile', 'acquiring'
        candidate.last_tick = state['world']['game_time']
        return candidate

    def key(self, resident, mapping, action):
        if action == 'down':
            self.held.add(mapping)  # Include possibly delivered writes in cleanup.
            self.release_confirmed = False
        path, body = '/control/key', {'mapping': mapping, 'action': action}
        if action == 'up' and mapping in self.releases:
            path, body = self.releases[mapping]
        result = resident.bridge.request('POST', path, body)
        if result.get('ok') is not True:
            raise BridgeError('combat_input_response_invalid', uncertain=True)
        if action == 'down' and result.get('key_type') == 'mouse' and type(result.get('button')) is int:
            # A mouse-bound /key up is rejected after a menu opens. The existing
            # /mouse up contract releases that held world button across menus.
            self.releases[mapping] = ('/control/mouse', {'button': result['button'], 'action': 'up'})
        if action == 'up':
            self.held.discard(mapping)
            self.releases.pop(mapping, None)
            self.release_confirmed = not self.held
        return result

    def set_key(self, resident, mapping, down):
        if down != (mapping in self.held):
            self.key(resident, mapping, 'down' if down else 'up')

    def confirm_released(self):
        """Reconcile a successful explicit global release, including old failures."""
        self.held.clear()
        self.releases.clear()
        self.release_confirmed = True

    def stop(self, resident, reason, *, release=True):
        was_active = self.active
        self.active, self.reason, self.phase = False, reason, 'stopped'
        if was_active and resident.aim.target_uuid == self.target_uuid:
            resident.aim.release(reason)
        if release:
            for key in tuple(sorted(self.held)):
                try:
                    self.key(resident, key, 'up')
                except BridgeError:
                    self.release_confirmed = False
        return self.status()

    def target(self, state):
        entity = next((e for e in state['nearby']['entities'] if e.get('uuid') == self.target_uuid), None)
        if entity is None:
            raise ValueError('combat_target_lost')
        if entity.get('entity_id') != self.target_id or entity.get('type') != self.target_type:
            raise ValueError('combat_target_identity_changed')
        if not living_hostile(entity):
            raise ValueError('combat_target_no_longer_alive_hostile')
        self.observed_target_health = entity.get('health')
        return entity

    def advance(self, resident):
        if not self.active or time.monotonic() < self.next_update:
            return
        if resident.paused or resident.active or resident.pending:
            self.stop(resident, 'combat_controller_or_task_interrupted')
            return
        if not resident.aim.active or resident.aim.target_uuid != self.target_uuid:
            if resident.aim.reason == 'action_owns_view':
                # ClientActions.start already cleared old holds before owning
                # new inputs. A key up here would cancel that newer action.
                self.confirm_released()
            self.stop(resident, 'combat_aim_released_' + str(resident.aim.reason),
                      release=resident.aim.reason != 'bridge_session_changed')
            return
        self.next_update = time.monotonic() + INTERVAL
        started = time.monotonic()
        state = resident.bridge.request('GET', f'/control/state?radius={self.radius}')
        # Reuse the same exact identity/life/menu/manual-view validation as the
        # aim loop, without dispatching a second view update.
        resident.aim.prepare(state, resident.bridge_identity['action_session'])
        if time.monotonic() - started > MAX_SAMPLE_SECONDS:
            raise ValueError('stale_combat_observation')
        # Decide from the current ray, then update view from this same sample.
        # The next tick observes the new ray. Applying look first and reusing
        # the pre-look crosshair would falsely claim a current hit target.
        self.decide(resident, state, started)
        if (self.active and resident.aim.active and time.monotonic() >= resident.aim.next_update
                and time.monotonic() - started <= MAX_SAMPLE_SECONDS):
            resident.apply_aim(state, started)

    def decide(self, resident, state, started):
        tick = state['world']['game_time']
        if tick <= self.last_tick:
            return
        self.last_tick = tick
        target = self.target(state)
        observed_combat = state.get('combat_observation_schema_version') == 1
        if observed_combat:
            strength = number(state['player']['attack_strength'])
            if not 0 <= strength <= 1 or type(state['player']['using_item']) is not bool:
                raise ValueError('invalid_combat_cooldown_observation')
            self.cadence_source = 'observed_client_attack_strength'
            self.blocking_observed = state['player'].get('blocking') is True
        weapons = hotbar_weapons(state)
        slot = state['player']['selected_slot']
        weapon = weapons.get(slot)
        sweep_risk = sweep_near_protected(state, target)
        # Prefer the user's selected weapon. If a sword might sweep a protected
        # entity, use an observed hotbar axe rather than attacking through them.
        choices = {s: w for s, w in weapons.items() if not (sweep_risk and w in SWORDS)}
        if weapon not in WEAPONS or (weapon in SWORDS and sweep_risk):
            self.set_key(resident, 'key.forward', False)
            self.set_key(resident, 'key.use', False)
            if not choices:
                raise ValueError('combat_sweep_near_protected_entity' if weapons else 'combat_weapon_unavailable')
            desired = min(choices)
            if self.requested_slot == desired:
                self.phase = 'waiting_weapon_selection'
                return
            self.key(resident, 'key.hotbar.' + str(desired + 1), 'click')
            self.requested_slot, self.weapon_selected_tick = desired, tick
            self.phase = 'selecting_weapon'
            return
        self.requested_slot = None
        if self.weapon_selected_tick is not None and tick <= self.weapon_selected_tick:
            return
        distance = box_distance(state['player']['eye_position'], target)
        crosshair_ready = crosshair_target_in_reach(state, self.target_uuid, self.target_id, self.target_type)
        # AABB nearest distance alone can stop short of the actual aim ray.
        # Keep closing until the current target is picked, or within 2.5 blocks.
        in_reach = crosshair_ready or distance <= 2.5
        crosshair = state.get('crosshair', {})
        shield_crosshair = (crosshair.get('type') == 'miss'
                            or (crosshair.get('type') == 'entity' and crosshair.get('uuid') == self.target_uuid
                                and crosshair.get('entity_type') == self.target_type))
        shield_available = (self.shield and state['player'].get('offhand', {}).get('id') == 'minecraft:shield'
                            and state['player']['offhand'].get('count', 0) > 0 and shield_crosshair
                            and not (observed_combat and state['player'].get('shield_cooldown') is not False))
        if not in_reach:
            self.set_key(resident, 'key.use', shield_available)
            if not self.approach:
                self.set_key(resident, 'key.forward', False)
                self.phase = 'waiting_in_range'
                return
            if time.monotonic() - resident.cache.terrain_received_at > TERRAIN_AGE or not resident.cache.cells:
                # Never keep advancing while a paginated terrain read blocks.
                self.set_key(resident, 'key.forward', False)
                resident.cache.scan(resident.bridge, radius=3, vertical=2)
                self.phase = 'refreshing_approach'
                return
            if (resident.cache.state['world']['world_generation'] != state['world']['world_generation']
                    or not flat_corridor_clear(state, target, resident.cache.cells)):
                raise ValueError('combat_flat_approach_blocked')
            if time.monotonic() - started > MAX_SAMPLE_SECONDS:
                raise ValueError('stale_combat_observation')
            self.set_key(resident, 'key.forward', True)
            self.phase = 'approaching'
            return
        self.set_key(resident, 'key.forward', False)
        now = time.monotonic()
        if (strength < .95 if observed_combat else now < self.next_attack):
            self.set_key(resident, 'key.use', shield_available)
            self.phase = 'shielding' if shield_available else 'waiting_attack_interval'
            return
        if 'key.use' in self.held:
            self.set_key(resident, 'key.use', False)
            self.shield_released_tick = tick
            self.phase = 'lowering_shield'
            return
        if self.shield_released_tick is not None and tick <= self.shield_released_tick:
            return
        if observed_combat and state['player']['using_item']:
            self.phase = 'waiting_item_use_end'
            return
        if not crosshair_ready:
            self.set_key(resident, 'key.use', shield_available)
            self.phase = 'waiting_target_crosshair'
            return
        # A preceding key-up may itself have blocked. Do not attack using the
        # pre-release crosshair after the observation has expired.
        if time.monotonic() - started > MAX_SAMPLE_SECONDS:
            raise ValueError('stale_combat_observation')
        self.attack_attempts += 1  # Attempt remains consumed if dispatch is ambiguous.
        self.next_attack = now + (0.7 if weapon in SWORDS else 1.35)
        self.key(resident, 'key.attack', 'click')
        self.attack_dispatches += 1
        self.shield_released_tick = None
        self.phase = 'attack_dispatched'

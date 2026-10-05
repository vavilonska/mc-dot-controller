"""External view-only tracker. No keys, combat, pathing, or simulated entity state."""
from __future__ import annotations

import math
import time
import uuid

SCHEMA = 1
VIEW_TOLERANCE = 0.01
INTERVAL = 0.1  # Best-effort 10 Hz; Minecraft still owns physics and input ticks.
MAX_SAMPLE_SECONDS = 0.5


def number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('invalid_aim_observation')
    return value


def canonical_uuid(value):
    if not isinstance(value, str):
        raise ValueError('invalid_target_uuid')
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise ValueError('invalid_target_uuid') from None


def view_changed(actual, expected):
    return (abs((number(actual[0]) - expected[0] + 180) % 360 - 180) > VIEW_TOLERANCE
            or abs(number(actual[1]) - expected[1]) > VIEW_TOLERANCE)


def angles_to_center(player, entity):
    """Use exact observed eye and AABB, including crouching and nonstandard entities."""
    eye, bounds = player['eye_position'], entity['bounding_box']
    center = {}
    for axis in ('x', 'y', 'z'):
        low, high = number(bounds['min'][axis]), number(bounds['max'][axis])
        if low > high:
            raise ValueError('invalid_entity_bounding_box')
        center[axis] = (low + high) / 2
    dx, dy, dz = (center[k] - number(eye[k]) for k in ('x', 'y', 'z'))
    horizontal = math.hypot(dx, dz)
    if horizontal < 1e-9 and abs(dy) < 1e-9:
        raise ValueError('target_center_at_eye')
    yaw = number(player['yaw']) if horizontal < 1e-9 else math.degrees(math.atan2(-dx, dz))
    return (yaw + 180) % 360 - 180, -math.degrees(math.atan2(dy, horizontal)), center


class EntityAimLock:
    def __init__(self):
        self.active = False
        self.reason = 'not_locked'
        self.target_uuid = None
        self.target_entity_id = None
        self.world_generation = None
        self.player_uuid = None
        self.expected_view = None
        self.radius = 16
        self.next_update = 0.0
        self.updates = 0
        self.last_center = None
        self.last_updated_at = None

    def status(self):
        return {'schema_version': SCHEMA, 'active': self.active, 'reason': self.reason,
                'target_uuid': self.target_uuid, 'target_entity_id': self.target_entity_id,
                'radius': self.radius, 'updates': self.updates, 'center': self.last_center,
                'updated_at': self.last_updated_at, 'view_only': True}

    def release(self, reason):
        self.active, self.reason = False, reason
        self.expected_view = None
        return self.status()

    def start(self, command, state, action_session):
        radius = command.get('radius', 16)
        if type(radius) is not int or not 1 <= radius <= 32:
            raise ValueError('aim_radius_1_to_32')
        target = command.get('target_uuid')
        if target is None:
            crosshair = state.get('crosshair', {})
            if crosshair.get('type') != 'entity':
                raise ValueError('aim_requires_entity_crosshair_or_target_uuid')
            target = crosshair.get('uuid')
        target = canonical_uuid(target)
        # Prepare everything before replacing an existing lock.
        candidate = EntityAimLock()
        candidate.target_uuid, candidate.radius = target, radius
        candidate.world_generation = state['world']['world_generation']
        candidate.player_uuid = state['player']['uuid']
        if not candidate.world_generation or not candidate.player_uuid:
            raise ValueError('invalid_aim_observation')
        candidate.active, candidate.reason = True, 'tracking'
        candidate.prepare(state, action_session)
        self.__dict__.update(candidate.__dict__)

    def prepare(self, state, action_session):
        """Make a guarded absolute view update from one fresh observation."""
        if state.get('aim_view_guard_schema_version') != SCHEMA:
            raise ValueError('aim_view_guard_mod_required')
        if state.get('client_action', {}).get('action_session') != action_session:
            raise ValueError('bridge_session_changed')
        if state['world']['world_generation'] != self.world_generation:
            raise ValueError('world_changed')
        player = state['player']
        if player['uuid'] != self.player_uuid:
            raise ValueError('player_changed')
        if player.get('alive') is not True or number(player['health']) <= 0:
            raise ValueError('player_unavailable')
        if state.get('screen_open') is not False:
            raise ValueError('screen_opened')
        if state.get('paused') is not False:
            raise ValueError('game_paused')
        if state['client_action'].get('status') == 'running':
            raise ValueError('action_owns_view')
        current = number(player['yaw']), number(player['pitch'])
        if self.expected_view and view_changed(current, self.expected_view):
            raise ValueError('manual_view_changed')
        entity = next((e for e in state['nearby']['entities'] if e.get('uuid') == self.target_uuid), None)
        if entity is None:
            # Truncation/out-of-radius are both lost observation, never pick another target.
            raise ValueError('target_missing')
        if entity.get('alive') is not True or ('health' in entity and number(entity['health']) <= 0):
            raise ValueError('target_dead')
        entity_id = entity.get('entity_id')
        if type(entity_id) is not int:
            raise ValueError('invalid_aim_observation')
        if self.target_entity_id is not None and entity_id != self.target_entity_id:
            raise ValueError('target_identity_changed')
        game_time = state['world']['game_time']
        if type(game_time) is not int or game_time < 0:
            raise ValueError('invalid_aim_observation')
        yaw, pitch, center = angles_to_center(player, entity)
        self.target_entity_id, self.last_center = entity_id, center
        return {'yaw': yaw, 'pitch': pitch, 'relative': False,
                'guard': {'schema_version': SCHEMA,
                          'expected_world_generation': self.world_generation,
                          'expected_player_uuid': self.player_uuid,
                          'expected_action_session': action_session,
                          'expected_game_time': game_time,
                          'expected_yaw': current[0], 'expected_pitch': current[1],
                          'target_entity_id': entity_id, 'target_uuid': self.target_uuid}}

    def accepted(self, result):
        if result.get('aim_view_guard_schema_version') != SCHEMA:
            raise ValueError('aim_view_guard_response_required')
        self.expected_view = number(result['yaw']), number(result['pitch'])
        self.updates += 1
        self.last_updated_at = time.time()
        self.next_update = time.monotonic() + INTERVAL

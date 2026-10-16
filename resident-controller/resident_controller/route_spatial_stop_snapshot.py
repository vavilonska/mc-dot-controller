"""Closed DEFAULT-STOP route evidence, separate from defense and legacy policies.

Complete loaded-entity rows remain authoritative. No distance-only or unknown
entity exception, combat target, pickup exception, or resumption authority exists.
"""
import json
import re
from .capability_snapshot import _require, _integer, _number, _text, exact, signed_long_string

PROFILE = 'movement-local-segment-spatial-stop-v1'
POLICY = 'route-spatial-stop-v1'
PROFILE_V2 = 'movement-local-segment-spatial-stop-v2'
POLICY_V2 = 'route-spatial-stop-v2'
PROFILES = {PROFILE: POLICY, PROFILE_V2: POLICY_V2}
BEE_CLASS = 'net.minecraft.world.entity.animal.Bee'

# These exact classes are independent of the legacy movement allowlist. New
# mechanics in another profile cannot silently enlarge this versioned policy.
SWEPT_TYPES = {
    'minecraft:sheep': ('net.minecraft.world.entity.animal.Sheep', True),
    'minecraft:cow': ('net.minecraft.world.entity.animal.Cow', True),
    'minecraft:chicken': ('net.minecraft.world.entity.animal.Chicken', True),
    'minecraft:pig': ('net.minecraft.world.entity.animal.Pig', True),
    'minecraft:frog': ('net.minecraft.world.entity.animal.frog.Frog', True),
    'minecraft:boat': ('net.minecraft.world.entity.vehicle.Boat', False),
    'minecraft:chest_minecart': ('net.minecraft.world.entity.vehicle.MinecartChest', False),
    'minecraft:item': ('net.minecraft.world.entity.item.ItemEntity', False),
}
FAR_TYPES = {
    'minecraft:bat': ('net.minecraft.world.entity.ambient.Bat', True),
    'minecraft:glow_squid': ('net.minecraft.world.entity.GlowSquid', True),
    **{'minecraft:' + name: ('net.minecraft.world.entity.animal.' + cls, True)
       for name, cls in (('cod', 'Cod'), ('salmon', 'Salmon'), ('tropical_fish', 'TropicalFish'),
           ('squid', 'Squid'), ('turtle', 'Turtle'), ('cat', 'Cat'),
           ('ocelot', 'Ocelot'), ('parrot', 'Parrot'))},
    **{'minecraft:' + name: ('net.minecraft.world.entity.animal.horse.' + cls, True)
       for name, cls in (('horse', 'Horse'), ('donkey', 'Donkey'), ('mule', 'Mule'))},
    **{'minecraft:' + name: ('net.minecraft.world.entity.npc.' + cls, True)
       for name, cls in (('villager', 'Villager'), ('wandering_trader', 'WanderingTrader'))},
}
UUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')


def validate_request(scope, intent):
    """Validate this opt-in profile before reads or mutation; never select it here."""
    if type(scope) is not dict or scope.get('profile') not in PROFILES:
        return
    _require(type(intent) is dict and intent.get('action') == 'follow_path'
             and intent.get('capability_route') is True
             and ('op' not in intent or intent['op'] == 'action')
             and not any(k in intent for k in ('route_threat_guard', 'route_stop_only', 'pickup_target',
                 'encounter_route_guard', 'coordination_step', 'capability_bridge', 'capability_descent',
                 'movement_budget_bundle_id')), 'route_spatial_stop_request')


def numbers(value, length):
    return type(value) is list and len(value) == length and all(_number(v) for v in value)


def swept_body(m):
    return [min(m['start_x'], m['end_x']) + .5 - .400002,
            min(m['start_y'], m['end_y']) - .000001,
            min(m['start_z'], m['end_z']) + .5 - .400002,
            max(m['start_x'], m['end_x']) + .5 + .400002,
            m['start_y'] + (1.26 if m['step_dy'] > 0 else 0) + 1.800002,
            max(m['start_z'], m['end_z']) + .5 + .400002]


def projected_box(row, horizon):
    # Binary64 operation order mirrors the native projection, including integer
    # JSON input. Overflow is rejected rather than used as a far-away shortcut.
    position, velocity, target = ([float(v) for v in row[k]] for k in ('position', 'velocity', 'lerp_target'))
    box = [float(v) for v in row['aabb']]
    _require(all(box[i] < box[i + 3] and box[i] <= position[i] <= box[i + 3] for i in range(3)),
             'route_spatial_stop_entity_box')
    projected = [0.] * 6
    for i in range(3):
        lerp, motion = target[i] - position[i], horizon * velocity[i]
        lows = (box[i], box[i] + lerp, box[i] + motion, (box[i] + lerp) + motion)
        highs = (box[i + 3], box[i + 3] + lerp, box[i + 3] + motion, (box[i + 3] + lerp) + motion)
        _require(all(_number(v) for v in (lerp, motion, *lows, *highs)), 'route_spatial_stop_projection_overflow')
        projected[i], projected[i + 3] = min(lows), max(highs)
    return projected


def validate_bee_living(value, row, frame, witness):
    """V2-only authoritative current calm facts; no future-behavior certificate."""
    keys = {'schema_version', 'entity_uuid', 'entity_id', 'entity_type', 'dimension', 'world_generation',
            'player_uuid', 'known', 'source', 'reason', 'current_target_known', 'coverage_complete',
            'inspected', 'sample_tick', 'sample_nano', 'source_tick', 'source_nano', 'sample_age_ms',
            'alive', 'aggressive', 'current_target', 'bee', 'bee_route'}
    _require(type(value) is dict and set(value) == keys
             and type(value['schema_version']) is int and value['schema_version'] == 1
             and value['known'] is True and value['alive'] is True and value['aggressive'] is False
             and value['current_target_known'] is True and value['current_target'] is None
             and value['coverage_complete'] is True and _integer(value['inspected'], 1, 4096)
             and value['source'] == 'integrated_server_tick' and value['reason'] == 'observed'
             and all(exact(value[k], row[r]) for k, r in
                     (('entity_uuid', 'uuid'), ('entity_id', 'id'), ('entity_type', 'type')))
             and all(exact(value[k], witness['context'][k]) for k in
                     ('player_uuid', 'world_generation', 'dimension')), 'route_bee_living_identity')
    _require(_integer(value['sample_tick']) and value['sample_tick'] == frame['source_tick']
             and _integer(value['source_tick']) and abs(frame['source_tick'] - value['source_tick']) <= 5
             and signed_long_string(value['sample_nano']) and signed_long_string(value['source_nano'])
             and 0 <= int(value['sample_nano']) - int(frame['source_nano']) <= 250000000
             and int(value['sample_nano']) <= int(witness['admitted_nano'])
             and 0 <= int(value['sample_nano']) - int(value['source_nano']) <= 250000000
             and 0 <= int(witness['admitted_nano']) - int(value['source_nano']) <= 250000000
             and _number(value['sample_age_ms'])
             and value['sample_age_ms'] == (int(value['sample_nano']) - int(value['source_nano'])) / 1000000.,
             'route_bee_living_clock')
    bee = value['bee']
    _require(type(bee) is dict and set(bee) == {'angry', 'remaining_anger_ticks', 'persistent_anger_target_uuid'}
             and bee['angry'] is False and type(bee['remaining_anger_ticks']) is int
             and bee['remaining_anger_ticks'] == 0 and bee['persistent_anger_target_uuid'] is None,
             'route_bee_living_not_calm')
    route = value['bee_route']
    _require(type(route) is dict and set(route) ==
             {'schema_version', 'server_class', 'has_stung', 'has_nectar', 'hive_pos', 'flower_pos'}
             and type(route['schema_version']) is int and route['schema_version'] == 1
             and route['server_class'] == BEE_CLASS and route['has_stung'] is False
             and type(route['has_nectar']) is bool, 'route_bee_living_route_state')
    for key in ('hive_pos', 'flower_pos'):
        pos = route[key]
        _require(pos is None or type(pos) is dict and set(pos) == {'x', 'y', 'z'}
                 and all(_integer(pos[axis], -(2**31), 2**31 - 1) for axis in pos),
                 'route_bee_living_destination')


def validate_entity_guard(frame, movement, witness):
    """Validate immutable admission evidence without certifying future dynamics."""
    v2 = witness['profile'] == PROFILE_V2
    keys = {'schema_version', 'policy', 'source', 'scope', 'guarantee', 'future_dynamics_certified',
            'server_confirmed', 'entity_limit', 'enumerated_count', 'self_count', 'live_other_count',
            'removed_count', 'unsupported_count', 'source_tick', 'source_nano', 'maximum_action_ticks',
            'remaining_projection_ticks', 'prism', 'rows', 'swept_aabb'}
    _require(type(frame) is dict and set(frame) == keys, 'route_spatial_stop_frame_schema')
    _require(type(frame['schema_version']) is int and frame['schema_version'] == (2 if v2 else 1)
             and witness['profile'] in PROFILES and frame['policy'] == PROFILES[witness['profile']] and frame['source'] == 'native-client-loaded-level'
             and frame['scope'] == ('all-client-loaded-route-swept-and-far-passives-and-calm-bees' if v2
                                     else 'all-client-loaded-route-swept-and-far-passives')
             and frame['guarantee'] == 'same-callback-current-facts-only'
             and frame['future_dynamics_certified'] is False and frame['server_confirmed'] is False
             and type(frame['entity_limit']) is int and frame['entity_limit'] == 1024
             and type(frame['self_count']) is int and frame['self_count'] == 1
             and type(frame['unsupported_count']) is int and frame['unsupported_count'] == 0
             and type(frame['maximum_action_ticks']) is int and frame['maximum_action_ticks'] == 160,
             'route_spatial_stop_frame_policy')
    _require(_integer(frame['source_tick']) and frame['source_tick'] == witness['source_tick']
             and signed_long_string(frame['source_nano'])
             and int(witness['source_nano']) <= int(frame['source_nano']) <= int(witness['admitted_nano'])
             and type(frame['remaining_projection_ticks']) is int and frame['remaining_projection_ticks'] == 160,
             'route_spatial_stop_frame_clock')
    prism = [movement[k] for k in ('min_x', 'min_y', 'min_z')] + [movement[k] + 1 for k in ('max_x', 'max_y', 'max_z')]
    _require(numbers(frame['prism'], 6) and frame['prism'] == prism
             and numbers(frame['swept_aabb'], 6) and frame['swept_aabb'] == swept_body(movement),
             'route_spatial_stop_frame_geometry')
    rows = frame['rows']
    _require(type(rows) is list and len(rows) <= 1023 and _integer(frame['enumerated_count'], 1, 1024)
             and frame['enumerated_count'] == len(rows) + 1
             and _integer(frame['live_other_count'], 0, 1023) and _integer(frame['removed_count'], 0, 1023)
             and frame['live_other_count'] + frame['removed_count'] == len(rows), 'route_spatial_stop_frame_coverage')
    identity = {'id', 'uuid', 'type', 'class', 'removed'}
    live = identity | {'position', 'aabb', 'velocity', 'lerp_target', 'flags', 'projected_aabb', 'verdict'}
    booleans = {'living', 'alive', 'dying', 'passenger', 'has_passengers', 'leashed', 'no_physics', 'on_fire'}
    flag_keys = booleans | {'active_effect_count', 'hurt_time', 'mob_target_uuid'}
    ids, uuids, order, removed = set(), set(), [], 0
    for row in rows:
        _require(type(row) is dict and type(row.get('removed')) is bool, 'route_spatial_stop_row_schema')
        bee = v2 and row.get('type') == 'minecraft:bee'
        _require(set(row) == (identity if row['removed'] else live | ({'native_living'} if bee else set())),
                 'route_spatial_stop_row_schema')
        _require(_integer(row['id'], -(2**31), 2**31 - 1) and type(row['uuid']) is str
                 and UUID.fullmatch(row['uuid']) is not None and _text(row['type']) and _text(row['class'])
                 and row['id'] not in ids and row['uuid'] not in uuids
                 and row['uuid'] != witness['context']['player_uuid'], 'route_spatial_stop_row_identity')
        ids.add(row['id']); uuids.add(row['uuid']); order.append((row['id'], row['uuid'], row['class']))
        if row['removed']:
            removed += 1
            continue
        far_only = bee or row['type'] in FAR_TYPES
        allowed = (BEE_CLASS, True) if bee else FAR_TYPES.get(row['type']) if far_only else SWEPT_TYPES.get(row['type'])
        _require(allowed is not None and row['class'] == allowed[0]
                 and row['verdict'] == ('outside_context' if far_only else 'outside_swept'),
                 'route_spatial_stop_row_unsupported')
        flags = row['flags']
        _require(type(flags) is dict and set(flags) == flag_keys
                 and all(type(flags[k]) is bool for k in booleans)
                 and flags['living'] is allowed[1] and flags['alive'] is True
                 and all(flags[k] is False for k in booleans - {'living', 'alive'})
                 and type(flags['active_effect_count']) is int and flags['active_effect_count'] == 0
                 and type(flags['hurt_time']) is int and flags['hurt_time'] == 0
                 and flags['mob_target_uuid'] is None, 'route_spatial_stop_row_flags')
        if bee:
            validate_bee_living(row['native_living'], row, frame, witness)
        _require(all(numbers(row[k], 3) for k in ('position', 'velocity', 'lerp_target'))
                 and numbers(row['aabb'], 6) and numbers(row['projected_aabb'], 6),
                 'route_spatial_stop_row_geometry')
        projected = projected_box(row, frame['remaining_projection_ticks'])
        _require(row['projected_aabb'] == projected, 'route_spatial_stop_projection_mismatch')
        exclusion = frame['prism'] if far_only else frame['swept_aabb']
        # Strict separation: current or projected contact, including equality,
        # refuses even when the entity centre is well outside the route.
        _require(any(projected[i + 3] < exclusion[i] or projected[i] > exclusion[i + 3] for i in range(3)),
                 'route_spatial_stop_projection_intersects')
    _require(order == sorted(order) and removed == frame['removed_count']
             and len(rows) - removed == frame['live_other_count'], 'route_spatial_stop_complete_frame')
    _require(len(json.dumps(frame, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8'))
             <= 192 * 1024, 'route_spatial_stop_frame_size')


REJECTION_CODES = frozenset((
    'route_stop_coverage_invalid',
    'route_stop_duplicate_identity',
    'route_stop_entity_state_unknown',
    'route_stop_entity_unsupported',
    'route_stop_evidence_too_large',
    'route_stop_far_context_conflict',
    'route_stop_geometry_missing',
    'route_stop_identity_invalid',
    'route_stop_order_invalid',
    'route_stop_projected_body_conflict',
    'route_stop_projection_changed',
    'route_stop_removed_shape',
    'scoped_movement_entities_changed_after_hooks',
    'scoped_movement_entity_box_invalid',
    'scoped_movement_entity_capture_stale',
    'scoped_movement_entity_coverage_invalid',
    'scoped_movement_entity_coverage_limit',
    'scoped_movement_entity_duplicate_identity',
    'scoped_movement_entity_duplicate_object',
    'scoped_movement_entity_evidence_too_large',
    'scoped_movement_entity_fire_reader_unavailable',
    'scoped_movement_entity_geometry_missing',
    'scoped_movement_entity_health_nonfinite',
    'scoped_movement_entity_horizon_invalid',
    'scoped_movement_entity_identity_missing',
    'scoped_movement_entity_nonfinite',
    'scoped_movement_entity_order_invalid',
    'scoped_movement_entity_projected_corridor_conflict',
    'scoped_movement_entity_projection_changed',
    'scoped_movement_entity_projection_nonfinite',
    'scoped_movement_entity_self_coverage',
    'scoped_movement_entity_state_unknown',
    'scoped_movement_entity_target_present',
    'scoped_movement_entity_tick_budget',
    'scoped_movement_entity_unsupported',
    'scoped_movement_entity_uuid_invalid',
    'scoped_movement_removed_entity_reader_unknown',
    'scoped_movement_removed_entity_shape',
    'scoped_movement_response_evidence_too_large',
    'scoped_movement_entity_coverage_unknown',
))


BEE_REJECTION_CODES = frozenset(('route_bee_native_unconfirmed', 'route_bee_native_stale',
    'route_bee_not_calm', 'route_bee_native_context_changed'))


def valid_rejection_diagnostic(value):
    """Recognize bounded native refusal facts without settlement/retry authority."""
    keys = {'schema_version', 'profile', 'policy', 'phase', 'entity_type', 'exception_type', 'rejection_code'}
    if type(value) is not dict or type(value.get('schema_version')) is not int:
        return False
    extended = value['schema_version'] == 2
    if set(value) != (keys | {'native_bee_diagnostic'} if extended else keys):
        return False
    if extended:
        from .route_bee_diagnostic import valid_native_bee_diagnostic
        if (value['profile'] != PROFILE_V2 or value['entity_type'] != 'minecraft:bee'
                or type(value['phase']) is not str or value['phase'] not in ('policy', 'freshness', 'compare')
                or not valid_native_bee_diagnostic(value['native_bee_diagnostic'])):
            return False
    entity_type = value['entity_type']
    return (value['schema_version'] in (1, 2)
            and type(value['profile']) is str and value['profile'] in PROFILES
            and value['policy'] == PROFILES[value['profile']]
            and type(value['phase']) is str and value['phase'] in
                ('enumeration', 'identity', 'type', 'geometry', 'state', 'policy', 'coverage', 'freshness', 'compare')
            and type(entity_type) is str and len(entity_type) <= 128
            and (entity_type == 'type_unavailable' or re.fullmatch(r'[a-z0-9_.-]+:[a-z0-9_./-]+', entity_type) is not None)
            and type(value['exception_type']) is str and value['exception_type'] in ('rejected', 'runtime_exception')
            and type(value['rejection_code']) is str and value['rejection_code'] in
                (REJECTION_CODES | BEE_REJECTION_CODES if value['profile'] == PROFILE_V2 else REJECTION_CODES))

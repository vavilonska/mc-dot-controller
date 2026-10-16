"""Closed route-only spatial threat evidence; never authorizes combat or resumption."""
import re
import math
import json
from .capability_snapshot import _require, _integer, _number, exact, signed_long_string

PROFILE = 'movement-local-segment-spatial-threat-v1'
POLICY = 'route-spatial-threat-v1'
MAX_STOP_PROOF_BYTES = 32 * 1024
UUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')


def valid_uuid(value):
    return type(value) is str and UUID.fullmatch(value) is not None


def validate_request(scope, intent):
    """Reject a spatial/legacy mismatch before any native action submission."""
    profile = scope.get('profile') if type(scope) is dict else None
    selected = profile == PROFILE
    _require(type(intent) is dict, 'route_threat_request')
    present = 'route_threat_guard' in intent
    _require(selected == present, 'route_threat_profile_binding')
    _require('route_stop_only' not in intent or selected and intent['route_stop_only'] is True,
             'route_threat_stop_only_request')
    if not selected:
        return
    guard = intent['route_threat_guard']
    _require(type(guard) is dict and set(guard) == {'schema_version', 'target_uuid'}
             and type(guard['schema_version']) is int and guard['schema_version'] == 1
             and valid_uuid(guard['target_uuid'])
             and guard['target_uuid'] != intent.get('expected_player_uuid')
             and intent.get('action') == 'follow_path' and intent.get('capability_route') is True
             and ('op' not in intent or intent['op'] == 'action')
             and not any(k in intent for k in ('pickup_target', 'encounter_route_guard', 'coordination_step',
                 'capability_bridge', 'capability_descent', 'movement_budget_bundle_id')),
             'route_threat_request')


def numbers(value, length):
    return type(value) is list and len(value) == length and all(_number(v) for v in value)


def swept_body(movement):
    """Independent finite sweep, including source centering and vanilla body tolerance."""
    m = movement
    return [min(m['start_x'], m['end_x']) + .5 - .400002,
            min(m['start_y'], m['end_y']) - .000001,
            min(m['start_z'], m['end_z']) + .5 - .400002,
            max(m['start_x'], m['end_x']) + .5 + .400002,
            m['start_y'] + (1.26 if m['step_dy'] > 0 else 0) + 1.800002,
            max(m['start_z'], m['end_z']) + .5 + .400002]


def separate(left, right):
    # Touching is a conflict, matching the native inclusive exclusion boundary.
    return any(left[i + 3] < right[i] or left[i] > right[i + 3] for i in range(3))


def projected_box(row, horizon):
    position, velocity, target = ([float(v) for v in row[k]] for k in ('position', 'velocity', 'lerp_target'))
    box = [float(v) for v in row['aabb']]
    _require(all(box[i] < box[i + 3] and box[i] <= position[i] <= box[i + 3] for i in range(3)),
             'route_threat_entity_box')
    projected = [0.] * 6
    for i in range(3):
        lerp, motion = target[i] - position[i], horizon * velocity[i]
        lows = (box[i], box[i] + lerp, box[i] + motion, (box[i] + lerp) + motion)
        highs = (box[i + 3], box[i + 3] + lerp, box[i + 3] + motion, (box[i + 3] + lerp) + motion)
        _require(all(_number(v) for v in (lerp, motion, *lows, *highs)), 'route_threat_projection_overflow')
        projected[i], projected[i + 3] = min(lows), max(highs)
    return projected


def player_pose_allowed(position, m):
    if not numbers(position, 3):
        return False
    x, y, z = position
    along = (x - m['start_x'] - .5) * (m['end_x'] - m['start_x']) + (z - m['start_z'] - .5) * (m['end_z'] - m['start_z'])
    cross = (x - m['start_x'] - .5) * (m['end_z'] - m['start_z']) - (z - m['start_z'] - .5) * (m['end_x'] - m['start_x'])
    return (-.100001 <= along <= 1.100001 and abs(cross) <= .100001
            and min(m['start_y'], m['end_y']) - 1e-6 <= y <= m['start_y'] + (1.26 if m['step_dy'] > 0 else 0) + 1e-6
            and not (m['step_dy'] > 0 and y < m['end_y'] - 1e-6 and along + .3 > .5 + 1e-6)
            and not (m['step_dy'] < 0 and y < m['start_y'] - 1e-6 and along - .3 < .5 - 1e-6))


def validate_living(value, row, frame, witness):
    keys = {'schema_version', 'entity_uuid', 'entity_id', 'entity_type', 'dimension', 'world_generation',
            'player_uuid', 'known', 'source', 'reason', 'current_target_known', 'coverage_complete',
            'inspected', 'sample_tick', 'sample_nano', 'source_tick', 'source_nano', 'sample_age_ms',
            'alive', 'aggressive', 'current_target'}
    _require(type(value) is dict and set(value) == keys and type(value['schema_version']) is int
             and value['schema_version'] == 1 and value['known'] is True and value['alive'] is True
             and value['current_target_known'] is True and value['coverage_complete'] is True
             and value['source'] == 'integrated_server_tick' and value['reason'] == 'observed'
             and type(value['aggressive']) is bool and _integer(value['inspected'], 1, 4096)
             and all(exact(value[k], row[r]) for k, r in (('entity_uuid', 'uuid'), ('entity_id', 'id'), ('entity_type', 'type')))
             and all(exact(value[k], witness['context'][k]) for k in ('player_uuid', 'world_generation', 'dimension')),
             'route_threat_living_identity')
    _require(_integer(value['sample_tick']) and value['sample_tick'] == frame['source_tick']
             and _integer(value['source_tick']) and abs(frame['source_tick'] - value['source_tick']) <= 5
             and signed_long_string(value['sample_nano']) and signed_long_string(value['source_nano'])
             and 0 <= int(value['sample_nano']) - int(frame['source_nano']) <= 250000000
             and 0 <= int(value['sample_nano']) - int(value['source_nano']) <= 250000000
             and _number(value['sample_age_ms'])
             and value['sample_age_ms'] == (int(value['sample_nano']) - int(value['source_nano'])) / 1000000.,
             'route_threat_living_clock')
    target = value['current_target']
    _require(target is None or type(target) is dict and set(target) == {'uuid', 'entity_id', 'type'}
             and valid_uuid(target['uuid']) and _integer(target['entity_id'], 0, 2**31 - 1)
             and target['uuid'] == witness['context']['player_uuid'] and target['type'] == 'minecraft:player',
             'route_threat_living_target')
    return target is not None


def validate_entity_guard(frame, movement, witness, selected_uuid, *, action_tick=0, admission=True, allow_projected_overlap=False):
    from .capability_snapshot import _MOVEMENT_ENTITY_TYPES, _text
    keys = {'schema_version', 'policy', 'source', 'scope', 'guarantee', 'future_dynamics_certified',
            'server_confirmed', 'entity_limit', 'enumerated_count', 'self_count', 'live_other_count',
            'removed_count', 'unsupported_count', 'source_tick', 'source_nano', 'maximum_action_ticks',
            'remaining_projection_ticks', 'prism', 'rows', 'swept_aabb', 'player_position',
            'selected_target_uuid', 'stop_only'}
    _require(type(frame) is dict and set(frame) == keys, 'route_threat_frame_schema')
    _require(type(frame['schema_version']) is int and frame['schema_version'] == 1
             and frame['policy'] == POLICY and frame['source'] == 'native-client-loaded-level'
             and frame['scope'] == 'all-client-loaded-route-swept-body-and-threats'
             and frame['guarantee'] == 'same-callback-current-facts-only'
             and frame['future_dynamics_certified'] is False and frame['server_confirmed'] is False
             and type(frame['entity_limit']) is int and frame['entity_limit'] == 1024
             and type(frame['self_count']) is int and frame['self_count'] == 1
             and type(frame['unsupported_count']) is int and frame['unsupported_count'] == 0
             and type(frame['maximum_action_ticks']) is int and frame['maximum_action_ticks'] == 160
             and valid_uuid(selected_uuid) and frame['selected_target_uuid'] == selected_uuid
             and type(frame['stop_only']) is bool, 'route_threat_frame_policy')
    _require(_integer(action_tick, 0, 159) and _integer(frame['source_tick'], witness['source_tick'])
             and signed_long_string(frame['source_nano'])
             and int(frame['source_nano']) >= int(witness['source_nano'])
             and int(frame['source_nano']) < int(movement['deadline_nano'])
             and type(frame['remaining_projection_ticks']) is int
             and frame['remaining_projection_ticks'] == 160 - action_tick, 'route_threat_frame_clock')
    if admission:
        _require(action_tick == 0 and frame['source_tick'] == witness['source_tick']
                 and int(frame['source_nano']) <= int(witness['admitted_nano'])
                 and numbers(frame['player_position'], 3)
                 and all(a == witness['facts'][k] for a, k in zip(frame['player_position'], ('x', 'y', 'z'))),
                 'route_threat_admission_frame')
    else:
        _require(int(frame['source_nano']) >= int(witness['admitted_nano']), 'route_threat_stop_before_admission')
    _require(player_pose_allowed(frame['player_position'], movement), 'route_threat_player_pose')
    prism = [movement[k] for k in ('min_x', 'min_y', 'min_z')] + [movement[k] + 1 for k in ('max_x', 'max_y', 'max_z')]
    _require(numbers(frame['prism'], 6) and frame['prism'] == prism
             and numbers(frame['swept_aabb'], 6) and frame['swept_aabb'] == swept_body(movement),
             'route_threat_frame_geometry')
    _require(len(json.dumps(frame, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8'))
             <= (192 * 1024 if admission else MAX_STOP_PROOF_BYTES), 'route_threat_frame_size')
    rows = frame['rows']
    _require(type(rows) is list and len(rows) <= 1023 and _integer(frame['enumerated_count'], 1, 1024)
             and frame['enumerated_count'] == len(rows) + 1
             and _integer(frame['live_other_count'], 0, 1023) and _integer(frame['removed_count'], 0, 1023)
             and frame['live_other_count'] + frame['removed_count'] == len(rows), 'route_threat_frame_coverage')
    identity = {'id', 'uuid', 'type', 'class', 'removed'}
    live = identity | {'position', 'aabb', 'velocity', 'lerp_target', 'flags', 'projected_aabb', 'verdict'}
    booleans = {'living', 'alive', 'dying', 'passenger', 'has_passengers', 'leashed', 'no_physics', 'on_fire'}
    flag_keys = booleans | {'active_effect_count', 'hurt_time', 'mob_target_uuid'}
    ids, uuids, order, removed, selected = set(), set(), [], 0, []
    for row in rows:
        _require(type(row) is dict and type(row.get('removed')) is bool, 'route_threat_row_schema')
        zombie = row.get('type') == 'minecraft:zombie'
        _require(set(row) == (identity if row['removed'] else live | ({'native_living'} if zombie else set()) | ({'projected_overlap'} if row.get('verdict') == 'selected_attacker' else set())),
                 'route_threat_row_schema')
        _require(_integer(row['id'], -(2**31), 2**31 - 1) and valid_uuid(row['uuid'])
                 and _text(row['type']) and _text(row['class']) and row['id'] not in ids and row['uuid'] not in uuids
                 and row['uuid'] != witness['context']['player_uuid'], 'route_threat_row_identity')
        ids.add(row['id']); uuids.add(row['uuid']); order.append((row['id'], row['uuid'], row['class']))
        if row['removed']:
            removed += 1
            continue
        allowed = ('net.minecraft.world.entity.monster.Zombie', True) if zombie else _MOVEMENT_ENTITY_TYPES.get(row['type'])
        _require(allowed is not None and row['type'] != 'minecraft:rabbit' and row['class'] == allowed[0], 'route_threat_row_unsupported')
        flags = row['flags']
        _require(type(flags) is dict and set(flags) == flag_keys
                 and all(type(flags[k]) is bool for k in booleans)
                 and flags['living'] is allowed[1] and flags['alive'] is True
                 and all(flags[k] is False for k in booleans - {'living', 'alive'})
                 and type(flags['active_effect_count']) is int and flags['active_effect_count'] == 0
                 and type(flags['hurt_time']) is int and flags['hurt_time'] == 0
                 and flags['mob_target_uuid'] is None, 'route_threat_row_flags')
        _require(all(numbers(row[k], 3) for k in ('position', 'velocity', 'lerp_target'))
                 and numbers(row['aabb'], 6) and numbers(row['projected_aabb'], 6), 'route_threat_row_geometry')
        projection = projected_box(row, frame['remaining_projection_ticks'])
        _require(row['projected_aabb'] == projection, 'route_threat_projection_mismatch')
        attacker = False
        if zombie:
            attacker = validate_living(row['native_living'], row, frame, witness)
            _require(attacker or row['native_living']['aggressive'] is False, 'route_threat_targetless_aggressive')
            delta = [float(a) - float(b) for a, b in zip(row['position'], frame['player_position'])]
            distance = math.hypot(math.hypot(delta[0], delta[2]), delta[1])
            _require(_number(distance), 'route_threat_distance_overflow')
            if row['uuid'] != selected_uuid:
                _require(not attacker and distance > 8, 'route_threat_other_zombie')
            elif attacker:
                _require(distance <= 3, 'route_threat_attacker_range')
                selected.append(row)
        expected_verdict = 'selected_attacker' if attacker and row['uuid'] == selected_uuid else 'outside'
        _require(row['verdict'] == expected_verdict, 'route_threat_verdict')
        overlap = not separate(projection, frame['swept_aabb'])
        if expected_verdict == 'selected_attacker':
            _require(type(row['projected_overlap']) is bool and row['projected_overlap'] == overlap
                     and separate(row['aabb'], frame['swept_aabb']), 'route_threat_current_collision_or_overlap')
        _require(not overlap or expected_verdict == 'selected_attacker' and frame['stop_only'] is True
                 and (admission or allow_projected_overlap), 'route_threat_projected_collision')
    _require(order == sorted(order) and removed == frame['removed_count']
             and len(rows) - removed == frame['live_other_count']
             and frame['stop_only'] == (len(selected) == 1) and len(selected) <= 1,
             'route_threat_complete_frame')
    return selected[0] if selected else None


def validate_defense_stop(native, configured_uuid):
    """Validate a known pre-effect stop; original owner/command correlation is still required."""
    _require(type(native) is dict and type(native.get('result')) is dict, 'route_threat_stop_receipt')
    result = native['result']
    witness = result.get('scoped_native_preflight')
    stop = result.get('route_threat_stop')
    keys = {'schema_version', 'profile', 'policy', 'target_uuid', 'entity_id', 'entity_type', 'player_uuid',
            'world_generation', 'dimension', 'before_next_effect', 'action_tick', 'entity_guard', 'preempted_before_motion'}
    _require(type(stop) is dict and set(stop) == keys and type(stop['schema_version']) is int
             and stop['schema_version'] == 1 and stop['profile'] == PROFILE and stop['policy'] == POLICY
             and valid_uuid(configured_uuid) and stop['target_uuid'] == configured_uuid
             and _integer(stop['entity_id'], -(2**31), 2**31 - 1) and stop['entity_type'] == 'minecraft:zombie'
             and stop['before_next_effect'] is True and _integer(stop['action_tick'], 0, 159)
             and type(stop['preempted_before_motion']) is bool, 'route_threat_stop_schema')
    _require(len(json.dumps(stop, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8'))
             <= MAX_STOP_PROOF_BYTES, 'route_threat_stop_size')
    _require(type(witness) is dict and witness.get('profile') == PROFILE
             and type(witness.get('context')) is dict and type(witness.get('facts')) is dict
             and all(exact(stop[k], witness['context'].get(k)) for k in ('player_uuid', 'world_generation', 'dimension'))
             and native.get('action') == 'follow_path' and native.get('status') == 'cancelled'
             and native.get('reason') == 'capability_threat_observed'
             and _integer(native.get('ticks'), 0, 159) and native['ticks'] == stop['action_tick']
             and result.get('input_release_confirmed') is True
             and all('effect_outcome' not in container for container in (native, result))
             and all(container.get(k, False) is False for container in (native, result)
                     for k in ('unknown_outcome', 'motion_gate_rejected', 'requires_handoff', 'input_release_unconfirmed', 'post_uncertain', 'uncertain')),
             'route_threat_stop_identity_or_release')
    movement = witness['facts'].get('local_segment')
    _require(type(movement) is dict and movement.get('profile') == PROFILE, 'route_threat_stop_movement')
    selected = validate_entity_guard(stop['entity_guard'], movement, witness, configured_uuid,
                                     action_tick=stop['action_tick'], admission=False, allow_projected_overlap=stop['preempted_before_motion'])
    _require(selected is not None and selected['uuid'] == stop['target_uuid']
             and selected['id'] == stop['entity_id'] and selected['type'] == stop['entity_type'], 'route_threat_stop_selected_identity')
    from .local_segment_snapshot import validate_terminal
    terminal = result.get('local_segment')
    validate_terminal(terminal, movement, witness)
    _require(terminal['input_neutral'] is True and terminal['entity_guard_policy'] == POLICY
             and _integer(terminal['local_checks'], 1)
             and terminal['last_entity_check_action_tick'] == stop['action_tick']
             and terminal['last_entity_check_tick'] == stop['entity_guard']['source_tick']
             and terminal['last_entity_check_nano'] == stop['entity_guard']['source_nano']
             and terminal['maximum_checked_population'] >= stop['entity_guard']['enumerated_count'], 'route_threat_stop_terminal')
    _require(stop['preempted_before_motion'] == movement['entity_guard']['stop_only']
             and stop['preempted_before_motion'] == (terminal['effect_attempted'] is False), 'route_threat_stop_effect_binding')
    if stop['preempted_before_motion']:
        _require(movement['entity_guard']['stop_only'] is True and terminal['effect_attempted'] is False
                 and stop['entity_guard']['source_tick'] == witness['source_tick']
                 and stop['entity_guard']['player_position'] == movement['entity_guard']['player_position'] and terminal['sampled_horizontal_distance'] == 0
                 and terminal['jump_pulses'] == 0 and terminal['local_checks'] == 1 and stop['action_tick'] == 0,
                 'route_threat_admission_stop_no_effect')
        admission_selected = [r for r in movement['entity_guard']['rows'] if r.get('verdict') == 'selected_attacker']
        _require(len(admission_selected) == 1 and all(exact(admission_selected[0][k], selected[k])
                 for k in ('id', 'uuid', 'type', 'class')), 'route_threat_admission_selected_identity')
    else:
        _require(movement['entity_guard']['stop_only'] is False, 'route_threat_admission_effect_forbidden')
    return stop


def validate_stop_only_failure(native):
    """Validate a known zero-effect cancellation, never threat/defense authority.

    Called only after validate_scoped_witness has bound the original action,
    owner, context, immutable command digests and complete admission evidence.
    Existing uncertain executions are never reconciled or replayed here.
    """
    _require(type(native) is dict and type(native.get('result')) is dict,
             'route_threat_stop_failure_receipt')
    result = native['result']
    witness = result.get('scoped_native_preflight')
    _require(type(witness) is dict and witness.get('profile') == PROFILE
             and type(witness.get('facts')) is dict,
             'route_threat_stop_failure_witness')
    movement = witness['facts'].get('local_segment')
    _require(type(movement) is dict and movement.get('profile') == PROFILE
             and type(movement.get('entity_guard')) is dict
             and movement['entity_guard'].get('stop_only') is True
             and 'route_threat_stop' not in result
             and native.get('action') == 'follow_path'
             and native.get('status') == 'cancelled'
             and native.get('reason') in ('local_segment_check_failed', 'route_spatial_stop_evidence_too_large',
                                           'route_spatial_evidence_too_large')
             and type(native.get('ticks')) is int and native['ticks'] == 0
             and result.get('input_release_confirmed') is True
             and all('effect_outcome' not in container for container in (native, result))
             and all(container.get(k, False) is False for container in (native, result)
                     for k in ('unknown_outcome', 'motion_gate_rejected', 'requires_handoff',
                               'input_release_unconfirmed', 'post_uncertain', 'uncertain')),
             'route_threat_stop_failure_identity_or_release')
    from .local_segment_snapshot import validate_terminal
    terminal = result.get('local_segment')
    validate_terminal(terminal, movement, witness)
    checks = terminal['local_checks']
    _require(terminal['effect_attempted'] is False and terminal['phase'] == 'ground'
             and terminal['landed'] is False and terminal['input_neutral'] is True
             and terminal['sampled_horizontal_distance'] == 0 and terminal['jump_pulses'] == 0
             and checks in (0, 1) and terminal['last_entity_check_action_tick'] == 0
             and terminal['last_entity_check_tick'] == witness['source_tick']
             and terminal['maximum_checked_population'] >= movement['entity_guard']['enumerated_count']
             and int(terminal['last_entity_check_nano']) < int(movement['deadline_nano'])
             and (checks == 0 and terminal['last_entity_check_nano'] == movement['entity_guard']['source_nano']
                  or checks == 1 and int(terminal['last_entity_check_nano']) >= int(witness['admitted_nano'])),
             'route_threat_stop_failure_no_effect')

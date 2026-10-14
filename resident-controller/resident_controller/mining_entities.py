import re
from .capability_snapshot import _require, _integer, _number, _text, signed_long_string, _MOVEMENT_ENTITY_TYPES

def validate_mining_entity_guard(guard, movement, witness):
    """Validate the complete native admission frame, not unobserved future dynamics.

    The producer's raw object-reference equality remains the consistency authority.
    Deliberately no cross-language rows digest or radius-based coverage shortcut.
    """
    keys = {'schema_version','policy','source','scope','guarantee','future_dynamics_certified',
            'server_confirmed','entity_limit','enumerated_count','self_count','live_other_count',
            'removed_count','unsupported_count','source_tick','source_nano','maximum_action_ticks',
            'remaining_projection_ticks','prism','rows'}
    _require(type(guard) is dict and set(guard) == keys, 'movement_entity_guard_schema')
    _require(type(guard['schema_version']) is int and guard['schema_version'] == 1
             and guard['policy'] == 'mining-observed-items-v1'
             and guard['source'] == 'native-client-loaded-level'
             and guard['scope'] == 'all-client-loaded-mining-prism-with-passive-items'
             and guard['guarantee'] == 'same-callback-current-facts-only'
             and guard['future_dynamics_certified'] is False and guard['server_confirmed'] is False
             and type(guard['entity_limit']) is int and guard['entity_limit'] == 1024
             and type(guard['self_count']) is int and guard['self_count'] == 1
             and type(guard['unsupported_count']) is int and guard['unsupported_count'] == 0
             and type(guard['maximum_action_ticks']) is int and guard['maximum_action_ticks'] == 160,
             'movement_entity_guard_policy')
    # The returned admission witness is immutable: later frames are not substituted here.
    _require(_integer(guard['source_tick']) and guard['source_tick'] == witness['source_tick']
             and signed_long_string(guard['source_nano'])
             and int(witness['source_nano']) <= int(guard['source_nano']) <= int(witness['admitted_nano'])
             and type(guard['remaining_projection_ticks']) is int
             and guard['remaining_projection_ticks'] == 160 - (guard['source_tick'] - witness['source_tick'])
             and guard['remaining_projection_ticks'] == 160, 'movement_entity_guard_clock')
    def numbers(value, length):
        return type(value) is list and len(value) == length and all(_number(v) for v in value)
    prism = guard['prism']
    expected_prism = [movement['min_x'], movement['min_y'], movement['min_z'],
                      movement['max_x']+1, movement['max_y']+1, movement['max_z']+1]
    _require(numbers(prism, 6) and all(a == b for a, b in zip(prism, expected_prism)),
             'movement_entity_guard_prism')
    rows = guard['rows']
    _require(type(rows) is list and len(rows) <= 1023
             and _integer(guard['enumerated_count'], 1, 1024) and guard['enumerated_count'] == 1 + len(rows)
             and _integer(guard['live_other_count'], 0, 1023) and _integer(guard['removed_count'], 0, 1023)
             and guard['live_other_count'] + guard['removed_count'] == len(rows),
             'movement_entity_guard_coverage')
    identity_keys = {'id','uuid','type','class','removed'}
    live_keys = identity_keys | {'position','aabb','velocity','lerp_target','flags','projected_aabb','verdict'}
    boolean_flags = {'living','alive','dying','passenger','has_passengers','leashed','no_physics','on_fire'}
    flag_keys = boolean_flags | {'active_effect_count','hurt_time','mob_target_uuid'}
    ids, uuids, order, removed_count = set(), set(), [], 0
    for row in rows:
        _require(type(row) is dict and type(row.get('removed')) is bool
                 and set(row) == (identity_keys if row['removed'] else live_keys),
                 'movement_entity_row_schema')
        _require(_integer(row['id'], -(2**31), 2**31-1)
                 and type(row['uuid']) is str
                 and re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', row['uuid']) is not None
                 and _text(row['type']) and _text(row['class'])
                 and row['id'] not in ids and row['uuid'] not in uuids
                 and row['uuid'] != witness['context']['player_uuid'], 'movement_entity_identity')
        ids.add(row['id']); uuids.add(row['uuid']); order.append((row['id'], row['uuid'], row['class']))
        if row['removed']:
            removed_count += 1
            continue
        allowed = _MOVEMENT_ENTITY_TYPES.get(row['type'])
        _require(allowed is not None and row['class'] == allowed[0] and row['verdict'] == ('passive_item' if row['type']=='minecraft:item' else 'outside'),
                 'movement_entity_unsupported')
        flags = row['flags']
        _require(type(flags) is dict and set(flags) == flag_keys
                 and all(type(flags[k]) is bool for k in boolean_flags)
                 and flags['living'] is allowed[1] and flags['alive'] is True
                 and all(flags[k] is False for k in boolean_flags - {'living','alive'})
                 and type(flags['active_effect_count']) is int and flags['active_effect_count'] == 0
                 and type(flags['hurt_time']) is int and flags['hurt_time'] == 0
                 and flags['mob_target_uuid'] is None, 'movement_entity_flags')
        _require(all(numbers(row[k], 3) for k in ('position','velocity','lerp_target'))
                 and numbers(row['aabb'], 6) and numbers(row['projected_aabb'], 6),
                 'movement_entity_finite_geometry')
        # Convert JSON integers to binary64 too, matching the native double operations.
        position, velocity, target = ([float(v) for v in row[k]] for k in ('position','velocity','lerp_target'))
        box = [float(v) for v in row['aabb']]
        _require(all(box[i] < box[i+3] and box[i] <= position[i] <= box[i+3] for i in range(3)),
                 'movement_entity_box')
        projected = [0.0] * 6
        for i in range(3):
            lerp = target[i] - position[i]
            motion = guard['remaining_projection_ticks'] * velocity[i]
            lows = (box[i], box[i]+lerp, box[i]+motion, (box[i]+lerp)+motion)
            highs = (box[i+3], box[i+3]+lerp, box[i+3]+motion, (box[i+3]+lerp)+motion)
            _require(all(_number(v) for v in (lerp, motion, *lows, *highs)),
                     'movement_entity_projection_overflow')
            projected[i], projected[i+3] = min(lows), max(highs)
        _require(all(a == b for a, b in zip(row['projected_aabb'], projected)),
                 'movement_entity_projection_mismatch')
        _require(row['type']=='minecraft:item' or any(projected[i+3] < prism[i] or projected[i] > prism[i+3] for i in range(3)),
                 'movement_entity_projection_intersects')
    _require(order == sorted(order) and removed_count == guard['removed_count']
             and len(rows) - removed_count == guard['live_other_count'], 'movement_entity_row_coverage')

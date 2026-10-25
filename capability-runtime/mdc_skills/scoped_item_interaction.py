"""Two closed, one-use item-on-block goals. Never arbitrary item use or a portal planner."""
from copy import deepcopy
from . import dimensions, reach
from .core import Outcome, SkillError, require
from .scoped_placement import _inventory, STACK_FIELDS

PROFILE = 'item-on-block-observed-v1'
KINDS = ('ignite_nether_portal', 'insert_end_eye')


def _point(value):
    require(type(value) is dict and set(value) == {'x', 'y', 'z'}, 'item_interaction_exact_coordinate_required')
    result = reach.coordinate(value)
    require(-2048 <= result['y'] <= 2048, 'item_interaction_coordinate_bounds')
    return result


def _profile(runtime):
    require(runtime.scoped_profile('interact_block') == PROFILE, 'item_interaction_profile_not_negotiated')
    require(getattr(runtime, 'required_execution_policy', None) == 'request_only',
            'item_interaction_request_only_required')


def _selected(before, item):
    rows = _inventory(before)
    slot = before.player.get('selected_slot')
    require(type(slot) is int and 0 <= slot <= 8, 'item_interaction_selected_slot_required')
    held = rows[slot]
    require(held['id'] == item and held['empty'] is False, 'item_interaction_selected_item_required')
    if item == 'minecraft:flint_and_steel':
        require(held['count'] == 1 and held['max_stack_size'] == 1
                and type(held.get('damage')) is int and type(held.get('max_damage')) is int
                and held['max_damage'] == 64 and 0 <= held['damage'] <= 62,
                'item_interaction_plain_tool_durability_reserve_required')
    else:
        require(1 <= held['count'] <= 64 and held['max_stack_size'] == 64,
                'item_interaction_eye_stack_required')
    return slot, held


def _row(position, expected_id, expected_properties, block_id, properties):
    return {'position': deepcopy(position), 'expected_id': expected_id,
            'expected_properties': deepcopy(expected_properties), 'block_id': block_id,
            'properties': deepcopy(properties)}


def _exact(a, b):
    if type(a) is not type(b): return False
    if type(a) is dict: return set(a) == set(b) and all(_exact(a[k], b[k]) for k in a)
    if type(a) is list: return len(a) == len(b) and all(_exact(x, y) for x, y in zip(a, b))
    return a == b


def _proof(before, after, kind, target, slot, footprint):
    native = after.state.get('client_action', {})
    result = native.get('result', {})
    proof = result.get('item_interaction', {})
    if not (native.get('action') == 'interact_block' and native.get('status') == 'succeeded'
            and result.get('input_release_confirmed') is True and proof.get('profile') == PROFILE
            and proof.get('kind') == kind and _exact(proof.get('target'), target)
            and proof.get('effect_attempted') is True and type(proof.get('use_count')) is int
            and proof['use_count'] == 1 and type(proof.get('packet_count')) is int
            and proof['packet_count'] == 1 and proof.get('input_neutral') is True
            and proof.get('unknown_outcome') is False and proof.get('protected_inventory_unchanged') is True
            and all(proof.get(k) is True for k in ('consumption_verified', 'durability_verified', 'block_outcome_verified'))
            and proof.get('automatic_replay_allowed') is False and proof.get('server_confirmed') is False
            and all(type(proof.get(k)) is int for k in ('use_count','packet_count','local_effect_count','selected_slot','initial_count','final_count','initial_damage','final_damage'))
            and proof['local_effect_count'] == (1 if kind == 'ignite_nether_portal' else 0)
            and proof['selected_slot'] == slot and type(after.player.get('selected_slot')) is int and after.player['selected_slot'] == slot):
        return False
    old, new = _inventory(before), _inventory(after)
    if any(any(not _exact(old[i].get(k), new[i].get(k)) for k in STACK_FIELDS) for i in old if i != slot):
        return False
    if any(not _exact(before.player.get(k), after.player.get(k)) for k in ('offhand', 'armor')):
        return False
    a, b = old[slot], new[slot]
    if kind == 'insert_end_eye':
        remaining = a['count'] - 1
        stack = (type(b.get('damage', 0)) is int and b.get('damage', 0) == a.get('damage', 0) and b['count'] == remaining and (b['empty'] is True and b['id'] in ('', 'minecraft:air')
                 if remaining == 0 else b['empty'] is False and b['id'] == a['id']
                 and b['component_fingerprint'] == a['component_fingerprint']))
    else:
        # Native compares all data components after replacing only DAMAGE with its original value.
        # The ordinary snapshot's component fingerprint necessarily changes with the one damage point.
        stack = (b['id'] == a['id'] and b['count'] == 1 and b['empty'] is False
                 and type(b.get('damage')) is int and type(b.get('max_damage')) is int
                 and b.get('damage') == a['damage'] + 1 and b.get('max_damage') == 64
                 and proof.get('initial_damage') == a['damage'] and proof.get('final_damage') == b['damage'])
    if not stack or proof.get('initial_count') != a['count'] or proof.get('final_count') != b['count']:
        return False
    try:
        return all(reach.block_at(after, row['position'])['id'] == row['block_id']
                   and reach.block_at(after, row['position'])['properties'] == row['properties']
                   for row in footprint)
    except SkillError:
        return False


def _execute(runtime, before, target, kind, metadata, footprint, item):
    slot, held = _selected(before, item)
    cell = reach.block_at(before, target)
    hit = {'x': target['x'] + .5, 'y': target['y'] + (13 / 16 if kind == 'insert_end_eye' else 1),
           'z': target['z'] + .5}
    command = {'op': 'action', 'action': 'interact_block', 'target': target, 'face': 'up',
               'expected_block_id': cell['id'], 'expected_block_properties': deepcopy(cell['properties']),
               'typed_item_interaction': {'kind': kind, **deepcopy(metadata)},
               'item_hit': hit, 'item_footprint': deepcopy(footprint), 'timeout_ms': 3000}
    outcome = runtime.execute('dimensions.' + kind, command,
        lambda old, new: _proof(old, new, kind, target, slot, footprint),
        before=before, stable_samples=2, max_samples=16)
    return Outcome(outcome.status, outcome.reason, outcome.request_ids,
        {**outcome.evidence, 'profile': PROFILE, 'kind': kind, 'target': target,
         'scope': 'one_stationary_typed_item_on_block', 'automatic_replay_allowed': False,
         'consumption_durability_and_block_verified_separately': True, 'server_confirmed': False},
        outcome.last_observation)


def ignite_portal_local(runtime, interior_base, *, axis='x', width=2, height=3):
    _profile(runtime)
    base = _point(interior_base)
    require(axis in ('x', 'z') and type(width) is int and 2 <= width <= 4
            and type(height) is int and 3 <= height <= 4, 'item_interaction_portal_geometry_required')
    before = runtime.observe(terrain=True, radius=6, vertical=4)
    require(before.context[1] in (dimensions.OVERWORLD, dimensions.NETHER), 'item_interaction_portal_dimension')
    def point(u, v):
        return _point(dimensions._offset(base, x=u if axis == 'x' else 0, y=v, z=u if axis == 'z' else 0))
    footprint = []
    for u, v in ([(u, v) for u in range(width) for v in (-1, height)]
                 + [(u, v) for u in (-1, width) for v in range(height)]):
        p = point(u, v); c = reach.block_at(before, p)
        require(c['id'] == 'minecraft:obsidian' and c['properties'] == {}, 'item_interaction_exact_obsidian_frame_required')
        footprint.append(_row(p, c['id'], {}, c['id'], {}))
    for u in range(width):
        for v in range(height):
            p = point(u, v); c = reach.block_at(before, p)
            require(c['id'] == 'minecraft:air' and c['properties'] == {}, 'item_interaction_literal_air_interior_required')
            footprint.append(_row(p, c['id'], {}, 'minecraft:nether_portal', {'axis': axis}))
    return _execute(runtime, before, point(0, -1), 'ignite_nether_portal',
        {'interior_base': base, 'axis': axis, 'width': width, 'height': height}, footprint, 'minecraft:flint_and_steel')


def insert_end_eye_local(runtime, interior_corner, target):
    _profile(runtime)
    base, target = _point(interior_corner), _point(target)
    before = runtime.observe(terrain=True, radius=6, vertical=4)
    require(before.context[1] == dimensions.OVERWORLD, 'item_interaction_eye_overworld_required')
    x, y, z = dimensions.threats.position(before.player)
    require(not (base['x'] - .31 <= x <= base['x'] + 3.31
                 and base['z'] - .31 <= z <= base['z'] + 3.31 and abs(y-base['y']) < 2),
            'item_interaction_stand_outside_end_ring')
    footprint, missing = [], []
    frames = dimensions.end_portal_frames(base)
    require(target in [p for p, _ in frames], 'item_interaction_target_not_in_end_ring')
    for p, facing in frames:
        c = reach.block_at(before, p); props = c['properties']
        require(c['id'] == 'minecraft:end_portal_frame' and set(props) == {'facing', 'eye'}
                and props['facing'] == facing and props['eye'] in ('true', 'false'),
                'item_interaction_exact_inward_end_ring_required')
        if props['eye'] == 'false': missing.append(p)
        final = {**props, 'eye': 'true'} if p == target else props
        footprint.append(_row(p, c['id'], props, c['id'], final))
    require(target in missing, 'item_interaction_target_already_filled')
    for dx in range(3):
        for dz in range(3):
            p = dimensions._offset(base, x=dx, z=dz); c = reach.block_at(before, p)
            require(c['id'] == 'minecraft:air' and c['properties'] == {}, 'item_interaction_end_interior_air_required')
            footprint.append(_row(p, c['id'], {}, 'minecraft:end_portal' if len(missing) == 1 else c['id'], {}))
    return _execute(runtime, before, target, 'insert_end_eye', {'interior_corner': base}, footprint, 'minecraft:ender_eye')

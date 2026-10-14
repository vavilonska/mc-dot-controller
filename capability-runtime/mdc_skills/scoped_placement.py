"""One explicit stationary cobblestone placement, never blueprint execution."""
from copy import deepcopy
from . import inventory, reach
from .core import Outcome, require
from .scoped_mining import BLOCKS

PROFILE = 'placement-local-observed-v1'
BLOCK = 'minecraft:cobblestone'
STACK_FIELDS = ('id', 'count', 'empty', 'item_fingerprint', 'component_fingerprint', 'max_stack_size')


def _inventory(observation):
    rows = inventory.items(observation)
    require(len(rows) == 36 and {r.get('slot') for r in rows} == set(range(36)),
            'placement_complete_ordinary_inventory_required')
    require(all(type(r.get('count')) is int and 0 <= r['count'] <= 64 and
                type(r.get('empty')) is bool and r['empty'] == (r['count'] == 0) and
                all(isinstance(r.get(k), str) and r[k] for k in ('item_fingerprint','component_fingerprint'))
                for r in rows), 'placement_complete_stack_identity_required')
    return {r['slot']: r for r in rows}


def _placed(before, after, target, slot):
    native = after.state.get('client_action', {})
    result = native.get('result', {})
    proof = result.get('placement', {})
    if not (native.get('action') == 'place_block' and native.get('status') == 'succeeded'
            and result.get('input_release_confirmed') is True and proof.get('profile') == PROFILE
            and proof.get('target') == target and proof.get('block_placed') is True
            and proof.get('effect_attempted') is True and type(proof.get('effect_count')) is int
            and proof['effect_count'] == 1 and type(proof.get('packet_count')) is int
            and proof['packet_count'] == 1 and proof.get('input_neutral') is True
            and proof.get('unknown_outcome') is False and proof.get('protected_inventory_unchanged') is True
            and proof.get('automatic_replay_allowed') is False and proof.get('server_confirmed') is False
            and after.player.get('selected_slot') == slot):
        return False
    old, new = _inventory(before), _inventory(after)
    if any(any(old[i].get(k) != new[i].get(k) for k in STACK_FIELDS) for i in old if i != slot):
        return False
    count = old[slot]['count'] - 1
    selected = new[slot]
    return (selected['count'] == count and proof.get('initial_count') == old[slot]['count']
            and proof.get('final_count') == count and proof.get('selected_slot') == slot
            and (selected['empty'] is True and selected['id'] in ('', 'minecraft:air') if count == 0 else
                 selected['empty'] is False and selected['id'] == BLOCK
                 and selected['component_fingerprint'] == old[slot]['component_fingerprint']))


def place_local(runtime, support, face, expected_support_id, expected_support_properties,
                expected_block_id, expected_block_properties):
    """The caller selects the exact support and face. Native admission owns geometry."""
    require(getattr(runtime, '_job_scoped_profiles', {}).get('place_block') == PROFILE,
            'scoped_placement_profile_not_negotiated')
    require(getattr(runtime, 'required_execution_policy', None) == 'request_only',
            'scoped_placement_request_only_required')
    require(type(support) is dict and set(support) == {'x','y','z'}, 'placement_exact_support_required')
    support = reach.coordinate(support)
    require(-2048 <= support['y'] <= 2048, 'placement_support_out_of_bounds')
    require(face in reach.FACES and expected_support_id in BLOCKS and expected_support_properties == {},
            'placement_static_support_and_face_required')
    require(expected_block_id == BLOCK and expected_block_properties == {}, 'placement_plain_cobblestone_required')
    target = {k: support[k] + reach.FACES[face][i] for i,k in enumerate(('x','y','z'))}
    require(-2048 <= target['y'] <= 2048 and abs(target['x']) <= 30000000 and abs(target['z']) <= 30000000,
            'placement_target_out_of_bounds')
    hit = {k: support[k] + .5 + reach.FACES[face][i] * .5 for i,k in enumerate(('x','y','z'))}
    before = runtime.observe(terrain=False)
    require(before.context[1] == 'minecraft:overworld', 'placement_overworld_required')
    rows = _inventory(before)
    slot = before.player.get('selected_slot')
    require(type(slot) is int and 0 <= slot <= 8, 'placement_selected_slot_required')
    held = rows[slot]
    require(held.get('id') == BLOCK and held.get('empty') is False and 1 <= held['count'] <= 64
            and held.get('max_stack_size') == 64, 'placement_selected_cobblestone_required')
    command = {'op':'action', 'action':'place_block', 'support':support, 'face':face,
        'expected_support_id':expected_support_id, 'expected_support_properties':deepcopy(expected_support_properties),
        'expected_block_id':BLOCK, 'expected_block_properties':{},
        'expected_target_id':'minecraft:air', 'expected_target_properties':{}, 'placement_hit':hit,
        'placement_footprint':[{'position':target, 'expected_id':'minecraft:air', 'expected_properties':{},
                                'block_id':BLOCK, 'properties':{}}], 'timeout_ms':2000}
    outcome = runtime.execute('building.place_local', command,
        lambda old,new: _placed(old,new,target,slot), before=before, stable_samples=2, max_samples=8)
    return Outcome(outcome.status, outcome.reason, outcome.request_ids,
        {**outcome.evidence, 'profile':PROFILE, 'target':target, 'support':support, 'face':face,
         'scope':'one_stationary_cobblestone_placement', 'automatic_replay_allowed':False,
         'server_confirmed':False}, outcome.last_observation)

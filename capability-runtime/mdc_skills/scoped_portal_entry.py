"""Exact prepared flat portal entry. Natural End drops and credits are deliberately unsupported."""
from copy import deepcopy
from . import dimensions
from .core import Outcome, require
from .scoped_placement import _inventory
from .scoped_item_interaction import _point, _exact

PROFILE = 'portal-entry-observed-v1'
CONTRACT = 'flat-supported-max-two-blocks-v1'
TRANSITIONS = {(dimensions.OVERWORLD, dimensions.NETHER): 'minecraft:nether_portal',
               (dimensions.NETHER, dimensions.OVERWORLD): 'minecraft:nether_portal',
               (dimensions.OVERWORLD, dimensions.END): 'minecraft:end_portal',
               (dimensions.END, dimensions.OVERWORLD): 'minecraft:end_portal'}


def _arrived(before, after, destination):
    p = after.player
    native = after.state.get('client_action', {})
    result = native.get('result', {})
    proof = result.get('portal_entry', {})
    same = (before.context[2:] == after.context[2:]
            and before.state['world'].get('integrated_server_instance') == after.state['world'].get('integrated_server_instance'))
    return (same and after.context[1] == destination and before.context[0] != after.context[0]
        and p.get('alive') is True and p.get('on_ground') is True
        and all(p.get(k) is False for k in dimensions.threats.ENVIRONMENT_FLAGS)
        and p.get('health', 0) >= before.player.get('health', 0)
        and _exact(_inventory(before), _inventory(after))
        and all(_exact(before.player.get(k), p.get(k)) for k in ('selected_slot', 'offhand', 'armor'))
        and native.get('action') == 'follow_path' and native.get('status') == 'cancelled'
        and native.get('reason') in ('world_changed','world_or_player_changed','world_transition','capability_world_changed','capability_dimension_changed')
        and proof.get('original_native_action_id') == native.get('action_id') and isinstance(native.get('action_id'), str)
        and proof.get('original_action_session') == before.context[3] == native.get('action_session')
        and proof.get('original_player_uuid') == before.context[2]
        and proof.get('source_world_generation') == before.context[0] and proof.get('source_dimension') == before.context[1]
        and proof.get('integrated_server_instance') == before.state['world'].get('integrated_server_instance')
        and proof.get('entry_contract') == CONTRACT
        and result.get('input_release_confirmed') is True and proof.get('profile') == PROFILE
        and proof.get('destination') == destination and proof.get('effect_attempted') is True
        and proof.get('transition_eligible') is True and proof.get('source_portal_contact') is True
        and proof.get('input_neutral') is True and proof.get('unknown_outcome') is False
        and proof.get('automatic_replay_allowed') is False and proof.get('server_confirmed') is False)


def enter_portal_local(runtime, portal_cell, destination, *, timeout_ms=8000):
    require(runtime.scoped_profile('follow_path') == PROFILE, 'portal_entry_profile_not_negotiated')
    require(getattr(runtime, 'required_execution_policy', None) == 'request_only', 'portal_entry_request_only_required')
    require(type(timeout_ms) is int and 5000 <= timeout_ms <= 8000, 'portal_entry_timeout_5000_to_8000')
    cell = _point(portal_cell)
    before = runtime.observe(terrain=True, radius=4, vertical=4)
    source = dimensions._dimension(before)
    kind = TRANSITIONS.get((source, destination))
    require(kind is not None, 'portal_entry_unsupported_dimension_pair')
    portal = dimensions.block_at(before, cell)
    require(portal['id'] == kind and (portal['properties'] == {} if kind == 'minecraft:end_portal'
            else set(portal['properties']) == {'axis'} and portal['properties']['axis'] in ('x', 'z')),
            'portal_entry_exact_observed_portal_required')
    point = dimensions._portal_corridor(before, cell)
    import math
    x,y,z = dimensions.threats.position(before.player)
    require(abs(x-math.floor(x)-.5)<=.10 and abs(z-math.floor(z)-.5)<=.10
            and abs(y-round(y))<1e-7 and math.hypot(point['x']-x,point['z']-z)>.23,
            'portal_entry_centered_origin_outside_target_required')
    _inventory(before)
    command = {'op': 'action', 'action': 'follow_path', 'waypoints': [{**point, 'jump': False}],
        'typed_portal_entry': {'portal_cell': cell, 'portal_id': kind,
            'portal_properties': deepcopy(portal['properties']), 'destination': destination, 'entry_contract': CONTRACT},
        'timeout_ms': timeout_ms}
    result = runtime.execute('dimensions.enter_portal', command,
        lambda old, new: _arrived(old, new, destination), before=before,
        allowed_dimension=destination, max_samples=128, stable_samples=3)
    return Outcome(result.status, result.reason, result.request_ids,
        {**result.evidence, 'profile': PROFILE, 'destination': destination, 'portal_cell': cell,
         'entry_contract': CONTRACT, 'automatic_replay_allowed': False,
         'natural_end_drop_supported': False, 'server_confirmed': False}, result.last_observation)

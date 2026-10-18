"""Typed interaction goals. Public JSON never includes an executable verifier."""
from copy import deepcopy
import hashlib
from pathlib import Path
from mdc_skills import reach, interaction_goals
from mdc_toolbox.contracts import validate_schema, ToolboxError, obj, integer
from .inventory import ITEM, _definition

COORDINATE = obj({k: integer(-30000000, 30000000) for k in ('x', 'y', 'z')}, ('x', 'y', 'z'))
_SCHEMAS = {
    'close_menu': obj(),
    'interact': obj({'target': COORDINATE, 'goal': interaction_goals.BLOCK_MENU_GOAL_SCHEMA,
        'face': {'enum': sorted(reach.FACES), 'default': 'up'},
        'expected_block_id': {'enum': sorted(interaction_goals.BLOCK_MENU_FAMILIES)},
        'expected_block_properties': {'type': 'object', 'maxProperties': 32,
            'propertyNames': {'pattern': '^[a-z0-9_]+$', 'maxLength': 64},
            'additionalProperties': {'type': 'string', 'minLength': 1, 'maxLength': 64}},
        'hotbar_slot': integer(0, 8)}, ('target', 'goal', 'expected_block_id', 'expected_block_properties')),
}


def definitions():
    output = [
        _definition('close_menu', _SCHEMAS['close_menu'], group='interaction', level='primitive', profile='menu',
            description='Close the exact menu only with an empty cursor and prove the closed state.',
            source='reach.py', actions=['close_menu'], bounds={'max_mutations': 1},
            limits=['Occupied cursor refuses closure; empty closed menu is an observed no-op.']),
        _definition('interact', _SCHEMAS['interact'], group='interaction', level='primitive', profile='menu',
            description='Open one supported vanilla block menu while stationary using native block-menu-v1 admission.',
            source='interaction_goals.py', actions=['interact_block'], adapter='implemented',
            bounds={'max_mutations': 1, 'max_properties': 32, 'native_max_reach': 6,
                    'supported_blocks': sorted(interaction_goals.BLOCK_MENU_FAMILIES)},
            limits=['Requires negotiated block-menu-v1; no legacy terrain or diagnostic-clock fallback.',
                'Exact full target properties and expected menu class; native capture validates loaded geometry, reach and LOS.',
                'Grounded stationary player on a full dry support cell, closed inventory, empty main/offhand; no slot switch.',
                'Existing native aim is followed by exact actual renderer ray and post-hook checks before one click.',
                'Chest/double chest, hopper, shulker, modded blocks and all block-toggle goals are unsupported.',
                'Native dispatch is separate from later stable menu class/container/revision proof; no replay on a missing menu.'])]
    root = Path(__file__).resolve().parents[2]
    for entry in output:
        if entry['capability'] == 'interact':
            entry['native_features'] += ['scoped-native-preflight/1', 'profile:block-menu-v1']
            entry['requirements'] = {'empty_mainhand': True, 'empty_offhand': True,
                'closed_inventory': True, 'public_preparation_capability': 'clear_hand',
                'preparation_arguments': {'hand': 'both'}, 'automatic_preparation': False}
            entry['blocked_reasons'] = ['block_menu_empty_unchanged_hands_required']
        else:
            entry['requirements'] = {'empty_cursor': True, 'public_recovery_capability': 'recover_cursor',
                'fresh_exact_cursor_and_window_required': True, 'automatic_recovery': False}
            entry['blocked_reasons'] = ['inventory_cursor_not_empty', 'capability_cursor_not_empty']
        for p in (Path(__file__), root / 'mdc_skills' / 'reach.py'):
            value = {'path': 'capability-runtime/' + str(p.relative_to(root)),
                     'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
            if value not in entry['source_fingerprints']:
                entry['source_fingerprints'].append(value)
    return output


_DISPATCH = {'close_menu': reach.close_menu, 'interact': interaction_goals.interact}


def invoke(capability, runtime, arguments, control):
    if capability not in _DISPATCH:
        raise ToolboxError('capability_unavailable', 'Unknown interaction capability')
    validate_schema(arguments, _SCHEMAS[capability])
    control.checkpoint()
    kwargs = deepcopy(arguments)
    if capability == 'interact':
        kwargs['stationary_menu'] = True
    result = _DISPATCH[capability](runtime, **kwargs)
    control.emit('interaction_goal_observed' if result.ok else 'interaction_goal_stopped', {
        'capability': capability, 'status': result.status, 'reason': result.reason,
        'request_ids': list(result.request_ids)})
    return result

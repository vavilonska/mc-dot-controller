"""Closed public inventory/container bindings; no import-time runtime access."""
from copy import deepcopy
import hashlib
from pathlib import Path
from mdc_skills import inventory as skills
from mdc_skills import container, inventory_recovery
from mdc_skills.stack_selector import SELECTOR_SCHEMA, ITEM_PATTERN
from mdc_toolbox.contracts import validate_schema, ToolboxError, obj, integer

ITEM = {'type': 'string', 'pattern': ITEM_PATTERN, 'maxLength': 128}
RESULT_SCHEMA = obj({
    'status': {'enum': ['succeeded', 'blocked', 'failed', 'cancelled', 'interrupted', 'unknown']},
    'reason': {'type': 'string', 'maxLength': 4096},
    'request_ids': {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 32768},
    'evidence': {'type': 'object'}, 'server_confirmed': {'const': False},
    'observation_ref': {'type': ['object', 'null']}},
    ('status', 'reason', 'request_ids', 'evidence', 'server_confirmed'))
COMMON_LIMITS = ['Private singleplayer and original Runtime guard required; client-observed evidence only.',
    'No automatic retry/resume after interruption or unknown outcome.',
    'Input release and ownership cleanup are separate from semantic success.']


def _definition(name, schema, *, description, actions, level='bounded_composite',
                profile='inventory', limits=(), bounds=None, source='inventory.py', group='inventory',
                adapter='implemented'):
    root = Path(__file__).resolve().parents[2]
    paths = [root / 'mdc_skills' / source, Path(__file__)]
    if source in ('inventory.py', 'inventory_recovery.py'):
        paths.append(root / 'mdc_skills' / 'stack_selector.py')
    if source == 'inventory_recovery.py':
        paths += [root / 'mdc_skills' / name for name in ('inventory.py', 'container.py')]
    return {'capability': name, 'capability_version': 1, 'group': group, 'level': level,
        'description': description, 'input_schema': deepcopy(schema), 'result_schema': deepcopy(RESULT_SCHEMA),
        'observation_profile': profile, 'native_features': ['capability_guard/1'] + ['action:' + x for x in actions],
        'bounds': bounds or {}, 'prerequisites': ['owned_fresh_observation', 'private_singleplayer',
            'known_previous_action_outcome', 'exact_stack_fingerprints'],
        'cancel_granularity': 'native_exact_action_and_between_verified_steps', 'resume_supported': False,
        'planner_available': False, 'implementation_status': 'implemented', 'adapter_status': adapter,
        'known_limits': [*COMMON_LIMITS, *limits],
        'source_fingerprints': [{'path': 'capability-runtime/' + str(p.relative_to(root)),
                                 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths],
        'validation': {'offline': 'focused_tests_available', 'live': 'not_run'}}


_RECOVERY_REFERENCE = {'type': 'string', 'minLength': 1, 'maxLength': 128}
_SCHEMAS = {
    'clear_hand': obj({'hand': {'enum': ['mainhand', 'offhand', 'both'], 'default': 'both'},
                       'max_actions': {**integer(1, 74), 'default': 74}}),
    'recover_cursor': obj({'container_id': integer(0, 2147483647), 'menu_state_id': integer(0, 32767),
        'menu_instance': _RECOVERY_REFERENCE, 'screen_instance': _RECOVERY_REFERENCE,
        'cursor_fingerprint': _RECOVERY_REFERENCE, 'max_actions': {**integer(1, 36), 'default': 36}},
        ('container_id', 'menu_state_id', 'menu_instance', 'screen_instance', 'cursor_fingerprint')),
    'select_hotbar': obj({'slot': integer(0, 8)}, ('slot',)),
    'ensure_hotbar': obj({'item_id': ITEM, 'hotbar_slot': {**integer(0, 8), 'default': 0},
                          'selector': SELECTOR_SCHEMA}, ('item_id',)),
    'equip': obj({'item_id': ITEM, 'slot': {'enum': list(skills.EQUIPMENT)},
                  'selector': SELECTOR_SCHEMA}, ('item_id', 'slot')),
    'consume': obj({'item_id': {'enum': sorted(skills.FOODS | {'minecraft:potion', 'minecraft:milk_bucket'})},
                    'effect_id': ITEM, 'max_use_ticks': {**integer(1, 100), 'default': 40},
                    'selector': SELECTOR_SCHEMA}, ('item_id',)),
}
_SCHEMAS['consume']['allOf'] = [{'if': {'properties': {'item_id': {'const': 'minecraft:potion'}}},
                               'then': {'required': ['effect_id']}}]
_TRANSFER_SCHEMA = obj({'container_id': integer(0, 2147483647), 'menu_state_id': integer(0, 32767),
    'source_slot': integer(0, 127), 'destination_slot': integer(0, 127), 'quantity': integer(1, 64),
    'max_actions': {**integer(2, 66), 'default': 66}, 'selector': SELECTOR_SCHEMA},
    ('container_id', 'menu_state_id', 'source_slot', 'destination_slot', 'quantity'))
for _operation in container.OPERATIONS:
    _SCHEMAS['container_' + _operation] = deepcopy(_TRANSFER_SCHEMA)


def definitions():
    output = [
        _definition('select_hotbar', _SCHEMAS['select_hotbar'], level='primitive',
            description='Select an occupied observed hotbar slot and verify its exact stack.',
            actions=['select_hotbar'], bounds={'hotbar_slot': [0, 8]},
            limits=['Empty hotbar selection is unsupported.']),
        _definition('ensure_hotbar', _SCHEMAS['ensure_hotbar'],
            description='Select or swap a matching observed stack into the hotbar.',
            actions=['click_slot', 'select_hotbar'], bounds={'max_mutations': 2},
            limits=['Closed screen and empty cursor required; selector handles must still match fresh inventory.']),
        _definition('equip', _SCHEMAS['equip'], description='Equip observed armor/offhand with exact swap verification.',
            actions=['click_slot', 'select_hotbar'], bounds={'max_mutations': 3},
            limits=['Requires closed vanilla InventoryMenu; armor source must be a single item.']),
        _definition('consume', _SCHEMAS['consume'], description='Consume finite food, timed potion or milk and prove its effect.',
            actions=['click_slot', 'select_hotbar', 'use_item'], bounds={'max_use_ticks': 100, 'max_mutations': 3},
            limits=['Only the explicit food list, drinkable timed-effect potion and milk are supported.',
                    'Instant-effect, splash and lingering potions are unsupported.',
                    'Food requires increased hunger; potion requires matching timed effect and bottle; milk requires cleared effects and bucket.'])]
    for name, description in (
            ('clear_hand', 'Clear main hand, offhand or both through conserved ordinary vanilla pickups.'),
            ('recover_cursor', 'Explicitly store the exact observed cursor stack in player storage.')):
        entry = _definition(name, _SCHEMAS[name], description=description, actions=['click_slot'],
            profile='menu', source='inventory_recovery.py', bounds={'max_actions': 74 if name == 'clear_hand' else 36,
                'max_observations_per_click': 8, 'supported_menu_classes': sorted(container.SUPPORTED_MENUS)},
            limits=['Whole 36-slot storage capacity and complete transaction budgets are checked before any click.',
                    'All slots, cursor, equipment, selection, menu instance and screen instance are bound.',
                    'clear_hand requires closed InventoryMenu and empty cursor; recover_cursor requires an exact current cursor/window reference.',
                    'Only vanilla storage menus or closed InventoryMenu; no production menus, drops, creative edits or replay.',
                    'Unknown previous execution must be reconciled before a separate explicitly requested recovery.'])
        entry['native_features'].append(inventory_recovery.FEATURE)
        entry['prerequisites'] += ['complete_inventory_and_menu', 'whole_transaction_capacity_and_budget',
                                  'native_inventory_recovery_v1']
        entry['requirements'] = {'public_route': name, 'native_feature': inventory_recovery.FEATURE,
            'explicit_request_required': True, 'empty_cursor_required': name == 'clear_hand',
            'closed_inventory_required': name == 'clear_hand', 'unknown_outcome_blocks_recovery': True}
        entry['blocked_reasons'] = ['inventory_recovery_context_required',
            'inventory_recovery_insufficient_storage_capacity', 'inventory_recovery_expected_window_changed',
            'inventory_recovery_expected_cursor_changed', 'inventory_recovery_shared_action_budget_insufficient_before_start',
            'inventory_recovery_shared_observation_budget_insufficient_before_start']
        entry['normal_fallback'] = {'automatic': False,
            'instruction': 'If unavailable or blocked, stop and use an explicitly authorized ordinary inventory interaction; preserve items and reconcile unknown original actions first.'}
        output.append(entry)
    for operation in container.OPERATIONS:
        name = 'container_' + operation
        output.append(_definition(name, _SCHEMAS[name], profile='menu', source='container.py',
            description='Bounded exact-slot ' + operation + ' with component conservation and empty final cursor.',
            actions=['click_slot'], bounds={'quantity': [1, 64], 'max_actions': [2, 66], 'max_observations_per_click': 8,
                'supported_menu_classes': sorted(container.SUPPORTED_MENUS)},
            limits=['Exact vanilla ChestMenu, HopperMenu, DispenserMenu, ShulkerBoxMenu and closed InventoryMenu only.',
                'Source/destination are actual menu indices; supplied container ID and revision must match a fresh read.',
                'No quick-move, drops, production/output/crafting/armor slots, modded subclasses or arbitrary slot rules.',
                'Capacity is conservatively min(64, observed source max_stack_size); destination must be empty or identical components.',
                'Shulker-box items cannot be deposited into shulker storage. Menu is left open.',
                'Original shared budgets must cover the full click sequence and up to eight verification observations per click before pickup.',
                'Conservation covers all observed menu slots and the cursor, with mapped player storage cross-checked.',
                'A stopped partial transfer may retain cursor items; no automatic placement, cleanup or replay.']))
    return output


_DISPATCH = {'select_hotbar': skills.select_hotbar, 'ensure_hotbar': skills.ensure_hotbar,
             'equip': skills.equip, 'consume': skills.consume}


def invoke(capability, runtime, arguments, control):
    if capability not in _SCHEMAS:
        raise ToolboxError('capability_unavailable', 'Unknown inventory capability')
    validate_schema(arguments, _SCHEMAS[capability])
    control.checkpoint()
    if capability in ('clear_hand', 'recover_cursor'):
        result = getattr(inventory_recovery, capability)(runtime, control=control, **deepcopy(arguments))
    elif capability in _DISPATCH:
        result = _DISPATCH[capability](runtime, **deepcopy(arguments))
    else:
        result = container.transfer(runtime, operation=capability.removeprefix('container_'),
                                    control=control, **deepcopy(arguments))
    control.emit('inventory_goal_observed' if result.ok else 'inventory_goal_stopped', {
        'capability': capability, 'status': result.status, 'reason': result.reason,
        'request_ids': list(result.request_ids)})
    return result

"""Bounded exact-slot transfers through existing guarded native click_slot.

Only exact vanilla storage menus are supported. Special production, armor and
modded slots are refused before mutation. Every click proves full component
conservation and the exact intended slot/cursor delta. Stops preserve partial
contents and original request IDs; no retry, rollback, drop or automatic close.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from .core import Outcome, SkillError, require
from .inventory import items, _inventory_item
from .stack_selector import matches, validate_selector

PREFIX = 'net.minecraft.world.inventory.'
SUPPORTED_MENUS = {
    PREFIX + 'ChestMenu': (9, 18, 27, 36, 45, 54),
    PREFIX + 'HopperMenu': (5,),
    PREFIX + 'DispenserMenu': (9,),
    PREFIX + 'ShulkerBoxMenu': (27,),
    PREFIX + 'InventoryMenu': (5,),
}
OPERATIONS = ('move', 'withdraw', 'deposit', 'split', 'merge')


def _stack(value):
    require(type(value) is dict and type(value.get('count')) is int
            and 0 <= value['count'] <= 99, 'container_invalid_stack_count')
    require(all(type(value.get(k)) is str and 0 < len(value[k]) <= 128
                for k in ('item_fingerprint', 'component_fingerprint')),
            'container_exact_stack_bindings_required')
    count = value['count']
    if not count:
        require(value.get('empty') is True, 'container_ambiguous_empty_stack')
        return ('', '', 0)
    require(value.get('empty') is False and type(value.get('id')) is str
            and value['id'].startswith('minecraft:')
            and type(value.get('max_stack_size')) is int
            and count <= value['max_stack_size'] <= 99, 'container_invalid_stack_identity_or_capacity')
    return value['id'], value['component_fingerprint'], count


def _quantity(stack, count):
    return (stack[0], stack[1], count) if count else ('', '', 0)


class _View:
    def __init__(self, observation):
        self.observation = observation
        self.menu = deepcopy(observation.state.get('menu', {}))
        m = self.menu
        require(m.get('menu_class') in SUPPORTED_MENUS, 'container_menu_unsupported')
        inventory_menu = m['menu_class'] == PREFIX + 'InventoryMenu'
        require(type(m.get('container_id')) is int
                and (m['container_id'] == 0 if inventory_menu else m['container_id'] > 0),
                'container_identity_invalid')
        require(observation.state.get('screen_open') is (not inventory_menu),
                'container_screen_state_unsupported')
        require(type(m.get('state_id')) is int and 0 <= m['state_id'] <= 32767,
                'container_menu_revision_required')
        require(m.get('slots_truncated') is False and type(m.get('slots')) is list
                and type(m.get('slots_total')) is int and m['slots_total'] == len(m['slots'])
                and m.get('slots_returned') == len(m['slots']), 'container_complete_topology_required')
        self.slots = {}
        player_mapping = {}
        external = []
        for row in m['slots']:
            require(type(row) is dict and type(row.get('menu_index')) is int
                    and row['menu_index'] not in self.slots and type(row.get('slot_index')) is int
                    and type(row.get('container_slot')) is int and type(row.get('active')) is bool
                    and type(row.get('player_inventory')) is bool, 'container_slot_mapping_invalid')
            self.slots[row['menu_index']] = row
            _stack(row.get('item'))
            if row['player_inventory']:
                index = row.get('inventory_index')
                require(type(index) is int and index not in player_mapping
                        and row['container_slot'] == index, 'container_inventory_mapping_ambiguous')
                player_mapping[index] = row
            else:
                require('inventory_index' not in row, 'container_external_slot_mapping_invalid')
                external.append(row)
        require(set(self.slots) == set(range(len(self.slots))), 'container_menu_indices_incomplete')
        expected_player = set(range(41 if inventory_menu else 36))
        require(set(player_mapping) == expected_player, 'container_player_storage_mapping_incomplete')
        require(len(external) in SUPPORTED_MENUS[m['menu_class']], 'container_storage_topology_unsupported')
        if not inventory_menu:
            require({row['container_slot'] for row in external} == set(range(len(external))),
                    'container_storage_mapping_ambiguous')
        else:
            # Exact vanilla inventory: result at menu 0, 2x2 craft at 1..4.
            require({row['menu_index'] for row in external} == set(range(5)),
                    'container_inventory_crafting_topology_unsupported')
        observed_items = items(observation)
        require({r.get('slot') for r in observed_items} == set(range(36)),
                'container_complete_player_inventory_required')
        for index, row in player_mapping.items():
            actual = _inventory_item(observation, index)
            require(_stack(actual) == _stack(row['item'])
                    and actual['item_fingerprint'] == row['item']['item_fingerprint'],
                    'container_menu_inventory_disagree')
        self.carried = _stack(m.get('carried'))
        self.values = {i: _stack(row['item']) for i, row in self.slots.items()}
        self.identity = (tuple(observation.context), m['container_id'], m['menu_class'])
        self.topology = tuple((i, row['slot_index'], row['container_slot'], row['player_inventory'],
                               row.get('inventory_index'), row['active'], row.get('may_place'),
                               row.get('may_pickup')) for i, row in sorted(self.slots.items()))

    def counts(self):
        result = Counter()
        for item_id, component, count in [*self.values.values(), self.carried]:
            if count:
                result[(item_id, component)] += count
        return result

    def endpoint(self, index):
        require(type(index) is int and index in self.slots, 'container_slot_not_observed')
        row = self.slots[index]
        require(row['active'] is True, 'container_inactive_slot')
        if row['player_inventory']:
            require(0 <= row['inventory_index'] <= 35, 'container_special_player_slot_disallowed')
        else:
            require(self.menu['menu_class'] != PREFIX + 'InventoryMenu', 'container_crafting_slot_disallowed')
        return row


def _verify_step(original, expected, carried, after):
    try:
        current = _View(after)
        if not (current.identity == original.identity and current.topology == original.topology
                and current.values == expected and current.carried == carried
                and current.counts() == original.counts()):
            return False
        for index, value in original.values.items():
            if value == current.values[index] and original.slots[index]['item']['item_fingerprint'] != current.slots[index]['item']['item_fingerprint']:
                return False
        return True
    except (SkillError, KeyError, TypeError):
        return False


def _partial(skill, outcomes, observation, reason, status, **facts):
    ids = tuple(dict.fromkeys(rid for outcome in outcomes for rid in outcome.request_ids))
    menu = observation.state.get('menu', {}) if observation is not None else {}
    return Outcome(status, reason, ids, {
        **(deepcopy(outcomes[-1].evidence) if outcomes else {}),
        'stages': [{'status': o.status, 'reason': o.reason, 'request_ids': list(o.request_ids),
                    'evidence': deepcopy(o.evidence)} for o in outcomes],
        'skill': skill, 'server_confirmed': False, 'auto_cleanup_attempted': False,
        'completed_clicks': sum(outcome.ok for outcome in outcomes),
        'original_requests': [list(outcome.request_ids) for outcome in outcomes],
        'last_observed_carried': deepcopy(menu.get('carried')),
        'last_observed_menu_state_id': menu.get('state_id'),
        'continuation': 'reconcile_original_id_required' if status == 'unknown' else 'fresh_replan_required',
        'public_recovery': {'capability': 'recover_cursor', 'automatic': False,
            'blocked_by_unknown_original': status == 'unknown',
            'requires': ['known_original_outcome', 'confirmed_owner_release', 'fresh_exact_cursor_and_window',
                         'native_inventory_recovery_v1']},
        **facts}, observation)


def transfer(runtime, *, operation='move', container_id, menu_state_id, source_slot,
             destination_slot, quantity, max_actions=66, selector=None, control=None):
    """Move an exact quantity between caller-selected observed menu slot indices."""
    require(operation in OPERATIONS, 'container_operation_unsupported')
    require(type(container_id) is int and 0 <= container_id <= 2147483647
            and type(menu_state_id) is int and 0 <= menu_state_id <= 32767,
            'container_expected_identity_required')
    require(type(quantity) is int and 1 <= quantity <= 64, 'container_quantity_must_be_1_to_64')
    require(type(max_actions) is int and 2 <= max_actions <= 66, 'container_action_budget_must_be_2_to_66')
    selector = validate_selector(selector)
    if control:
        control.checkpoint()
    first = observation = runtime.observe(allow_menu=True)
    view = _View(observation)
    require(view.menu['container_id'] == container_id and view.menu['state_id'] == menu_state_id,
            'container_expected_menu_revision_changed')
    require(view.carried[2] == 0, 'container_cursor_not_empty')
    source, destination = view.endpoint(source_slot), view.endpoint(destination_slot)
    require(source_slot != destination_slot, 'container_distinct_slots_required')
    require(source.get('may_pickup') is not False and destination.get('may_place') is not False,
            'container_slot_rules_disallow_transfer')
    require(source.get('may_place') is not False, 'container_source_return_disallowed')
    src, dst = view.values[source_slot], view.values[destination_slot]
    require(src[2] >= quantity, 'container_source_quantity_unavailable')
    selected = dict(source['item'])
    if source['player_inventory']:
        selected['slot'] = source['inventory_index']
    require(matches(selected, selector), 'container_source_selector_mismatch')
    require(dst[2] == 0 or src[:2] == dst[:2], 'container_destination_components_differ')
    # Supported vanilla generic storage Slot semantics, conservatively cap at64.
    capacity = min(64, source['item']['max_stack_size'])
    require(dst[2] + quantity <= capacity, 'container_destination_full')
    if view.menu['menu_class'] == PREFIX + 'ShulkerBoxMenu':
        shulker = src[0] == 'minecraft:shulker_box' or src[0].endswith('_shulker_box')
        require(not (shulker and not destination['player_inventory']), 'container_nested_shulker_disallowed')
    if operation == 'withdraw':
        require(not source['player_inventory'] and destination['player_inventory'], 'container_withdraw_direction_invalid')
    elif operation == 'deposit':
        require(source['player_inventory'] and not destination['player_inventory'], 'container_deposit_direction_invalid')
    elif operation == 'split':
        require(dst[2] == 0 and quantity < src[2], 'container_split_requires_empty_destination_and_remainder')
    elif operation == 'merge':
        require(dst[2] > 0, 'container_merge_requires_existing_destination')
    steps = [(source_slot, 0)]
    if quantity == src[2]:
        steps.append((destination_slot, 0))
    else:
        steps += [(destination_slot, 1)] * quantity + [(source_slot, 0)]
    require(len(steps) <= max_actions, 'container_action_budget_insufficient_before_start')
    if control is not None and getattr(control, 'budget', None) is not None:
        ledger = control.budget.snapshot()
        limits, used, remaining = ledger['limits'], ledger['used']['ordinary'], ledger['remaining']
        action_allowance = min(remaining['actions'], limits['max_actions']
            - limits['reflex_reserve_actions'] - limits['cleanup_reserve_actions'] - used['actions'])
        observation_allowance = min(remaining['observations'],
            limits['max_observations'] - 1 - used['observations'])
        require(action_allowance >= len(steps), 'container_shared_action_budget_insufficient_before_start')
        # execute() may use its original eight-sample bound for each click.
        # Initial observe was already charged; result() adds no further read.
        require(observation_allowance >= 8 * len(steps),
                'container_shared_observation_budget_insufficient_before_start')
    skill = 'container.' + operation
    outcomes = []
    expected = dict(view.values)
    cursor = view.carried
    initial_counts = view.counts()
    try:
        for index, button in steps:
            if control:
                control.checkpoint()
            old_value = expected[index]
            if not cursor[2]:
                cursor, expected[index] = old_value, ('', '', 0)
            else:
                amount = cursor[2] if button == 0 else 1
                expected[index] = _quantity(cursor, old_value[2] + amount)
                cursor = _quantity(cursor, cursor[2] - amount)
            target_values, target_cursor = dict(expected), cursor
            command = {'op': 'action', 'action': 'click_slot', 'container_id': container_id,
                'slot': index, 'button': button, 'click_type': 'pickup', 'timeout_ms': 3000,
                'expected_menu_state_id': view.menu['state_id'],
                'expected_slot_item': deepcopy(view.slots[index]['item']),
                'expected_carried': deepcopy(view.menu['carried'])}
            original = view
            outcome = runtime.execute(skill, command,
                lambda _before, after, original=original, target_values=target_values, target_cursor=target_cursor:
                    _verify_step(original, target_values, target_cursor, after),
                before=observation, allow_menu=True)
            outcomes.append(outcome)
            if not outcome.ok:
                return _partial(skill, outcomes, outcome.last_observation, outcome.reason, outcome.status)
            observation = runtime.require_success(outcome)
            view = _View(observation)
            if control:
                control.emit('container_click_observed', {'operation': operation, 'slot': index,
                    'completed_clicks': len(outcomes), 'carried_count': view.carried[2],
                    'request_ids': list(outcome.request_ids), 'menu_state_id': view.menu['state_id']})
        require(view.carried[2] == 0 and view.counts() == initial_counts, 'container_final_conservation_failed')
        if control:
            control.checkpoint()
        verified = runtime.result(skill, [first, observation], operation=operation, quantity=quantity,
            source_slot=source_slot, destination_slot=destination_slot, component_fingerprint=src[1],
            total_conserved=True, conservation_scope='observed_menu_slots_and_cursor',
            cursor_empty=True, performed_clicks=len(outcomes),
            supported_menu_class=view.menu['menu_class'], continuation='none')
        ids = tuple(dict.fromkeys(rid for result in [*outcomes, verified] for rid in result.request_ids))
        return Outcome(verified.status, verified.reason, ids, verified.evidence, observation)
    except SkillError as exc:
        if outcomes:
            return _partial(skill, outcomes, observation, exc.reason, exc.status)
        raise

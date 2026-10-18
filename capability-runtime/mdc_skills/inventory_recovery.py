"""Explicit state-bound vanilla hand clearing and cursor storage; never rollback/replay."""
from __future__ import annotations
from copy import deepcopy
import re
from .core import Outcome, SkillError, require
from . import container
from .inventory import _inventory_item

FEATURE = 'inventory-recovery/1'
_UUID = re.compile(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}')


class View(container._View):
    def __init__(self, observation):
        super().__init__(observation)
        context = self.menu.get('recovery_context')
        require(type(context) is dict and set(context) == {'schema_version', 'menu_instance', 'screen_instance', 'screen_open'}
                and type(context.get('schema_version')) is int and context['schema_version'] == 1
                and type(context.get('menu_instance')) is str and _UUID.fullmatch(context['menu_instance'])
                and type(context.get('screen_instance')) is str
                and (context['screen_instance'] == 'none' or _UUID.fullmatch(context['screen_instance']))
                and context.get('screen_open') is observation.state['screen_open']
                and (context['screen_instance'] == 'none') is (not observation.state['screen_open']),
                'inventory_recovery_context_required')
        self.selected = observation.player.get('selected_slot')
        require(type(self.selected) is int and 0 <= self.selected <= 8,
                'inventory_recovery_selection_required')
        self.inventory = {i: deepcopy(_inventory_item(observation, i)) for i in range(41)}
        for value in self.inventory.values():
            container._stack(value)
        self.identity += (context['menu_instance'], context['screen_instance'], self.selected)
        self.unmapped = {i: container._stack(value) for i, value in self.inventory.items()
                         if not any(row.get('inventory_index') == i for row in self.slots.values())}

    def binding(self, phase):
        return {'schema_version': 1, 'phase': phase,
                'context': deepcopy(self.menu['recovery_context']), 'selected_slot': self.selected,
                'inventory': [{'slot': i, 'item_fingerprint': value['item_fingerprint']}
                              for i, value in self.inventory.items()],
                'slots': [{'menu_index': i, 'slot_index': row['slot_index'],
                           'container_slot': row['container_slot'],
                           'player_inventory': row['player_inventory'], 'active': row['active'],
                           **({'inventory_index': row['inventory_index']} if row['player_inventory'] else {}),
                           'item_fingerprint': row['item']['item_fingerprint']}
                          for i, row in sorted(self.slots.items())]}


def _verify(original, expected, cursor, after):
    try:
        current = View(after)
        return (current.identity == original.identity and current.topology == original.topology
                and current.unmapped == original.unmapped and current.values == expected
                and current.carried == cursor and current.counts() == original.counts()
                and all(original.inventory[i]['item_fingerprint'] == current.inventory[i]['item_fingerprint']
                        for i in original.unmapped))
    except (SkillError, KeyError, TypeError, ValueError):
        return False


def _storage_steps(view, values, cursor, excluded):
    rows = [row for row in view.slots.values() if row['player_inventory']
            and 0 <= row['inventory_index'] <= 35 and row['inventory_index'] not in excluded
            and row['active'] is True and row.get('may_place') is not False]
    # Merge compatible stacks first, then use empty storage. Inspect the whole inventory.
    rows.sort(key=lambda row: (values[row['menu_index']][2] == 0, row['inventory_index']))
    capacity = min(64, next(value['max_stack_size'] for value in [view.menu['carried'],
        *view.inventory.values()] if container._stack(value)[:2] == cursor[:2] and value['count']))
    steps = []
    for row in rows:
        index = row['menu_index']; old = values[index]
        if old[2] and old[:2] != cursor[:2]:
            continue
        amount = min(cursor[2], max(0, capacity - old[2]))
        if not amount:
            continue
        values[index] = container._quantity(cursor, old[2] + amount)
        cursor = container._quantity(cursor, cursor[2] - amount)
        steps.append((index, 'store_cursor', dict(values), cursor))
        if not cursor[2]:
            return steps
    raise SkillError('inventory_recovery_insufficient_storage_capacity')


def _budget(control, steps, max_actions):
    require(type(max_actions) is int and 1 <= max_actions <= 74, 'inventory_recovery_invalid_action_budget')
    require(len(steps) <= max_actions, 'inventory_recovery_action_budget_insufficient_before_start')
    if control is None or getattr(control, 'budget', None) is None:
        return
    ledger = control.budget.snapshot()
    limits, used, remaining = ledger['limits'], ledger['used']['ordinary'], ledger['remaining']
    allowance = min(remaining['actions'], limits['max_actions'] - limits['reflex_reserve_actions']
                    - limits['cleanup_reserve_actions'] - used['actions'])
    require(allowance >= len(steps), 'inventory_recovery_shared_action_budget_insufficient_before_start')
    require(min(remaining['observations'], limits['max_observations'] - 1 - used['observations'])
            >= 8 * len(steps), 'inventory_recovery_shared_observation_budget_insufficient_before_start')


def _execute(runtime, first, view, steps, *, skill, control, max_actions):
    _budget(control, steps, max_actions)
    outcomes = []; observation = first
    try:
        for index, phase, expected, cursor in steps:
            if control:
                control.checkpoint()
            original = view
            command = {'op': 'action', 'action': 'click_slot', 'container_id': view.menu['container_id'],
                       'slot': index, 'button': 0, 'click_type': 'pickup', 'timeout_ms': 3000,
                       'expected_menu_state_id': view.menu['state_id'],
                       'expected_slot_item': deepcopy(view.slots[index]['item']),
                       'expected_carried': deepcopy(view.menu['carried']),
                       'inventory_recovery': view.binding(phase)}
            outcome = runtime.execute(skill, command,
                lambda _old, after, original=original, expected=expected, cursor=cursor:
                    _verify(original, expected, cursor, after), before=observation, allow_menu=True)
            outcomes.append(outcome)
            if not outcome.ok:
                return container._partial(skill, outcomes, outcome.last_observation, outcome.reason, outcome.status,
                    automatic_replay_allowed=False, recovery_requires_explicit_new_request=True)
            observation = runtime.require_success(outcome); view = View(observation)
            if control:
                control.emit('inventory_recovery_click_observed', {'phase': phase, 'slot': index,
                    'completed_clicks': len(outcomes), 'carried_count': view.carried[2],
                    'request_ids': list(outcome.request_ids)})
        require(view.carried[2] == 0, 'inventory_recovery_cursor_not_empty')
        if control:
            control.checkpoint()
        result = runtime.result(skill, [first, observation], total_conserved=True,
            conservation_scope='all_menu_slots_cursor_and_unmapped_equipment', cursor_empty=True,
            performed_clicks=len(outcomes), automatic_replay_allowed=False)
        ids = tuple(dict.fromkeys(rid for outcome in [*outcomes, result] for rid in outcome.request_ids))
        return Outcome(result.status, result.reason, ids, {**result.evidence,
            'stages': [{'status': o.status, 'reason': o.reason, 'request_ids': list(o.request_ids),
                        'evidence': deepcopy(o.evidence)} for o in outcomes]}, observation)
    except SkillError as exc:
        if outcomes:
            return container._partial(skill, outcomes, observation, exc.reason, exc.status,
                automatic_replay_allowed=False, recovery_requires_explicit_new_request=True)
        raise


def clear_hand(runtime, *, hand='both', max_actions=74, control=None):
    require(hand in ('mainhand', 'offhand', 'both'), 'inventory_recovery_invalid_hand')
    if control:
        control.checkpoint()
    first = runtime.observe(allow_menu=True); view = View(first)
    require(view.menu['menu_class'] == container.PREFIX + 'InventoryMenu'
            and first.state['screen_open'] is False, 'inventory_recovery_closed_inventory_required')
    require(not view.carried[2], 'inventory_recovery_clear_hand_requires_empty_cursor')
    sources = ([view.selected] if hand in ('mainhand', 'both') else []) + ([40] if hand in ('offhand', 'both') else [])
    excluded = {view.selected} if view.selected in sources else set()
    values = dict(view.values); steps = []
    # Plan every source before pickup. A second-hand capacity failure cannot leave a partial first hand.
    for source in sources:
        row = next(row for row in view.slots.values() if row.get('inventory_index') == source)
        index = row['menu_index']; cursor = values[index]
        if not cursor[2]:
            continue
        require(row['active'] is True and row.get('may_pickup') is not False,
                'inventory_recovery_hand_pickup_disallowed')
        values[index] = ('', '', 0)
        steps.append((index, 'pickup_hand', dict(values), cursor))
        steps += _storage_steps(view, values, cursor, excluded)
    result = _execute(runtime, first, view, steps, skill='inventory.clear_hand', control=control, max_actions=max_actions)
    if result.ok:
        require(all(_inventory_item(result.last_observation, i).get('empty') is True for i in sources),
                'inventory_recovery_hand_not_empty')
    return result


def recover_cursor(runtime, *, container_id, menu_state_id, menu_instance, screen_instance,
                   cursor_fingerprint, max_actions=36, control=None):
    require(type(container_id) is int and 0 <= container_id <= 2147483647
            and type(menu_state_id) is int and 0 <= menu_state_id <= 32767,
            'inventory_recovery_expected_menu_required')
    require(all(type(value) is str and 0 < len(value) <= 128
                for value in (menu_instance, screen_instance, cursor_fingerprint)),
            'inventory_recovery_expected_cursor_required')
    if control:
        control.checkpoint()
    first = runtime.observe(allow_menu=True); view = View(first)
    context = view.menu['recovery_context']
    require((container_id, menu_state_id, menu_instance, screen_instance) ==
            (view.menu['container_id'], view.menu['state_id'], context['menu_instance'], context['screen_instance']),
            'inventory_recovery_expected_window_changed')
    require(view.menu['carried']['item_fingerprint'] == cursor_fingerprint,
            'inventory_recovery_expected_cursor_changed')
    require(view.carried[2] > 0, 'inventory_recovery_cursor_already_empty')
    steps = _storage_steps(view, dict(view.values), view.carried, set())
    return _execute(runtime, first, view, steps, skill='inventory.recover_cursor', control=control, max_actions=max_actions)

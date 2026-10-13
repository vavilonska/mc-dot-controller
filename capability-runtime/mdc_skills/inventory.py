"""Observed inventory topology, guarded swaps/equipment and bounded consumables."""
from __future__ import annotations

from .core import Outcome, SkillError, require
from .stack_selector import selected_rows, validate_selector, matches as selector_matches, INSTANT_EFFECTS

EQUIPMENT = {'feet': 36, 'legs': 37, 'chest': 38, 'head': 39, 'offhand': 40}
FOODS = frozenset('minecraft:' + item for item in (
    'bread', 'apple', 'baked_potato', 'carrot', 'golden_carrot', 'cooked_beef',
    'cooked_porkchop', 'cooked_chicken', 'cooked_mutton', 'cooked_rabbit',
    'cooked_cod', 'cooked_salmon', 'pumpkin_pie', 'melon_slice', 'sweet_berries',
    'glow_berries', 'cookie', 'dried_kelp'))


def _combine(*outcomes):
    """Preserve all exact request IDs when composing already verified operations."""
    require(outcomes and all(outcome.ok for outcome in outcomes), 'cannot_combine_unverified_outcomes')
    last = outcomes[-1]
    ids = tuple(dict.fromkeys(rid for outcome in outcomes for rid in outcome.request_ids))
    return Outcome(last.status, last.reason, ids, {**last.evidence,
        'stages': [{'status': outcome.status, 'reason': outcome.reason,
                    'request_ids': list(outcome.request_ids), 'evidence': outcome.evidence}
                   for outcome in outcomes], 'server_confirmed': False}, last.last_observation)


def items(observation):
    p = observation.player
    require(p.get('inventory_truncated') is False and isinstance(p.get('inventory'), list),
            'complete_inventory_required')
    rows = p['inventory']
    require(len({row.get('slot') for row in rows}) == len(rows)
            and len(rows) == p.get('inventory_total'), 'inventory_slot_mapping_incomplete')
    return rows


def count(observation, item_id):
    return sum(item['count'] for item in items(observation) if item.get('id') == item_id)


def _same(a, b, *, count=True):
    if not isinstance(a, dict) or not isinstance(b, dict):
        return False
    key = 'item_fingerprint' if count else 'component_fingerprint'
    return bool(a.get(key)) and a.get(key) == b.get(key) and (
        a.get('count') == b.get('count') if count else True)


def _menu(observation):
    menu = observation.state.get('menu', {})
    require(menu.get('slots_truncated') is False and isinstance(menu.get('slots'), list),
            'complete_menu_required')
    require(type(menu.get('state_id')) is int and type(menu.get('container_id')) is int,
            'menu_revision_required')
    require(menu.get('carried', {}).get('empty') is True, 'inventory_cursor_not_empty')
    return menu


def _storage(menu, index):
    rows = [s for s in menu['slots'] if s.get('player_inventory') is True
            and s.get('inventory_index') == index and s.get('active') is True]
    require(len(rows) == 1, 'inventory_menu_mapping_missing_or_ambiguous')
    return rows[0]


def _inventory_item(observation, index):
    if index == 40:
        return observation.player.get('offhand', {})
    if index >= 36:
        name = next((k for k, v in EQUIPMENT.items() if v == index), None)
        return next((row for row in observation.player.get('armor', []) if row.get('slot') == name), {})
    return next((row for row in items(observation) if row.get('slot') == index), {})


def select_hotbar(runtime, slot):
    require(type(slot) is int and 0 <= slot <= 8, 'invalid_hotbar_slot')
    before = runtime.observe()
    selected = _inventory_item(before, slot)
    require(selected.get('empty') is False, 'selected_hotbar_empty')
    if before.player.get('selected_slot') == slot:
        return runtime.result('inventory.select_hotbar', [before], hotbar_slot=slot)
    return runtime.execute('inventory.select_hotbar', {'op': 'action', 'action': 'select_hotbar',
                           'hotbar_slot': slot, 'expected_held_item': selected,
                           'expected_hotbar_slot': before.player['selected_slot'], 'timeout_ms': 3000},
                           lambda old, new: new.player.get('selected_slot') == slot
                           and _same(selected, _inventory_item(new, slot)), before=before)


def _swap(runtime, before, source, destination):
    menu = _menu(before)
    src, dest = _storage(menu, source), _inventory_item(before, destination)
    require(destination in range(9) or destination == 40, 'swap_destination_must_be_hotbar_or_offhand')
    source_item = src['item']
    require(source_item.get('item_fingerprint') and dest.get('item_fingerprint'), 'item_binding_missing')
    command = {'op': 'action', 'action': 'click_slot', 'container_id': menu['container_id'],
               'slot': src['menu_index'], 'button': destination, 'click_type': 'swap',
               'expected_menu_state_id': menu['state_id'], 'expected_slot_item': source_item,
               'expected_carried': menu['carried'], 'expected_swap_item': dest, 'timeout_ms': 3000}
    def verify(old, new):
        try:
            updated = _menu(new)
            new_source = _storage(updated, source)['item']
        except SkillError:
            return False
        return (updated['container_id'] == menu['container_id']
                and _same(source_item, _inventory_item(new, destination)) and _same(dest, new_source))
    return runtime.execute('inventory.swap', command, verify, before=before, allow_menu=True)


def ensure_hotbar(runtime, item_id, *, hotbar_slot=0, selector=None):
    require(isinstance(item_id, str) and item_id.startswith('minecraft:'), 'item_id_required')
    require(type(hotbar_slot) is int and 0 <= hotbar_slot <= 8, 'invalid_hotbar_slot')
    before = runtime.observe(allow_menu=True)
    require(before.state.get('screen_open') is False, 'close_menu_before_hotbar_mutation')
    rows = selected_rows(before, item_id, selector)
    require(rows, 'observed_potion_effect_does_not_match_goal'
            if item_id == 'minecraft:potion' and selector and selector.get('effect_id')
            else 'requested_item_missing')
    hotbar = next((r for r in rows if 0 <= r['slot'] <= 8), None)
    if hotbar is not None:
        require(before.state.get('screen_open') is False, 'close_menu_before_hotbar_selection')
        return select_hotbar(runtime, hotbar['slot'])
    result = _swap(runtime, before, rows[0]['slot'], hotbar_slot)
    runtime.require_success(result)
    selected = select_hotbar(runtime, hotbar_slot)
    runtime.require_success(selected)
    return _combine(result, selected)


def equip(runtime, item_id, *, slot, selector=None):
    selector = validate_selector(selector)
    require(slot in EQUIPMENT, 'invalid_equipment_slot')
    before = runtime.observe(allow_menu=True)
    menu = _menu(before)
    require(menu.get('container_id') == 0 and menu.get('menu_class', '').endswith('InventoryMenu'),
            'player_inventory_menu_required')
    require(before.state.get('screen_open') is False, 'close_menu_before_equipment_mutation')
    destination = EQUIPMENT[slot]
    if ('inventory_slot' not in selector
            and _inventory_item(before, destination).get('id') == item_id
            and selector_matches(_inventory_item(before, destination), selector, check_slot=False)):
        return runtime.result('inventory.equip', [before], equipment_slot=slot, item_id=item_id)
    source = next(iter(selected_rows(before, item_id, selector)), None)
    require(source is not None, 'equipment_item_missing')
    if destination == 40:
        return _swap(runtime, before, source['slot'], destination)
    # Use vanilla SWAP with an observed armor menu slot and observed hotbar.
    ready = ensure_hotbar(runtime, item_id, selector=selector)
    before = runtime.require_success(ready)
    menu = _menu(before)
    armor = _storage(menu, destination)
    hotbar_slot = before.player['selected_slot']
    held = _inventory_item(before, hotbar_slot)
    previous = armor['item']
    require(held.get('count') == 1, 'armor_item_must_be_single')
    equipped = runtime.execute('inventory.equip', {'op': 'action', 'action': 'click_slot',
                           'container_id': menu['container_id'], 'slot': armor['menu_index'],
                           'button': hotbar_slot, 'click_type': 'swap',
                           'expected_menu_state_id': menu['state_id'], 'expected_slot_item': previous,
                           'expected_swap_item': held, 'expected_carried': menu['carried'], 'timeout_ms': 3000},
                           lambda old, new: _same(held, _inventory_item(new, destination))
                           and _same(previous, _inventory_item(new, hotbar_slot))
                           and new.state.get('menu', {}).get('carried', {}).get('empty') is True,
                           before=before, allow_menu=True)
    runtime.require_success(equipped)
    return _combine(ready, equipped)


def consume(runtime, item_id, *, effect_id=None, max_use_ticks=40, selector=None):
    selector = validate_selector(selector)
    require(type(max_use_ticks) is int and 1 <= max_use_ticks <= 100, 'invalid_use_tick_budget')
    require(item_id in FOODS or item_id in {'minecraft:potion', 'minecraft:milk_bucket'},
            'consumable_not_in_explicit_supported_set')
    require(item_id != 'minecraft:potion' or isinstance(effect_id, str), 'potion_effect_goal_required')
    if item_id == 'minecraft:potion':
        require(effect_id not in INSTANT_EFFECTS, 'instant_effect_potion_unsupported')
        require('effect_id' not in selector or selector['effect_id'] == effect_id,
                'potion_selector_effect_conflicts_with_goal')
        selector['effect_id'] = effect_id
    ready = ensure_hotbar(runtime, item_id, selector=selector)
    before = runtime.require_success(ready)
    if item_id == 'minecraft:potion':
        held = _inventory_item(before, before.player['selected_slot'])
        require(held.get('potion_effects_truncated') is False
                and any(effect.get('id') == effect_id and effect.get('duration_ticks', 0) > 0
                        for effect in held.get('potion_effects', [])), 'observed_potion_effect_does_not_match_goal')
    if item_id in FOODS:
        require(before.player.get('food', 20) < 20, 'hunger_not_missing')
    if item_id == 'minecraft:milk_bucket':
        require(before.player.get('effects_truncated') is False and before.player.get('effects'),
                'milk_effect_removal_goal_required')
    old_count = count(before, item_id)
    old_food = before.player.get('food', 0)
    effects = {e['id']: e for e in before.player.get('effects', [])}
    def verified(old, new):
        if count(new, item_id) != old_count - 1 or new.player.get('using_item') is not False:
            return False
        if item_id in FOODS:
            return new.player.get('food', 0) > old_food
        if new.player.get('effects_truncated') is not False:
            return False
        new_effects = {e['id']: e for e in new.player.get('effects', [])}
        if item_id == 'minecraft:milk_bucket':
            return not new_effects and count(new, 'minecraft:bucket') == count(old, 'minecraft:bucket') + 1
        observed = new_effects.get(effect_id)
        prior = effects.get(effect_id, {})
        return (observed is not None and (effect_id not in effects
                or observed.get('amplifier', -1) > prior.get('amplifier', -1)
                or observed.get('duration_ticks', 0) > prior.get('duration_ticks', 0))
                and count(new, 'minecraft:glass_bottle') == count(old, 'minecraft:glass_bottle') + 1)
    consumed = runtime.execute('inventory.consume', {'op': 'action', 'action': 'use_item',
                           'hotbar_slot': before.player['selected_slot'], 'use_ticks': max_use_ticks,
                           'timeout_ms': 1000 + max_use_ticks * 100}, verified, before=before)

    runtime.require_success(consumed)
    return _combine(ready, consumed)

"""A few explicit gameplay recipes using real menu/world observations."""
from __future__ import annotations

import math
import time

WOOD = ('oak', 'spruce', 'birch', 'jungle', 'acacia', 'dark_oak', 'mangrove', 'cherry')
LOGS = {f'minecraft:{prefix}{wood}_{kind}': f'minecraft:{wood}_planks'
        for wood in WOOD for prefix in ('', 'stripped_') for kind in ('log', 'wood')}


def observe():
    return {'step': 'observe'}


def action(name, **body):
    return {'step': 'action', 'body': {'action': name, **body}}


def menu_of(state):
    menu = state.get('menu')
    if not isinstance(menu, dict) or not isinstance(menu.get('slots'), list):
        raise ValueError('menu_observation_missing')
    return menu


def player_menu(state):
    menu = menu_of(state)
    if menu.get('container_id') != 0 or not menu.get('menu_class', '').endswith('InventoryMenu'):
        raise ValueError('requires_player_inventory_menu')
    if menu.get('slots_truncated') is not False:
        raise ValueError('incomplete_menu')
    return menu


def slots_of(menu):
    return {slot['menu_index']: slot for slot in menu['slots']}


def count(state, item_id):
    return sum(item['count'] for item in state['player']['inventory'] if item['id'] == item_id)


def empty(item):
    return item.get('empty') is True and item.get('count') == 0


def click(menu, slot, button=0, click_type='pickup'):
    return action('click_slot', container_id=menu['container_id'], slot=slot,
                  button=button, click_type=click_type, timeout_ms=3000)


def basic(command):
    body = {key: value for key, value in command.items()
            if key not in ('op', 'session_id', 'request_id', 'submitted_at')}
    body.pop('action_id', None)  # The resident owns stable per-request step IDs.
    response = yield {'step': 'action', 'body': body}
    state = yield observe()
    return {'action': response, 'state': state, 'server_confirmed': False}


def walk_to(command, cache, bridge):
    waypoints = cache.route(bridge, command['target'], command.get('radius', 4), command.get('vertical', 2))
    if not waypoints:
        return {'reason': 'already_at_target', 'state': cache.state, 'server_confirmed': False}
    result = yield action('follow_path', waypoints=waypoints, timeout_ms=command.get('timeout_ms', 15000))
    state = yield observe()
    return {'action': result, 'waypoints': waypoints, 'state': state, 'server_confirmed': False}


def craft_planks(command):
    """Craft exactly ONE log/wood into four planks; no recipe or inventory mirror."""
    state = yield observe()
    menu = player_menu(state)
    slots = slots_of(menu)
    if not empty(menu['carried']) or any(not empty(slots[i]['item']) for i in range(1, 5)):
        raise ValueError('craft_grid_or_cursor_not_empty')
    requested = command.get('log_id')
    # Use the live menu's player_inventory/inventory_index mapping, then click
    # its published menu_index, never an inventory-array index.
    candidates = [s for s in menu['slots'] if s.get('player_inventory') is True and 0 <= s.get('inventory_index', -1) <= 35
                  and s['item']['id'] in LOGS
                  and (requested is None or s['item']['id'] == requested)]
    if not candidates:
        raise ValueError('no_matching_log_in_inventory')
    source = candidates[0]
    log_id = source['item']['id']
    planks = LOGS[log_id]
    before_log, before_planks = count(state, log_id), count(state, planks)
    source_slot = source['menu_index']
    source_count = source['item']['count']
    yield click(menu, source_slot)
    state = yield observe()
    menu = player_menu(state)
    if menu['carried']['id'] != log_id or menu['carried']['count'] != source_count:
        raise ValueError('log_pickup_not_observed')
    yield click(menu, 1, button=1)
    state = yield observe()
    menu = player_menu(state)
    if slots_of(menu)[1]['item']['id'] != log_id or slots_of(menu)[1]['item']['count'] != 1:
        raise ValueError('single_log_in_grid_not_observed')
    if source_count > 1:
        if menu['carried']['id'] != log_id or menu['carried']['count'] != source_count - 1:
            raise ValueError('remaining_logs_not_observed')
        yield click(menu, source_slot)
    deadline = time.monotonic() + 3.0
    while True:
        state = yield observe()
        menu = player_menu(state)
        output = slots_of(menu)[0]['item']
        if output['id'] == planks and output['count'] == 4 and empty(menu['carried']):
            break
        if time.monotonic() >= deadline:
            raise ValueError('plank_recipe_output_not_observed')
        yield {'step': 'wait', 'seconds': 0.1}
    yield click(menu, 0, click_type='quick_move')
    deadline = time.monotonic() + 3.0
    while True:
        state = yield observe()
        menu = player_menu(state)
        if (count(state, log_id) == before_log - 1 and count(state, planks) == before_planks + 4
                and empty(menu['carried']) and all(empty(slots_of(menu)[i]['item']) for i in range(1, 5))):
            return {'reason': 'one_log_crafted_client_observed', 'log_id': log_id, 'planks_id': planks,
                    'logs_consumed': 1, 'planks_added': 4, 'state': state, 'server_confirmed': False}
        if time.monotonic() >= deadline:
            raise ValueError('craft_inventory_delta_not_observed')
        yield {'step': 'wait', 'seconds': 0.1}


def pillar(command):
    """Place 1..8 blocks beneath the player, checking each actual placement."""
    height = command.get('height', 1)
    if type(height) is not int or not 1 <= height <= 8:
        raise ValueError('pillar_height_must_be_1_to_8')
    block_id = command['block_id']
    state = yield observe()
    p = state['player']
    base = command.get('base') or {k: math.floor(p[k]) for k in ('x', 'y', 'z')}
    if any(type(base.get(k)) is not int for k in ('x', 'y', 'z')):
        raise ValueError('invalid_pillar_base')
    if count(state, block_id) < height:
        raise ValueError('not_enough_pillar_blocks')
    hotbar = next((s['slot'] for s in p['inventory'] if s['id'] == block_id and 0 <= s['slot'] <= 8), None)
    if hotbar is None:
        menu = player_menu(state)
        if not empty(menu['carried']):
            raise ValueError('cursor_not_empty')
        source = next((s for s in menu['slots'] if s.get('player_inventory') is True and 9 <= s.get('inventory_index', -1) <= 35 and s['item']['id'] == block_id), None)
        if source is None:
            raise ValueError('pillar_material_not_in_player_storage')
        hotbar = command.get('hotbar_slot', 0)
        if type(hotbar) is not int or not 0 <= hotbar <= 8:
            raise ValueError('invalid_hotbar_slot')
        yield click(menu, source['menu_index'], button=hotbar, click_type='swap')
        state = yield observe()
        if not any(s['slot'] == hotbar and s['id'] == block_id for s in state['player']['inventory']):
            raise ValueError('material_hotbar_swap_not_observed')
    placements = []
    for i in range(height):
        # Observe actual feet; do not integrate motion or pretend to simulate jump physics.
        deadline = time.monotonic() + 3.0
        while True:
            state = yield observe()
            p = state['player']
            if (abs(p['x'] - (base['x'] + 0.5)) < 0.35
                    and abs(p['z'] - (base['z'] + 0.5)) < 0.35
                    and abs(p['y'] - (base['y'] + i)) < 0.15 and p['on_ground']):
                break
            if time.monotonic() >= deadline:
                raise ValueError('stand_centered_on_pillar_base_first')
            yield {'step': 'wait', 'seconds': 0.1}
        selected = next((s for s in p['inventory'] if s['slot'] == hotbar), {})
        if selected.get('id') != block_id or selected.get('count', 0) < 1:
            raise ValueError('pillar_hotbar_material_changed')
        result = yield action('place_block', support={'x': base['x'], 'y': base['y'] + i - 1, 'z': base['z']},
                              face='up', hotbar_slot=hotbar, jump=True, timeout_ms=5000)
        placements.append(result)
    state = yield observe()
    return {'reason': 'pillar_placements_client_observed', 'placements': placements,
            'state': state, 'server_confirmed': False}


def make_task(command, cache, bridge):
    operation = command['op']
    if operation == 'action':
        return basic(command)
    if operation == 'walk_to':
        return walk_to(command, cache, bridge)
    if operation == 'craft_planks':
        return craft_planks(command)
    if operation == 'pillar':
        return pillar(command)
    raise ValueError('unknown_task')

"""Native-shaped offline fixtures, never used by production or live execution."""
from copy import deepcopy

PROTOCOL = {'ok': True, 'protocol': 'mineclient-bridge', 'schema_version': 2}


def native_bundle(observed, radius=48, *, run_id='test-run', process_id=1234, source_nano='100000000000'):
    state = deepcopy(observed)
    state.update(PROTOCOL)
    world, player = state['world'], state['player']
    player.setdefault('dimension', world['dimension'])
    action = {'ok': True, 'action_schema_version': 1, 'action_id': None, 'status': 'idle',
              'input_owner': 'direct', **state['client_action']}
    state['client_action'] = deepcopy(action)
    state.setdefault('menu', {'menu_class': 'InventoryMenu', 'container_id': 0, 'state_id': 0,
                              'carried': {'id': '', 'count': 0, 'empty': True}, 'slots': []})
    state.setdefault('screen_open', False)
    state.setdefault('paused', False)
    state.setdefault('focused', True)
    state.setdefault('private_singleplayer', True)
    state['capability_guard'] = {'schema_version': 1, 'source_tick': world['game_time'],
                                 'source_nano': source_nano, **state.get('capability_guard', {})}
    nearby = state.get('nearby', {})
    entities = nearby.get('entities', [])
    state['nearby'] = {'radius': float(radius), 'total': len(entities), 'returned': len(entities),
                       'truncated': False, 'entities': entities, 'loaded_chunks': [], **nearby}
    status = {**PROTOCOL, 'run_id': run_id, 'process_id': process_id, 'in_world': True,
              'client_action': deepcopy(action),
              'world': {'present': True, **{key: world[key] for key in ('world_generation', 'dimension', 'game_time')}},
              'player': {'present': True, **{key: player[key] for key in ('uuid', 'x', 'y', 'z')}},
              'screen': {'present': state['screen_open']}, 'held_mappings': []}
    screen = {**PROTOCOL, 'open': state['screen_open'], 'menu': deepcopy(state['menu']),
              'children_total': 0, 'children_returned': 0, 'children_truncated': False, 'children': []}
    if screen['open']:
        status['screen'].update({'class': 'InventoryScreen', 'title': 'Inventory', 'width': 800, 'height': 600})
        screen.update({'class': 'InventoryScreen', 'title': 'Inventory', 'gui_width': 800, 'gui_height': 600})
    return {**PROTOCOL, 'capability_snapshot_schema_version': 1, 'status': status,
            'action': {**deepcopy(action), **PROTOCOL}, 'state': state, 'screen': screen}


def freshness(**changes):
    return {'schema_version': 1, 'phase': 'guard_start', 'source_tick': 100, 'current_tick': 106,
            'tick_delta': 6, 'source_nano': '100000000000', 'current_nano': '100300000000',
            'elapsed_nanos': '300000000', 'max_elapsed_nanos': '800000000', 'max_tick_delta': 5,
            'nano_age_negative': False, 'nano_age_exceeded': False, 'tick_reversed': False,
            'tick_delta_exceeded': True, **changes}

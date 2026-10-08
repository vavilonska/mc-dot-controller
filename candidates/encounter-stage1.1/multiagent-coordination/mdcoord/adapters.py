"""Pure whitelist adapters. No client, queue submission, file write, or goal invention."""
from __future__ import annotations

from .schema import Context, fields, identifier, integer, number, point, require
from .snapshots import Acquisition, sanitize


def resident_observation(result):
    """Extract an ALREADY completed resident observe result. Capture time is not invented.

    Return sanitized section DATA, context and the original resident finished wall
    time. A caller without the original owner monotonic capture interval must
    publish with Acquisition(..., None, None, ..., source_clock=...), hence unknown.
    """
    require(type(result) is dict and result.get('status') == 'succeeded', 'observation_not_completed')
    observed = result.get('result')
    require(type(observed) is dict and type(observed.get('state')) is dict, 'missing_state')
    state = observed['state']
    world, player, action = state.get('world'), state.get('player'), observed.get('action')
    require(all(type(v) is dict for v in (world, player, action)), 'missing_context')
    context = Context(world.get('dimension'), world.get('world_generation'), player.get('uuid'),
                      action.get('action_session'), result.get('session_id'))
    when = number(result.get('finished_at'), 0, 1e12) * 1000
    player_data = {k: player.get(k) for k in ('x', 'y', 'z', 'health', 'food', 'alive')}
    player_data['grounded'] = player.get('on_ground')
    player_data['screen_closed'] = not state['screen_open'] if type(state.get('screen_open')) is bool else None
    inventory = player.get('inventory')
    slots = [{'slot': item.get('slot'), 'item_id': item.get('id'), 'count': item.get('count')}
             if type(item) is dict else {} for item in inventory[:46]] if type(inventory) is list else None
    raw = {'player': player_data,
           'inventory': {'slots': slots, 'complete': type(inventory) is list and len(inventory) <= 46
                         and player.get('inventory_truncated') is False},
           # Native terminal/idle ownership does not itself prove a global release-all.
           'action': {'status': action.get('status'), 'action_id': action.get('action_id'),
                      'input_released': None}}
    # TerrainReader reports hazards_exhaustive:false, and state lacks an attackable
    # guarantee. Do NOT turn these into certified corridor/target safety here.
    # The future sole owner must publish verified planner-specific terrain/entities.
    sections = {name: sanitize(name, value)[0] for name, value in raw.items()}
    return {'context': context, 'sections': sections, 'source_time_ms': when,
            'source_tick': world.get('game_time'), 'source_clock': 'resident_result_finished_wall',
            'source_id': identifier(result.get('request_id'))}


def publish_recorded(store, result):
    """An imported result can be displayed, never upgraded to fresh by import time."""
    extracted = resident_observation(result)
    return store.publish(extracted['context'], extracted['source_id'], extracted['sections'],
                         Acquisition(store.epoch, None, None, extracted['source_time_ms'],
                                     extracted['source_tick'], extracted['source_clock']))


def goal_record(value):
    """Separate task-maintenance data with its own unchanged timestamp; never authority."""
    fields(value, ('goal_id', 'task_id', 'status', 'updated_at_ms', 'target'))
    require(value['status'] in ('planned', 'active', 'blocked', 'complete', 'cancelled'), 'goal_status')
    return {'goal_id': identifier(value['goal_id']), 'task_id': identifier(value['task_id']),
            'status': value['status'], 'updated_at_ms': number(value['updated_at_ms'], 0, 1e15),
            'target': point(value['target']) if value['target'] is not None else None,
            'source': 'task_maintenance_record', 'confers_authorization': False}


def dashboard_view(snapshot, goal=None):
    """Reusable private view of one shared snapshot. It does not refresh/export files."""
    player = snapshot.get('sections', {}).get('player')
    inventory = snapshot.get('sections', {}).get('inventory')
    require(player is not None, 'missing_player_section')
    def check_metadata(section):
        require(type(section) is dict, 'invalid_section_metadata')
        require(section.get('freshness') in ('fresh', 'stale', 'unknown', 'truncated'), 'invalid_freshness')
        require(section.get('source_time_clock') in ('resident_result_finished_wall', 'fixture_wall', 'unknown'),
                'invalid_source_clock')
        integer(section.get('revision'), 1, 2**63 - 1)
        if section.get('source_time_ms') is not None:
            number(section['source_time_ms'], 0, 1e15)
    check_metadata(player)
    p = sanitize('player', player.get('data'))[0]
    result = {'schema_version': 1, 'source': 'sanitized_shared_observation',
              'world': Context.parse(player['context']).wire(),
              'observed_at_ms': player['source_time_ms'],
              'observation_time_meaning': player['source_time_clock'],
              'position': {key: p.get(key) for key in ('x', 'y', 'z')},
              'health': p.get('health'), 'food': p.get('food'),
              'state_freshness': player['freshness'], 'state_revision': player['revision'],
              'inventory': None, 'goal': goal_record(goal) if goal is not None else None}
    if inventory:
        check_metadata(inventory)
        result['inventory'] = {**sanitize('inventory', inventory.get('data'))[0],
                               'observed_at_ms': inventory['source_time_ms'],
                               'freshness': inventory['freshness'], 'revision': inventory['revision']}
    return result

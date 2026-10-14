"""Detached predicate test support copied from the action-tick driver. Synthetic fixtures only; no dispatch or saved-world authority."""
from copy import deepcopy
import math
import re

GOAL = {'x':12,'y':64,'z':24}
TARGET = {'x':12.5,'y':64,'z':24.5}
ARGUMENTS = {'goal':GOAL,'min_health':math.nextafter(20.0, -math.inf)}
PUBLIC_BUDGET = {'deadline_seconds':20,'max_actions':2,'max_observations':24,
                 'reflex_reserve_actions':0,'cleanup_reserve_actions':1}
PROFILE = 'movement-flat-observed-v2'  # Policy unchanged; coherent wire encoding is separately versioned.

def require(value, reason):
    if not value: raise ValueError(reason)

def exact(left,right):
    if type(left) is not type(right): return False
    if type(left) is dict: return left.keys()==right.keys() and all(exact(left[k],right[k]) for k in left)
    if type(left) is list: return len(left)==len(right) and all(exact(a,b) for a,b in zip(left,right))
    return left==right

def number(value):
    return type(value) in (int,float) and math.isfinite(value)

def require_origin(player):
    require(all(number(player[k]) for k in ('x','y','z')), 'finite_origin')
    require(abs(player['x']-12.5)<=.1 and abs(player['z']-25.5)<=.1 and abs(player['y']-64)<=1e-7,
            'exact_north_origin_cell')
    require(math.hypot(player['velocity']['x'],player['velocity']['z'])<=.003 and
            -.09<=player['velocity']['y']<=0 and player['on_ground'] is True,'settled_origin')

def expected_after(expected, state):
    value=deepcopy(expected)
    value.update({k:state['player'][k] for k in ('x','y','z')})
    return value

def movement_state_valid(before, state):
    """Typed conservation plus independently measured destination/stopping proof."""
    old=before.player; player=state['player']
    require_origin(old)
    require(all(number(player[k]) for k in ('x','y','z','yaw')), 'finite_destination')
    require(math.hypot(player['x']-TARGET['x'],player['z']-TARGET['z'])<=.23 and
            abs(player['y']-TARGET['y'])<=1e-6, 'settled_target_tolerance')
    displacement=math.hypot(player['x']-old['x'],player['z']-old['z'])
    require(.75<=displacement<=1.25 and player['z']<old['z'],'north_displacement')
    v=player['velocity']
    require(all(number(v.get(k)) for k in ('x','y','z')) and math.hypot(v['x'],v['z'])<=.003 and
            -.09<=v['y']<=0 and player['on_ground'] is True,'velocity_not_stopped')
    allowed={'x','y','z','yaw','velocity','eye_position','bounding_box'}
    require(exact({k:v for k,v in old.items() if k not in allowed},
                  {k:v for k,v in player.items() if k not in allowed}), 'unrelated_typed_player_change')
    # Eye and hitbox translate with the player. No crouch, scale or pitch change.
    for k in ('x','y','z'):
        delta=player[k]-old[k]
        require(abs(player['eye_position'][k]-old['eye_position'][k]-delta)<=1e-6,'eye_pose_not_translated')
        for side in ('min','max'):
            require(abs(player['bounding_box'][side][k]-old['bounding_box'][side][k]-delta)<=1e-6,
                    'bounding_box_not_translated')
    require(exact(before.state['menu'],state['menu']) and state['menu']['carried']['empty'] is True and
            state['menu']['carried']['count']==0,'menu_or_cursor_changed')
    require(player['health']==20 and player['selected_slot']==8 and player['sprinting'] is False and
            player['using_item'] is False and state['held_inputs']['neutral'] is True,'health_selection_or_input_change')
    action=state['client_action']
    require(action['status']=='succeeded' and action['reason']=='path_reached' and
            action['result']['input_release_confirmed'] is True and
            state['movement_budget']['status']=='unarmed','terminal_release_not_confirmed')
    return {'origin':{k:old[k] for k in ('x','y','z')},'destination':{k:player[k] for k in ('x','y','z')},
            'horizontal_displacement':displacement,'goal_tolerance':.23,'velocity_stopped_by_later_sample':True,
            'yaw_before':old['yaw'],'yaw_after':player['yaw'],'pitch_unchanged':True,
            'all_typed_items_and_equipment_unchanged':True,'health_unchanged':True,'cursor_empty':True}

def north_admission_valid(witness):
    """Case narrowing only after the complete production v2 witness validator."""
    m=witness['facts']['movement']
    bounds={'min_x':10,'max_x':14,'min_y':63,'max_y':67,'min_z':22,'max_z':27,
            'feet_y':64,'steps':1,'halo':2,'expected_cells':150}
    require(all(type(m[k]) is int and m[k]==v for k,v in bounds.items()),'exact_north_150_cell_footprint')
    require(m['all_loaded'] is True,'fresh_native_loaded_corridor')
    guard=m['entity_guard']
    require(guard['policy']=='observed-projection-v1' and
            guard['scope']=='all-client-loaded-enumerated-local-corridor-exclusion' and
            guard['guarantee']=='same-callback-current-facts-only' and
            guard['future_dynamics_certified'] is False and guard['server_confirmed'] is False and
            type(guard['maximum_action_ticks']) is int and guard['maximum_action_ticks']==160 and
            type(guard['remaining_projection_ticks']) is int and guard['remaining_projection_ticks']==160,
            'native_observed_entity_guard_guarantee')
    # A positive live_other_count is permitted only by the complete production
    # validator's per-row class/flags/projection/separation proof. Never replace
    # that proof with the public radius8 observation or a zero-entity shortcut.
    # Retained save selected this direction only. Authority is the fresh witness;
    # the case also refuses a changed floor/clearance instead of adopting a new route.
    require(len(m['cells'])==150 and all(c['id']==('minecraft:grass_block' if c['y']==63 else 'minecraft:air')
            for c in m['cells']),'selected_corridor_changed')
    return guard

def north_witness_valid(witness, native):
    north_admission_valid(witness)
    m=witness['facts']['movement']
    terminal=native['result']['scoped_movement']
    require(terminal['profile']==PROFILE and terminal['effect_attempted'] is True and
            type(terminal['local_checks']) is int and terminal['local_checks']>0 and
            number(terminal['sampled_distance']) and 0<terminal['sampled_distance']<=2 and
            terminal['distance_accounting']=='callback-sampled-not-all-move-instrumentation' and
            terminal['input_neutral'] is True and terminal['velocity_stopped_proven'] is False and
            terminal['deadline_nano']==m['deadline_nano'],'native_callback_terminal_proof')
    observed_entity_terminal_valid(witness,terminal,native_ticks=native['ticks'])
    return terminal

def observed_entity_terminal_valid(witness,terminal,*,native_ticks):
    """Bind successful beforeEffect summary to the original admission clocks.

    This summary is native attestation of completed checks. It does not certify
    unobserved future dynamics or replace later velocity/goal observations.
    """
    g=witness['facts']['movement']['entity_guard']
    require(terminal['entity_guard_policy']=='observed-projection-v1' and
            type(terminal['entity_guard_checks']) is int and terminal['entity_guard_checks']>0 and
            type(terminal['local_checks']) is int and terminal['entity_guard_checks']==terminal['local_checks'],
            'completed_per_write_entity_checks')
    require(terminal['timing_contract']=='native-action-pre-ticks-v1', 'native_action_timing_contract')
    action_tick=terminal['last_entity_check_action_tick']
    # This success path finishes inside followPath after its leading beforeEffect.
    require(type(native_ticks) is int and 1<=native_ticks<160 and
            type(action_tick) is int and action_tick==native_ticks,
            'same_successful_native_action_tick')
    tick=terminal['last_entity_check_tick'];nano=terminal['last_entity_check_nano']
    # World stamps remain world-domain evidence, not cross-callback action ages.
    require(type(tick) is int and 0<=tick<2**63 and
            type(nano) is str and re.fullmatch(r'-?(0|[1-9][0-9]{0,18})',nano) is not None and
            -(2**63)<=int(nano)<2**63 and
            int(g['source_nano'])<=int(nano)<int(terminal['deadline_nano']),
            'entity_world_tick_type_and_original_nanotime_bound')
    population=terminal['maximum_checked_population']
    require(type(population) is int and g['enumerated_count']<=population<=1024,
            'complete_checked_population_bound')
    require(terminal['velocity_stopped_proven'] is False,'native_stopping_claim_forbidden')
    return {'policy':'observed-projection-v1','guarantee':'same-callback-current-facts-only',
            'future_dynamics_certified':False,'server_confirmed':False,
            'completed_checks':terminal['entity_guard_checks'],'maximum_checked_population':population}

"""Strict opt-in native coherent reads. Never repairs, falls back, or re-stamps."""
from __future__ import annotations

import math
import re


def _require(condition, detail):
    if not condition:
        raise ValueError('invalid_capability_snapshot_' + detail)


def _integer(value, minimum=0, maximum=2**53 - 1):
    return type(value) is int and minimum <= value <= maximum


def _text(value):
    return type(value) is str and bool(value)


def _number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def exact(left, right):
    """JSON equality without Python's bool/int equality weakening a sibling fence."""
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return left.keys() == right.keys() and all(exact(left[k], right[k]) for k in left)
    if type(left) is list:
        return len(left) == len(right) and all(exact(a, b) for a, b in zip(left, right))
    return left == right


def signed_long_string(value):
    return (type(value) is str and re.fullmatch(r'-?(0|[1-9][0-9]{0,18})', value) is not None
            and -(2**63) <= int(value) <= 2**63 - 1)


def validate_snapshot(bundle, entity_radius, *, observation_clock=None):
    """Validate native provenance and the complete unchanged sibling payloads.

    The schema attests to a single native callback. These checks reject a mixed
    or downgraded envelope; Python cannot manufacture that callback provenance.
    Source nano values are retained, never compared with Python's clock.
    """
    _require(type(bundle) is dict, 'envelope')
    from .movement_wire import decode
    bundle = decode(bundle)  # Declared lossless representation only; raw input remains untouched.
    _require(observation_clock in (None, 'client-pre-tick-v1'), 'clock_selection')
    version = 2 if observation_clock is not None else 1
    _require(type(bundle.get('capability_snapshot_schema_version')) is int
             and bundle['capability_snapshot_schema_version'] == version, 'schema')
    if version == 2:
        from navigation_controller.observation_clock import ClockStamp, bind, PROFILE
        _require(bundle.get('observation_clock_profile') == PROFILE, 'clock_profile')
        stamp = ClockStamp.parse(bundle.get('observation_clock'))
        for key in ('status', 'action', 'state', 'screen'):
            _require(type(bundle.get(key)) is dict and
                     ClockStamp.parse(bundle[key].get('observation_clock')) == stamp, 'clock_sibling')
        bind(bundle['observation_clock'],bundle['status'],bundle['state'])
    else:
        _require('observation_clock' not in bundle and 'observation_clock_profile' not in bundle
                 and all(type(bundle.get(k)) is not dict or 'observation_clock' not in bundle[k]
                         for k in ('status','action','state','screen')), 'clock_not_selected')
    for name, value in [('envelope', bundle)] + [(key, bundle.get(key)) for key in ('status', 'action', 'state', 'screen')]:
        _require(type(value) is dict and value.get('ok') is True
                 and value.get('protocol') == 'mineclient-bridge'
                 and type(value.get('schema_version')) is int and value['schema_version'] == 2,
                 name + '_protocol')
    status, action, state, screen = (bundle[key] for key in ('status', 'action', 'state', 'screen'))
    _require(status.get('in_world') is True and _text(status.get('run_id'))
             and _integer(status.get('process_id'), 1, 2**63 - 1), 'bridge_identity')
    for name in ('world', 'player', 'screen'):
        _require(type(status.get(name)) is dict, 'status_' + name)
    for name in ('world', 'player', 'client_action', 'menu', 'capability_guard', 'nearby'):
        _require(type(state.get(name)) is dict, 'state_' + name)
    world, player = state['world'], state['player']
    _require(status['world'].get('present') is True and status['player'].get('present') is True,
             'world_presence')
    _require(all(_text(world.get(k)) for k in ('world_generation', 'dimension'))
             and _integer(world.get('game_time')), 'world_identity')
    _require(all(exact(status['world'].get(k), world[k]) for k in ('world_generation', 'dimension', 'game_time')),
             'world_mismatch')
    _require(_text(player.get('uuid')) and player.get('dimension') == world['dimension']
             and status['player'].get('uuid') == player['uuid'], 'player_identity')
    _require(all(_number(player.get(k)) and exact(status['player'].get(k), player[k]) for k in ('x', 'y', 'z')),
             'player_mismatch')
    _require(type(action.get('action_schema_version')) is int and action['action_schema_version'] == 1
             and _text(action.get('action_session'))
             and action.get('status') in ('idle', 'running', 'succeeded', 'failed', 'cancelled')
             and 'action_id' in action and (action['action_id'] is None or _text(action['action_id'])), 'action_schema')
    native_action = {key: value for key, value in action.items() if key not in (('protocol', 'schema_version', 'observation_clock') if version == 2 else ('protocol', 'schema_version'))}
    _require(exact(status.get('client_action'), native_action) and exact(state['client_action'], native_action),
             'action_mismatch')
    if 'movement_budget' in native_action or 'movement_budget' in state:
        _require(exact(state.get('movement_budget'), native_action.get('movement_budget')), 'movement_budget_mismatch')
    _require(type(state.get('screen_open')) is bool and type(screen.get('open')) is bool
             and type(status['screen'].get('present')) is bool
             and state['screen_open'] == screen['open'] == status['screen']['present'], 'screen_mismatch')
    _require(all(type(state.get(key)) is bool for key in ('paused', 'focused', 'private_singleplayer')),
             'state_flags')
    menu = state['menu']
    _require(_text(menu.get('menu_class')) and _integer(menu.get('container_id'))
             and _integer(menu.get('state_id')) and type(menu.get('carried')) is dict
             and type(menu.get('slots')) is list and all(type(row) is dict for row in menu['slots']), 'menu_schema')
    _require(type(screen.get('menu')) is dict and exact(menu, screen['menu']), 'menu_mismatch')
    if screen['open']:
        _require(_text(screen.get('class')) and type(screen.get('title')) is str
                 and _integer(screen.get('gui_width')) and _integer(screen.get('gui_height')), 'screen_details')
        _require(all(exact(status['screen'].get(a), screen.get(b)) for a, b in
                     (('class', 'class'), ('title', 'title'), ('width', 'gui_width'), ('height', 'gui_height'))),
                 'screen_details_mismatch')
    guard = state['capability_guard']
    _require(type(guard.get('schema_version')) is int and guard['schema_version'] == 1
             and _integer(guard.get('source_tick')) and guard['source_tick'] == world['game_time']
             and signed_long_string(guard.get('source_nano')), 'source_guard')
    nearby = state['nearby']
    _require(_number(nearby.get('radius')) and nearby['radius'] == entity_radius, 'entity_radius')
    _require(_integer(nearby.get('returned')) and _integer(nearby.get('total'))
             and nearby['returned'] <= nearby['total'] and type(nearby.get('truncated')) is bool
             and nearby['truncated'] == (nearby['returned'] < nearby['total'])
             and type(nearby.get('entities')) is list and len(nearby['entities']) == nearby['returned']
             and all(type(row) is dict for row in nearby['entities']), 'entities')
    return bundle


def source_freshness(value):
    """Recognize bounded native diagnostic metadata without making it authority."""
    keys = {'schema_version', 'phase', 'source_tick', 'current_tick', 'tick_delta',
            'source_nano', 'current_nano', 'elapsed_nanos', 'max_elapsed_nanos', 'max_tick_delta',
            'nano_age_negative', 'nano_age_exceeded', 'tick_reversed', 'tick_delta_exceeded'}
    if type(value) is not dict or set(value) != keys:
        return False
    return (type(value['schema_version']) is int and value['schema_version'] == 1
            and value['phase'] in ('guard_start', 'before_input_release', 'after_input_release')
            and all(_integer(value[k], -(2**63), 2**63 - 1) for k in ('source_tick', 'current_tick', 'tick_delta'))
            and all(signed_long_string(value[k]) for k in ('source_nano', 'current_nano', 'elapsed_nanos'))
            and value['max_elapsed_nanos'] == '800000000'
            and type(value['max_tick_delta']) is int and value['max_tick_delta'] == 5
            and all(type(value[k]) is bool for k in ('nano_age_negative', 'nano_age_exceeded', 'tick_reversed', 'tick_delta_exceeded')))


def validate_scoped_witness(native, request, action_id, native_intent=None):
    """Require complete action-local evidence and both immutable command digests."""
    import hashlib
    import json
    from copy import deepcopy
    def digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                         ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()
    def stack(value):
        return (type(value) is dict and type(value.get('id')) is str
                and (value.get('empty') is True and value['id'] in ('', 'minecraft:air')
                     or value.get('empty') is False and ':' in value['id'])
                and _integer(value.get('count'), 0, 2147483647) and type(value.get('empty')) is bool
                and value['empty'] == (value['count'] == 0)
                and all(type(value.get(k)) is str and re.fullmatch(r'[0-9a-f-]{36}', value[k]) is not None
                        for k in ('item_fingerprint', 'component_fingerprint'))
                and _integer(value.get('max_stack_size'), 0, 2147483647))
    _require(type(native) is dict and native.get('action_id') == action_id, 'scoped_action_identity')
    _require(type(native_intent) is dict and native_intent.get('action_id') == action_id,
             'scoped_original_intent_required')
    value = native.get('result', {}).get('scoped_native_preflight')
    _require(type(value) is dict and value.get('version') == 'scoped-native-preflight/1'
             and type(value.get('schema_version')) is int and value['schema_version'] == 1,
             'scoped_version')
    _require(type(request) is dict and set(request) == {'version','profile','owner_id','owner_generation','job_id','defense_epoch'}
             and all(exact(value.get(k), v) for k, v in request.items())
             and _integer(value.get('defense_epoch')) and _integer(value.get('owner_generation'), 1)
             and value.get('action_id') == action_id and value.get('action_session') == native.get('action_session'),
             'scoped_owner_identity')
    _require(value.get('profile') in ('state-menu-v1', 'state-use-v1', 'block-menu-v1', 'movement-flat-observed-v2', 'mining-local-observed-v2', 'collect-local-observed-v1', 'combat-local-observed-v1')
             and native_intent.get('action') in {'state-menu-v1': {'click_slot','close_menu','select_hotbar'},
                 'state-use-v1': {'use_item'}, 'block-menu-v1': {'interact_block'},
                 'movement-flat-observed-v2': {'follow_path'}, 'collect-local-observed-v1': {'follow_path'}, 'mining-local-observed-v2': {'break_block'}, 'combat-local-observed-v1': {'combat_entity'}}[value['profile']]
             and value.get('coverage_complete') is True and value.get('admitted') is True
             and value.get('clock_domain') == 'native-system-nanotime'
             and _integer(value.get('source_tick')) and _integer(value.get('native_owner_revision'))
             and signed_long_string(value.get('source_nano')) and signed_long_string(value.get('admitted_nano'))
             and 0 <= int(value['admitted_nano']) - int(value['source_nano']) <= 250000000,
             'scoped_coverage_or_clock')
    compiled = deepcopy(native_intent)
    compiled['capability_guard'] = {'schema_version':1,'source_tick':value['source_tick'],'source_nano':value['source_nano']}
    _require(value.get('command_digest_format') == 'sorted-json-utf8/1'
             and value.get('submitted_intent_sha256') == digest(native_intent)
             and value.get('command_sha256') == digest(compiled)
             and exact(value.get('planning_guard'), native_intent.get('capability_guard')), 'scoped_command_digest')
    facts = value.get('facts')
    _require(type(facts) is dict and type(facts.get('context')) is dict
             and exact(facts['context'], value.get('context'))
             and facts['context'].get('action_session') == native.get('action_session')
             and all(_text(facts['context'].get(k)) and facts['context'][k] == native_intent.get('expected_' + k)
                     for k in ('world_generation','dimension','player_uuid','action_session'))
             and _text(facts['context'].get('integrated_server_instance'))
             and facts['context']['integrated_server_instance'] == value.get('integrated_server_instance')
             and facts.get('private_singleplayer') is True and facts.get('focused') is True
             and facts.get('paused') is False and facts.get('alive') is True and facts.get('spectator') is False
             and _number(facts.get('health')) and facts['health'] > 0
             and _integer(facts.get('hurt_time')) and all(_number(facts.get(k)) for k in ('x','y','z'))
             and all(type(facts.get(k)) is bool for k in ('on_fire','in_water','in_lava','powder_snow','using_item'))
             and _integer(facts.get('selected_slot'), 0, 8) and type(facts.get('screen_class')) is str
             and _integer(facts.get('food_level'), 0, 20) and _number(facts.get('food_saturation'))
             and type(facts.get('held_inputs')) is dict and facts['held_inputs'].get('neutral') is True,
             'scoped_facts')
    inventory = facts.get('inventory')
    _require(type(inventory) is list and len(inventory) == facts.get('inventory_total') == 41
             and all(type(row) is dict and type(row.get('slot')) is int and row['slot'] == i
                     and stack(row.get('item')) for i,row in enumerate(inventory)), 'scoped_inventory_coverage')
    equipment = facts.get('equipment')
    _require(type(equipment) is dict and {'mainhand','offhand','feet','legs','chest','head'} <= set(equipment)
             and set(equipment) <= {'mainhand','offhand','feet','legs','chest','head','body'}
             and all(stack(v) for v in equipment.values()), 'scoped_equipment_coverage')
    effects = facts.get('effects')
    _require(type(effects) is list and len(effects) <= 64
             and all(type(e) is dict and _text(e.get('id')) and _integer(e.get('amplifier'), 0, 255)
                     and _integer(e.get('duration'), -1, 2147483647) for e in effects), 'scoped_effect_coverage')
    menu = facts.get('menu', {})
    counts = {'InventoryMenu': {46}, 'CraftingMenu': {46}, 'ChestMenu': set(range(45,91,9)),
              'HopperMenu': {41}, 'DispenserMenu': {45}, 'ShulkerBoxMenu': {63},
              'FurnaceMenu': {39}, 'BlastFurnaceMenu': {39}, 'SmokerMenu': {39}}
    cls = menu.get('menu_class') if type(menu) is dict else None
    name = cls.removeprefix('net.minecraft.world.inventory.') if type(cls) is str else ''
    _require(type(menu) is dict and menu.get('slots_truncated') is False and name in counts
             and cls == 'net.minecraft.world.inventory.' + name
             and _integer(menu.get('state_id')) and _integer(menu.get('container_id')) and stack(menu.get('carried'))
             and type(menu.get('slots')) is list and len(menu['slots']) in counts[name]
             and len(menu['slots']) == menu.get('slots_total') == menu.get('slots_returned')
             and type(menu.get('slot_permissions')) is list and len(menu['slots']) == len(menu['slot_permissions']),
             'scoped_menu_coverage')
    if name == 'InventoryMenu':
        player_mapping = {**{i: 44 - i for i in range(5, 9)}, **{i: i for i in range(9, 36)},
                          **{i: i - 36 for i in range(36, 45)}, 45: 40}
    else:
        offset = len(menu['slots']) - 36
        player_mapping = {**{offset+i: 9+i for i in range(27)},
                          **{offset+27+i: i for i in range(9)}}
    bound_fields = ('id','count','empty','item_fingerprint','component_fingerprint','max_stack_size')
    def same_stack(left, right):
        return all(exact(left.get(k), right.get(k)) for k in bound_fields)
    equipment_mapping = {'mainhand':facts['selected_slot'],'offhand':40,'feet':36,'legs':37,'chest':38,'head':39}
    _require(all(same_stack(equipment[k], inventory[index]['item']) for k,index in equipment_mapping.items()),
             'scoped_equipment_inventory_agreement')
    for i, row in enumerate(menu['slots']):
        _require(type(row) is dict and type(row.get('menu_index')) is int and row['menu_index'] == i
                 and _integer(row.get('slot_index')) and _integer(row.get('container_slot'))
                 and type(row.get('active')) is bool and type(row.get('player_inventory')) is bool
                 and (not row['player_inventory'] or _integer(row.get('inventory_index'), 0, 40))
                 and stack(row.get('item')), 'scoped_menu_slot')
        expected_index = player_mapping.get(i)
        _require(row['slot_index'] == i and row['player_inventory'] == (expected_index is not None)
                 and (expected_index is None or row.get('inventory_index') == expected_index
                      and row['container_slot'] == expected_index
                      and same_stack(row['item'], inventory[expected_index]['item'])),
                 'scoped_menu_inventory_mapping')
        permission = menu['slot_permissions'][i]
        _require(type(permission) is dict and type(permission.get('may_pickup')) is bool
                 and type(permission.get('may_place_carried')) is bool
                 and _integer(permission.get('max_stack_size'), 0, 2147483647), 'scoped_slot_permissions')
    if value['profile'] == 'block-menu-v1':
        from .block_menu_snapshot import validate
        validate(value, native, native_intent)
    if value['profile'] in ('movement-flat-observed-v2','collect-local-observed-v1'):
        validate_movement_footprint(facts, value, native_intent)
    if value['profile'] == 'mining-local-observed-v2':
        from .mining_snapshot import validate_mining
        validate_mining(value, native_intent, native)
    if value['profile'] == 'combat-local-observed-v1':
        from .combat_snapshot import validate_combat
        validate_combat(value, native_intent, native)
    return value


def validate_movement_footprint(facts, witness, intent):
    """Complete finite footprint validation; verifies attestation, not engine geometry itself."""
    m = facts.get('movement')
    collecting = witness.get('profile') == 'collect-local-observed-v1'
    origin = intent.get('expected_origin', {})
    points = intent.get('waypoints')
    _require(type(m) is dict and set(m) == ({'pickup_target'} if collecting else set()) | {'profile','source','min_x','max_x','min_y','max_y',
                 'min_z','max_z','feet_y','steps','halo','expected_cells','all_loaded','closed_inventory',
                 'survival','using_item','maximum_horizontal_speed','maximum_tick_sampled_displacement',
                 'deadline_nano','cells','entity_guard'}
             and m.get('profile') == ('collect-local-observed-v1' if collecting else 'movement-flat-observed-v2')
             and m.get('source') == 'native-client-loaded-level'
             and facts['context']['dimension'] == 'minecraft:overworld'
             and facts.get('screen_class') == '' and facts.get('using_item') is False
             and facts.get('menu',{}).get('menu_class') == 'net.minecraft.world.inventory.InventoryMenu'
             and facts.get('menu',{}).get('carried',{}).get('empty') is True
             and m.get('closed_inventory') is True and m.get('survival') is True and m.get('using_item') is False,
             'movement_context')
    _require(type(origin) is dict and all(_number(origin.get(k)) for k in ('x','y','z'))
             and type(points) is list and len(points) == 1
             and _integer(intent.get('timeout_ms'),50,8000)
             and intent.get('capability_route') is True and intent.get('jump',False) is False
             and intent.get('sneak',False) is False and intent.get('sprint',False) is False
             and 'hotbar_slot' not in intent, 'movement_request')
    sx, sy, sz = math.floor(facts['x']), round(facts['y']), math.floor(facts['z'])
    _require(abs(facts['x']-sx-.5)<=.1 and abs(facts['z']-sz-.5)<=.1 and abs(facts['y']-sy)<=1e-7
             and -63<=sy<=316 and abs(facts['x'])<=29999990 and abs(facts['z'])<=29999990
             and all(abs(origin[k]-facts[k])<=.03 for k in ('x','y','z')),
             'movement_origin')
    _require(all(type(p) is dict and all(_number(p.get(k)) for k in ('x','y','z'))
                 and p.get('jump',False) is False for p in points), 'movement_waypoints')
    dx, dz = points[0]['x']-sx-.5, points[0]['z']-sz-.5
    _require((dx,dz) in ((1,0),(-1,0),(0,1),(0,-1))
             and all(p['x']==sx+.5+dx*(i+1) and p['y']==sy and p['z']==sz+.5+dz*(i+1)
                     for i,p in enumerate(points)), 'movement_straight_route')
    ex, ez = int(sx+dx*len(points)), int(sz+dz*len(points))
    bounds = {'min_x':min(sx,ex)-2,'max_x':max(sx,ex)+2,'min_y':sy-1,'max_y':sy+3,
              'min_z':min(sz,ez)-2,'max_z':max(sz,ez)+2,'feet_y':sy,'steps':len(points),'halo':2}
    expected = [(x,y,z) for x in range(bounds['min_x'],bounds['max_x']+1)
                for y in range(sy-1,sy+4) for z in range(bounds['min_z'],bounds['max_z']+1)]
    _require(all(type(m.get(k)) is int and m[k]==n for k,n in bounds.items())
             and m.get('all_loaded') is True and type(m.get('expected_cells')) is int
             and m['expected_cells']==len(expected)==150
             and type(m.get('maximum_horizontal_speed')) is float and m['maximum_horizontal_speed']==.30
             and type(m.get('maximum_tick_sampled_displacement')) is float and m['maximum_tick_sampled_displacement']==.35
             and signed_long_string(m.get('deadline_nano'))
             and int(m['deadline_nano'])==int(witness['source_nano'])+intent['timeout_ms']*1000000,
             'movement_bounds')
    cells=m.get('cells')
    floors={'minecraft:'+name for name in ('stone','cobblestone','dirt','grass_block','oak_planks','andesite',
        'granite','diorite','cobbled_deepslate','smooth_stone','stone_bricks','bricks')}
    _require(type(cells) is list and len(cells)==len(expected), 'movement_coverage')
    for cell, xyz in zip(cells,expected):
        _require(type(cell) is dict and set(cell)=={'x','y','z','id','state','fluid','full_cube','friction'}
                 and all(type(cell.get(k)) is int and cell[k]==n for k,n in zip(('x','y','z'),xyz))
                 and cell.get('fluid')=='minecraft:empty' and _text(cell.get('state')),
                 'movement_cell_identity')
        floor=xyz[1]==sy-1
        _require(cell.get('full_cube') is floor and _number(cell.get('friction'))
                 and (cell.get('id') in floors and .5999999<=cell['friction']<=.6000001 if floor
                      else cell.get('id') in ('minecraft:air','minecraft:cave_air') and cell['friction']==0),
                 'movement_cell_geometry')
    if collecting:
        from .collect_snapshot import validate_pickup
        validate_pickup(m, witness, intent)
    else:
        _require('pickup_target' not in intent, 'collect_requires_distinct_profile')
    validate_movement_entity_guard(m['entity_guard'], m, witness)


_MOVEMENT_ENTITY_TYPES = {
    'minecraft:sheep': ('net.minecraft.world.entity.animal.Sheep', True),
    'minecraft:cow': ('net.minecraft.world.entity.animal.Cow', True),
    'minecraft:chicken': ('net.minecraft.world.entity.animal.Chicken', True),
    'minecraft:pig': ('net.minecraft.world.entity.animal.Pig', True),
    'minecraft:rabbit': ('net.minecraft.world.entity.animal.Rabbit', True),
    'minecraft:frog': ('net.minecraft.world.entity.animal.frog.Frog', True),
    'minecraft:boat': ('net.minecraft.world.entity.vehicle.Boat', False),
    'minecraft:chest_minecart': ('net.minecraft.world.entity.vehicle.MinecartChest', False),
    'minecraft:item': ('net.minecraft.world.entity.item.ItemEntity', False),
}


def validate_movement_entity_guard(guard, movement, witness):
    """Validate the complete native admission frame, not unobserved future dynamics.

    The producer's raw object-reference equality remains the consistency authority.
    Deliberately no cross-language rows digest or radius-based coverage shortcut.
    """
    keys = {'schema_version','policy','source','scope','guarantee','future_dynamics_certified',
            'server_confirmed','entity_limit','enumerated_count','self_count','live_other_count',
            'removed_count','unsupported_count','source_tick','source_nano','maximum_action_ticks',
            'remaining_projection_ticks','prism','rows'}
    pickup = movement.get('pickup_target') if witness.get('profile') == 'collect-local-observed-v1' else None
    if pickup is not None: keys.add('permitted_pickup_uuid')
    _require(type(guard) is dict and set(guard) == keys, 'movement_entity_guard_schema')
    if pickup is not None:
        _require(guard.get('permitted_pickup_uuid') == pickup['uuid'], 'collect_guard_target_mismatch')
    _require(type(guard['schema_version']) is int and guard['schema_version'] == 1
             and guard['policy'] == 'observed-projection-v1'
             and guard['source'] == 'native-client-loaded-level'
             and guard['scope'] == 'all-client-loaded-enumerated-local-corridor-exclusion'
             and guard['guarantee'] == 'same-callback-current-facts-only'
             and guard['future_dynamics_certified'] is False and guard['server_confirmed'] is False
             and type(guard['entity_limit']) is int and guard['entity_limit'] == 1024
             and type(guard['self_count']) is int and guard['self_count'] == 1
             and type(guard['unsupported_count']) is int and guard['unsupported_count'] == 0
             and type(guard['maximum_action_ticks']) is int and guard['maximum_action_ticks'] == 160,
             'movement_entity_guard_policy')
    # The returned admission witness is immutable: later frames are not substituted here.
    _require(_integer(guard['source_tick']) and guard['source_tick'] == witness['source_tick']
             and signed_long_string(guard['source_nano'])
             and int(witness['source_nano']) <= int(guard['source_nano']) <= int(witness['admitted_nano'])
             and type(guard['remaining_projection_ticks']) is int
             and guard['remaining_projection_ticks'] == 160 - (guard['source_tick'] - witness['source_tick'])
             and guard['remaining_projection_ticks'] == 160, 'movement_entity_guard_clock')
    def numbers(value, length):
        return type(value) is list and len(value) == length and all(_number(v) for v in value)
    prism = guard['prism']
    expected_prism = [movement['min_x'], movement['min_y'], movement['min_z'],
                      movement['max_x']+1, movement['max_y']+1, movement['max_z']+1]
    _require(numbers(prism, 6) and all(a == b for a, b in zip(prism, expected_prism)),
             'movement_entity_guard_prism')
    rows = guard['rows']
    _require(type(rows) is list and len(rows) <= 1023
             and _integer(guard['enumerated_count'], 1, 1024) and guard['enumerated_count'] == 1 + len(rows)
             and _integer(guard['live_other_count'], 0, 1023) and _integer(guard['removed_count'], 0, 1023)
             and guard['live_other_count'] + guard['removed_count'] == len(rows),
             'movement_entity_guard_coverage')
    identity_keys = {'id','uuid','type','class','removed'}
    live_keys = identity_keys | {'position','aabb','velocity','lerp_target','flags','projected_aabb','verdict'}
    boolean_flags = {'living','alive','dying','passenger','has_passengers','leashed','no_physics','on_fire'}
    flag_keys = boolean_flags | {'active_effect_count','hurt_time','mob_target_uuid'}
    ids, uuids, order, removed_count = set(), set(), [], 0
    for row in rows:
        _require(type(row) is dict and type(row.get('removed')) is bool
                 and set(row) == (identity_keys if row['removed'] else live_keys),
                 'movement_entity_row_schema')
        _require(_integer(row['id'], -(2**31), 2**31-1)
                 and type(row['uuid']) is str
                 and re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', row['uuid']) is not None
                 and _text(row['type']) and _text(row['class'])
                 and row['id'] not in ids and row['uuid'] not in uuids
                 and row['uuid'] != witness['context']['player_uuid'], 'movement_entity_identity')
        ids.add(row['id']); uuids.add(row['uuid']); order.append((row['id'], row['uuid'], row['class']))
        if row['removed']:
            removed_count += 1
            continue
        allowed = _MOVEMENT_ENTITY_TYPES.get(row['type'])
        _require(allowed is not None and row['class'] == allowed[0] and row['verdict'] == ('pickup_target' if pickup is not None and row['uuid'] == pickup['uuid'] else 'outside'),
                 'movement_entity_unsupported')
        flags = row['flags']
        _require(type(flags) is dict and set(flags) == flag_keys
                 and all(type(flags[k]) is bool for k in boolean_flags)
                 and flags['living'] is allowed[1] and flags['alive'] is True
                 and all(flags[k] is False for k in boolean_flags - {'living','alive'})
                 and type(flags['active_effect_count']) is int and flags['active_effect_count'] == 0
                 and type(flags['hurt_time']) is int and flags['hurt_time'] == 0
                 and flags['mob_target_uuid'] is None, 'movement_entity_flags')
        _require(all(numbers(row[k], 3) for k in ('position','velocity','lerp_target'))
                 and numbers(row['aabb'], 6) and numbers(row['projected_aabb'], 6),
                 'movement_entity_finite_geometry')
        # Convert JSON integers to binary64 too, matching the native double operations.
        position, velocity, target = ([float(v) for v in row[k]] for k in ('position','velocity','lerp_target'))
        box = [float(v) for v in row['aabb']]
        _require(all(box[i] < box[i+3] and box[i] <= position[i] <= box[i+3] for i in range(3)),
                 'movement_entity_box')
        projected = [0.0] * 6
        for i in range(3):
            lerp = target[i] - position[i]
            motion = guard['remaining_projection_ticks'] * velocity[i]
            lows = (box[i], box[i]+lerp, box[i]+motion, (box[i]+lerp)+motion)
            highs = (box[i+3], box[i+3]+lerp, box[i+3]+motion, (box[i+3]+lerp)+motion)
            _require(all(_number(v) for v in (lerp, motion, *lows, *highs)),
                     'movement_entity_projection_overflow')
            projected[i], projected[i+3] = min(lows), max(highs)
        _require(all(a == b for a, b in zip(row['projected_aabb'], projected)),
                 'movement_entity_projection_mismatch')
        is_pickup = pickup is not None and row['uuid'] == pickup['uuid']
        _require(not is_pickup or row['type'] == 'minecraft:item' and row['id'] == pickup['entity_id'],
                 'collect_guard_target_identity')
        _require(is_pickup or any(projected[i+3] < prism[i] or projected[i] > prism[i+3] for i in range(3)),
                 'movement_entity_projection_intersects')
    if pickup is not None:
        _require(sum(r['uuid'] == pickup['uuid'] and r['removed'] is False for r in rows) == 1,
                 'collect_guard_target_missing')
    _require(order == sorted(order) and removed_count == guard['removed_count']
             and len(rows) - removed_count == guard['live_other_count'], 'movement_entity_row_coverage')

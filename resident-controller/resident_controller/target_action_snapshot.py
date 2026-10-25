"""Closed native single-target witness. Evidence is never a retarget/replay permission."""
import math
import re
from .capability_snapshot import _require, _integer, _number, exact, signed_long_string

PROFILE = 'target-action-stationary-v1'
ACTIONS = ('attack_entity', 'shoot_entity')
BASE_TYPES = frozenset('minecraft:' + n for n in ('zombie','husk','zombie_villager','skeleton','stray','bogged','spider','shulker'))
MELEE = BASE_TYPES | {'minecraft:enderman','minecraft:ender_dragon'}
RANGED = BASE_TYPES | {'minecraft:creeper','minecraft:cave_spider','minecraft:blaze','minecraft:end_crystal'}
UUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
FIELDS = set(('profile action target_entity_id target_uuid target_type min_health timeout_ms alive target_health '
              'x y z station_x station_y station_z ranged shield_window draw_ticks dragon_phase selected_slot '
              'support_complete station_cells deadline_nano maximum_offense_effects maximum_offense_packets '
              'automatic_replay_allowed species support_cells entity_frame').split())


def validate_request(scope, intent):
    if type(scope) is not dict or scope.get('profile') != PROFILE:
        return
    _require(type(intent) is dict and intent.get('action') in ACTIONS, 'target_action_intent')
    ranged = intent['action'] == 'shoot_entity'
    kind = intent.get('target_type')
    _require(kind in (RANGED if ranged else MELEE), 'target_action_type_mode')
    held = intent.get('expected_held_item')
    _require(type(held) is dict and (held.get('id') == 'minecraft:bow' if ranged else held.get('id') in
        {'minecraft:'+material+'_axe' for material in ('wooden','stone','iron','golden','diamond','netherite')}), 'target_action_nonsweeping_weapon')
    required = set(('action action_id target_entity_id target_uuid target_type min_health timeout_ms capability_guard '
                    'expected_world_generation expected_dimension expected_player_uuid expected_action_session '
                    'expected_hotbar_slot expected_held_item').split())
    if ranged:
        required.add('draw_ticks')
    if kind == 'minecraft:ender_dragon':
        required.add('expected_dragon_phase')
    flag = {'minecraft:enderman':'enderman_shelter_required', 'minecraft:creeper':'creeper_safety_required',
            'minecraft:cave_spider':'poison_guard_required'}.get(kind)
    if flag:
        required.add(flag)
        _require(intent.get(flag) is True, 'target_action_species_flag')
    shield = kind == 'minecraft:blaze' and intent.get('blaze_safety_mode') == 'shield_window'
    if kind == 'minecraft:blaze':
        required.update(('blaze_safety_mode', 'expected_offhand_item' if shield else 'fire_resistance_required'))
        _require(intent.get('blaze_safety_mode') in ('shield_window','fire_resistance')
                 and (shield or intent.get('fire_resistance_required') is True), 'target_action_blaze_policy')
    _require(set(intent) in (required, required | {'expected_navigation_epoch','expected_origin'}),
             'target_action_closed_intent')
    _require(_integer(intent['target_entity_id'],0,2**31-1) and type(intent['target_uuid']) is str
             and UUID.fullmatch(intent['target_uuid']) is not None
             and _integer(intent['expected_hotbar_slot'],0,8)
             and _number(intent['min_health']) and (18 if shield else 12 if kind in
                 {'minecraft:enderman','minecraft:blaze','minecraft:creeper','minecraft:cave_spider','minecraft:end_crystal'} else 8)
                 <= intent['min_health'] <= 20
             and _integer(intent['timeout_ms'],18000 if shield else 50,20000 if shield else 10000), 'target_action_bounds')
    _require(not ranged or exact(intent.get('draw_ticks'),20), 'target_action_draw_ticks')
    _require(kind != 'minecraft:ender_dragon' or type(intent.get('expected_dragon_phase')) is int
             and intent['expected_dragon_phase'] in (6,7), 'target_action_dragon_phase')
    guard = intent.get('capability_guard')
    _require(type(guard) is dict and set(guard) == {'schema_version','source_tick','source_nano'}
             and exact(guard['schema_version'],1) and _integer(guard['source_tick'])
             and signed_long_string(guard['source_nano']), 'target_action_planning_guard')


def validate_target_action(witness, intent, native):
    validate_request({'profile':PROFILE}, intent)
    f = witness['facts']
    t = f.get('target_action')
    _require(type(t) is dict and set(t) == FIELDS and t['profile'] == PROFILE
             and t['action'] == native.get('action') == intent['action'], 'target_action_schema')
    _require(all(exact(t[k],intent[k]) for k in ('target_entity_id','target_uuid','target_type','timeout_ms'))
             and _number(t['min_health']) and t['min_health'] == intent['min_health']
             and t['target_uuid'] != f['context']['player_uuid'] and t['alive'] is True
             and _number(t['target_health']) and (t['target_health'] == 0 if t['target_type'] == 'minecraft:end_crystal'
                                                else t['target_health'] > 0), 'target_action_target_binding')
    ranged = intent['action'] == 'shoot_entity'
    shield = intent.get('blaze_safety_mode') == 'shield_window'
    _require(t['ranged'] is ranged and t['shield_window'] is shield
             and exact(t['draw_ticks'],20 if ranged else 0)
             and exact(t['dragon_phase'],intent.get('expected_dragon_phase',-1))
             and exact(t['selected_slot'],f['selected_slot']) and exact(t['selected_slot'],intent['expected_hotbar_slot'])
             and t['support_complete'] is True and _integer(t['station_cells'],3,12)
             and exact(t['maximum_offense_effects'],1) and exact(t['maximum_offense_packets'],1)
             and t['automatic_replay_allowed'] is False and signed_long_string(t['deadline_nano'])
             and int(t['deadline_nano']) == int(witness['source_nano']) + intent['timeout_ms'] * 1000000,
             'target_action_lifetime_binding')
    _require(all(_number(t[k]) and abs(t[k]) <= limit for k,limit in
                 (('x',30000000),('y',2048),('z',30000000),('station_x',30000000),('station_y',2048),('station_z',30000000)))
             and all(abs(t['station_'+k]-f[k]) <= .03 for k in ('x','y','z'))
             and abs(t['station_y']-round(t['station_y'])) <= .03, 'target_action_station')
    _require(f['health'] > t['min_health'] and f['screen_class'] == '' and f['using_item'] is False
             and not any(f[k] for k in ('on_fire','in_water','in_lava','powder_snow'))
             and f['menu']['menu_class'] == 'net.minecraft.world.inventory.InventoryMenu'
             and f['menu']['container_id'] == 0 and f['menu']['carried']['empty'] is True,
             'target_action_player_context')
    held = intent['expected_held_item']
    actual = f['inventory'][f['selected_slot']]['item']
    _require(type(held) is dict and all(exact(held.get(k),actual.get(k)) for k in
                 ('id','count','empty','item_fingerprint','component_fingerprint','max_stack_size')),
             'target_action_exact_held')
    _require(actual['count'] == 1 and (actual['id'] == 'minecraft:bow' if ranged else
             actual['id'] in {'minecraft:'+material+suffix for material in ('wooden','stone','iron','golden','diamond','netherite')
                             for suffix in ('_axe',)}), 'target_action_weapon')
    if ranged:
        _require(any(row['item']['id'] == 'minecraft:arrow' and row['item']['count'] > 0
                     for row in f['inventory']), 'target_action_plain_ammunition')
    if shield:
        offhand = f['equipment']['offhand']
        _require(offhand['id'] == 'minecraft:shield' and offhand['count'] == 1
                 and type(intent['expected_offhand_item']) is dict
                 and all(exact(intent['expected_offhand_item'].get(k),offhand.get(k)) for k in
                     ('id','count','empty','item_fingerprint','component_fingerprint','max_stack_size')),
                 'target_action_exact_shield')
    guard = intent['capability_guard']
    _require(guard['source_tick'] <= witness['source_tick']
             and int(guard['source_nano']) <= int(witness['source_nano']), 'target_action_future_planning_guard')
    if 'expected_origin' in intent:
        origin = intent['expected_origin']
        _require(_integer(intent['expected_navigation_epoch']) and type(origin) is dict and set(origin) == {'x','y','z'}
                 and all(_number(origin[k]) and abs(origin[k]-f[k]) <= .03 for k in origin), 'target_action_origin_binding')
    _validate_species(t, intent)
    _validate_station(t)
    _validate_entities(t, f)
    if native.get('status') == 'succeeded':
        validate_terminal(native, intent)


def _validate_species(t, intent):
    p, kind = t['species'], t['target_type']
    _require(type(p) is dict and p.get('type') == kind, 'target_action_species_schema')
    distance = math.dist(tuple(t[k] for k in ('x','y','z')),tuple(t['station_'+k] for k in ('x','y','z')))
    fields = {'type'}
    if kind == 'minecraft:enderman':
        fields.add('shelter_safe');_require(p.get('shelter_safe') is True, 'target_action_enderman_shelter')
    elif kind == 'minecraft:creeper':
        fields.update(('powered','ignited','swell','swell_direction','fuse_ticks','explosion_radius'))
        _require(type(p.get('powered')) is bool and p.get('ignited') is False and exact(p.get('swell'),0)
                 and type(p.get('swell_direction')) is int and p['swell_direction'] <= 0
                 and _integer(p.get('fuse_ticks'),1) and _integer(p.get('explosion_radius'),1,6)
                 and distance >= (16 if p['powered'] else 12), 'target_action_creeper_clearance')
    elif kind == 'minecraft:cave_spider':
        fields.add('poisoned');_require(p.get('poisoned') is False and distance >= 8, 'target_action_poison_guard')
    elif kind == 'minecraft:blaze':
        fields.update(('charged','mode','fire_resistance_ticks'))
        _require(type(p.get('charged')) is bool and p.get('mode') == intent['blaze_safety_mode']
                 and _integer(p.get('fire_resistance_ticks'),-1)
                 and (16 <= distance <= 32 if t['shield_window'] else distance >= 12 and
                      (p['fire_resistance_ticks'] == -1 or p['fire_resistance_ticks'] >= 60)), 'target_action_blaze_safety')
    elif kind == 'minecraft:shulker':
        fields.add('shell_open');_require(p.get('shell_open') is True, 'target_action_shulker_open')
    elif kind == 'minecraft:ender_dragon':
        fields.update(('phase','head_entity_id'))
        _require(exact(p.get('phase'),intent['expected_dragon_phase']) and _integer(p.get('head_entity_id'),0), 'target_action_dragon_head')
    elif kind == 'minecraft:end_crystal':
        _require(12 <= distance <= 32, 'target_action_crystal_clearance')
    _require(set(p) == fields, 'target_action_closed_species')


def _validate_station(t):
    cells = t['support_cells']
    _require(type(cells) is list and len(cells) == t['station_cells'], 'target_action_support_coverage')
    expected = {(x,y,z) for x in range(math.floor(t['station_x']-.31),math.floor(t['station_x']+.31)+1)
                for z in range(math.floor(t['station_z']-.31),math.floor(t['station_z']+.31)+1)
                for y in range(math.floor(t['station_y'])-1,math.floor(t['station_y'])+2)}
    observed = set()
    for c in cells:
        _require(type(c) is dict and set(c) == {'x','y','z','id','loaded','fluid_empty','support','full_collision','air'}
                 and all(type(c[k]) is int for k in ('x','y','z')) and type(c['id']) is str
                 and c['loaded'] is True and c['fluid_empty'] is True
                 and type(c['support']) is bool and type(c['full_collision']) is bool and type(c['air']) is bool,
                 'target_action_support_cell')
        point = c['x'],c['y'],c['z']
        _require(point in expected and point not in observed and c['support'] is (c['y'] < t['station_y']-.1)
                 and (c['full_collision'] and not c['air'] if c['support'] else c['air'] and not c['full_collision']),
                 'target_action_support_geometry')
        observed.add(point)
    _require(observed == expected, 'target_action_support_complete')


def _validate_entities(t, facts):
    frame = t['entity_frame']
    _require(type(frame) is dict and set(frame) == {'complete','count','entities'} and frame['complete'] is True
             and _integer(frame['count'],1,1024) and type(frame['entities']) is list
             and len(frame['entities']) == frame['count'], 'target_action_entity_coverage')
    ids, uuids, target, player = set(), set(), 0, 0
    for row in frame['entities']:
        _require(type(row) is dict and set(row) == {'id','uuid','type','x','y','z','alive','living','projectile','aabb'}
                 and _integer(row['id'],0,2**31-1) and type(row['uuid']) is str and UUID.fullmatch(row['uuid']) is not None
                 and type(row['type']) is str and all(type(row[k]) is bool for k in ('alive','living','projectile'))
                 and all(_number(row[k]) for k in ('x','y','z'))
                 and type(row['aabb']) is list and len(row['aabb']) == 6 and all(_number(v) for v in row['aabb'])
                 and all(row['aabb'][i] <= row['aabb'][i+3] for i in range(3))
                 and row['id'] not in ids and row['uuid'] not in uuids, 'target_action_entity_row')
        ids.add(row['id']);uuids.add(row['uuid'])
        if row['uuid'] == t['target_uuid']:
            target += 1
            _require(row['id'] == t['target_entity_id'] and row['type'] == t['target_type'] and row['alive'] is True
                     and all(row[k] == t[k] for k in ('x','y','z')), 'target_action_entity_identity')
        if row['uuid'] == facts['context']['player_uuid']:
            player += 1
            _require(row['alive'] is True and row['living'] is True, 'target_action_player_entity')
        elif t['target_type'] == 'minecraft:end_crystal' and row['living'] and row['alive']:
            _require(math.dist(tuple(row[k] for k in ('x','y','z')),tuple(t[k] for k in ('x','y','z'))) >= 12,
                     'target_action_crystal_collateral')
    _require(target == 1 and player == 1, 'target_action_exact_entity_coverage')


def validate_terminal(native, intent):
    p = native.get('result',{}).get('target_scope')
    fields = {'profile','target_entity_id','target_uuid','target_type','offense_effects','offense_packets',
              'draw_effects','draw_packets','shield_use_effects','shield_use_packets','shield_release_effects',
              'shield_release_packets','input_neutral','unknown_outcome','automatic_replay_allowed','server_confirmed'}
    ranged = intent['action'] == 'shoot_entity'
    shield = intent.get('blaze_safety_mode') == 'shield_window'
    _require(type(p) is dict and set(p) == fields and p['profile'] == PROFILE
             and all(exact(p[k],intent[k]) for k in ('target_entity_id','target_uuid','target_type'))
             and all(exact(p[k],value) for k,value in (('offense_effects',1),('offense_packets',1),
                 ('draw_effects',int(ranged)),('draw_packets',int(ranged)),('shield_use_effects',2 if shield else 0),
                 ('shield_use_packets',2 if shield else 0),('shield_release_effects',2 if shield else 0),
                 ('shield_release_packets',2 if shield else 0)))
             and p['input_neutral'] is True and p['unknown_outcome'] is False
             and p['automatic_replay_allowed'] is False and p['server_confirmed'] is False,
             'target_action_terminal_effect_proof')


def validate_witness(native, intent, scope):
    if type(scope) is not dict or scope.get('profile') != PROFILE:
        return
    witness = native.get('result',{}).get('scoped_native_preflight') if type(native) is dict else None
    _require(type(witness) is dict and witness.get('profile') == PROFILE, 'target_action_missing_witness')
    validate_target_action(witness, intent, native)

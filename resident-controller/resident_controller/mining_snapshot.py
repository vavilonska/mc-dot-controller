"""Closed mining-local-observed-v2 wire witness. Synthetic tests do not establish native execution."""
import math
from .capability_snapshot import _require, _integer, _number, exact, signed_long_string

LEGACY_BLOCKS = frozenset('minecraft:' + b for b in ('stone','cobblestone','dirt','andesite','granite','diorite',
    'smooth_stone','stone_bricks','bricks','oak_planks','spruce_planks','birch_planks'))
AIR = {'minecraft:air','minecraft:cave_air','minecraft:void_air'}
LEGACY_STATIC = LEGACY_BLOCKS | AIR | {'minecraft:grass_block','minecraft:bedrock'}
LOGS = frozenset('minecraft:'+name+'_log' for name in ('oak','spruce','birch','jungle','acacia','dark_oak','mangrove'))
LEAVES = frozenset(name.removesuffix('_log')+'_leaves' for name in LOGS)
ORES = frozenset(('minecraft:iron_ore','minecraft:deepslate_iron_ore'))
BLOCKS = LEGACY_BLOCKS | LOGS | ORES
ORE_CONTEXT = ORES | {'minecraft:coal_ore','minecraft:deepslate_coal_ore'}
FLOWERS = frozenset('minecraft:'+name for name in ('dandelion','poppy','blue_orchid','allium','azure_bluet',
    'red_tulip','orange_tulip','white_tulip','pink_tulip','oxeye_daisy','cornflower','lily_of_the_valley'))
PLANTS = FLOWERS | {'minecraft:short_grass','minecraft:fern','minecraft:tall_grass','minecraft:large_fern','minecraft:vine'}
STATIC = LEGACY_STATIC | LOGS | ORE_CONTEXT | LEAVES | PLANTS | {'minecraft:deepslate'}


def cell_class(block_id):
    kind = ('AirBlock' if block_id in AIR else 'GrassBlock' if block_id == 'minecraft:grass_block'
            else 'RotatedPillarBlock' if block_id in LOGS or block_id == 'minecraft:deepslate'
            else 'DropExperienceBlock' if block_id in ORE_CONTEXT else 'MangroveLeavesBlock' if block_id == 'minecraft:mangrove_leaves' else 'LeavesBlock' if block_id in LEAVES
            else 'FlowerBlock' if block_id in FLOWERS else 'TallGrassBlock' if block_id in ('minecraft:short_grass','minecraft:fern')
            else 'DoublePlantBlock' if block_id in ('minecraft:tall_grass','minecraft:large_fern')
            else 'VineBlock' if block_id == 'minecraft:vine' else 'Block')
    return 'net.minecraft.world.level.block.' + kind


def valid_properties(block_id, properties):
    if type(properties) is not dict or block_id not in STATIC or any(type(v) is not str for v in properties.values()):
        return False
    if block_id in LOGS or block_id == 'minecraft:deepslate':
        return set(properties) == {'axis'} and properties['axis'] in ('x','y','z')
    if block_id == 'minecraft:grass_block':
        return set(properties) == {'snowy'} and properties['snowy'] in ('true','false')
    if block_id in LEAVES:
        return (set(properties) == {'distance','persistent','waterlogged'} and properties['distance'] in tuple(map(str,range(1,8)))
                and properties['persistent'] in ('true','false') and properties['waterlogged'] == 'false')
    if block_id in ('minecraft:tall_grass','minecraft:large_fern'):
        return set(properties) == {'half'} and properties['half'] in ('lower','upper')
    if block_id == 'minecraft:vine':
        return set(properties) == {'up','north','south','east','west'} and all(v in ('true','false') for v in properties.values())
    return properties == {}



def coordinate(v):
    return (type(v) is dict and set(v) == {'x','y','z'} and all(type(v[k]) is int for k in v)
            and -30000000 <= v['x'] <= 30000000 and -30000000 <= v['z'] <= 30000000
            and -2048 <= v['y'] <= 2048)


def validate_mining(witness, intent, native):
    facts = witness['facts']; m = facts.get('mining')
    _require(type(m) is dict and m.get('profile') == 'mining-local-observed-v2'
             and m.get('source') == 'native-client-loaded-level', 'mining_witness_profile')
    target = intent.get('target')
    _require(coordinate(target) and intent.get('expected_block_id') in BLOCKS
             and valid_properties(intent.get('expected_block_id'), intent.get('expected_block_properties'))
             and type(intent.get('require_correct_tool')) is bool
             and _integer(intent.get('timeout_ms'),50,8000)
             and 'hotbar_slot' not in intent and 'capability_descent' not in intent
             and 'coordination_step' not in intent, 'mining_closed_intent')
    support = {'x':math.floor(facts['x']),'y':math.floor(facts['y']-.01),'z':math.floor(facts['z'])}
    _require(coordinate(support) and abs(facts['y']-support['y']-1) < 1e-7
             and not (target['x']==support['x'] and target['z']==support['z'])
             and exact(m.get('target'),target) and exact(m.get('support'),support), 'mining_support_or_target')
    expected = {'min_x':min(support['x'],target['x'])-1,'max_x':max(support['x'],target['x'])+1,
                'min_y':min(support['y'],target['y']-1),'max_y':max(support['y']+3,target['y']+1),
                'min_z':min(support['z'],target['z'])-1,'max_z':max(support['z'],target['z'])+1}
    _require(all(exact(m.get(k),v) for k,v in expected.items()), 'mining_exact_prism_bounds')
    count = math.prod(expected['max_'+k]-expected['min_'+k]+1 for k in ('x','y','z'))
    _require(0<count<=512, 'mining_footprint_bound')
    coords = [(x,y,z) for x in range(expected['min_x'],expected['max_x']+1)
              for y in range(expected['min_y'],expected['max_y']+1)
              for z in range(expected['min_z'],expected['max_z']+1)]
    _require(0<len(coords)<=512 and exact(m.get('expected_cells'),len(coords))
             and type(m.get('cells')) is list and len(m['cells'])==len(coords), 'mining_exact_footprint_coverage')
    rows={}
    for row,xyz in zip(m['cells'],coords):
        _require(type(row) is dict and all(exact(row.get(k),v) for k,v in zip(('x','y','z'),xyz))
                 and row.get('id') in STATIC and row.get('loaded') is True and row.get('fluid')=='minecraft:empty'
                 and type(row.get('state')) is str and 0<len(row['state'])<=512
                 and type(row.get('properties')) is dict, 'mining_cell_state')
        air=row['id'] in AIR
        full_cube=not air and row['id'] not in PLANTS
        _require(exact(row.get('air'),air) and exact(row.get('static_full_cube'),full_cube)
                 and row.get('block_class')==cell_class(row['id']), 'mining_static_geometry_class')
        _require(valid_properties(row['id'],row['properties']),'mining_unknown_properties')
        rows[xyz]=row
    st=rows[tuple(support[k] for k in ('x','y','z'))]
    t=rows[tuple(target[k] for k in ('x','y','z'))]
    _require(st['static_full_cube'] and st['id'] not in LEAVES and t['id']==intent['expected_block_id'] and t['properties']==intent['expected_block_properties']
             and all((rows[(support['x'],y,support['z'])]['id'] in AIR | (PLANTS - {'minecraft:vine'}))
                     for y in (support['y']+1,support['y']+2)),
             'mining_target_support_body')
    _require(all(m.get(k) is True for k in ('all_loaded','stationary','survival','closed_inventory','callbacks_installed'))
             and m.get('entity_scope')=='all-client-loaded-mining-prism-with-passive-items'
             and m.get('entity_policy')=='mining-observed-items-v1'
             and _integer(m.get('passive_items'),0,1023) and exact(m.get('entity_limit'),1024)
             and _integer(m.get('other_entities'),0,1023)
             and m['passive_items']<=m['other_entities']
             and exact(m.get('maximum_action_ticks'),160) and exact(m.get('maximum_timeout_ms'),8000) and m.get('target_static_class')==cell_class(intent['expected_block_id'])
             and exact(m.get('require_correct_tool'),intent['require_correct_tool'])
             and exact(m.get('maximum_reach'),6), 'mining_coverage_restrictions')
    from .mining_entities import validate_mining_entity_guard
    validate_mining_entity_guard(m.get('entity_guard'),m,witness)
    rows=m['entity_guard']['rows']
    _require(m['other_entities']==sum(not r['removed'] for r in rows)
             and m['passive_items']==sum(not r['removed'] and r['type']=='minecraft:item' for r in rows),'mining_entity_counts')
    _require(signed_long_string(m.get('deadline_nano')) and int(m['deadline_nano'])==int(witness['source_nano'])+intent['timeout_ms']*1000000,
             'mining_original_deadline')
    for key in ('eye','velocity'):
        _require(type(m.get(key)) is dict and set(m[key])=={'x','y','z'} and all(_number(v) for v in m[key].values()),'mining_pose')
    v=m['velocity'];eye=m['eye']
    _require(math.hypot(v['x'],v['z'])<=.0001 and -.09<=v['y']<=0 and abs(eye['x']-facts['x'])<1e-7
             and abs(eye['z']-facts['z'])<1e-7 and 0<eye['y']-facts['y']<=1.8,'mining_stationary_eye')
    _require(facts['screen_class']=='' and facts['effects']==[] and facts['hurt_time']==0
             and all(facts[k] is False for k in ('on_fire','in_water','in_lava','powder_snow','using_item'))
             and facts['menu']['menu_class']=='net.minecraft.world.inventory.InventoryMenu'
             and facts['menu']['container_id']==0 and facts['menu']['carried']['empty'] is True
             and exact(intent.get('expected_hotbar_slot'),facts['selected_slot']), 'mining_player_tool_context')
    held=intent.get('expected_held_item');actual=facts['inventory'][facts['selected_slot']]['item']
    _require(type(held) is dict and all(exact(held.get(k),actual.get(k)) for k in
             ('id','count','empty','item_fingerprint','component_fingerprint','max_stack_size')), 'mining_exact_tool_binding')
    if native.get('status') in ('succeeded','cancelled','failed'):
        result=native.get('result',{});terminal=result.get('mining')
        _require(type(terminal) is dict and terminal.get('profile')=='mining-local-observed-v2'
                 and exact(terminal.get('target'),target) and terminal.get('server_confirmed') is False
                 and terminal.get('drops_or_pickup_proven') is False
                 and terminal.get('entity_policy')=='mining-observed-items-v1'
                 and _integer(terminal.get('observed_passive_items'),0,1023)
                 and _integer(terminal.get('last_entity_check_action_tick'),0,159)
                 and exact(terminal.get('maximum_action_ticks'),160)
                 and terminal.get('future_dynamics_certified') is False
                 and type(terminal.get('effect_attempted')) is bool and type(terminal.get('unknown_outcome')) is bool
                 and type(terminal.get('block_removed')) is bool and type(terminal.get('input_neutral')) is bool
                 and _integer(terminal.get('local_checks')) and exact(terminal.get('deadline_nano'),m['deadline_nano']),
                 'mining_terminal_witness')
        if native['status']=='succeeded':
            _require(terminal['effect_attempted'] is True and terminal['unknown_outcome'] is False
                     and terminal['block_removed'] is True and terminal['input_neutral'] is True
                     and result.get('input_release_confirmed') is True and result.get('observed_block')=='minecraft:air',
                     'mining_success_requires_removal_and_cleanup')

            ray=terminal.get('final_ray')
            _require(type(ray) is dict and exact(ray.get('target'),target)
                     and ray.get('face') in ('up','down','north','south','east','west')
                     and exact(ray.get('eye'),m['eye']) and _number(ray.get('reach')) and 0<ray['reach']<=6
                     and _number(ray.get('yaw')) and _number(ray.get('pitch')) and -90<=ray['pitch']<=90
                     and type(ray.get('hit')) is dict and set(ray['hit'])=={'x','y','z'}
                     and all(_number(v) for v in ray['hit'].values()),'mining_final_ray')
            hit=ray['hit'];axis,offset={'west':('x',0),'east':('x',1),'down':('y',0),
                'up':('y',1),'north':('z',0),'south':('z',1)}[ray['face']]
            _require(abs(hit[axis]-target[axis]-offset)<=1e-6
                     and all(target[k]-1e-6<=hit[k]<=target[k]+1+1e-6 for k in ('x','y','z'))
                     and math.dist(tuple(hit[k] for k in ('x','y','z')),tuple(m['eye'][k] for k in ('x','y','z')))<=ray['reach'],
                     'mining_hit_face_and_ordinary_reach')

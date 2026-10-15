"""Closed descent witness validation; never manufactures native collision authority."""
import math
from .capability_snapshot import (_require, _integer, _number, _text, signed_long_string,
                                  validate_movement_entity_guard)

PROFILE = 'movement-step-down-observed-v1'
FLOORS = {'minecraft:'+name for name in ('stone','cobblestone','dirt','grass_block','oak_planks',
    'andesite','granite','diorite','cobbled_deepslate','smooth_stone','stone_bricks','bricks')}


def validate_step_down(witness, intent, native):
    facts = witness['facts']
    m = facts.get('step_down')
    keys = {'profile','source','min_x','max_x','min_y','max_y','min_z','max_z',
        'start_x','start_y','start_z','end_x','end_y','end_z','steps','halo','expected_cells',
        'all_loaded','closed_inventory','survival','using_item','maximum_horizontal_speed',
        'maximum_tick_sampled_displacement','maximum_downward_speed','maximum_fall_distance',
        'deadline_nano','cells','entity_guard','movement_budget_status','maximum_airborne_ticks','source_food_level'}
    _require(type(m) is dict and set(m)==keys and m['profile']==PROFILE
        and m['source']=='native-client-loaded-level' and 'movement' not in facts
        and facts['context']['dimension']=='minecraft:overworld'
        and facts.get('screen_class')=='' and facts.get('using_item') is False
        and facts.get('menu',{}).get('menu_class')=='net.minecraft.world.inventory.InventoryMenu'
        and facts.get('menu',{}).get('carried',{}).get('empty') is True
        and m['closed_inventory'] is True and m['survival'] is True and m['using_item'] is False
        and m['movement_budget_status']=='unarmed' and _integer(m['source_food_level'],6,20)
        and m['source_food_level']==facts.get('food_level')
        and type(m['maximum_airborne_ticks']) is int and m['maximum_airborne_ticks']==20,'step_down_context')
    origin, points = intent.get('expected_origin'), intent.get('waypoints')
    allowed_intent = {'action_id','action','timeout_ms','waypoints','capability_route','min_health','jump','sprint','sneak',
        'capability_guard','expected_origin','expected_navigation_epoch','expected_world_generation','expected_dimension',
        'expected_player_uuid','expected_action_session','expected_hotbar_slot','expected_held_item'}
    _require(set(intent)<=allowed_intent and intent.get('action')=='follow_path' and native.get('action')=='follow_path'
        and _number(intent.get('min_health')) and 8<=intent['min_health']<=20 and facts['health']>intent['min_health']
        and type(origin) is dict and set(origin)=={'x','y','z'} and all(_number(v) for v in origin.values())
        and type(points) is list and len(points)==1 and _integer(intent.get('timeout_ms'),50,8000)
        and intent.get('capability_route') is True and all(intent.get(k,False) is False for k in ('jump','sneak','sprint'))
        and not any(k in intent for k in ('hotbar_slot','pickup_target','encounter_route_guard','coordination_step',
            'capability_bridge','capability_descent','movement_budget_bundle_id')),'step_down_request')
    sx,sy,sz = math.floor(facts['x']),round(facts['y']),math.floor(facts['z'])
    _require(abs(facts['x']-sx-.5)<=.10 and abs(facts['z']-sz-.5)<=.10 and abs(facts['y']-sy)<=1e-7
        and -62<=sy<=316 and abs(facts['x'])<=29999990 and abs(facts['z'])<=29999990
        and all(abs(origin[k]-facts[k])<=.03 for k in ('x','y','z')),'step_down_origin')
    point = points[0]
    _require(type(point) is dict and set(point)<={'x','y','z','jump'} and all(_number(point.get(k)) for k in ('x','y','z'))
        and point.get('jump',False) is False,'step_down_waypoint')
    dx,dz = point['x']-sx-.5,point['z']-sz-.5
    _require((dx,dz) in ((1,0),(-1,0),(0,1),(0,-1)) and point['y']==sy-1,'step_down_exact_descent')
    ex,ey,ez = sx+int(dx),sy-1,sz+int(dz)
    bounds = {'min_x':min(sx,ex)-2,'max_x':max(sx,ex)+2,'min_y':sy-2,'max_y':sy+3,
        'min_z':min(sz,ez)-2,'max_z':max(sz,ez)+2,'start_x':sx,'start_y':sy,'start_z':sz,
        'end_x':ex,'end_y':ey,'end_z':ez,'steps':1,'halo':2,'expected_cells':180}
    _require(all(type(m[k]) is int and m[k]==v for k,v in bounds.items()) and m['all_loaded'] is True
        and all(type(m[k]) is float and m[k]==v for k,v in {
            'maximum_horizontal_speed':.30,'maximum_tick_sampled_displacement':.35,
            'maximum_downward_speed':.5,'maximum_fall_distance':1.01}.items())
        and signed_long_string(m['deadline_nano'])
        and int(m['deadline_nano'])==int(witness['source_nano'])+intent['timeout_ms']*1000000,'step_down_bounds')
    expected = [(x,y,z) for x in range(bounds['min_x'],bounds['max_x']+1)
        for y in range(sy-2,sy+4) for z in range(bounds['min_z'],bounds['max_z']+1)]
    cells = m['cells']
    _require(type(cells) is list and len(cells)==len(expected)==180,'step_down_coverage')
    for cell,xyz in zip(cells,expected):
        _require(type(cell) is dict and set(cell)=={'x','y','z','id','state','fluid','full_cube','friction'}
            and all(type(cell.get(k)) is int and cell[k]==n for k,n in zip(('x','y','z'),xyz))
            and cell.get('fluid')=='minecraft:empty' and _text(cell.get('state')),'step_down_cell_identity')
        floor = xyz[1]==sy-2 or xyz==(sx,sy-1,sz)
        _require(cell.get('full_cube') is floor and _number(cell.get('friction'))
            and (cell.get('id') in FLOORS and .5999999<=cell['friction']<=.6000001 if floor
                 else cell.get('id') in ('minecraft:air','minecraft:cave_air') and cell['friction']==0),
            'step_down_cell_geometry')
    validate_movement_entity_guard(m['entity_guard'],m,witness)
    terminal = native.get('result',{}).get('step_down')
    # Admission responses may already have reached a terminal state. If a terminal
    # record is present its schema and bounded metrics must still be exact.
    if terminal is not None:
        validate_terminal(terminal,m,witness)
    if native.get('status')=='succeeded':
        _require(type(terminal) is dict and terminal['phase']=='landed' and terminal['landed'] is True
            and terminal['input_neutral'] is True and native.get('result',{}).get('input_release_confirmed') is True,
            'step_down_success_terminal_required')


def validate_terminal(t, movement, witness):
    keys = {'profile','effect_attempted','local_checks','phase','landed','sampled_horizontal_distance',
        'distance_accounting','input_neutral','velocity_stopped_proven','deadline_nano','entity_guard_policy',
        'entity_guard_checks','last_entity_check_tick','last_entity_check_nano','timing_contract',
        'last_entity_check_action_tick','maximum_checked_population'}
    _require(type(t) is dict and set(t)==keys and t['profile']==PROFILE
        and all(type(t[k]) is bool for k in ('effect_attempted','landed','input_neutral','velocity_stopped_proven'))
        and t['velocity_stopped_proven'] is False and t['phase'] in ('upper','descending','landed')
        and t['landed']==(t['phase']=='landed')
        and _integer(t['local_checks']) and _integer(t['entity_guard_checks'])
        and t['local_checks']==t['entity_guard_checks']
        and _number(t['sampled_horizontal_distance']) and 0<=t['sampled_horizontal_distance']<=2
        and t['distance_accounting']=='callback-sampled-not-all-move-instrumentation'
        and t['deadline_nano']==movement['deadline_nano']
        and t['entity_guard_policy']=='observed-projection-v1'
        and t['timing_contract']=='native-action-pre-ticks-v1'
        and _integer(t['last_entity_check_action_tick'],0,159)
        and _integer(t['last_entity_check_tick'],witness['source_tick'])
        and signed_long_string(t['last_entity_check_nano'])
        and int(t['last_entity_check_nano'])>=int(witness['source_nano'])
        and _integer(t['maximum_checked_population'],1,1024),'step_down_terminal')

"""Closed composable local-segment witness validation; never manufactures native collision authority."""
import math
from .capability_snapshot import (_require, _integer, _number, _text, signed_long_string,
                                  validate_movement_entity_guard)

PROFILE = 'movement-local-segment-observed-v1'
FLOORS = {'minecraft:'+name for name in ('stone','cobblestone','dirt','grass_block','oak_planks',
    'andesite','granite','diorite','cobbled_deepslate','smooth_stone','stone_bricks','bricks')}
CONTEXT_STATIONS = {'minecraft:barrel','minecraft:furnace','minecraft:crafting_table'}
CONTEXT_LOGS = {'minecraft:'+name+'_log' for name in ('oak','spruce','birch','jungle','acacia','dark_oak')}
CONTEXT_LEAVES = {'minecraft:oak_leaves','minecraft:birch_leaves'}
CONTEXT_BLOCKS = CONTEXT_STATIONS | CONTEXT_LEAVES | CONTEXT_LOGS


def validate_local_segment(witness, intent, native):
    from .spatial_threat_snapshot import (PROFILE as SPATIAL_PROFILE, validate_entity_guard,
                                          validate_defense_stop, validate_stop_only_failure)
    from .route_spatial_stop_snapshot import PROFILES as STOP_PROFILES, validate_entity_guard as validate_stop_guard
    spatial = witness['profile'] == SPATIAL_PROFILE
    stop = witness['profile'] in STOP_PROFILES
    profile = SPATIAL_PROFILE if spatial else witness['profile'] if stop else PROFILE
    facts = witness['facts']
    m = facts.get('local_segment')
    keys = {'profile','source','min_x','max_x','min_y','max_y','min_z','max_z',
        'start_x','start_y','start_z','end_x','end_y','end_z','steps','halo','expected_cells',
        'all_loaded','closed_inventory','survival','using_item','maximum_horizontal_speed',
        'maximum_tick_sampled_displacement','maximum_vertical_speed','maximum_fall_distance',
        'maximum_rise','source_center_tolerance','arrival_radius','step_dy',
        'deadline_nano','cells','entity_guard','movement_budget_status','maximum_airborne_ticks','source_food_level'}
    _require(type(m) is dict and set(m)==keys and m['profile']==profile
        and m['source']=='native-client-loaded-level' and 'movement' not in facts
        and facts['context']['dimension']=='minecraft:overworld'
        and facts.get('screen_class')=='' and facts.get('using_item') is False
        and facts.get('menu',{}).get('menu_class')=='net.minecraft.world.inventory.InventoryMenu'
        and facts.get('menu',{}).get('carried',{}).get('empty') is True
        and m['closed_inventory'] is True and m['survival'] is True and m['using_item'] is False
        and m['movement_budget_status']=='unarmed' and _integer(m['source_food_level'],6,20)
        and m['source_food_level']==facts.get('food_level')
        and type(m['maximum_airborne_ticks']) is int and m['maximum_airborne_ticks']==20,'local_segment_context')
    origin, points = intent.get('expected_origin'), intent.get('waypoints')
    allowed_intent = {'action_id','action','timeout_ms','waypoints','capability_route','min_health','jump','sprint','sneak',
        'capability_guard','expected_origin','expected_navigation_epoch','expected_world_generation','expected_dimension',
        'expected_player_uuid','expected_action_session','expected_hotbar_slot','expected_held_item'}
    if spatial:
        allowed_intent.update(('route_threat_guard', 'route_stop_only'))
    _require(set(intent)<=allowed_intent and intent.get('action')=='follow_path' and native.get('action')=='follow_path'
        and _number(intent.get('min_health')) and 8<=intent['min_health']<=20 and facts['health']>intent['min_health']
        and type(origin) is dict and set(origin)=={'x','y','z'} and all(_number(v) for v in origin.values())
        and type(points) is list and len(points)==1 and _integer(intent.get('timeout_ms'),50,8000)
        and intent.get('capability_route') is True and all(intent.get(k,False) is False for k in ('jump','sneak','sprint'))
        and not any(k in intent for k in ('hotbar_slot','pickup_target','encounter_route_guard','coordination_step',
            'capability_bridge','capability_descent','movement_budget_bundle_id')),'local_segment_request')
    sx,sy,sz = math.floor(facts['x']),round(facts['y']),math.floor(facts['z'])
    _require(abs(facts['x']-sx-.5)<=.10 and abs(facts['z']-sz-.5)<=.10 and abs(facts['y']-sy)<=1e-7
        and -63<=sy<=316 and abs(facts['x'])<=29999990 and abs(facts['z'])<=29999990
        and all(abs(origin[k]-facts[k])<=.03 for k in ('x','y','z')),'local_segment_origin')
    point = points[0]
    _require(type(point) is dict and set(point)<={'x','y','z','jump'} and all(_number(point.get(k)) for k in ('x','y','z'))
        and point.get('jump',False) is False,'local_segment_waypoint')
    dx,dz = point['x']-sx-.5,point['z']-sz-.5
    dy=point['y']-sy
    _require((dx,dz) in ((1,0),(-1,0),(0,1),(0,-1)) and dy in (-1,0,1) and -63<=point['y']<=316,'local_segment_exact_edge')
    ex,ey,ez = sx+int(dx),sy+int(dy),sz+int(dz)
    bounds = {'min_x':min(sx,ex)-2,'max_x':max(sx,ex)+2,'min_y':min(sy,ey)-1,'max_y':max(sy,ey)+3,
        'min_z':min(sz,ez)-2,'max_z':max(sz,ez)+2,'start_x':sx,'start_y':sy,'start_z':sz,
        'end_x':ex,'end_y':ey,'end_z':ez,'steps':1,'halo':2,'step_dy':int(dy),
        'expected_cells':150 if dy==0 else 180}
    _require(all(type(m[k]) is int and m[k]==v for k,v in bounds.items()) and m['all_loaded'] is True
        and all(type(m[k]) is float and m[k]==v for k,v in {
            'maximum_horizontal_speed':.30,'maximum_tick_sampled_displacement':.35,
            'maximum_vertical_speed':.5,'maximum_fall_distance':1.01,
            'maximum_rise':1.26,'source_center_tolerance':.10,'arrival_radius':.08}.items())
        and signed_long_string(m['deadline_nano'])
        and int(m['deadline_nano'])==int(witness['source_nano'])+intent['timeout_ms']*1000000,'local_segment_bounds')
    expected = [(x,y,z) for x in range(bounds['min_x'],bounds['max_x']+1)
        for y in range(bounds['min_y'],bounds['max_y']+1) for z in range(bounds['min_z'],bounds['max_z']+1)]
    cells = m['cells']
    _require(type(cells) is list and len(cells)==len(expected)==bounds['expected_cells'],'local_segment_coverage')
    for cell,xyz in zip(cells,expected):
        _require(type(cell) is dict and set(cell)=={'x','y','z','id','state','fluid','full_cube','friction','role'}
            and all(type(cell.get(k)) is int and cell[k]==n for k,n in zip(('x','y','z'),xyz))
            and cell.get('fluid')=='minecraft:empty' and _text(cell.get('state')),'local_segment_cell_identity')
        role = cell_role(sx,sy,sz,ex,ey,ez,*xyz)
        _require(cell.get('role')==role and type(cell.get('full_cube')) is bool and _number(cell.get('friction')),
            'local_segment_cell_role')
        solid=(cell['full_cube'] is True and cell.get('id') in FLOORS and .5999999<=cell['friction']<=.6000001)
        air=(cell['full_cube'] is False and cell.get('id') in ('minecraft:air','minecraft:cave_air') and cell['friction']==0)
        context_solid=(cell['full_cube'] is True and cell.get('id') in CONTEXT_BLOCKS
            and .5999999<=cell['friction']<=.6000001)
        _require(solid if role=='support' else air if role=='clear' else solid or air or context_solid,
            'local_segment_cell_geometry')
    if spatial:
        validate_entity_guard(m['entity_guard'], m, witness, intent['route_threat_guard']['target_uuid'])
        _require('route_stop_only' not in intent or m['entity_guard']['stop_only'] is True,
                 'route_threat_stop_only_admission_required')
    elif stop:
        validate_stop_guard(m['entity_guard'], m, witness)
    else:
        validate_movement_entity_guard(m['entity_guard'],m,witness)
    terminal = native.get('result',{}).get('local_segment')
    # Admission responses may already have reached a terminal state. If a terminal
    # record is present its schema and bounded metrics must still be exact.
    if terminal is not None:
        validate_terminal(terminal,m,witness)
    if spatial:
        if ('route_threat_stop' in native.get('result', {})
                or native.get('reason') == 'capability_threat_observed'):
            validate_defense_stop(native, intent['route_threat_guard']['target_uuid'])
        elif m['entity_guard']['stop_only']:
            # A failed proof construction is not a known threat stop. Accept only
            # a narrowly bounded, correlated no-effect failure; never grant defense.
            validate_stop_only_failure(native)
    if native.get('status')=='succeeded':
        _require(type(terminal) is dict and terminal['phase']=='landed' and terminal['landed'] is True
            and terminal['input_neutral'] is True and native.get('result',{}).get('input_release_confirmed') is True,
            'local_segment_success_terminal_required')


def validate_terminal(t, movement, witness):
    from .spatial_threat_snapshot import PROFILE as SPATIAL_PROFILE, POLICY as SPATIAL_POLICY
    from .route_spatial_stop_snapshot import PROFILES as STOP_PROFILES
    spatial = witness['profile'] == SPATIAL_PROFILE
    stop = witness['profile'] in STOP_PROFILES
    profile = SPATIAL_PROFILE if spatial else witness['profile'] if stop else PROFILE
    keys = {'profile','effect_attempted','local_checks','phase','landed','sampled_horizontal_distance',
        'distance_accounting','input_neutral','velocity_stopped_proven','deadline_nano','entity_guard_policy',
        'entity_guard_checks','last_entity_check_tick','last_entity_check_nano','timing_contract',
        'last_entity_check_action_tick','maximum_checked_population','jump_pulses'}
    _require(type(t) is dict and set(t)==keys and t['profile']==profile
        and all(type(t[k]) is bool for k in ('effect_attempted','landed','input_neutral','velocity_stopped_proven'))
        and t['velocity_stopped_proven'] is False and t['phase'] in ('ground','rising','falling','landed')
        and t['landed']==(t['phase']=='landed')
        and _integer(t['local_checks']) and _integer(t['entity_guard_checks'])
        and t['local_checks']==t['entity_guard_checks']
        and _number(t['sampled_horizontal_distance']) and 0<=t['sampled_horizontal_distance']<=2
        and t['distance_accounting']=='callback-sampled-not-all-move-instrumentation'
        and t['deadline_nano']==movement['deadline_nano']
        and t['entity_guard_policy']==(SPATIAL_POLICY if spatial else STOP_PROFILES[profile] if stop else 'observed-projection-v1')
        and t['timing_contract']=='native-action-pre-ticks-v1'
        and _integer(t['last_entity_check_action_tick'],0,159)
        and _integer(t['last_entity_check_tick'],witness['source_tick'])
        and signed_long_string(t['last_entity_check_nano'])
        and int(t['last_entity_check_nano'])>=int(witness['source_nano'])
        and _integer(t['maximum_checked_population'],1,1024)
        and _integer(t['jump_pulses'],0,1)
        and (movement['step_dy']==1 or t['jump_pulses']==0)
        and (not t['landed'] or movement['step_dy']!=1 or t['jump_pulses']==1),'local_segment_terminal')


def cell_role(sx,sy,sz,ex,ey,ez,x,y,z):
    """Literal finite sweep policy; independent of the native producer's row labels."""
    if (x,z)==(sx,sz):
        if y==sy-1:return 'support'
        top=sy+3 if ey>sy else sy+2 if ey<sy else sy+1
        if sy<=y<=top:return 'clear'
    if (x,z)==(ex,ez):
        if y==ey-1:return 'support'
        top=sy+3 if ey>sy else sy+2 if ey<sy else sy+1
        if ey<=y<=top:return 'clear'
    return 'context'

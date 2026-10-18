"""Strict bounded display-only single-epoch telemetry. Never a capability witness."""
from copy import deepcopy
import json
import re
from navigation_controller.observation_clock import ClockStamp
from .capability_snapshot import exact

MAX_BYTES = 65536
KEYS = {'ok','protocol','schema_version','compact_observation_schema_version','request_id','read_only',
    'execution_authority','server_confirmed','observation_clock','context','bounds','native_elapsed_nanos',
    'native_budget_nanos','world','player','inventory','menu','control','action','terrain','coverage',
    'external_controller','native_fall_rescue_status'}
COVERAGE = {'terrain_coordinate_complete':True,'terrain_physics_omitted':True,'entities_captured':False,
            'menu_slots_captured':False,'action_details_captured':False,'inventory_recovery_complete':False}

def need(ok, reason):
    if not ok: raise ValueError('compact_observation_' + reason)

def integer(value, low=0, high=2**53-1):
    return type(value) is int and low <= value <= high

def validate(value, request_id, radius, *, identity=None, context=None, prior=None):
    need(type(value) is dict and KEYS <= set(value) <= KEYS | {'native_timing'}, 'schema')
    need(len(json.dumps(value,ensure_ascii=False,allow_nan=False).encode()) <= MAX_BYTES, 'size')
    need(value['ok'] is True and value['protocol'] == 'mineclient-bridge'
         and type(value['schema_version']) is int and value['schema_version'] == 2
         and type(value['compact_observation_schema_version']) is int and value['compact_observation_schema_version'] == 1, 'protocol')
    need(value['request_id'] == request_id and type(request_id) is str
         and re.fullmatch(r'[A-Za-z0-9_-]{1,64}',request_id) is not None, 'request')
    need(value['read_only'] is True and value['execution_authority'] is False and value['server_confirmed'] is False, 'authority')
    need(integer(radius,1,2) and exact(value['bounds'],{'radius':radius,'vertical':2}), 'bounds')
    need(exact(value['coverage'],COVERAGE), 'coverage')
    stamp=ClockStamp.parse(value['observation_clock']); ctx=stamp.as_domain()['context']
    need(exact(value['context'],ctx), 'context')
    if prior is not None: stamp.after(prior)
    if identity is not None: need(all(exact(ctx.get(k),v) for k,v in identity.items()), 'bridge_identity')
    if context is not None: need(all(exact(ctx.get(k),v) for k,v in context.items()), 'owner_context')
    for name in ('world','player','inventory','menu','control','action','terrain','external_controller','native_fall_rescue_status'):
        need(type(value[name]) is dict, name)
    world,player,action,terrain=(value[k] for k in ('world','player','action','terrain'))
    need(all(world.get(k)==ctx[k] for k in ('world_generation','dimension','integrated_server_instance'))
         and player.get('uuid')==ctx['player_uuid'] and player.get('dimension')==ctx['dimension']
         and action.get('action_session')==ctx['action_session'], 'binding')
    need(integer(world.get('game_time')) and action.get('details_omitted') is True, 'world_action')
    for key in ('native_elapsed_nanos','native_budget_nanos'):
        need(type(value[key]) is str and re.fullmatch(r'0|[1-9][0-9]{0,8}',value[key]) is not None, 'budget')
    need(value['native_budget_nanos']=='100000000' and int(value['native_elapsed_nanos'])<=100000000, 'budget')
    if 'native_timing' in value:
        need(valid_diagnostic(value['native_timing'],request_id,radius)
            and value['native_timing']['callback_elapsed_nanos']==value['native_elapsed_nanos']
            and value['native_timing']['stage']=='projection'
            and value['native_timing']['terrain_returned']==value['native_timing']['terrain_total'], 'timing')
    need(all(ClockStamp.parse(terrain.get(k))==stamp for k in ('source_clock','response_clock')), 'terrain_clock')
    need(all(terrain.get(k)==world[k] for k in ('world_generation','dimension')), 'terrain_context')
    need(integer(terrain.get('game_time')) and integer(terrain.get('response_game_time'))
         and terrain['game_time']<=terrain['response_game_time']<=world['game_time'], 'terrain_ahead_of_state')
    total=(2*radius+1)**2*5
    need(terrain.get('complete') is True and all(type(terrain.get(k)) is int and terrain[k]==v for k,v in
         {'radius':radius,'vertical':2,'offset':0,'next_offset':total,'total_cells':total,'returned':total}.items()), 'terrain_complete')
    origin=terrain.get('origin');cells=terrain.get('cells')
    need(type(origin) is dict and set(origin)=={'x','y','z'} and all(integer(v,-30000000,30000000) for v in origin.values()), 'origin')
    need(type(cells) is list and len(cells)==total, 'cells')
    expected={(x,y,z) for x in range(origin['x']-radius,origin['x']+radius+1)
        for z in range(origin['z']-radius,origin['z']+radius+1) for y in range(origin['y']-2,origin['y']+3)}
    observed=set(); unknown=0
    for cell in cells:
        need(type(cell) is dict and set(cell)<= {'x','y','z','status','known','id'} and {'x','y','z','status'}<=set(cell), 'cell')
        need(all(integer(cell[k],-30000000,30000000) for k in ('x','y','z')), 'coordinate')
        pos=tuple(cell[k] for k in ('x','y','z'));need(pos in expected and pos not in observed,'duplicate_or_outside_cell');observed.add(pos)
        need(cell['status'] in ('loaded','unloaded','out_of_world','read_failed'), 'cell_status')
        if cell['status']!='loaded': unknown+=1;need(cell.get('known') is False,'unknown_cell')
        else: need(type(cell.get('id')) is str and 0<len(cell['id'])<=160,'cell_id')
    need(observed==expected and type(terrain.get('unknown_cells')) is int and terrain['unknown_cells']==unknown,'coverage_count')
    return deepcopy(value),stamp


def valid_diagnostic(value, request_id, radius):
    keys={'schema_version','request_id','read_only','execution_authority','stage','radius','terrain_returned','terrain_total',
          'terrain_elapsed_nanos','terrain_budget_nanos','callback_elapsed_nanos','callback_budget_nanos',
          'stage_elapsed_nanos','external_controller_elapsed_nanos','external_controller_samples'}
    if not (type(value) is dict and set(value)==keys and type(value['schema_version']) is int and value['schema_version']==1
            and value['request_id']==request_id and type(value['request_id']) is str
            and value['read_only'] is True and value['execution_authority'] is False
            and value['stage'] in ('context','terrain_ids','state','final_context','projection')
            and integer(radius,1,2) and exact(value['radius'],radius)
            and integer(value['terrain_returned'],0,(2*radius+1)**2*5)
            and exact(value['terrain_total'],(2*radius+1)**2*5)):
        return False
    for key in ('terrain_elapsed_nanos','callback_elapsed_nanos','external_controller_elapsed_nanos'):
        if not (type(value[key]) is str and re.fullmatch(r'0|[1-9][0-9]{0,18}',value[key]) and int(value[key])<=2**63-1):return False
    stages=value['stage_elapsed_nanos'];total=int(value['callback_elapsed_nanos'])
    if not (type(stages) is dict and set(stages)=={'context','terrain_ids','state','final_context','projection'}
            and all(type(n) is str and re.fullmatch(r'0|[1-9][0-9]{0,18}',n) and int(n)<=total for n in stages.values())
            and sum(map(int,stages.values()))==total
            and integer(value['external_controller_samples'],0,1)
            and int(value['external_controller_elapsed_nanos'])<=int(stages['state'])
            and (value['external_controller_samples']==1 or value['external_controller_elapsed_nanos']=='0')):return False
    order=('context','terrain_ids','state','final_context','projection')
    if int(value['terrain_elapsed_nanos'])>int(stages['terrain_ids']):return False
    if any(stages[name]!='0' for name in order[order.index(value['stage'])+1:]):return False
    return value['terrain_budget_nanos']=='8000000' and value['callback_budget_nanos']=='100000000'


def snapshot(resident, command):
    need(command.get('op')=='observe' and command.get('compact_observation') is True
         and command.get('capability_observation') is True
         and not any(k in command for k in ('terrain','terrain_acquisition','observation_clock','capability_survey','coordination_step','frame')), 'options')
    radius=command.get('radius',1);need(integer(radius,1,2),'radius')
    request_id=command['request_id']
    raw=resident.bridge.request('GET',f'/control/compact-observation?request_id={request_id}&radius={radius}')
    value,stamp=validate(raw,request_id,radius,identity=resident.bridge_identity,
        prior=getattr(resident,'_compact_observation_clock',None))
    resident._compact_observation_clock=stamp
    # Does not replace the authoritative world cache or provide action preflight facts.
    return {'compact_observation':value,'resident_policy':resident.observation_policy()}

"""Synthetic finite descent witness for offline consumers, never native physics evidence."""
from copy import deepcopy
import math
from mining_collect.collect.collect_fixture import collect_fixture, redigest

PROFILE='movement-step-down-observed-v1'


def fixture(intent_override=None,scope_override=None):
    native,scope,aid,intent=collect_fixture(False)
    intent['waypoints'][0]['y']=63
    intent['min_health']=12
    if intent_override is not None:intent=deepcopy(intent_override);aid=intent['action_id']
    scope['profile']=PROFILE
    if scope_override is not None:scope=deepcopy(scope_override)
    w=native['result']['scoped_native_preflight'];w.update(scope)
    w.update(action_id=aid,action_session=intent['expected_action_session'],source_tick=intent['capability_guard']['source_tick']+1,
        source_nano=str(int(intent['capability_guard']['source_nano'])+1),admitted_nano=str(int(intent['capability_guard']['source_nano'])+21))
    f=w['facts'];f.update(intent['expected_origin'])
    f['context'].update({k:intent['expected_'+k] for k in ('world_generation','dimension','player_uuid','action_session')})
    w['context']=deepcopy(f['context']);w['planning_guard']=deepcopy(intent['capability_guard'])
    if 'expected_hotbar_slot' in intent:
        f['selected_slot']=intent['expected_hotbar_slot']
        held={k:v for k,v in intent['expected_held_item'].items() if k!='slot'}
        f['inventory'][f['selected_slot']]['item']=deepcopy(held);f['equipment']['mainhand']=deepcopy(held)
        f['menu']['slots'][36+f['selected_slot']]['item']=deepcopy(held)
    sx,sy,sz=math.floor(f['x']),round(f['y']),math.floor(f['z']);p=intent['waypoints'][0]
    ex,ey,ez=math.floor(p['x']),round(p['y']),math.floor(p['z'])
    m=f.pop('movement')
    for k in ('feet_y',):m.pop(k)
    m.update(profile=PROFILE,min_x=min(sx,ex)-2,max_x=max(sx,ex)+2,min_y=sy-2,max_y=sy+3,
        min_z=min(sz,ez)-2,max_z=max(sz,ez)+2,start_x=sx,start_y=sy,start_z=sz,end_x=ex,end_y=ey,end_z=ez,
        steps=1,expected_cells=180,maximum_downward_speed=.5,maximum_fall_distance=1.01,
        maximum_airborne_ticks=20,source_food_level=20,movement_budget_status='unarmed',
        deadline_nano=str(int(w['source_nano'])+intent['timeout_ms']*1000000))
    m['cells']=[]
    for x in range(m['min_x'],m['max_x']+1):
        for y in range(m['min_y'],m['max_y']+1):
            for z in range(m['min_z'],m['max_z']+1):
                floor=y==sy-2 or (x,y,z)==(sx,sy-1,sz)
                m['cells'].append(dict(x=x,y=y,z=z,id='minecraft:stone' if floor else 'minecraft:air',
                    state='synthetic block state',fluid='minecraft:empty',full_cube=floor,friction=.6000000238418579 if floor else 0.))
    m['entity_guard'].update(source_tick=w['source_tick'],source_nano=w['source_nano'],
        prism=[m['min_x'],m['min_y'],m['min_z'],m['max_x']+1,m['max_y']+1,m['max_z']+1])
    f['step_down']=m
    native.update(action_id=aid,action_session=intent['expected_action_session'],action='follow_path',status='running')
    native['result']['input_release_confirmed']=False
    redigest(native,intent)
    return native,scope,aid,intent


def terminal(native,*,landed=True):
    w=native['result']['scoped_native_preflight'];m=w['facts']['step_down']
    return {'profile':PROFILE,'effect_attempted':True,'local_checks':20,'phase':'landed' if landed else 'upper',
        'landed':landed,'sampled_horizontal_distance':1.,'distance_accounting':'callback-sampled-not-all-move-instrumentation',
        'input_neutral':True,'velocity_stopped_proven':False,'deadline_nano':m['deadline_nano'],
        'entity_guard_policy':'observed-projection-v1','entity_guard_checks':20,'last_entity_check_tick':w['source_tick']+10,
        'last_entity_check_nano':str(int(w['source_nano'])+500000000),'timing_contract':'native-action-pre-ticks-v1',
        'last_entity_check_action_tick':10,'maximum_checked_population':1}

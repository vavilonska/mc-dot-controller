"""Synthetic local-segment witness. This is not native or game-physics evidence."""
from copy import deepcopy
import math
from mining_collect.collect.collect_fixture import collect_fixture, redigest

PROFILE='movement-local-segment-observed-v1'

def cell_role(sx,sy,sz,ex,ey,ez,x,y,z):
    if (x,z)==(sx,sz):
        if y==sy-1:return 'support'
        if sy<=y<=sy+(3 if ey>sy else 2 if ey<sy else 1):return 'clear'
    if (x,z)==(ex,ez):
        if y==ey-1:return 'support'
        if ey<=y<=sy+(3 if ey>sy else 2 if ey<sy else 1):return 'clear'
    return 'context'

def fixture(intent_override=None,scope_override=None,*,dy=0,block=None):
    native,scope,aid,intent=collect_fixture(False)
    intent['waypoints'][0].update(y=64+dy,jump=False);intent['min_health']=12
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
    ex,ey,ez=math.floor(p['x']),round(p['y']),math.floor(p['z']);dy=ey-sy
    m=f.pop('movement');m.pop('feet_y')
    m.update(profile=PROFILE,min_x=min(sx,ex)-2,max_x=max(sx,ex)+2,min_y=min(sy,ey)-1,max_y=max(sy,ey)+3,
        min_z=min(sz,ez)-2,max_z=max(sz,ez)+2,start_x=sx,start_y=sy,start_z=sz,end_x=ex,end_y=ey,end_z=ez,
        steps=1,step_dy=dy,expected_cells=150 if dy==0 else 180,maximum_vertical_speed=.5,maximum_fall_distance=1.01,
        maximum_rise=1.26,source_center_tolerance=.10,arrival_radius=.08,
        maximum_airborne_ticks=20,source_food_level=20,movement_budget_status='unarmed',
        deadline_nano=str(int(w['source_nano'])+intent['timeout_ms']*1000000))
    m['cells']=[]
    for x in range(m['min_x'],m['max_x']+1):
        for y in range(m['min_y'],m['max_y']+1):
            for z in range(m['min_z'],m['max_z']+1):
                role=cell_role(sx,sy,sz,ex,ey,ez,x,y,z)
                block_id=block(x,y,z) if block else 'minecraft:stone' if role=='support' or y<min(sy,ey) else 'minecraft:air'
                solid=block_id not in ('minecraft:air','minecraft:cave_air')
                m['cells'].append(dict(x=x,y=y,z=z,id=block_id,role=role,
                    state='synthetic block state',fluid='minecraft:empty',full_cube=solid,friction=.6000000238418579 if solid else 0.))
    m['entity_guard'].update(source_tick=w['source_tick'],source_nano=w['source_nano'],
        prism=[m['min_x'],m['min_y'],m['min_z'],m['max_x']+1,m['max_y']+1,m['max_z']+1])
    f['local_segment']=m
    native.update(action_id=aid,action_session=intent['expected_action_session'],action='follow_path',status='running')
    native['result']['input_release_confirmed']=False;redigest(native,intent)
    return native,scope,aid,intent

def terminal(native,*,landed=True):
    w=native['result']['scoped_native_preflight'];m=w['facts']['local_segment']
    return {'profile':PROFILE,'effect_attempted':True,'local_checks':20,'phase':'landed' if landed else 'ground',
        'landed':landed,'sampled_horizontal_distance':1.,'distance_accounting':'callback-sampled-not-all-move-instrumentation',
        'input_neutral':True,'velocity_stopped_proven':False,'deadline_nano':m['deadline_nano'],
        'entity_guard_policy':'observed-projection-v1','entity_guard_checks':20,'last_entity_check_tick':w['source_tick']+10,
        'last_entity_check_nano':str(int(w['source_nano'])+500000000),'timing_contract':'native-action-pre-ticks-v1',
        'last_entity_check_action_tick':10,'maximum_checked_population':1,'jump_pulses':int(m['step_dy']==1 and landed)}

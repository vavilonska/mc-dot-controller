"""Synthetic witness builder only, not native facts or a game simulator."""
from copy import deepcopy
from .menu_fixture import fixture, digest


def movement_fixture(intent_override=None, scope_override=None):
    native, scope, action_id, intent = fixture()
    intent.pop('hotbar_slot')
    intent.update(action='follow_path',timeout_ms=8000,capability_route=True,
                  expected_origin={'x':.5,'y':64.0,'z':.5},expected_navigation_epoch=1,
                  waypoints=[{'x':1.5,'y':64,'z':.5,'jump':False}])
    if intent_override is not None: intent=deepcopy(intent_override);action_id=intent['action_id']
    scope.update(profile='movement-flat-v1')
    if scope_override is not None: scope=deepcopy(scope_override)
    w=native['result']['scoped_native_preflight'];w.update(scope)
    w.update(action_id=action_id,action_session=intent['expected_action_session'],
             source_tick=intent['capability_guard']['source_tick']+1,
             source_nano=str(int(intent['capability_guard']['source_nano'])+1),
             admitted_nano=str(int(intent['capability_guard']['source_nano'])+21))
    facts=w['facts']
    facts['context'].update({k:intent['expected_'+k] for k in ('world_generation','dimension','player_uuid','action_session')})
    facts.update(intent['expected_origin'])
    w['context']=deepcopy(facts['context'])
    import math
    sx,sy,sz=math.floor(facts['x']),round(facts['y']),math.floor(facts['z'])
    end=intent['waypoints'][-1];ex,ez=math.floor(end['x']),math.floor(end['z'])
    m={'profile':'movement-flat-v1','source':'native-client-loaded-level','min_x':min(sx,ex)-2,'max_x':max(sx,ex)+2,
       'min_y':sy-1,'max_y':sy+3,'min_z':min(sz,ez)-2,'max_z':max(sz,ez)+2,'feet_y':sy,
       'steps':len(intent['waypoints']),'halo':2,'all_loaded':True,'entity_limit':1024,'live_other_entities':0,
       'entity_scope':'all-client-loaded-entities-except-bound-player','closed_inventory':True,'survival':True,'using_item':False,
       'maximum_horizontal_speed':.30,'maximum_tick_sampled_displacement':.35,
       'deadline_nano':str(int(w['source_nano'])+intent['timeout_ms']*1000000)}
    m['cells']=[{'x':x,'y':y,'z':z,'id':'minecraft:stone' if y==sy-1 else 'minecraft:air',
                 'state':'synthetic block state','fluid':'minecraft:empty','full_cube':y==sy-1,
                 'friction':.6000000238418579 if y==sy-1 else 0.0}
                for x in range(m['min_x'],m['max_x']+1) for y in range(sy-1,sy+4)
                for z in range(m['min_z'],m['max_z']+1)]
    m['expected_cells']=len(m['cells']);facts['movement']=m
    w['planning_guard']=deepcopy(intent['capability_guard'])
    compiled=deepcopy(intent);compiled['capability_guard']={'schema_version':1,'source_tick':w['source_tick'],'source_nano':w['source_nano']}
    w.update(submitted_intent_sha256=digest(intent),command_sha256=digest(compiled))
    native.update(action_id=action_id,action_session=intent['expected_action_session'],action='follow_path')
    return native,scope,action_id,intent

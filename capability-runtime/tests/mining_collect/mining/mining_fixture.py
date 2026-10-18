"""Explicitly fabricated native facts for consumer tests; no mining/physics simulation."""
from copy import deepcopy
from .mining_menu_fixture import fixture, digest


def mining_fixture(intent_override=None,scope_override=None):
    native,scope,action_id,intent=fixture()
    intent.pop('hotbar_slot');intent.update(action='break_block',timeout_ms=8000,
        target={'x':2,'y':64,'z':0},expected_block_id='minecraft:stone',expected_block_properties={},
        require_correct_tool=True,expected_hotbar_slot=0,
        expected_held_item=deepcopy(native['result']['scoped_native_preflight']['facts']['inventory'][0]['item']))
    if intent_override is not None:intent=deepcopy(intent_override);action_id=intent['action_id']
    scope.update(profile='mining-local-observed-v2')
    if scope_override is not None:scope=deepcopy(scope_override)
    w=native['result']['scoped_native_preflight'];w.update(scope)
    w.update(action_id=action_id,action_session=intent['expected_action_session'],
        source_tick=intent['capability_guard']['source_tick']+1,
        source_nano=str(int(intent['capability_guard']['source_nano'])+1),
        admitted_nano=str(int(intent['capability_guard']['source_nano'])+21))
    f=w['facts'];f['context'].update({k:intent['expected_'+k] for k in ('world_generation','dimension','player_uuid','action_session')})
    w['context']=deepcopy(f['context']);f['selected_slot']=intent['expected_hotbar_slot']
    held={k:v for k,v in intent['expected_held_item'].items() if k!='slot'}
    f['inventory'][f['selected_slot']]['item']=deepcopy(held);f['equipment']['mainhand']=deepcopy(held)
    f['menu']['slots'][36+f['selected_slot']]['item']=deepcopy(held)
    t=intent['target'];support={'x':0,'y':63,'z':0}
    m={'profile':'mining-local-observed-v2','source':'native-client-loaded-level','target':deepcopy(t),'support':support,
       'min_x':min(0,t['x'])-1,'max_x':max(0,t['x'])+1,'min_y':min(63,t['y']-1),'max_y':max(66,t['y']+1),
       'min_z':min(0,t['z'])-1,'max_z':max(0,t['z'])+1,'all_loaded':True,'stationary':True,'survival':True,
       'closed_inventory':True,'entity_scope':'all-client-loaded-mining-prism-with-passive-items','entity_policy':'mining-observed-items-v1','passive_items':0,'other_entities':0,'entity_limit':1024,
       'target_static_class':'net.minecraft.world.level.block.'+('RotatedPillarBlock' if intent['expected_block_id'].endswith('_log') else 'DropExperienceBlock' if intent['expected_block_id'] in ('minecraft:iron_ore','minecraft:deepslate_iron_ore') else 'Block'),'require_correct_tool':intent['require_correct_tool'],
       'deadline_nano':str(int(w['source_nano'])+intent['timeout_ms']*1000000),'maximum_reach':6,
       'eye':{'x':.5,'y':65.62,'z':.5},'velocity':{'x':0.,'y':0.,'z':0.},'callbacks_installed':True}
    cells=[]
    for x in range(m['min_x'],m['max_x']+1):
        for y in range(m['min_y'],m['max_y']+1):
            for z in range(m['min_z'],m['max_z']+1):
                is_target=(x,y,z)==tuple(t[k] for k in ('x','y','z'));solid=y==63 or is_target
                cells.append({'x':x,'y':y,'z':z,'id':intent['expected_block_id'] if is_target else 'minecraft:stone' if solid else 'minecraft:air',
                    'state':'synthetic exact block state','loaded':True,'fluid':'minecraft:empty','air':not solid,
                    'static_full_cube':solid,'block_class':m['target_static_class'] if is_target else 'net.minecraft.world.level.block.'+('Block' if solid else 'AirBlock'),
                    'properties':deepcopy(intent['expected_block_properties']) if is_target else {}})
    m.update(cells=cells,expected_cells=len(cells),maximum_action_ticks=160,maximum_timeout_ms=8000)
    m['entity_guard']={'schema_version':1,'policy':'mining-observed-items-v1','source':'native-client-loaded-level',
        'scope':'all-client-loaded-mining-prism-with-passive-items','guarantee':'same-callback-current-facts-only',
        'future_dynamics_certified':False,'server_confirmed':False,'entity_limit':1024,'enumerated_count':1,
        'self_count':1,'live_other_count':0,'removed_count':0,'unsupported_count':0,'source_tick':w['source_tick'],
        'source_nano':str(int(w['source_nano'])+1),'maximum_action_ticks':160,'remaining_projection_ticks':160,
        'prism':[m['min_x'],m['min_y'],m['min_z'],m['max_x']+1,m['max_y']+1,m['max_z']+1],'rows':[]}
    f['mining']=m
    w['planning_guard']=deepcopy(intent['capability_guard']);compiled=deepcopy(intent)
    compiled['capability_guard']={'schema_version':1,'source_tick':w['source_tick'],'source_nano':w['source_nano']}
    w.update(submitted_intent_sha256=digest(intent),command_sha256=digest(compiled))
    native.update(action_id=action_id,action_session=intent['expected_action_session'],action='break_block')
    native['result'].update(observed_block='minecraft:air',mining={'profile':'mining-local-observed-v2','target':deepcopy(t),
        'effect_attempted':True,'unknown_outcome':False,'block_removed':True,'server_confirmed':False,'input_neutral':True,
        'local_checks':2,'deadline_nano':m['deadline_nano'],'drops_or_pickup_proven':False,'entity_policy':'mining-observed-items-v1','observed_passive_items':0,'last_entity_check_action_tick':1,'maximum_action_ticks':160,'future_dynamics_certified':False,
        'final_ray':{'target':deepcopy(t),'face':'west','hit':{'x':t['x'],'y':t['y']+.5,'z':t['z']+.5},
                     'eye':deepcopy(m['eye']),'reach':4.5,'yaw':-90.,'pitch':30.}}) 
    return native,scope,action_id,intent


def add_entity(d,kind='sheep',position=(20.,64.,0.),velocity=(0.,0.,0.)):
    m=d[0]['result']['scoped_native_preflight']['facts']['mining'];g=m['entity_guard']
    item=kind=='item';classes={'sheep':'animal.Sheep','item':'item.ItemEntity','arrow':'projectile.Arrow'}
    p=list(position);v=list(velocity);b=[p[0]-.125,p[1],p[2]-.125,p[0]+.125,p[1]+.25,p[2]+.125]
    proj=[min(b[i],b[i]+160*v[i]) for i in range(3)]+[max(b[i+3],b[i+3]+160*v[i]) for i in range(3)]
    row={'id':42,'uuid':'33333333-3333-4333-8333-333333333333','type':'minecraft:'+kind,
        'class':'net.minecraft.world.entity.'+classes[kind],'removed':False,'position':p,'velocity':v,
        'lerp_target':p[:],'aabb':b,'projected_aabb':proj,'verdict':'passive_item' if item else 'outside',
        'flags':{'living':not item,'alive':True,'dying':False,'passenger':False,'has_passengers':False,'leashed':False,
        'no_physics':False,'on_fire':False,'active_effect_count':0,'hurt_time':0,'mob_target_uuid':None}}
    g.update(rows=[row],enumerated_count=2,live_other_count=1);m.update(other_entities=1,passive_items=int(item));return row

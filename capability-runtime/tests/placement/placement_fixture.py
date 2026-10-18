"""Fabricated placement receipts for consumer/owner-chain tests, never engine proof."""
from copy import deepcopy
import math
from mining_collect.mining.mining_menu_fixture import fixture, digest
from resident_controller.placement_snapshot import PROFILE, FACES


def placement_fixture(intent_override=None, scope_override=None):
    native,scope,action_id,intent=fixture()
    held={'id':'minecraft:cobblestone','count':5,'empty':False,'max_stack_size':64,
          'item_fingerprint':'22222222-2222-4222-8222-222222222222',
          'component_fingerprint':'33333333-3333-4333-8333-333333333333'}
    intent.pop('hotbar_slot');intent.update(action='place_block',timeout_ms=2000,support={'x':2,'y':63,'z':0},face='up',
        expected_support_id='minecraft:stone',expected_support_properties={},expected_target_id='minecraft:air',
        expected_target_properties={},expected_block_id='minecraft:cobblestone',expected_block_properties={},
        placement_hit={'x':2.5,'y':64.,'z':.5},placement_footprint=[{'position':{'x':2,'y':64,'z':0},
        'expected_id':'minecraft:air','expected_properties':{},'block_id':'minecraft:cobblestone','properties':{}}],
        expected_navigation_epoch=0,expected_origin={'x':.5,'y':64.,'z':.5},expected_hotbar_slot=0,expected_held_item=held)
    if intent_override is not None:intent=deepcopy(intent_override);action_id=intent['action_id']
    scope.update(profile=PROFILE)
    if scope_override is not None:scope=deepcopy(scope_override)
    w=native['result']['scoped_native_preflight'];w.update(scope)
    w.update(action_id=action_id,action_session=intent['expected_action_session'],
        source_tick=intent['capability_guard']['source_tick']+1,source_nano=str(int(intent['capability_guard']['source_nano'])+1),
        admitted_nano=str(int(intent['capability_guard']['source_nano'])+21))
    f=w['facts'];f['context'].update({k:intent['expected_'+k] for k in ('world_generation','dimension','player_uuid','action_session')})
    w['context']=deepcopy(f['context']);f.update(intent['expected_origin']);f['selected_slot']=intent['expected_hotbar_slot']
    held={k:v for k,v in intent['expected_held_item'].items() if k!='slot'}
    f['inventory'][f['selected_slot']]['item']=deepcopy(held);f['equipment']['mainhand']=deepcopy(held)
    f['menu']['slots'][36+f['selected_slot']]['item']=deepcopy(held)
    s=intent['support'];face=intent['face'];t={k:s[k]+FACES[face][i] for i,k in enumerate(('x','y','z'))}
    standing={'x':math.floor(f['x']),'y':math.floor(f['y']-.01),'z':math.floor(f['z'])}
    p={'profile':PROFILE,'source':'native-client-loaded-level','support':deepcopy(s),'target':t,'standing_support':standing,
       'face':face,'support_id':intent['expected_support_id'],'support_properties':{},'block_id':intent['expected_block_id'],
       'block_properties':deepcopy(intent['expected_block_properties']),'selected_slot':f['selected_slot'],'initial_count':held['count'],
       'all_loaded':True,'complete':True,'callbacks_installed':True,'maximum_action_ticks':40,'maximum_timeout_ms':2000,
       'deadline_nano':str(int(w['source_nano'])+intent['timeout_ms']*1000000)}
    for k in ('x','y','z'):
        p['min_'+k]=min(standing[k],t[k],s[k])-1
        p['max_'+k]=max(standing[k]+3,max(t[k],s[k])+1) if k=='y' else max(standing[k],t[k],s[k])+1
    cells=[]
    for x in range(p['min_x'],p['max_x']+1):
        for y in range(p['min_y'],p['max_y']+1):
            for z in range(p['min_z'],p['max_z']+1):
                xyz=(x,y,z);support=xyz==tuple(s[k] for k in ('x','y','z'));target=xyz==tuple(t[k] for k in ('x','y','z'))
                solid=not target and (support or y<=standing['y'])
                cells.append({'x':x,'y':y,'z':z,'id':intent['expected_support_id'] if support else 'minecraft:stone' if solid else 'minecraft:air',
                    'state':'synthetic static state','loaded':True,'fluid':'minecraft:empty','air':not solid,
                    'static_full_cube':solid,'block_class':'net.minecraft.world.level.block.'+('Block' if solid else 'AirBlock'),'properties':{}})
    p.update(cells=cells,expected_cells=len(cells))
    p['entity_guard']={'schema_version':1,'policy':'observed-projection-v1','source':'native-client-loaded-level',
        'scope':'all-client-loaded-enumerated-local-corridor-exclusion','guarantee':'same-callback-current-facts-only',
        'future_dynamics_certified':False,'server_confirmed':False,'entity_limit':1024,'enumerated_count':1,
        'self_count':1,'live_other_count':0,'removed_count':0,'unsupported_count':0,'source_tick':w['source_tick'],
        'source_nano':str(int(w['source_nano'])+1),'maximum_action_ticks':160,'remaining_projection_ticks':160,
        'prism':[p['min_x'],p['min_y'],p['min_z'],p['max_x']+1,p['max_y']+1,p['max_z']+1],'rows':[]}
    f['placement']=p
    w['planning_guard']=deepcopy(intent['capability_guard']);compiled=deepcopy(intent)
    compiled['capability_guard']={'schema_version':1,'source_tick':w['source_tick'],'source_nano':w['source_nano']}
    w.update(submitted_intent_sha256=digest(intent),command_sha256=digest(compiled))
    native.update(action_id=action_id,action_session=intent['expected_action_session'],action='place_block')
    native['result']['placement']={'profile':PROFILE,'target':deepcopy(t),'support':deepcopy(s),'face':face,
        'effect_attempted':True,'effect_count':1,'packet_count':1,'unknown_outcome':False,'block_placed':True,
        'server_confirmed':False,'input_neutral':True,'local_checks':7,'selected_slot':f['selected_slot'],
        'initial_count':held['count'],'final_count':held['count']-1,'protected_inventory_unchanged':True,
        'deadline_nano':p['deadline_nano'],'automatic_replay_allowed':False,'future_dynamics_certified':False}
    return native,scope,action_id,intent

"""Complete fabricated native receipts for offline consumer tests, never engine proof."""
from copy import deepcopy
import math
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
# Import the fixture directly: mining_collect.__init__ rewrites sys.path for its
# own checkout, which must never select another production Watchdog here.
_spec = spec_from_file_location('typed_portal_generic_wire_fixture',
    Path(__file__).resolve().parents[1] / 'mining_collect/mining/mining_menu_fixture.py')
_generic = module_from_spec(_spec)
_spec.loader.exec_module(_generic)
generic_fixture, digest = _generic.fixture, _generic.digest
from resident_controller.item_interaction_snapshot import PROFILE as ITEM_PROFILE
from resident_controller.portal_entry_snapshot import PROFILE as PORTAL_PROFILE, CONTRACT

EMPTY_FP = '11111111-1111-4111-8111-111111111111'
HELD_FP = '22222222-2222-4222-8222-222222222222'
COMPONENT_FP = '33333333-3333-4333-8333-333333333333'
SERVER = '33333333-3333-4333-8333-333333333333'
SOURCE_WORLD = '11111111-2222-4333-8444-555555555555'
DESTINATION_WORLD = '22222222-2222-4333-8444-555555555555'


def held_item(kind):
    eye = kind == 'eye'
    return {'id': 'minecraft:ender_eye' if eye else 'minecraft:flint_and_steel',
        'count': 3 if eye else 1, 'empty': False, 'max_stack_size': 64 if eye else 1,
        'item_fingerprint': HELD_FP, 'component_fingerprint': COMPONENT_FP,
        'damage': 0 if eye else 4, 'max_damage': 0 if eye else 64}


def footprint(kind, last_eye=False):
    rows = []
    def add(p, before, props, after, final):
        rows.append({'position': p, 'expected_id': before, 'expected_properties': props,
                     'block_id': after, 'properties': final})
    if kind == 'flint':
        def point(u, v): return {'x': 2 + u, 'y': 64 + v, 'z': 0}
        for u, v in [(u,v) for u in range(2) for v in (-1,3)] + [(u,v) for u in (-1,2) for v in range(3)]:
            add(point(u,v), 'minecraft:obsidian', {}, 'minecraft:obsidian', {})
        for u in range(2):
            for v in range(3): add(point(u,v), 'minecraft:air', {}, 'minecraft:nether_portal', {'axis':'x'})
    else:
        target = {'x': 3, 'y': 63, 'z': -1}
        for i in range(3):
            for p, facing in [({'x':3+i,'y':63,'z':-1},'south'), ({'x':3+i,'y':63,'z':3},'north'),
                              ({'x':2,'y':63,'z':i},'east'), ({'x':6,'y':63,'z':i},'west')]:
                props = {'facing':facing, 'eye':'true' if last_eye and p != target else 'false'}
                add(p, 'minecraft:end_portal_frame', props, 'minecraft:end_portal_frame',
                    {**props,'eye':'true'} if p == target else deepcopy(props))
        for x in range(3):
            for z in range(3): add({'x':3+x,'y':63,'z':z},'minecraft:air',{},'minecraft:end_portal' if last_eye else 'minecraft:air',{})
    return rows


def canonical_intent(kind='flint', last_eye=False):
    _, _, action_id, intent = generic_fixture()
    intent.pop('hotbar_slot')
    intent.update(action_id=action_id, expected_navigation_epoch=4, expected_origin={'x':.5,'y':64.,'z':.5},
        expected_hotbar_slot=0, expected_held_item=held_item(kind))
    if kind == 'portal':
        intent.update(action='follow_path', timeout_ms=5000, waypoints=[{'x':1.5,'y':64,'z':.5,'jump':False}],
            typed_portal_entry={'portal_cell':{'x':1,'y':64,'z':0}, 'portal_id':'minecraft:nether_portal',
            'portal_properties':{'axis':'x'}, 'destination':'minecraft:the_nether', 'entry_contract':CONTRACT})
    else:
        target = {'x':2,'y':63,'z':0} if kind == 'flint' else {'x':3,'y':63,'z':-1}
        props = {} if kind == 'flint' else {'facing':'south','eye':'false'}
        metadata = {'kind':'ignite_nether_portal','interior_base':{'x':2,'y':64,'z':0},'axis':'x','width':2,'height':3} if kind == 'flint' else {'kind':'insert_end_eye','interior_corner':{'x':3,'y':63,'z':0}}
        intent.update(action='interact_block', timeout_ms=3000, target=target, face='up',
            expected_block_id='minecraft:obsidian' if kind == 'flint' else 'minecraft:end_portal_frame',
            expected_block_properties=props, typed_item_interaction=metadata,
            item_hit={'x':target['x']+.5,'y':target['y']+(1 if kind=='flint' else 13/16),'z':target['z']+.5},
            item_footprint=footprint(kind,last_eye))
    return intent


def cell(x, y, z, id, props=None):
    cls = {'minecraft:grass_block':'GrassBlock','minecraft:end_portal_frame':'EndPortalFrameBlock',
           'minecraft:nether_portal':'NetherPortalBlock','minecraft:end_portal':'EndPortalBlock'}.get(id, 'AirBlock' if id=='minecraft:air' else 'Block')
    return {'x':x,'y':y,'z':z,'id':id,'state':'synthetic offline cell',
        'block_class':'net.minecraft.world.level.block.'+cls,'loaded':True,'fluid':'minecraft:empty','properties':deepcopy(props or {})}


def entity_guard(p, w):
    return {'schema_version':1,'policy':'observed-projection-v1','source':'native-client-loaded-level',
        'scope':'all-client-loaded-enumerated-local-corridor-exclusion','guarantee':'same-callback-current-facts-only',
        'future_dynamics_certified':False,'server_confirmed':False,'entity_limit':1024,'enumerated_count':1,
        'self_count':1,'live_other_count':0,'removed_count':0,'unsupported_count':0,'source_tick':w['source_tick'],
        'source_nano':str(int(w['source_nano'])+1),'maximum_action_ticks':160,'remaining_projection_ticks':160,
        'prism':[p['min_x'],p['min_y'],p['min_z'],p['max_x']+1,p['max_y']+1,p['max_z']+1],'rows':[]}


def typed_fixture(kind='flint', intent_override=None, scope_override=None, *, terminal=True, last_eye=False):
    native, scope, _, _ = generic_fixture()
    intent = deepcopy(intent_override) if intent_override is not None else canonical_intent(kind,last_eye)
    action_id = intent['action_id']
    scope.update(profile=PORTAL_PROFILE if kind=='portal' else ITEM_PROFILE)
    if scope_override is not None: scope=deepcopy(scope_override)
    w=native['result']['scoped_native_preflight']; w.update(scope)
    w.update(action_id=action_id, action_session=intent['expected_action_session'],
        source_tick=intent['capability_guard']['source_tick']+1, source_nano=str(int(intent['capability_guard']['source_nano'])+1),
        admitted_nano=str(int(intent['capability_guard']['source_nano'])+21))
    f=w['facts']; f['context'].update({k:intent['expected_'+k] for k in ('world_generation','dimension','player_uuid','action_session')})
    w['context']=deepcopy(f['context']);f.update(intent['expected_origin']);f['selected_slot']=intent['expected_hotbar_slot']
    held={k:v for k,v in intent['expected_held_item'].items() if k!='slot'}
    f['inventory'][f['selected_slot']]['item']=deepcopy(held);f['equipment']['mainhand']=deepcopy(held)
    f['menu']['slots'][36+f['selected_slot']]['item']=deepcopy(held)
    p={'profile':scope['profile'],'source':'native-client-loaded-level','all_loaded':True,'complete':True,
       'maximum_action_ticks':160 if kind=='portal' else 60,'maximum_timeout_ms':8000 if kind=='portal' else 3000,
       'deadline_nano':str(int(w['source_nano'])+intent['timeout_ms']*1000000)}
    if kind=='portal':
        m=intent['typed_portal_entry'];point=intent['waypoints'][0];x,y,z=(f[k] for k in ('x','y','z'));sy=round(y)
        p.update(typed_portal_entry=deepcopy(m),min_x=math.floor(min(x,point['x'])-.31),max_x=math.floor(max(x,point['x'])+.31),
            min_y=sy-1,max_y=sy+1,min_z=math.floor(min(z,point['z'])-.31),max_z=math.floor(max(z,point['z'])+.31))
        p['cells']=[cell(x,y,z,m['portal_id'] if {'x':x,'y':y,'z':z}==m['portal_cell'] else 'minecraft:stone' if y==sy-1 else 'minecraft:air',
            m['portal_properties'] if {'x':x,'y':y,'z':z}==m['portal_cell'] else {})
            for x in range(p['min_x'],p['max_x']+1) for y in range(p['min_y'],p['max_y']+1) for z in range(p['min_z'],p['max_z']+1)]
    else:
        standing={'x':math.floor(f['x']),'y':math.floor(f['y']-.01),'z':math.floor(f['z'])}
        positions=[standing]+[r['position'] for r in intent['item_footprint']]
        p.update(kind=intent['typed_item_interaction']['kind'],target=deepcopy(intent['target']),standing_support=standing,
            typed_item_interaction=deepcopy(intent['typed_item_interaction']),item_hit=deepcopy(intent['item_hit']),
            item_footprint=deepcopy(intent['item_footprint']),selected_slot=f['selected_slot'],initial_count=held['count'],
            initial_damage=held['damage'],callbacks_installed=True)
        p.update({prefix+k:func(v[k]+(3 if k=='y' and prefix=='max_' and v is standing else 0) for v in positions)+delta
            for k in ('x','y','z') for prefix,func,delta in (('min_',min,-1),('max_',max,1))})
        overrides={tuple(r['position'][k] for k in ('x','y','z')):r for r in intent['item_footprint']}
        cells=[]
        for x in range(p['min_x'],p['max_x']+1):
            for y in range(p['min_y'],p['max_y']+1):
                for z in range(p['min_z'],p['max_z']+1):
                    row=overrides.get((x,y,z));cells.append(cell(x,y,z,row['expected_id'] if row else 'minecraft:stone' if y<=standing['y'] else 'minecraft:air',row['expected_properties'] if row else {}))
        p['cells']=cells
    p.update(expected_cells=len(p['cells']),entity_guard=entity_guard(p,w))
    key='portal_entry' if kind=='portal' else 'item_interaction';f[key]=p
    w['planning_guard']=deepcopy(intent['capability_guard']);compiled=deepcopy(intent)
    compiled['capability_guard']={'schema_version':1,'source_tick':w['source_tick'],'source_nano':w['source_nano']}
    w.update(submitted_intent_sha256=digest(intent),command_sha256=digest(compiled))
    native.update(action_id=action_id,action_session=intent['expected_action_session'],action=intent['action'],
        ok=True,action_schema_version=1,server_confirmed=False,status='cancelled' if kind=='portal' else 'succeeded',
        reason='world_transition' if kind=='portal' else 'synthetic_item_success')
    if kind=='portal':
        t={'profile':PORTAL_PROFILE,'effect_attempted':True,'unknown_outcome':False,'transition_eligible':True,'source_portal_contact':True,
            'source_dimension':intent['expected_dimension'],'destination':m['destination'],'portal_cell':deepcopy(m['portal_cell']),
            'entry_contract':CONTRACT,'original_native_action_id':action_id,'original_action_session':intent['expected_action_session'],
            'original_player_uuid':intent['expected_player_uuid'],'integrated_server_instance':f['context']['integrated_server_instance'],
            'source_world_generation':intent['expected_world_generation'],'deadline_nano':p['deadline_nano'],'input_neutral':True,
            'local_checks':8,'sampled_distance':0.,'destination_arrival_proven':False,'automatic_replay_allowed':False,'server_confirmed':False}
    else:
        eye=kind=='eye'; t={'profile':ITEM_PROFILE,'kind':p['kind'],'target':deepcopy(p['target']),'effect_attempted':True,
            'use_count':1,'local_effect_count':0 if eye else 1,'packet_count':1,'unknown_outcome':False,
            'consumption_verified':True,'durability_verified':True,'block_outcome_verified':True,'input_neutral':True,
            'protected_inventory_unchanged':True,'selected_slot':p['selected_slot'],'initial_count':p['initial_count'],
            'final_count':p['initial_count']-(1 if eye else 0),'initial_damage':p['initial_damage'],
            'final_damage':p['initial_damage']+(0 if eye else 1),'local_checks':8,'guard_reason':'',
            'deadline_nano':p['deadline_nano'],'automatic_replay_allowed':False,'server_confirmed':False}
    native['result'][key]=t
    if not terminal: native.update(status='running',reason='synthetic_admitted')
    return native,scope,action_id,intent

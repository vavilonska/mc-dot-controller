"""Exact source-action transition witness. Never substitutes portal disappearance for arrival."""
import math
from .capability_snapshot import _require,_integer,_number,exact,signed_long_string,validate_movement_entity_guard
from .item_interaction_snapshot import COMMON, validate_cells, STACK
from .mining_snapshot import coordinate, AIR
PROFILE='portal-entry-observed-v1'
CONTRACT='flat-supported-max-two-blocks-v1'
PAIRS={('minecraft:overworld','minecraft:the_nether'):'minecraft:nether_portal',
    ('minecraft:the_nether','minecraft:overworld'):'minecraft:nether_portal',
    ('minecraft:overworld','minecraft:the_end'):'minecraft:end_portal',
    ('minecraft:the_end','minecraft:overworld'):'minecraft:end_portal'}
FLOORS={'minecraft:'+k for k in ('stone','cobblestone','dirt','grass_block','obsidian','netherrack','end_stone','stone_bricks')}
KEYS={'profile','source','typed_portal_entry','min_x','max_x','min_y','max_y','min_z','max_z','expected_cells','cells',
    'all_loaded','complete','maximum_action_ticks','maximum_timeout_ms','deadline_nano','entity_guard'}
TERMINAL={'profile','effect_attempted','unknown_outcome','transition_eligible','source_portal_contact','source_dimension','destination','portal_cell','entry_contract',
    'original_native_action_id','original_action_session','original_player_uuid','integrated_server_instance','source_world_generation',
    'deadline_nano','input_neutral','local_checks','sampled_distance','destination_arrival_proven','automatic_replay_allowed','server_confirmed'}
TRANSITIONS={'world_changed','world_or_player_changed','world_transition','capability_world_changed','capability_dimension_changed'}


def validate_request(scope,intent):
    _require(type(scope) is dict and type(intent) is dict,'portal_entry_request_objects')
    if scope.get('profile')!=PROFILE:
        _require('typed_portal_entry' not in intent,'portal_entry_profile_mismatch')
        return
    allowed=COMMON|{'waypoints','typed_portal_entry'}
    _require(allowed<=set(intent)<=allowed|{'hotbar_slot','jump','sneak'} and intent['action']=='follow_path'
        and _integer(intent['timeout_ms'],5000,8000) and exact(intent.get('hotbar_slot',-1),-1)
        and intent.get('jump',False) is False and intent.get('sneak',False) is False,'portal_entry_closed_request')
    m=intent['typed_portal_entry']
    _require(type(m) is dict and set(m)=={'portal_cell','portal_id','portal_properties','destination','entry_contract'}
        and coordinate(m['portal_cell']) and m['entry_contract']==CONTRACT,'portal_entry_request_metadata')
    kind=PAIRS.get((intent['expected_dimension'],m['destination']));props=m['portal_properties'];c=m['portal_cell']
    _require(kind is not None and m['portal_id']==kind and (exact(props,{}) if kind=='minecraft:end_portal' else
        type(props) is dict and set(props)=={'axis'} and props['axis'] in ('x','z')),'portal_entry_request_dimension')
    _require(exact(intent['waypoints'],[{'x':c['x']+.5,'y':c['y'],'z':c['z']+.5,'jump':False}]),'portal_entry_request_waypoint')


def validate_portal_entry(witness,intent,native):
    validate_request({"profile":PROFILE},intent)
    facts=witness['facts'];p=facts.get('portal_entry');allowed=COMMON|{'waypoints','typed_portal_entry'}
    _require(type(intent) is dict and allowed<=set(intent)<=allowed|{'hotbar_slot','jump','sneak'}
        and intent['action']=='follow_path' and _integer(intent['timeout_ms'],5000,8000)
        and exact(intent.get('hotbar_slot',-1),-1) and intent.get('jump',False) is False and intent.get('sneak',False) is False,
        'portal_entry_closed_intent')
    m=intent['typed_portal_entry'];_require(type(m) is dict and set(m)=={'portal_cell','portal_id','portal_properties','destination','entry_contract'}
        and coordinate(m['portal_cell']) and m['entry_contract']==CONTRACT,'portal_entry_metadata')
    source=facts['context']['dimension'];kind=PAIRS.get((source,m['destination']));cell=m['portal_cell'];props=m['portal_properties']
    _require(kind is not None and m['portal_id']==kind and (exact(props,{}) if kind=='minecraft:end_portal' else
        type(props) is dict and set(props)=={'axis'} and props['axis'] in ('x','z')),'portal_entry_dimension_and_state')
    point={'x':cell['x']+.5,'y':cell['y'],'z':cell['z']+.5,'jump':False}
    _require(exact(intent['waypoints'],[point]) and type(p) is dict and set(p)==KEYS and p['profile']==PROFILE
        and p['source']=='native-client-loaded-level' and exact(p['typed_portal_entry'],m),'portal_entry_closed_coverage')
    x,y,z=(facts[k] for k in ('x','y','z'));sx,sy,sz=math.floor(x),round(y),math.floor(z)
    _require(abs(x-sx-.5)<=.10 and abs(z-sz-.5)<=.10 and abs(y-sy)<1e-7 and cell['y']==sy
        and .23<math.hypot(point['x']-x,point['z']-z)<=2 and all(exact(intent['expected_origin'][k],facts[k]) for k in ('x','y','z')),
        'portal_entry_centered_flat_two_block_origin')
    bounds={'min_x':math.floor(min(x,point['x'])-.31),'max_x':math.floor(max(x,point['x'])+.31),
        'min_y':sy-1,'max_y':sy+1,'min_z':math.floor(min(z,point['z'])-.31),'max_z':math.floor(max(z,point['z'])+.31)}
    count=math.prod(bounds['max_'+k]-bounds['min_'+k]+1 for k in ('x','y','z'))
    _require(0<count<=48 and all(exact(p[k],v) for k,v in bounds.items()) and exact(p['expected_cells'],count),'portal_entry_exact_bounds')
    rows=validate_cells(p,bounds,FLOORS|AIR|{kind})
    for xyz,r in rows.items():
        _require(r['id'] in FLOORS if xyz[1]==sy-1 else r['id'] in AIR or r['id']==kind and exact(r['properties'],props),'portal_entry_corridor_cell')
    _require(rows[tuple(cell[k] for k in ('x','y','z'))]['id']==kind,'portal_entry_exact_target_cell')
    _require(p['all_loaded'] is True and p['complete'] is True and exact(p['maximum_action_ticks'],160)
        and exact(p['maximum_timeout_ms'],8000) and signed_long_string(p['deadline_nano'])
        and int(p['deadline_nano'])==int(witness['source_nano'])+intent['timeout_ms']*1000000,'portal_entry_fixed_deadline')
    validate_movement_entity_guard(p['entity_guard'],p,witness)
    slot=facts['selected_slot'];held=facts['inventory'][slot]['item']
    _require(exact(intent['expected_hotbar_slot'],slot) and all(exact(intent['expected_held_item'].get(k),held.get(k)) for k in STACK)
        and facts['screen_class']=='' and facts['effects']==[] and facts['hurt_time']==0
        and all(facts[k] is False for k in ('on_fire','in_water','in_lava','powder_snow','using_item'))
        and facts['menu']['menu_class']=='net.minecraft.world.inventory.InventoryMenu' and facts['menu']['container_id']==0
        and facts['menu']['carried']['empty'] is True,'portal_entry_inventory_and_player')
    if native.get('status') in ('succeeded','cancelled','failed'):
        result=native.get('result',{});t=result.get('portal_entry')
        _require(type(t) is dict and set(t)==TERMINAL and t['profile']==PROFILE
            and all(type(t[k]) is bool for k in ('effect_attempted','unknown_outcome','transition_eligible','source_portal_contact','input_neutral'))
            and t['source_dimension']==source and t['destination']==m['destination'] and exact(t['portal_cell'],cell) and t['entry_contract']==CONTRACT
            and t['original_native_action_id']==intent['action_id'] and t['original_action_session']==intent['expected_action_session']
            and t['original_player_uuid']==intent['expected_player_uuid'] and t['source_world_generation']==intent['expected_world_generation']
            and t['integrated_server_instance']==facts['context']['integrated_server_instance'] and t['deadline_nano']==p['deadline_nano']
            and _integer(t['local_checks']) and _number(t['sampled_distance']) and 0<=t['sampled_distance']<=3
            and t['destination_arrival_proven'] is False and t['automatic_replay_allowed'] is False and t['server_confirmed'] is False,
            'portal_entry_exact_terminal_binding')
        _require(native['status']!='succeeded','portal_entry_native_arrival_not_proven')
        if t['transition_eligible']:
            _require(native['status']=='cancelled' and native.get('reason') in TRANSITIONS and t['effect_attempted'] is True
                and t['source_portal_contact'] is True and t['unknown_outcome'] is False and t['input_neutral'] is True and result.get('input_release_confirmed') is True,
                'portal_entry_transition_requires_exact_release')
        elif native.get('reason') in TRANSITIONS:
            _require(t['unknown_outcome'] is True,'portal_entry_unbound_transition_unknown')

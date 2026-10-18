"""Closed placement witness validator. Client observations never prove server acceptance."""
import math
from .capability_snapshot import _require, _integer, exact, signed_long_string, validate_movement_entity_guard
from .mining_snapshot import LEGACY_BLOCKS as BLOCKS, AIR, LEGACY_STATIC, coordinate

STATIC = LEGACY_STATIC | {'minecraft:crafting_table'}
MATERIALS = {'minecraft:cobblestone', 'minecraft:crafting_table', 'minecraft:furnace'}

def exact_material(block_id, properties):
    return (type(properties) is dict and block_id in MATERIALS
            and (set(properties) == {'facing', 'lit'}
                 and properties['facing'] in ('north','south','east','west')
                 and properties['lit'] == 'false' if block_id == 'minecraft:furnace' else properties == {}))

PROFILE = 'placement-local-observed-v1'
FACES = {'up':(0,1,0),'down':(0,-1,0),'north':(0,0,-1),'south':(0,0,1),'east':(1,0,0),'west':(-1,0,0)}
KEYS = {'profile','source','support','target','standing_support','face','support_id','support_properties',
        'block_id','block_properties','selected_slot','initial_count','min_x','max_x','min_y','max_y',
        'min_z','max_z','expected_cells','cells','all_loaded','complete','callbacks_installed',
        'maximum_action_ticks','maximum_timeout_ms','deadline_nano','entity_guard'}
TERMINAL = {'profile','target','support','face','effect_attempted','effect_count','packet_count','unknown_outcome',
            'block_placed','server_confirmed','input_neutral','local_checks','selected_slot','initial_count',
            'final_count','protected_inventory_unchanged','deadline_nano','automatic_replay_allowed','future_dynamics_certified'}
INTENT = {'action_id','action','timeout_ms','support','face','expected_support_id','expected_support_properties',
          'expected_target_id','expected_target_properties','expected_block_id','expected_block_properties',
          'placement_hit','placement_footprint','expected_navigation_epoch','expected_origin','capability_guard',
          'expected_world_generation','expected_dimension','expected_player_uuid','expected_action_session',
          'expected_hotbar_slot','expected_held_item'}
STACK = ('id','count','empty','item_fingerprint','component_fingerprint','max_stack_size')


def validate_placement(witness, intent, native):
    facts = witness['facts']; p = facts.get('placement')
    _require(type(p) is dict and set(p) == KEYS and p['profile'] == PROFILE
             and p['source'] == 'native-client-loaded-level', 'placement_closed_coverage')
    _require(set(intent) >= INTENT and set(intent) <= INTENT | {'hotbar_slot','jump','sneak'}
             and intent.get('action') == 'place_block' and _integer(intent.get('timeout_ms'),50,2000)
             and ('hotbar_slot' not in intent or exact(intent['hotbar_slot'],-1))
             and intent.get('jump',False) is False and intent.get('sneak',False) is False,
             'placement_closed_intent')
    support = intent['support']; face = intent['face']
    _require(coordinate(support) and face in FACES and intent['expected_support_id'] in BLOCKS
             and exact(intent['expected_support_properties'],{}) and intent['expected_target_id'] == 'minecraft:air'
             and exact(intent['expected_target_properties'],{})
             and exact_material(intent['expected_block_id'], intent['expected_block_properties']), 'placement_exact_material_and_support')
    target = {k:support[k]+FACES[face][i] for i,k in enumerate(('x','y','z'))}
    hit = {k:support[k]+.5+FACES[face][i]*.5 for i,k in enumerate(('x','y','z'))}
    footprint = [{'position':target,'expected_id':'minecraft:air','expected_properties':{},
                  'block_id':intent['expected_block_id'],'properties':intent['expected_block_properties']}]
    _require(coordinate(target) and exact(intent['placement_hit'],hit) and exact(intent['placement_footprint'],footprint)
             and exact(p['target'],target) and exact(p['support'],support) and p['face'] == face
             and p['support_id'] == intent['expected_support_id'] and exact(p['support_properties'],{})
             and p['block_id'] == intent['expected_block_id'] and exact(p['block_properties'],intent['expected_block_properties']), 'placement_exact_target_face')
    standing = {'x':math.floor(facts['x']),'y':math.floor(facts['y']-.01),'z':math.floor(facts['z'])}
    _require(coordinate(standing) and exact(p['standing_support'],standing)
             and abs(facts['y']-standing['y']-1)<1e-7 and facts['context']['dimension']=='minecraft:overworld'
             and _integer(intent['expected_navigation_epoch']) and type(intent['expected_origin']) is dict
             and set(intent['expected_origin']) == {'x','y','z'}
             and all(exact(intent['expected_origin'][k],facts[k]) for k in ('x','y','z')),
             'placement_stationary_origin')
    bounds = {key+axis: value for axis in ('x','y','z') for key,value in (
        ('min_',min(standing[axis],target[axis],support[axis])-1),
        ('max_',max(standing[axis]+3,max(target[axis],support[axis])+1) if axis=='y'
         else max(standing[axis],target[axis],support[axis])+1))}
    _require(all(exact(p[k],v) for k,v in bounds.items()),'placement_exact_bounds')
    count = math.prod(bounds['max_'+k]-bounds['min_'+k]+1 for k in ('x','y','z'))
    _require(0<count<=512 and exact(p['expected_cells'],count) and type(p['cells']) is list
             and len(p['cells']) == count,'placement_exact_coverage')
    coords = [(x,y,z) for x in range(bounds['min_x'],bounds['max_x']+1)
              for y in range(bounds['min_y'],bounds['max_y']+1) for z in range(bounds['min_z'],bounds['max_z']+1)]
    rows = {}
    for row, xyz in zip(p['cells'],coords):
        _require(type(row) is dict and set(row)=={'x','y','z','id','state','loaded','fluid','air','static_full_cube','block_class','properties'}
                 and all(exact(row[k],v) for k,v in zip(('x','y','z'),xyz)) and row['id'] in STATIC
                 and row['loaded'] is True and row['fluid']=='minecraft:empty' and type(row['state']) is str
                 and 0<len(row['state'])<=512 and type(row['properties']) is dict,'placement_cell')
        air=row['id'] in AIR
        cls='net.minecraft.world.level.block.'+('AirBlock' if air else 'GrassBlock' if row['id']=='minecraft:grass_block' else 'CraftingTableBlock' if row['id']=='minecraft:crafting_table' else 'Block')
        _require(exact(row['air'],air) and exact(row['static_full_cube'],not air) and row['block_class']==cls
                 and (set(row['properties'])=={'snowy'} and row['properties']['snowy'] in ('true','false')
                      if row['id']=='minecraft:grass_block' else row['properties']=={}), 'placement_static_class_state')
        rows[xyz]=row
    def at(pos):return rows[tuple(pos[k] for k in ('x','y','z'))]
    _require(at(target)['id']=='minecraft:air' and at(support)['id']==p['support_id'] and at(standing)['id'] in LEGACY_STATIC-AIR
             and all(rows[(standing['x'],y,standing['z'])]['air'] for y in (standing['y']+1,standing['y']+2)),
             'placement_support_target_and_body')
    _require(all(p[k] is True for k in ('all_loaded','complete','callbacks_installed'))
             and exact(p['maximum_action_ticks'],40) and exact(p['maximum_timeout_ms'],2000)
             and signed_long_string(p['deadline_nano'])
             and int(p['deadline_nano']) == int(witness['source_nano'])+intent['timeout_ms']*1000000,
             'placement_bounded_deadline')
    # Uses the unchanged stricter movement entity policy: all ordinary entities,
    # including drops, must remain outside the complete prism's projected horizon.
    validate_movement_entity_guard(p['entity_guard'],p,witness)
    selected=facts['selected_slot']; held=facts['inventory'][selected]['item']
    _require(exact(p['selected_slot'],selected) and exact(intent['expected_hotbar_slot'],selected)
             and _integer(p['initial_count'],1,64) and exact(p['initial_count'],held['count'])
             and held['id']==intent['expected_block_id'] and held['empty'] is False and exact(held['max_stack_size'],64)
             and type(intent['expected_held_item']) is dict
             and all(exact(intent['expected_held_item'].get(k),held.get(k)) for k in STACK)
             and facts['screen_class']=='' and facts['effects']==[] and facts['hurt_time']==0
             and all(facts[k] is False for k in ('on_fire','in_water','in_lava','powder_snow','using_item'))
             and facts['menu']['menu_class']=='net.minecraft.world.inventory.InventoryMenu'
             and facts['menu']['container_id']==0 and facts['menu']['carried']['empty'] is True,
             'placement_selected_plain_stack_and_player')
    if native.get('status') in ('succeeded','cancelled','failed'):
        result=native.get('result',{}); t=result.get('placement')
        _require(type(t) is dict and set(t)==TERMINAL and t['profile']==PROFILE
                 and exact(t['target'],target) and exact(t['support'],support) and t['face']==face
                 and all(type(t[k]) is bool for k in ('effect_attempted','unknown_outcome','block_placed','input_neutral','protected_inventory_unchanged'))
                 and t['server_confirmed'] is False and t['automatic_replay_allowed'] is False and t['future_dynamics_certified'] is False
                 and _integer(t['effect_count'],0,1) and _integer(t['packet_count'],0,1)
                 and t['packet_count']<=t['effect_count'] and (t['effect_attempted'] or t['effect_count']==0)
                 and _integer(t['local_checks']) and _integer(t['final_count'],0,64)
                 and exact(t['selected_slot'],selected) and exact(t['initial_count'],p['initial_count'])
                 and exact(t['deadline_nano'],p['deadline_nano']), 'placement_terminal')
        if native['status']=='succeeded':
            _require(t['effect_attempted'] is True and t['effect_count']==t['packet_count']==1
                     and t['unknown_outcome'] is False and t['block_placed'] is True
                     and t['input_neutral'] is True and result.get('input_release_confirmed') is True
                     and t['protected_inventory_unchanged'] is True and t['final_count']==t['initial_count']-1,
                     'placement_success_requires_exact_effect_and_cleanup')
        elif t['effect_attempted']:
            _require(t['unknown_outcome'] is True,'placement_attempted_failure_must_be_unknown')

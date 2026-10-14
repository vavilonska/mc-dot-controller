"""Strict actual consumer checks with complete synthetic wire facts, no native execution."""
from copy import deepcopy
import hashlib
import json
import unittest
from resident_controller.capability_snapshot import validate_scoped_witness


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def base_fixture():
    action_id='c'*32; session='22222222-2222-4222-8222-222222222222'
    stack={'id':'','count':0,'empty':True,'max_stack_size':0,
           'item_fingerprint':'11111111-1111-4111-8111-111111111111',
           'component_fingerprint':'11111111-1111-4111-8111-111111111111'}
    context={'world_generation':'world-one','dimension':'minecraft:overworld','player_uuid':'player-one',
             'action_session':session,'integrated_server_instance':'33333333-3333-4333-8333-333333333333'}
    intent={'action':'select_hotbar','action_id':action_id,'hotbar_slot':1,
            'capability_guard':{'schema_version':1,'source_tick':99,'source_nano':'90'},
            **{'expected_'+k:v for k,v in context.items() if k != 'integrated_server_instance'}}
    scope={'version':'scoped-native-preflight/1','profile':'state-menu-v1','owner_id':'d'*32,
           'owner_generation':1,'job_id':'job_one','defense_epoch':7}
    menu={'menu_class':'net.minecraft.world.inventory.InventoryMenu','container_id':0,'state_id':1,
          'carried':deepcopy(stack),'slots_truncated':False,'slots_total':46,'slots_returned':46,
          'slots':[{'menu_index':i,'slot_index':i,'container_slot':i,'active':True,
                    'player_inventory':False,'item':deepcopy(stack)} for i in range(46)],
          'slot_permissions':[{'may_pickup':True,'may_place_carried':True,'max_stack_size':64} for _ in range(46)]}
    mapping={**{i:44-i for i in range(5,9)},**{i:i for i in range(9,36)},
             **{i:i-36 for i in range(36,45)},45:40}
    for i,index in mapping.items():menu['slots'][i].update(player_inventory=True,inventory_index=index,container_slot=index)
    facts={'context':context,'private_singleplayer':True,'focused':True,'paused':False,'alive':True,
           'spectator':False,'health':20.0,'hurt_time':0,'x':0.5,'y':64.0,'z':0.5,
           'on_fire':False,'in_water':False,'in_lava':False,'powder_snow':False,'using_item':False,
           'selected_slot':0,'screen_class':'','food_level':20,'food_saturation':5.0,
           'held_inputs':{'neutral':True},'inventory_total':41,
           'inventory':[{'slot':i,'item':deepcopy(stack)} for i in range(41)],
           'equipment':{k:deepcopy(stack) for k in ('mainhand','offhand','feet','legs','chest','head','body')},
           'effects':[],'menu':menu}
    compiled=deepcopy(intent);compiled['capability_guard']={'schema_version':1,'source_tick':100,'source_nano':'100'}
    witness={**scope,'schema_version':1,'action_id':action_id,'action_session':session,'source_tick':100,
             'source_nano':'100','admitted_nano':'120','native_owner_revision':8,
             'integrated_server_instance':context['integrated_server_instance'],
             'command_digest_format':'sorted-json-utf8/1','submitted_intent_sha256':digest(intent),
             'command_sha256':digest(compiled),'planning_guard':deepcopy(intent['capability_guard']),
             'clock_domain':'native-system-nanotime','coverage_complete':True,'admitted':True,
             'facts':facts,'context':deepcopy(context)}
    native={'action_id':action_id,'action_session':session,'action':'select_hotbar','status':'succeeded',
            'result':{'scoped_native_preflight':witness,'input_release_confirmed':True}}
    return native,scope,action_id,intent


def fixture():
    native, scope, action_id, intent = base_fixture()
    del intent['hotbar_slot']
    native['action'] = intent['action'] = 'combat_entity'
    native['status'] = 'running'
    scope['profile'] = 'combat-local-observed-v1'
    witness = native['result']['scoped_native_preflight']
    witness.update(scope)
    facts = witness['facts']
    intent.update(target_entity_id=9, target_uuid='44444444-4444-4444-8444-444444444444',
                  target_type='minecraft:zombie', approach=True, shield=True,
                  min_health=14, timeout_ms=15000, expected_hotbar_slot=0,
                  expected_held_item=deepcopy(facts['inventory'][0]['item']))
    facts['combat'] = {k: deepcopy(intent[k]) for k in
        ('target_entity_id','target_uuid','target_type','approach','shield','min_health','timeout_ms')}
    facts['combat'].update(profile=scope['profile'], target_health=20., x=2.5, y=64., z=.5, alive=True)
    reseal((native, scope, action_id, intent))
    return native, scope, action_id, intent


def reseal(data):
    native, scope, action_id, intent = data
    witness = native['result']['scoped_native_preflight']
    witness['planning_guard'] = deepcopy(intent['capability_guard'])
    witness['submitted_intent_sha256'] = digest(intent)
    compiled = deepcopy(intent)
    compiled['capability_guard'] = dict(schema_version=1, source_tick=witness['source_tick'],
                                        source_nano=witness['source_nano'])
    witness['command_sha256'] = digest(compiled)

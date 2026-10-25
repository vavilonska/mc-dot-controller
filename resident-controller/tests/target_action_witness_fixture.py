"""Synthetic complete witness for actual consumer tests; never a game observation."""
from copy import deepcopy
from combat_witness_fixture import base_fixture, reseal
from resident_controller.target_action_snapshot import PROFILE

TARGET = '44444444-4444-4444-8444-444444444444'
PLAYER = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'


def fixture(ranged=False):
    native, scope, aid, intent = base_fixture()
    witness = native['result']['scoped_native_preflight'];facts = witness['facts']
    intent.pop('hotbar_slot')
    scope['profile'] = witness['profile'] = PROFILE
    facts['context']['player_uuid'] = PLAYER
    witness['context'] = deepcopy(facts['context'])
    intent['expected_player_uuid'] = PLAYER
    native['action'] = intent['action'] = 'shoot_entity' if ranged else 'attack_entity'
    native['status'] = 'running'
    held = dict(facts['inventory'][0]['item'],id='minecraft:bow' if ranged else 'minecraft:iron_axe',
                count=1,empty=False,max_stack_size=1)
    facts['inventory'][0]['item'] = deepcopy(held)
    facts['equipment']['mainhand'] = deepcopy(held)
    facts['menu']['slots'][36]['item'] = deepcopy(held)
    if ranged:
        arrow=dict(held,id='minecraft:arrow',count=8,max_stack_size=64)
        facts['inventory'][1]['item']=deepcopy(arrow);facts['menu']['slots'][37]['item']=deepcopy(arrow)
    intent.update(target_entity_id=9,target_uuid=TARGET,target_type='minecraft:zombie',min_health=10,
                  timeout_ms=5000,expected_hotbar_slot=0,expected_held_item=deepcopy(held))
    if ranged:intent['draw_ticks']=20
    t={k:deepcopy(intent[k]) for k in ('action','target_entity_id','target_uuid','target_type','min_health','timeout_ms')}
    t.update(profile=PROFILE,alive=True,target_health=20.,x=12.5 if ranged else 2.5,y=64.,z=.5,
             station_x=.5,station_y=64.,station_z=.5,ranged=ranged,shield_window=False,draw_ticks=20 if ranged else 0,
             dragon_phase=-1,selected_slot=0,support_complete=True,station_cells=3,
             deadline_nano=str(int(witness['source_nano'])+5000000000),maximum_offense_effects=1,
             maximum_offense_packets=1,automatic_replay_allowed=False,species={'type':'minecraft:zombie'})
    t['support_cells']=[dict(x=0,y=y,z=0,id='minecraft:stone' if y==63 else 'minecraft:air',loaded=True,
                            fluid_empty=True,support=y==63,full_collision=y==63,air=y!=63) for y in (63,64,65)]
    def row(ident,uid,kind,x):
        return dict(id=ident,uuid=uid,type=kind,x=x,y=64.,z=.5,alive=True,living=True,projectile=False,
                    aabb=[x-.3,64.,.2,x+.3,65.8,.8])
    t['entity_frame']={'complete':True,'count':2,'entities':[row(1,PLAYER,'minecraft:player',.5),row(9,TARGET,'minecraft:zombie',t['x'])]}
    facts['target_action']=t
    reseal((native,scope,aid,intent))
    return native,scope,aid,intent


def terminal(native,intent):
    native['status']='succeeded'
    ranged=intent['action']=='shoot_entity';shield=intent.get('blaze_safety_mode')=='shield_window'
    proof={k:deepcopy(intent[k]) for k in ('target_entity_id','target_uuid','target_type')}
    proof.update(profile=PROFILE,offense_effects=1,offense_packets=1,draw_effects=int(ranged),draw_packets=int(ranged),
                 shield_use_effects=2 if shield else 0,shield_use_packets=2 if shield else 0,
                 shield_release_effects=2 if shield else 0,shield_release_packets=2 if shield else 0,
                 input_neutral=True,unknown_outcome=False,automatic_replay_allowed=False,server_confirmed=False)
    native['result']['target_scope']=proof
    return native

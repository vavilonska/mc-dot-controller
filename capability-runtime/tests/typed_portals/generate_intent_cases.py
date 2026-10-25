"""Produce actual skill commands plus closed-schema mutations for both production validators."""
from copy import deepcopy
import json, sys
from typed_portals.test_producers import Runtime, observation, cell, item, portal
from resident_controller import item_interaction_snapshot as iv, portal_entry_snapshot as pv


def cases():
    out=[]
    def add(name,kind,intent,valid=True):out.append(dict(name=name,type=kind,intent=deepcopy(intent),valid=valid))
    def native(r):
        command=deepcopy(r.calls[-1][2]);command.pop('op')
        held=r.before.player['inventory'][0]
        command.update(action_id='c'*32, expected_navigation_epoch=0, expected_origin={'x':.5,'y':64.,'z':.5},
            capability_guard={'schema_version':1,'source_tick':99,'source_nano':'90'},expected_dimension='minecraft:overworld',
            expected_player_uuid='player-one',expected_world_generation='world-one',expected_action_session='22222222-2222-4222-8222-222222222222',
            expected_hotbar_slot=0,expected_held_item={k:held[k] for k in iv.STACK})
        return command
    r=Runtime(observation());item.ignite_portal_local(r,{'x':2,'y':64,'z':0});flint=native(r);add('flint','item',flint)
    r=Runtime(observation('eye'));item.insert_end_eye_local(r,{'x':3,'y':63,'z':0},{'x':3,'y':63,'z':-1});eye=native(r);add('eye','item',eye)
    o=observation();o.terrain['cells']=[cell({'x':x,'y':y,'z':0},'minecraft:stone' if y==63 else 'minecraft:nether_portal' if x==1 and y==64 else 'minecraft:air',{'axis':'x'} if x==1 and y==64 else {}) for x in (0,1) for y in (63,64,65)]
    r=Runtime(o);r.profile=portal.PROFILE;portal.enter_portal_local(r,{'x':1,'y':64,'z':0},'minecraft:the_nether');entry=native(r);add('entry','portal',entry)
    for base,kind,mutations in [(flint,'item',[
        lambda c:c.update(face='down'),lambda c:c.update(raw_input=True),lambda c:c.update(hotbar_slot=0),lambda c:c.update(timeout_ms=3001),
        lambda c:c['typed_item_interaction'].update(width=5),lambda c:c['item_footprint'].pop(),lambda c:c['item_hit'].update(y=65),lambda c:c.update(expected_dimension='minecraft:the_end')]),
        (eye,'item',[lambda c:c['expected_block_properties'].update(eye='true'),lambda c:c['item_footprint'][0]['expected_properties'].update(facing='north'),
                    lambda c:c['item_footprint'][-1].update(block_id='minecraft:end_portal'),lambda c:c['item_hit'].update(y=64)]),
        (entry,'portal',[lambda c:c['typed_portal_entry'].update(destination='minecraft:the_end'),lambda c:c['typed_portal_entry'].update(entry_contract='natural-drop'),
            lambda c:c['waypoints'].append(deepcopy(c['waypoints'][0])),lambda c:c['waypoints'][0].update(jump=True),lambda c:c.update(timeout_ms=8001),lambda c:c.update(raw_input=True)])]:
        for i,mutate in enumerate(mutations):
            c=deepcopy(base);mutate(c);add(('entry' if kind=='portal' else base['typed_item_interaction']['kind'])+'-negative-'+str(i),kind,c,False)
    return out

if __name__=='__main__':
    result=cases()
    for case in result:
        validator=iv if case['type']=='item' else pv
        try:validator.validate_request({'profile':validator.PROFILE},case['intent']);valid=True
        except (ValueError,KeyError,TypeError):valid=False
        assert valid==case['valid'],case['name']
    with open(sys.argv[1],'w') as f:json.dump(result,f,sort_keys=True,indent=2)
    print('typed portal Resident intent checks:',len(result),'passed')

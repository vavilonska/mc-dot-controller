from copy import deepcopy
import unittest
from resident_controller.target_action_snapshot import validate_target_action, validate_request, validate_terminal
from target_action_witness_fixture import fixture, terminal

class TargetWitnessTests(unittest.TestCase):
    def validate(self,data):
        native,scope,aid,intent=data
        validate_request(scope,intent)
        validate_target_action(native['result']['scoped_native_preflight'],intent,native)
    def test_melee_bow_and_terminal_exact_proofs(self):
        for ranged in (False,True):
            data=fixture(ranged);self.validate(data);terminal(data[0],data[3]);self.validate(data)
    def test_closed_request_rejects_authority_and_numeric_coercion(self):
        for key,value in [('approach',True),('max_actions',3),('hotbar_slot',0),('target_entity_id',True),
                          ('timeout_ms',True),('min_health',True),('enderman_shelter_required',True)]:
            data=fixture();data[3][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.validate(data)
        data=fixture(True);data[3]['draw_ticks']=40
        with self.assertRaises(ValueError):self.validate(data)
    def test_exact_identity_context_support_and_coverage(self):
        changes=[('target_uuid','55555555-5555-4555-8555-555555555555'),('target_entity_id',True),
                 ('ranged',True),('station_x',.6),('station_cells',4),('deadline_nano','5000000101'),
                 ('target_health',0),('automatic_replay_allowed',True)]
        for key,value in changes:
            data=fixture();data[0]['result']['scoped_native_preflight']['facts']['target_action'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.validate(data)
        for field in ('loaded','fluid_empty','full_collision'):
            data=fixture();data[0]['result']['scoped_native_preflight']['facts']['target_action']['support_cells'][0][field]=False
            with self.subTest(field=field),self.assertRaises(ValueError):self.validate(data)
        data=fixture();frame=data[0]['result']['scoped_native_preflight']['facts']['target_action']['entity_frame'];frame['entities'].append(deepcopy(frame['entities'][0]));frame['count']=3
        with self.assertRaises(ValueError):self.validate(data)
    def test_final_unknown_duplicate_or_missing_packet_never_success(self):
        for key,value in [('offense_effects',0),('offense_packets',2),('offense_packets',True),
                          ('draw_packets',1),('input_neutral',False),('unknown_outcome',True),('automatic_replay_allowed',True)]:
            data=fixture();terminal(data[0],data[3]);data[0]['result']['target_scope'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.validate(data)
        data=fixture();data[0]['status']='succeeded'
        with self.assertRaises(ValueError):self.validate(data)
    def test_enderman_requires_actual_shelter_and_reserve(self):
        data=fixture();n,s,a,i=data;t=n['result']['scoped_native_preflight']['facts']['target_action']
        i.update(target_type='minecraft:enderman',enderman_shelter_required=True,min_health=12)
        t.update(target_type='minecraft:enderman',min_health=12,species={'type':'minecraft:enderman','shelter_safe':True})
        t['entity_frame']['entities'][1]['type']='minecraft:enderman';self.validate(data)
        t['species']['shelter_safe']=False
        with self.assertRaises(ValueError):self.validate(data)
    def test_dragon_phase_and_head_are_closed(self):
        data=fixture();n,s,a,i=data;t=n['result']['scoped_native_preflight']['facts']['target_action']
        i.update(target_type='minecraft:ender_dragon',expected_dragon_phase=6)
        t.update(target_type='minecraft:ender_dragon',dragon_phase=6,species={'type':'minecraft:ender_dragon','phase':6,'head_entity_id':10})
        t['entity_frame']['entities'][1]['type']='minecraft:ender_dragon';self.validate(data)
        for phase in (5,8,True):
            t['species']['phase']=phase
            with self.assertRaises(ValueError):self.validate(data)

if __name__=='__main__':unittest.main()

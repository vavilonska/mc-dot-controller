"""Exact new-mode contracts using synthetic observations and in-memory bridges only."""
import copy
import unittest
from resident_controller.encounter_contract import (
    MODE, THREE_MODE, MODES, validate_encounter_request, validate_encounter_receipt)
from resident_controller.pause_contract import validate_pause_receipt
from resident_controller.tasks import basic
from test_encounter_contract import body as old_body, receipt as old_receipt, U
from test_encounter_pause import pause_body, acknowledgement

THIRD = '00000000-0000-0000-0000-000000000004'

def body():
    b=old_body();b['encounter_mode']=THREE_MODE
    b['encounter_scope'].append(dict(entity_id=3,uuid=THIRD,type='minecraft:zombie'))
    return b

def receipt(request=None,status='running',reason=None):
    b=request or body();r=old_receipt(b,status,reason);e=r['result']['combat']['encounter']
    e['encounter_mode']=b['encounter_mode']
    e['outcome_scope']=MODES[b['encounter_mode']][1] if status=='succeeded' else None
    if b['encounter_mode']==THREE_MODE:
        e['projectile_observation']=dict(known=True,count=0,policy='any_loaded_projectile_refuses',
            scope='client_loaded_projectiles_within_16_not_server_complete')
    return r

class ThreeZombieContract(unittest.TestCase):
    def test_explicit_cardinality_and_original_mode_still_two(self):
        self.assertEqual(validate_encounter_request(body()),body())
        for b in (dict(body(),encounter_mode=MODE),dict(old_body(),encounter_mode=THREE_MODE),
                  dict(body(),encounter_scope=body()['encounter_scope']*2)):
            with self.assertRaises(ValueError):validate_encounter_request(b)
        self.assertEqual(validate_encounter_request(old_body()),old_body())
    def test_all_third_identity_bindings_are_unique_canonical_and_zombie_only(self):
        for field,value in [('entity_id',1),('entity_id',2),('entity_id',True),('uuid',old_body()['target_uuid']),
                            ('uuid','invalid'),('type','minecraft:skeleton'),('type','minecraft:husk'),('extra',1)]:
            b=body();b['encounter_scope'][2][field]=value
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):validate_encounter_request(b)
    def test_cannot_acquire_unlisted_target_or_enable_more_inputs(self):
        for change in [dict(target_uuid=U),dict(approach=True),dict(shield=True),dict(jump=False),dict(hotbar_slot=0)]:
            with self.subTest(change=change),self.assertRaises(ValueError):validate_encounter_request(dict(body(),**change))
    def test_all_statuses_keep_exact_three_scope_and_risk(self):
        for status in ('running','succeeded','failed','cancelled'):
            validate_encounter_receipt(receipt(status=status),body())
        b=body();r=receipt(b,'succeeded');e=r['result']['combat']['encounter']
        for mutate in (lambda x:x.update(encounter_mode=MODE),lambda x:x['encounter_scope'].reverse(),
                       lambda x:x['encounter_scope'].pop(),lambda x:x.update(outcome_scope=MODES[MODE][1])):
            bad=copy.deepcopy(r);mutate(bad['result']['combat']['encounter'])
            with self.assertRaises(ValueError):validate_encounter_receipt(bad,b)
    def test_success_requires_complete_zero_projectile_observation(self):
        for key,value in [('known',False),('count',None),('count',False),('count',-1),('count',1),
                          ('policy','arrows_safe'),('scope','global_complete')]:
            r=receipt(status='succeeded');r['result']['combat']['encounter']['projectile_observation'][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):validate_encounter_receipt(r,body())
        r=receipt(status='succeeded');del r['result']['combat']['encounter']['projectile_observation']
        with self.assertRaises(ValueError):validate_encounter_receipt(r,body())
    def test_third_missing_dead_near_or_renamed_does_not_prove_clearance(self):
        for key,value in [('known',False),('alive',False),('clearance',8),('uuid',U)]:
            r=receipt(status='succeeded');r['result']['combat']['encounter']['scoped_living_threats'][2][key]=value
            with self.assertRaises(ValueError):validate_encounter_receipt(r,body())
        r=receipt(status='succeeded');r['result']['combat']['encounter']['scoped_living_threats'].pop()
        with self.assertRaises(ValueError):validate_encounter_receipt(r,body())
    def test_request_copy_and_recipe_preserve_exact_scope_one_action(self):
        b=body();contract=validate_encounter_request(b);b['encounter_scope'][2]['entity_id']=99
        self.assertEqual(contract['encounter_scope'][2]['entity_id'],3)
        recipe=basic(dict(body(),op='action'));command=next(recipe);self.assertEqual(command['body'],body())
        self.assertEqual(recipe.send(receipt(status='succeeded'))['step'], 'observe')
        with self.assertRaises(StopIteration):recipe.send({'synthetic': True})
    def test_bound_terminal_pause_keeps_context_and_three_mode(self):
        b=dict(body(),action_id='known-action');p=pause_body('known-action');r=receipt(b,'cancelled','encounter_paused_risk_remaining')
        value=acknowledgement(p,r);self.assertFalse(validate_pause_receipt(value,p,b)['pause_effect_confirmed'])
        self.assertFalse(validate_pause_receipt(value,p)['pause_effect_confirmed'])
        for key,value2 in [('action_session','other'),('world_generation','other'),('expected_action_id','other')]:
            bad=copy.deepcopy(value);bad[key]=value2
            with self.assertRaises(ValueError):validate_pause_receipt(bad,p,b)
    def test_native_pause_hook_true_still_requires_same_receipt_evidence(self):
        b=dict(body(),encounter_pause_on_terminal=True);r=receipt(b,'failed')
        r['result']['combat']['encounter']['encounter_pause_on_terminal']=True
        with self.assertRaises(ValueError):validate_encounter_receipt(r,b)

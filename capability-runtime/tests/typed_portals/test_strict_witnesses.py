"""Full generic and typed consumer validation with complete synthetic native wire facts."""
from copy import deepcopy
import unittest
from resident_controller.capability_snapshot import validate_scoped_witness
from typed_portals.typed_portal_fixture import typed_fixture, ITEM_PROFILE, PORTAL_PROFILE

class StrictTypedWitnessTests(unittest.TestCase):
    def validate(self, values): return validate_scoped_witness(*values)
    def test_complete_admission_and_terminal_fixtures(self):
        for kind in ('flint','eye','portal'):
            for terminal in (False,True):
                with self.subTest(kind=kind,terminal=terminal): self.validate(typed_fixture(kind,terminal=terminal))
        self.validate(typed_fixture('eye',last_eye=True))
    def test_portal_exact_original_binding_rejects_forgery(self):
        for key,value in [('original_native_action_id','0'*32),('original_action_session','wrong'),('original_player_uuid','wrong'),
            ('integrated_server_instance','wrong'),('source_world_generation','wrong'),('source_dimension','minecraft:the_end'),
            ('destination','minecraft:the_end'),('deadline_nano','999'),('transition_eligible',1),('unknown_outcome',True),
            ('input_neutral',False),('source_portal_contact',False),('source_portal_contact',1),('destination_arrival_proven',True),('automatic_replay_allowed',True)]:
            with self.subTest(key=key):
                values=typed_fixture('portal');values[0]['result']['portal_entry'][key]=value
                with self.assertRaises(ValueError):self.validate(values)
    def test_portal_missing_source_contact_is_not_transition_proof(self):
        values=typed_fixture('portal');values[0]['result']['portal_entry'].pop('source_portal_contact')
        with self.assertRaises(ValueError):self.validate(values)
    def test_portal_success_and_unrelated_cancel_cannot_authorize_transition(self):
        for status,reason in [('succeeded','world_transition'),('cancelled','cancel_requested'),('failed','world_transition')]:
            values=typed_fixture('portal');values[0].update(status=status,reason=reason)
            with self.assertRaises(ValueError):self.validate(values)
    def test_item_all_semantics_are_independent_and_one_use_only(self):
        for kind in ('flint','eye'):
            for key,value in [('consumption_verified',False),('durability_verified',False),('block_outcome_verified',False),
                ('protected_inventory_unchanged',False),('use_count',2),('use_count',True),('packet_count',2),('packet_count',True),
                ('unknown_outcome',True),('final_count',64),('final_damage',62),('input_neutral',False)]:
                with self.subTest(kind=kind,key=key):
                    values=typed_fixture(kind);values[0]['result']['item_interaction'][key]=value
                    with self.assertRaises(ValueError):self.validate(values)
    def test_typed_keys_under_legacy_or_wrong_profiles_are_refused(self):
        for kind,profile in [('flint','block-menu-v1'),('eye','state-use-v1'),('portal','movement-flat-observed-v2')]:
            values=typed_fixture(kind);values[1]['profile']=profile;values[0]['result']['scoped_native_preflight']['profile']=profile
            with self.assertRaises(ValueError):self.validate(values)
    def test_generic_identity_digest_inventory_and_coverage_still_required(self):
        for mutation in (lambda n:n['result']['scoped_native_preflight'].update(command_sha256='0'*64),
                         lambda n:n['result']['scoped_native_preflight']['facts']['inventory'].pop(),
                         lambda n:n['result']['scoped_native_preflight']['facts']['portal_entry']['cells'].pop(),
                         lambda n:n['result']['scoped_native_preflight']['facts']['portal_entry']['entity_guard'].update(enumerated_count=2)):
            values=typed_fixture('portal');mutation(values[0])
            with self.assertRaises(ValueError):self.validate(values)

if __name__=='__main__':unittest.main()

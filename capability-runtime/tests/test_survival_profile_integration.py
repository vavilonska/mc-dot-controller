"""Closed profile registration and legacy-lane isolation; no game physics proof."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from mdc_toolbox import scoped_survival as profiles
from mdc_toolbox.runtime_adapter import OwnerRuntimeBackend

class ProfileRegistrationTests(unittest.TestCase):
    def scoped(self):
        return {'version':'scoped-native-preflight/1','same_callback_capture_validate_admit':True,
            'private_singleplayer_only':True,'capability_guard_schema_version':1,
            'profiles':deepcopy(profiles.PROFILE_ACTIONS),'guarded_actions':['attack_entity','shoot_entity','interact_block','follow_path']}
    def backend(self, scoped=None, policy='request_only'):
        session={'state':'ready','session_id':'s','execution_policy':policy,
            'capability_context':dict(world_generation='world',dimension='minecraft:overworld',player_uuid='p',action_session='a'),
            'scoped_native_preflight':self.scoped() if scoped is None else scoped,
            'private_singleplayer':True,'capability_lease_schema_version':1}
        runtime=SimpleNamespace(client=SimpleNamespace(session=lambda:deepcopy(session)),has_unresolved_execution=False)
        return OwnerRuntimeBackend(runtime,bindings={name:object() for name in profiles.CAPABILITY_PROFILE})
    def test_exact_negotiation_exposes_only_named_primitives(self):
        self.assertEqual(set(self.backend().describe()['supported_capabilities']),set(profiles.CAPABILITY_PROFILE))
    def test_partial_extra_wrong_profile_or_guard_schema_not_available(self):
        for edit in (lambda s:s['profiles'].__setitem__(profiles.TARGET_PROFILE,['attack_entity']),
                     lambda s:s['profiles'].__setitem__(profiles.TARGET_PROFILE,['attack_entity','shoot_entity','combat_entity']),
                     lambda s:s.__setitem__('capability_guard_schema_version',True),
                     lambda s:s.__setitem__('same_callback_capture_validate_admit',False)):
            scoped=self.scoped();edit(scoped)
            self.assertFalse(profiles.available('strike',scoped))
    def test_nonrequest_policy_cannot_enable_new_lanes(self):
        self.assertEqual(self.backend(policy='standard').describe()['supported_capabilities'],[])
    def test_underlying_action_overlap_does_not_change_ordinary_job(self):
        ordinary={'follow_path':'movement-flat-observed-v2','interact_block':'block-menu-v1'}
        for name in ('navigate_local','interact','engage','end_battle','end_expedition'):
            self.assertEqual(profiles.select(name,deepcopy(ordinary)),ordinary)
        self.assertEqual(profiles.select('enter_portal_local',deepcopy(ordinary))['follow_path'],profiles.PORTAL_PROFILE)
        self.assertEqual(profiles.select('ignite_portal_local',deepcopy(ordinary))['interact_block'],profiles.ITEM_PROFILE)
    def test_no_global_target_profile_fallback(self):
        self.assertNotIn('attack_entity',self.backend()._profile_actions({'scoped_profiles':self.scoped()['profiles']}))
        self.assertNotIn('shoot_entity',self.backend()._profile_actions({'scoped_profiles':self.scoped()['profiles']}))
    def test_missing_registry_entry_not_inferred_from_raw_action_support(self):
        s=self.scoped();s['profiles']={}
        self.assertEqual(self.backend(scoped=s).describe()['supported_capabilities'],[])

if __name__=='__main__':unittest.main()

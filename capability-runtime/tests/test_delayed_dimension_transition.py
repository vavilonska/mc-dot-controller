"""Exact adapter-chain delayed portal permits; synthetic Bridge, no gameplay.

Every case uses the checked-in IntentClient/Watchdog/QueueClient/Resident.
Neither a same-source read nor a rejected crossing submits another action.
"""
from copy import deepcopy
import time
import unittest
import test_capability_ownership as fixture
from mdc_skills.core import Runtime


class DelayedDimensionTransitionTests(unittest.TestCase):
    setUp = fixture.ActualGatewayOwnershipTests.setUp
    tearDown = fixture.ActualGatewayOwnershipTests.tearDown
    until = fixture.ActualGatewayOwnershipTests.until
    claim = fixture.ActualGatewayOwnershipTests.claim
    command = fixture.ActualGatewayOwnershipTests.command
    read = fixture.ActualGatewayOwnershipTests.read
    action = fixture.ActualGatewayOwnershipTests.action
    assert_no_legacy_attack = fixture.ActualGatewayOwnershipTests.assert_no_legacy_attack

    def enter(self, **kwargs):
        self.claim()
        before = self.read()
        self.started = time.monotonic()
        rid = self.action('follow_path', before,
            waypoints=[{'x':1.5,'y':64,'z':.5}],
            _capability_expected_dimension='minecraft:the_nether', **kwargs)
        outcome = self.client.wait(rid, timeout=3)
        self.assertEqual(outcome['status'], 'succeeded', outcome)
        self.until(lambda: self.dog.capability_lease.get('transition') is not None)
        self.original = deepcopy(self.dog.capability_lease['transition'])
        return before, outcome

    def one_post(self):
        self.assertEqual(len([b for p,b in self.bridge.posts if p == '/control/action']),1)

    def test_source_source_destination_retains_original_permit_and_rebinds_once(self):
        before, result = self.enter(timeout_ms=2500)
        for _ in range(2):
            self.assertEqual(self.read()['world']['dimension'], 'minecraft:overworld')
            permit = self.dog.capability_lease['transition']
            self.assertEqual(permit['deadline'], self.original['deadline'])
            self.assertEqual(permit['request_id'], result['queue_request_id'])
            self.assertTrue(self.dog.capability_lease['post_observation_required'])
        self.assertEqual(permit['observations_remaining'],126)
        self.assertLessEqual(permit['deadline'],self.started+2.6)
        self.bridge.destination='minecraft:the_nether'
        self.assertEqual(self.read()['world']['dimension'],'minecraft:the_nether')
        self.assertIsNone(self.dog.capability_lease.get('transition'))
        self.assertFalse(self.dog.capability_lease['post_observation_required'])
        self.assertEqual(self.read()['world']['dimension'],'minecraft:the_nether')
        self.assertEqual(self.client.release_capability(self.owner)['status'],'succeeded')
        self.one_post()
        self.assert_no_legacy_attack()

    def test_same_source_read_does_not_authorize_a_second_mutation(self):
        self.enter(timeout_ms=2500)
        source=self.read()
        rid=self.action('select_hotbar',source)
        result=self.client.wait(rid,timeout=3)
        self.assertEqual(result['reason'],'capability_command_out_of_scope')
        self.assertIsNone(result['queue_request_id'])
        self.one_post()

    def test_wrong_destination_pauses_without_reissue(self):
        self.enter(timeout_ms=2500)
        self.read()
        self.bridge.destination='minecraft:the_end'
        self.read()
        self.until(lambda:self.dog.handoff_latched)
        self.assertEqual(self.dog.reason,'capability_observation_context_changed')
        self.one_post()

    def test_same_dimension_new_world_is_not_expected_crossing(self):
        self.enter(timeout_ms=2500)
        self.bridge.destination='minecraft:overworld'
        self.read()
        self.until(lambda:self.dog.handoff_latched)
        self.assertEqual(self.dog.reason,'capability_observation_context_changed')
        self.one_post()

    def test_changed_player_cannot_use_expected_destination(self):
        self.enter(timeout_ms=2500)
        self.bridge.destination='minecraft:the_nether'
        self.bridge.other_player=True
        self.read()
        self.until(lambda:self.dog.handoff_latched)
        self.assertEqual(self.dog.reason,'capability_observation_context_changed')
        self.one_post()

    def test_original_action_deadline_expires_without_post_read_refresh(self):
        self.enter(timeout_ms=1000)
        self.read()
        self.until(lambda:self.dog.handoff_latched,timeout=2)
        self.assertEqual(self.dog.reason,'capability_transition_deadline_expired')
        self.assertEqual(self.dog.capability_lease['transition']['deadline'],self.original['deadline'])
        self.one_post()

    def test_consumed_permit_cannot_cross_again(self):
        self.enter(timeout_ms=2500)
        self.bridge.destination='minecraft:the_nether'
        self.read()
        self.bridge.destination='minecraft:overworld'
        self.read()
        self.until(lambda:self.dog.handoff_latched)
        self.assertEqual(self.dog.reason,'capability_observation_context_changed')
        self.one_post()

    def test_replaced_native_identity_blocks_source_observation(self):
        self.enter(timeout_ms=2500)
        self.bridge.action['action_id']='different-native-action'
        self.read()
        self.until(lambda:self.dog.handoff_latched)
        self.assertEqual(self.dog.reason,'capability_transition_action_binding_changed')
        self.one_post()

    def test_new_integrated_save_rejects_even_with_same_player_and_action(self):
        self.enter(timeout_ms=2500)
        self.bridge.destination='minecraft:the_nether'
        self.bridge.integrated_server_instance='44444444-4444-4444-8444-444444444444'
        self.read()
        self.until(lambda:self.dog.handoff_latched)
        self.assertEqual(self.dog.reason,'capability_transition_action_binding_changed')
        self.one_post()

    def test_absent_or_malformed_native_server_identity_blocks_before_mutation(self):
        self.bridge.integrated_server_instance=None
        self.claim()
        for identity in (None,'caller-world-name',True):
            self.bridge.integrated_server_instance=identity
            rid=self.action('follow_path',self.read(),waypoints=[{'x':1.5,'y':64,'z':.5}],
                            _capability_expected_dimension='minecraft:the_nether')
            result=self.client.wait(rid,timeout=3)
            self.assertEqual(result['reason'],'capability_command_out_of_scope')
        self.assertFalse(self.bridge.posts)

    def test_non_navigation_action_cannot_grant_a_portal_permit(self):
        self.claim()
        rid=self.action('use_item',self.read(),_capability_expected_dimension='minecraft:the_nether')
        result=self.client.wait(rid,timeout=3)
        self.assertEqual(result['reason'],'capability_command_out_of_scope')
        self.assertFalse(self.bridge.posts)
        self.assertIsNone(self.dog.capability_lease.get('transition'))

    def test_unknown_transition_action_never_grants_or_replays(self):
        self.claim()
        self.bridge.mode='unknown'
        rid=self.action('follow_path',self.read(),waypoints=[{'x':1.5,'y':64,'z':.5}],
                        _capability_expected_dimension='minecraft:the_nether')
        result=self.client.wait(rid,timeout=3)
        self.assertEqual(result['status'],'uncertain')
        self.until(lambda:self.dog.handoff_latched)
        self.assertIsNone(self.dog.capability_lease.get('transition'))
        self.one_post()

    def test_real_runtime_waits_source_then_verifies_later_destination_samples(self):
        runtime=Runtime(self.client,self.root/'runtime',wait_timeout=3)
        try:
            before=runtime.observe()
            seen=[]
            def verify(old,new):
                seen.append(new.context[1])
                if new.context[1]=='minecraft:overworld':
                    self.bridge.destination='minecraft:the_nether'
                return new.context[1]=='minecraft:the_nether'
            outcome=runtime.execute('portal-delayed',{'op':'action','action':'follow_path',
                'waypoints':[{'x':1.5,'y':64,'z':.5}], 'hotbar_slot':0,'timeout_ms':2500},verify,
                before=before,allowed_dimension='minecraft:the_nether',max_samples=8,stable_samples=2)
            self.assertTrue(outcome.ok,outcome)
            self.assertEqual(seen,['minecraft:overworld','minecraft:the_nether','minecraft:the_nether'])
            self.assertEqual(outcome.evidence['integrated_server_instance'],self.bridge.integrated_server_instance)
            self.assertFalse(runtime.has_unresolved_execution)
            self.one_post()
        finally:runtime.close()
        self.assertIsNone(self.client.session()['capability_lease'])

    def test_rejected_new_instance_cannot_be_revived_by_delayed_old_instance_frame(self):
        self.enter(timeout_ms=2500)
        original=self.bridge.integrated_server_instance
        self.bridge.integrated_server_instance='44444444-4444-4444-8444-444444444444'
        self.read()
        self.until(lambda:self.dog.handoff_latched)
        self.bridge.integrated_server_instance=original
        with self.assertRaisesRegex(ValueError,'watchdog_not_accepting_intents'):
            self.client.submit(self.command({'op':'observe','capability_observation':True,'entity_radius':48}))
        self.one_post()


if __name__=='__main__':unittest.main()

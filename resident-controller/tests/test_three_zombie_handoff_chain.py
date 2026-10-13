"""Existing real consumer-chain assertions repeated with exact P2 native fixtures.

Only native I/O is synthetic. Resident/QueueClient/Watchdog/Navigator are real.
The original two-target test files and assertions remain unchanged. Native action
IDs/sessions are adapted by the original chain helper as already documented there.
"""
import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_encounter_handoff_chain as chain
import test_encounter_contract as two
import test_encounter_pause as pause
import test_pause_handoff_policy as policy
import test_three_zombie_contract as three

FIXTURE = Path(chain.ROOT) / 'test-tools/encounter-stage1.1-safety-v2/fixtures/three-zombie-native-emitted-receipts.json'


class ThreeZombieHandoffChainTests(unittest.TestCase):
    def repeat_chain(self, name):
        cases = {x['name']: x for x in json.loads(FIXTURE.read_bytes())['cases']}
        with patch.object(chain, 'CASES', cases):
            helper = chain.EncounterHandoffChainTests()
            try:
                getattr(helper, name)()
            finally:
                helper.doCleanups()

    def repeat_pause(self, name):
        # Adapt only synthetic native receipts and test command factories.
        # Every actual producer/consumer method under test is unchanged.
        with patch.object(two, 'receipt', three.receipt), \
             patch.object(pause, 'receipt', three.receipt), \
             patch.object(policy, 'receipt', three.receipt), \
             patch.object(policy, 'body', three.body):
            helper = policy.PausePolicy()
            helper.setUp()
            try:
                getattr(helper, name)()
            finally:
                helper.tearDown()
                helper.doCleanups()

    def test_original_three_fixture_bytes_are_fixed(self):
        self.assertEqual('3a1622b8da273cb9be29124436b9103e101027a6b0d5fde50be39d31b4b9c4e7',
                         hashlib.sha256(FIXTURE.read_bytes()).hexdigest())
        cases = json.loads(FIXTURE.read_bytes())['cases']
        self.assertEqual(8, len(cases))
        for case in cases:
            self.assertEqual('three_zombie_retreat_v1', case['request']['encounter_mode'])
            self.assertEqual(3, len(case['request']['encounter_scope']))

    def test_three_native_terminals_preserve_raw_and_block_second_dispatch(self):
        for name in ('test_success_with_confirmed_release_still_requires_handoff',
                     'test_failure_with_confirmed_release_still_requires_handoff',
                     'test_cancellation_with_confirmed_release_still_requires_handoff',
                     'test_cleanup_failure_preserves_failed_native_receipt_and_release_latch'):
            with self.subTest(name=name): self.repeat_chain(name)

    def test_three_running_owner_survives_environment_and_ranged_priority(self):
        self.repeat_chain('test_running_hold_prevents_environment_and_ranged_priority_preemption')

    def test_three_restart_current_handoff_never_generic_releases(self):
        self.repeat_chain('test_restarted_watchdog_cannot_clear_resident_handoff_with_automatic_cancel')

    def test_three_unknown_post_preserves_original_identity_without_replay(self):
        self.repeat_chain('test_uncertain_post_with_unknown_cancellation_stops_without_action_replay')

    def test_three_unknown_status_preserves_last_valid_receipt(self):
        self.repeat_chain('test_unknown_polled_status_preserves_last_valid_running_receipt_and_stops')

    def test_three_pause_unknown_and_late_terminal_keep_original_receipt(self):
        self.repeat_pause('test_unknown_pause_keeps_original_body_and_uncertain_envelope')

    def test_three_pause_ack_release_false_keeps_release_priority(self):
        self.repeat_pause('test_bound_release_false_keeps_raw_terminal_and_release_priority')

    def test_three_unknown_pause_cannot_erase_preexisting_release_lock(self):
        self.repeat_pause('test_unknown_pause_preserves_preexisting_release_policy_without_replay')

    def test_three_old_cleanup_failure_not_erased_by_pause_ack(self):
        self.repeat_pause('test_old_cleanup_failure_cannot_be_erased_by_pause_acknowledgement')

    def test_three_undispatched_pause_preserves_pending_owner(self):
        self.repeat_pause('test_undispatched_pause_holds_exact_pending_command_for_fresh_watchdog')

    def test_three_policy_published_before_only_pause_post(self):
        self.repeat_pause('test_policy_is_published_before_the_only_pause_post')


if __name__ == '__main__':
    unittest.main()

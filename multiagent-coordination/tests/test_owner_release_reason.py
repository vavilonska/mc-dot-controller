"""Owned receipt cleanup retains the root native-release evidence contract."""
import unittest

import test_live_owner as fixture
from resident_controller.action_safety import native_release_unconfirmed


class OwnerReleaseReasonTests(unittest.TestCase):
    setUp = fixture.LiveOwnerTests.setUp
    tearDown = fixture.LiveOwnerTests.tearDown
    capture = fixture.LiveOwnerTests.capture
    proposal = fixture.LiveOwnerTests.proposal
    start = fixture.LiveOwnerTests.start
    finish = fixture.LiveOwnerTests.finish

    def terminal(self, status, reason=None, *, released=True):
        active=self.start();self.finish(active,released=released)
        raw=self.dog.q.results[active['request_id']]
        raw['status']=status
        native=raw['result']['action'];native['status']=status
        if reason is not None:native['reason']=reason
        return active,raw,native

    def test_release_failure_reason_overrules_payload_true_and_handoff(self):
        active,raw,native=self.terminal('failed','input_release_unconfirmed')
        raw['requires_handoff']=True
        self.assertTrue(native_release_unconfirmed(native))
        self.owner.advance()
        self.assertTrue(self.owner.recovery_blocked)
        self.assertEqual(self.owner.active['request_id'],active['request_id'])
        self.assertTrue(self.dog.input_release_latched)
        self.assertEqual(self.dog.reason,'coordination_terminal_release_unconfirmed')
        self.assertNotIn(active['request_id'],self.bridge.confirmed_release)
        self.assertEqual(len(self.dog.q.commands),1)

    def test_discontinuity_failed_with_true_payload_remains_unreleased(self):
        active,raw,native=self.terminal('failed','position_discontinuity_rebind_required')
        self.assertTrue(native_release_unconfirmed(native))
        self.owner.advance()
        self.assertTrue(self.owner.recovery_blocked)
        self.assertTrue(self.dog.input_release_latched)
        self.assertNotIn(active['request_id'],self.bridge.confirmed_release)

    def test_discontinuity_cancelled_with_true_payload_is_confirmed(self):
        active,raw,native=self.terminal('cancelled','position_discontinuity_rebind_required')
        self.assertFalse(native_release_unconfirmed(native))
        self.owner.advance()
        self.assertIsNone(self.owner.active)
        self.assertEqual(self.owner.result('plan')['status'],'cancelled')
        self.assertFalse(self.dog.input_release_latched)
        self.assertIn(active['request_id'],self.bridge.confirmed_release)

    def test_actual_released_success_remains_success(self):
        active,raw,native=self.terminal('succeeded')
        self.assertFalse(native_release_unconfirmed(native))
        self.owner.advance()
        self.assertEqual(self.owner.result('plan')['status'],'succeeded')
        self.assertFalse(self.dog.input_release_latched)
        self.assertIn(active['request_id'],self.bridge.confirmed_release)


if __name__ == '__main__': unittest.main()

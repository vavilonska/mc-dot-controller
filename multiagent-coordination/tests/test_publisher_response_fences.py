"""Each completed response must itself authorize its own capture bytes."""
from copy import deepcopy
import unittest

import test_live_owner as fixture
from mdcoord.schema import Rejected


class PublisherResponseFenceTests(unittest.TestCase):
    setUp = fixture.LiveOwnerTests.setUp
    tearDown = fixture.LiveOwnerTests.tearDown

    def rejected_capture(self, rid, mutate):
        publisher = self.adapter.publisher
        ticket = publisher.begin(rid)
        raw = fixture.observed(rid)
        mutate(raw)
        with self.assertRaises(Rejected): publisher.complete(ticket, raw)
        self.assertEqual(self.owner.snapshots.read()['sections'], {})
        # A clear current session and corrected bytes cannot resurrect the same ticket.
        with self.assertRaises(Rejected): publisher.complete(ticket, fixture.observed(rid))
        with self.assertRaises(Rejected): publisher.begin(rid)
        self.assertFalse(self.dog.input_release_latched)
        self.assertFalse(self.dog.handoff_latched)
        self.assertEqual(self.dog.q.commands, [])

    def fresh_clear_capture(self, *, explicit_flags=False):
        publisher = self.adapter.publisher
        raw = fixture.observed('new-clear-request')
        if explicit_flags:
            raw.update(unknown_outcome=False, uncertain=False, post_uncertain=False)
        snapshot = publisher.complete(publisher.begin('new-clear-request'), raw)
        self.assertEqual(snapshot['sections']['player']['freshness'], 'fresh')
        self.assertFalse(self.bridge.interrupted)
        self.assertFalse(self.dog.input_release_latched)
        self.assertFalse(self.dog.handoff_latched)

    def test_each_uncertainty_flag_requires_literal_false_or_absence(self):
        for flag in ('unknown_outcome', 'uncertain', 'post_uncertain'):
            for index, value in enumerate((True, None, 0, 1, 'false')):
                with self.subTest(flag=flag, value=value):
                    self.rejected_capture(flag+str(index), lambda raw, f=flag, v=value: raw.update({f:v}))
        self.fresh_clear_capture(explicit_flags=True)

    def test_capture_handoff_blocks_even_with_current_clear_session(self):
        self.rejected_capture('handoff-response',
            lambda raw: raw['result']['resident_policy'].update(requires_handoff=True))
        self.fresh_clear_capture()

    def test_capture_release_blocks_even_with_current_clear_session(self):
        self.rejected_capture('release-response',
            lambda raw: raw['result']['resident_policy'].update(input_release_unconfirmed=True))
        self.fresh_clear_capture()

    def test_capture_both_policy_blocks_cannot_be_reused(self):
        self.rejected_capture('both-response',
            lambda raw: raw['result']['resident_policy'].update(requires_handoff=True,input_release_unconfirmed=True))
        self.fresh_clear_capture()

    def test_actual_current_release_still_wins_before_bad_response(self):
        ticket = self.adapter.publisher.begin('current-release')
        self.dog.q.data['resident_policy'].update(requires_handoff=True, input_release_unconfirmed=True)
        raw = fixture.observed('current-release'); raw['unknown_outcome'] = True
        with self.assertRaises(Rejected): self.adapter.publisher.complete(ticket, raw)
        self.assertTrue(self.dog.input_release_latched)
        self.assertEqual(self.dog.reason, 'owner_input_release_unconfirmed')
        self.assertEqual(self.owner.snapshots.read()['sections'], {})


if __name__ == '__main__': unittest.main()

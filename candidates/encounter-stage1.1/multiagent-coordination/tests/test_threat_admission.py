"""Offline navigation requires independent owner clearance, never version equality."""
import copy
from dataclasses import replace
import tempfile
import unittest

from mdcoord import Acquisition, Coordinator, Rejected
from mdcoord.safety import preflight
from mdcoord.threats import ThreatClearance, ThreatStore
from support import CONTEXT, Clock, grant, player, proposal, publish, sections


class ThreatAdmissionChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.clock = Clock()
        self.owner = Coordinator(self.tmp.name, clock=self.clock)
        self.addCleanup(self.owner.close)
        self.owner.activate(grant())
        publish(self.owner, threat_clearance=False)

    def make_proof(self, **changes):
        entity = self.owner.snapshots.read()['sections']['entities']
        values = dict(proof_id='clearance', context=CONTEXT, entities_sample_id=entity['sample_id'],
                      entities_content_revision=entity['content_revision'],
                      acquisition=Acquisition(self.owner.snapshots.epoch,
                          entity['capture_started_mono'], entity['capture_finished_mono'],
                          entity['source_time_ms'], entity['source_tick']),
                      ttl_ms=3000, complete=True, no_threats=True, valid=True,
                      bounds=(.5, 64, .5, 17.5, 64, .5))
        values.update(changes)
        return ThreatClearance(**values)

    def approve(self, **changes):
        proof = self.make_proof(**changes)
        self.owner.threats.publish(proof)
        return proof

    def run_plan(self, plan=None):
        self.owner.propose(plan or proposal(self.owner))
        self.owner.advance()
        return self.owner.result((plan or {}).get('proposal_id', 'plan1'))

    def assert_rejected(self, reason, plan=None):
        result = self.run_plan(plan)
        self.assertEqual(result['status'], 'rejected')
        self.assertEqual(result['reason'], reason)
        self.assertEqual(self.owner.executor.dispatches, [])

    def check(self, *, snapshot=None, proof_id=None, plan=None):
        return preflight(plan or proposal(self.owner), self.owner.lease.grant,
                         snapshot or self.owner.snapshots.read(), self.owner.threats, proof_id)

    def test_fresh_entities_without_proof_fail_closed(self):
        self.assert_rejected('threat_proof_missing')

    def test_empty_entities_list_is_not_independent_clearance(self):
        publish(self.owner, 'empty-entities', {'entities': {'entities': [], 'truncated': False}},
                tick=11, threat_clearance=False)
        self.assert_rejected('threat_proof_missing')

    def test_same_revision_alive_threat_is_not_clearance(self):
        plan = proposal(self.owner)
        entities = self.owner.snapshots.read()['sections']['entities']
        self.assertTrue(entities['data']['entities'][0]['alive'])
        plan['based_on']['entities'] = entities['revision']
        self.assert_rejected('threat_proof_missing', plan)

    def test_missing_entities_fail_closed(self):
        snapshot = self.owner.snapshots.read()
        del snapshot['sections']['entities']
        with self.assertRaisesRegex(Rejected, '^entities_missing$'):
            self.check(snapshot=snapshot)

    def test_stale_entities_fail_even_with_unexpired_proof(self):
        self.clock.step(.01)
        publish(self.owner, 'brief-entities', {'entities': sections()['entities']},
                ttl=50, tick=11, threat_clearance=False)
        self.approve(ttl_ms=3000)
        self.clock.step(.051)
        with self.assertRaisesRegex(Rejected, '^entities_not_fresh$'):
            self.check()
        self.assert_rejected('observation_not_fresh')

    def test_unknown_and_truncated_entities_fail_closed(self):
        for name, raw in [('unknown', {'entities': [{}], 'truncated': False}),
                          ('truncated', {'entities': [], 'truncated': True})]:
            with self.subTest(name=name):
                publish(self.owner, name, {'entities': raw}, tick=11, threat_clearance=False)
                with self.assertRaisesRegex(Rejected, '^entities_not_fresh$'):
                    self.check()

    def test_explicit_synthetic_clearance_allows_fixture_route(self):
        self.approve()
        self.assertEqual(self.run_plan()['status'], 'running')
        self.assertEqual(len(self.owner.executor.dispatches), 1)
        self.assertTrue(self.owner.executor.dry_run)

    def test_default_preflight_store_is_fail_closed(self):
        self.approve()
        with self.assertRaisesRegex(Rejected, '^threat_proof_missing$'):
            preflight(proposal(self.owner), self.owner.lease.grant, self.owner.snapshots.read())

    def test_wrong_sample_id_fails_even_when_content_matches(self):
        self.approve(entities_sample_id=999999)
        self.assert_rejected('threat_entities_sample_changed')

    def test_new_same_content_entities_sample_needs_new_proposal(self):
        self.approve()
        self.owner.propose(proposal(self.owner))
        before = self.owner.snapshots.read()['sections']['entities']
        self.clock.step(.01)
        publish(self.owner, 'new-sample', {'entities': sections()['entities']}, tick=11)
        after = self.owner.snapshots.read()['sections']['entities']
        self.assertEqual(before['content_revision'], after['content_revision'])
        self.assertNotEqual(before['sample_id'], after['sample_id'])
        self.owner.advance()
        self.assertEqual(self.owner.result('plan1')['reason'], 'threat_entities_sample_changed')
        self.assertEqual(self.owner.executor.dispatches, [])
        self.assertEqual(self.run_plan(proposal(self.owner, 'new-plan'))['status'], 'running')

    def test_same_capture_changed_entities_invalidates_pinned_proof(self):
        self.approve()
        plan = proposal(self.owner)
        self.assertNotIn('entities', plan['based_on'])
        self.owner.propose(plan)
        before = self.owner.snapshots.read()['sections']['entities']
        entities = copy.deepcopy(sections()['entities'])
        entities['entities'][0]['type'] = 'minecraft:creeper'
        publish(self.owner, 'changed-same-capture', {'entities': entities}, threat_clearance=False)
        after = self.owner.snapshots.read()['sections']['entities']
        self.assertEqual(before['sample_id'], after['sample_id'])
        self.assertNotEqual(before['content_revision'], after['content_revision'])
        self.owner.advance()
        self.assertEqual(self.owner.result('plan1')['reason'], 'threat_entities_content_changed')
        self.assertEqual(self.owner.executor.dispatches, [])

    def test_missing_receipt_proof_cannot_be_rescued_later(self):
        self.owner.propose(proposal(self.owner))
        self.approve()
        self.owner.advance()
        self.assertEqual(self.owner.result('plan1')['reason'], 'threat_proof_missing')
        self.assertEqual(self.owner.executor.dispatches, [])

    def test_expired_pinned_proof_cannot_be_replaced(self):
        self.approve(ttl_ms=50)
        self.owner.propose(proposal(self.owner))
        self.clock.step(.051)
        capture = Acquisition(self.owner.snapshots.epoch, self.clock(), self.clock(), 1700000000051, 11)
        self.approve(proof_id='replacement', acquisition=capture)
        self.owner.advance()
        self.assertEqual(self.owner.result('plan1')['reason'], 'threat_proof_expired')
        self.assertEqual(self.owner.executor.dispatches, [])

    def test_invalid_incomplete_or_threat_present_proofs_reject(self):
        for index, field in enumerate(('valid', 'complete', 'no_threats')):
            with self.subTest(field=field):
                self.clock.step(.1)
                capture = Acquisition(self.owner.snapshots.epoch, self.clock(), self.clock(),
                                      1700000000100 + index * 100, 11 + index)
                self.approve(proof_id=field, acquisition=capture, **{field: False})
                with self.assertRaisesRegex(Rejected, '^threat_not_cleared$'):
                    self.check(proof_id=field)

    def test_negative_assessment_revokes_previously_pinned_clearance(self):
        self.approve()
        self.owner.propose(proposal(self.owner))
        self.approve(proof_id='threat-now-observed', no_threats=False)
        with self.assertRaisesRegex(Rejected, '^threat_clearance_not_newer_than_hazard$'):
            self.approve(proof_id='later-positive')
        self.owner.advance()
        self.assertEqual(self.owner.result('plan1')['reason'], 'threat_proof_revoked')
        self.assertEqual(self.owner.executor.dispatches, [])

    def test_owner_revocation_is_sticky(self):
        proof = self.approve()
        self.owner.propose(proposal(self.owner))
        self.owner.threats.revoke(proof.proof_id)
        self.owner.threats.publish(proof)
        self.owner.advance()
        self.assertEqual(self.owner.result('plan1')['reason'], 'threat_proof_revoked')

    def test_revoked_capture_cannot_be_laundered_under_new_proof_id(self):
        proof = self.approve()
        self.owner.threats.revoke(proof.proof_id)
        alias = self.owner.threats.publish(replace(proof, proof_id='revoked-capture-alias'))
        self.assertTrue(alias['revoked'])
        self.assert_rejected('threat_proof_revoked')

    def test_revoked_start_cannot_be_laundered_with_new_source_and_finish(self):
        proof = self.approve()
        self.owner.threats.revoke(proof.proof_id)
        self.clock.step(.1)
        alias = self.owner.threats.publish(replace(proof, proof_id='revoked-start-alias',
            acquisition=replace(proof.acquisition, source_tick=11, end_mono=self.clock())))
        self.assertTrue(alias['revoked'])
        self.assert_rejected('threat_proof_revoked')

    def test_genuinely_newer_capture_after_revocation_requires_new_proposal(self):
        proof = self.approve()
        self.owner.propose(proposal(self.owner))
        self.owner.threats.revoke(proof.proof_id)
        self.clock.step(.1)
        capture = Acquisition(self.owner.snapshots.epoch, self.clock(), self.clock(), 1700000000100, 11)
        self.approve(proof_id='new-clearance', acquisition=capture)
        self.owner.advance()
        self.assertEqual(self.owner.result('plan1')['reason'], 'threat_proof_revoked')
        self.assertEqual(self.run_plan(proposal(self.owner, 'new-plan'))['status'], 'running')

    def test_proof_context_must_match_all_identity_fields(self):
        for field, value in [('dimension', 'minecraft:the_nether'), ('world_generation', 'other-world'),
                             ('player_id', 'other-player'), ('action_session', 'other-action'),
                             ('resident_session', 'other-resident')]:
            with self.subTest(field=field):
                self.approve(proof_id=field, context=replace(CONTEXT, **{field: value}))
                with self.assertRaisesRegex(Rejected, '^threat_context_changed$'):
                    self.check(proof_id=field)

    def test_negative_assessment_in_other_context_does_not_revoke_this_context(self):
        self.approve()
        self.approve(proof_id='foreign-hazard', context=replace(CONTEXT, world_generation='other-world'),
                     no_threats=False)
        self.assertEqual(self.check(proof_id='clearance'), 'clearance')
        self.assertEqual(self.run_plan()['status'], 'running')

    def test_genuinely_newer_clearance_clears_hazard_only_for_new_proposals(self):
        self.approve()
        self.owner.propose(proposal(self.owner))
        self.approve(proof_id='hazard', no_threats=False)
        self.clock.step(.1)
        capture = Acquisition(self.owner.snapshots.epoch, self.clock(), self.clock(), 1700000000100, 11)
        self.approve(proof_id='new-assessment', acquisition=capture)
        self.owner.advance()
        self.assertEqual(self.owner.result('plan1')['reason'], 'threat_proof_revoked')
        self.assertEqual(self.run_plan(proposal(self.owner, 'new-plan'))['status'], 'running')

    def test_exact_corridor_covers_start_and_full_ordered_route(self):
        proof = self.approve(bounds=None, start=(.5, 64, .5), waypoints=((1.5, 64, .5),))
        self.assertEqual(self.check(), proof.proof_id)
        self.approve(proof_id='wrong-start', bounds=None, start=(1.5, 64, .5), waypoints=((.5, 64, .5),))
        with self.assertRaisesRegex(Rejected, '^threat_coverage_mismatch$'):
            self.check(proof_id='wrong-start')
        self.approve(proof_id='extra-segment', bounds=None, start=(.5, 64, .5),
                     waypoints=((1.5, 64, .5), (2.5, 64, .5)))
        with self.assertRaisesRegex(Rejected, '^threat_coverage_mismatch$'):
            self.check(proof_id='extra-segment')

    def test_bounds_must_cover_actual_start_and_every_waypoint(self):
        for pid, bounds in [('misses-start', (1, 64, 0, 2, 64, 1)),
                            ('misses-end', (0, 64, 0, 1, 64, 1))]:
            self.approve(proof_id=pid, bounds=bounds)
            with self.subTest(pid=pid), self.assertRaisesRegex(Rejected, '^threat_coverage_mismatch$'):
                self.check(proof_id=pid)

    def test_bad_proof_schemas_are_strict(self):
        for changes in [dict(complete=1), dict(no_threats='true'), dict(valid=None),
                        dict(entities_sample_id=True), dict(entities_content_revision=True), dict(ttl_ms=True), dict(ttl_ms=3001),
                        dict(bounds=[.5, 64, .5, 1.5, 64, .5]),
                        dict(bounds=(.5, 64, .5, 100.5, 64, .5)),
                        dict(bounds=(float('nan'), 64, .5, 1.5, 64, .5)),
                        dict(start=(.5, 64, .5)), dict(bounds=None),
                        dict(bounds=None, start=(.5, 64, .5), waypoints=((2.5, 64, .5),))]:
            with self.subTest(changes=changes), self.assertRaises(Rejected):
                self.make_proof(**changes)
        with self.assertRaisesRegex(Rejected, '^owner_threat_clearance_required$'):
            self.owner.threats.publish(self.make_proof().wire())

    def test_unknown_foreign_future_or_live_acquisitions_reject(self):
        base = self.make_proof().acquisition
        for capture in [replace(base, start_mono=None, end_mono=None),
                        replace(base, source_clock='resident_result_finished_wall'),
                        replace(base, source_clock='unknown')]:
            with self.subTest(capture=capture), self.assertRaises(Rejected):
                self.make_proof(acquisition=capture)
        for capture in [replace(base, clock_epoch='foreign-epoch'),
                        replace(base, start_mono=101, end_mono=101)]:
            with self.subTest(capture=capture), self.assertRaises(Rejected):
                self.owner.threats.publish(self.make_proof(acquisition=capture))

    def test_original_capture_start_sets_expiry_not_publication_or_read(self):
        self.clock.step(.9)
        self.approve(ttl_ms=1000)
        self.clock.step(.11)
        with self.assertRaisesRegex(Rejected, '^threat_proof_expired$'):
            self.check()

    def test_duplicate_proof_cannot_refresh_original_ttl(self):
        proof = self.approve(ttl_ms=50)
        before = self.owner.threats.read(proof.proof_id)
        self.clock.step(.04)
        after = self.owner.threats.publish(replace(proof, ttl_ms=3000))
        self.assertEqual(before['expires_mono'], after['expires_mono'])
        self.clock.step(.011)
        with self.assertRaisesRegex(Rejected, '^threat_proof_expired$'):
            self.check()

    def test_new_proof_id_cannot_refresh_same_original_capture_ttl(self):
        proof = self.approve(ttl_ms=50)
        self.clock.step(.04)
        self.owner.threats.publish(replace(proof, proof_id='new-id', ttl_ms=3000))
        self.clock.step(.011)
        with self.assertRaisesRegex(Rejected, '^threat_proof_expired$'):
            self.check()

    def test_reclocking_named_or_renamed_capture_does_not_refresh_short_ttl(self):
        proof = self.approve(ttl_ms=50)
        self.clock.step(.06)
        rewritten = replace(proof.acquisition, start_mono=self.clock(), end_mono=self.clock())
        for pid in ('clearance', 'renamed-old-capture'):
            with self.subTest(pid=pid), self.assertRaises(Rejected):
                self.owner.threats.publish(replace(proof, proof_id=pid, acquisition=rewritten, ttl_ms=3000))
        with self.assertRaisesRegex(Rejected, '^threat_proof_expired$'):
            self.check(proof_id='clearance')

    def test_unstamped_proof_cannot_relabel_read_time_as_new_capture(self):
        capture = replace(self.make_proof().acquisition, source_time_ms=None, source_tick=None)
        proof = self.approve(acquisition=capture, ttl_ms=50)
        self.clock.step(.06)
        with self.assertRaisesRegex(Rejected, '^threat_capture_retimestamped$'):
            self.owner.threats.publish(replace(proof, proof_id='unstamped-renamed', ttl_ms=3000,
                acquisition=replace(capture, start_mono=self.clock(), end_mono=self.clock())))

    def test_reversed_positive_capture_cannot_override_newer_assessment(self):
        self.clock.step(.1)
        capture = Acquisition(self.owner.snapshots.epoch, self.clock(), self.clock(), 1700000000100, 11)
        self.approve(acquisition=capture)
        with self.assertRaisesRegex(Rejected, '^threat_observation_time_reversed$'):
            self.approve(proof_id='old-clearance')

    def test_reversed_negative_capture_still_revokes_prior_positive(self):
        self.clock.step(.1)
        capture = Acquisition(self.owner.snapshots.epoch, self.clock(), self.clock(), 1700000000100, 11)
        self.approve(acquisition=capture)
        self.owner.propose(proposal(self.owner))
        self.approve(proof_id='old-but-unsafe', no_threats=False)
        self.owner.advance()
        self.assertEqual(self.owner.result('plan1')['reason'], 'threat_proof_revoked')

    def test_same_interval_with_changed_source_stamp_cannot_extend_original_ttl(self):
        proof = self.approve(ttl_ms=50)
        self.clock.step(.06)
        self.owner.threats.publish(replace(proof, proof_id='renamed-stamp', ttl_ms=3000,
            acquisition=replace(proof.acquisition, source_tick=11)))
        with self.assertRaisesRegex(Rejected, '^threat_proof_expired$'):
            self.check(proof_id='renamed-stamp')

    def test_extended_capture_finish_and_new_tick_cannot_extend_original_ttl(self):
        proof = self.approve(ttl_ms=50)
        self.clock.step(.1)
        rewritten = replace(proof.acquisition, end_mono=self.clock(), source_tick=11)
        self.owner.threats.publish(replace(proof, proof_id='extended-finish', ttl_ms=3000,
                                          acquisition=rewritten))
        with self.assertRaisesRegex(Rejected, '^threat_proof_expired$'):
            self.check(proof_id='extended-finish')
        self.assert_rejected('threat_proof_expired')

    def test_assessment_cannot_predate_its_claimed_entities_sample(self):
        capture = replace(self.make_proof().acquisition, start_mono=99, end_mono=99)
        self.approve(acquisition=capture)
        self.assert_rejected('threat_assessment_predates_entities')

    def test_proof_id_payload_conflict_rejects(self):
        proof = self.approve()
        with self.assertRaisesRegex(Rejected, '^threat_proof_id_payload_conflict$'):
            self.owner.threats.publish(replace(proof, no_threats=False))

    def test_mutating_returned_proof_does_not_change_owner_evidence(self):
        self.approve(no_threats=False)
        view = self.owner.threats.read('clearance')
        view['no_threats'] = True
        view['expires_mono'] = 99999
        with self.assertRaisesRegex(Rejected, '^threat_not_cleared$'):
            self.check()

    def test_mutating_original_dataclass_does_not_change_owned_proof(self):
        proof = self.approve(no_threats=False)
        object.__setattr__(proof, 'no_threats', True)
        with self.assertRaisesRegex(Rejected, '^threat_not_cleared$'):
            self.check()
        object.__setattr__(proof, 'bounds', (0, 0, 0, 100000, 100000, 100000))
        with self.assertRaises(Rejected):
            self.owner.threats.publish(proof)

    def test_planner_cannot_supply_or_publish_clearance(self):
        plan = proposal(self.owner)
        plan['threat_clearance'] = self.make_proof().wire()
        with self.assertRaises(Rejected):
            self.owner.propose(plan)
        for method in ('threats', 'publish_clearance', 'revoke_clearance'):
            self.assertFalse(hasattr(self.owner.planner(), method))

    def test_valid_proof_never_bypasses_latest_player_safety(self):
        self.approve()
        for field, value in [('alive', False), ('grounded', False), ('screen_closed', False), ('health', 1)]:
            changed = player(); changed[field] = value
            publish(self.owner, 'unsafe-' + field, {'player': changed}, tick=11)
            with self.subTest(field=field), self.assertRaisesRegex(Rejected, '^precondition_failed$'):
                self.check()
        publish(self.owner, 'displaced', {'player': player(1.5)}, tick=11)
        with self.assertRaisesRegex(Rejected, '^expected_start_changed$'):
            self.check()

    def test_valid_proof_never_bypasses_terrain_corridor_check(self):
        self.approve()
        terrain = copy.deepcopy(sections()['terrain'])
        terrain['cells'][3]['hazard'] = True
        publish(self.owner, 'hazardous-terrain', {'terrain': terrain}, tick=11)
        with self.assertRaisesRegex(Rejected, '^unknown_or_hazardous_corridor$'):
            self.check()

    def test_capacity_exhaustion_cannot_drop_hazard_and_leave_clearance_usable(self):
        self.approve()
        for index in range(255):
            self.approve(proof_id='proof-' + str(index))
        self.owner.propose(proposal(self.owner))
        with self.assertRaisesRegex(Rejected, '^threat_proof_capacity$'):
            self.approve(proof_id='cannot-store-hazard', no_threats=False)
        self.owner.advance()
        self.assertEqual(self.owner.result('plan1')['reason'], 'threat_store_blocked')
        self.assertEqual(self.owner.executor.dispatches, [])
        self.assertEqual(len(self.owner.threats._proofs), 256)
        with self.assertRaisesRegex(Rejected, '^threat_store_blocked$'):
            self.check(proof_id='clearance')

    def test_restart_has_no_clearance_and_foreign_epoch_cannot_reuse_it(self):
        proof = self.approve()
        other = ThreatStore(self.clock, epoch='new-owner-epoch')
        with self.assertRaisesRegex(Rejected, '^threat_foreign_monotonic_clock$'):
            other.publish(proof)
        self.assertEqual(len(other._proofs), 0)

    def test_defense_does_not_require_navigation_clearance(self):
        self.assertEqual(self.run_plan(proposal(self.owner, kind='defend_entity'))['status'], 'running')


if __name__ == '__main__':
    unittest.main()

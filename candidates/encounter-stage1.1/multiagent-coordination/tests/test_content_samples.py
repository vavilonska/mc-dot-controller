"""Offline boundaries for content identity, original sampling and continuity."""
import copy
from dataclasses import replace
import unittest

from mdcoord import Acquisition, Rejected
from mdcoord.metrics import Metrics
from mdcoord.snapshots import SnapshotStore
from support import Clock, CONTEXT, player, sections


class ContentSampleChecks(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.metrics = Metrics(self.clock)
        self.store = SnapshotStore(self.clock, self.metrics, epoch='sample-test')
        self.seq = 0

    def capture(self, *, start=None, end=None, tick=10, wall=1700000000000,
                source_clock='fixture_wall'):
        return Acquisition(self.store.epoch, self.clock() if start is None else start,
                           self.clock() if end is None else end, wall, tick, source_clock)

    def publish(self, data=None, *, capture=None, ttl=1000, source=None, context=CONTEXT):
        self.seq += 1
        return self.store.publish(context, source or 'sample-' + str(self.seq),
                                  {'player': player()} if data is None else data,
                                  capture or self.capture(), ttl_ms=ttl)

    def current(self, section='player'):
        return self.store.read()['sections'][section]

    def assert_atomic_rejection(self, code, data, capture, *, source='rejected'):
        before = self.store.read()
        metrics = self.metrics.snapshot()
        state = (self.store._revision, self.store._sample_id,
                 copy.deepcopy(self.store._watermarks), dict(self.store._publications),
                 copy.deepcopy(self.store._captures))
        sub = self.store.subscribe()
        with self.assertRaisesRegex(Rejected, code):
            self.publish(data, capture=capture, source=source)
        self.assertEqual(self.store.read(), before)
        self.assertEqual(self.metrics.snapshot(), metrics)
        self.assertEqual((self.store._revision, self.store._sample_id,
                          self.store._watermarks, self.store._publications, self.store._captures), state)
        self.assertEqual(self.store.poll(sub)['events'], [])
        self.store.unsubscribe(sub)

    def test_content_revision_alias_and_distinct_sample_identity(self):
        self.publish()
        before = self.current()
        self.clock.step(.25)
        self.publish(capture=self.capture(tick=11))
        after = self.current()
        self.assertEqual(before['content_revision'], after['content_revision'])
        self.assertEqual(after['revision'], after['content_revision'])
        self.assertGreater(after['sample_id'], before['sample_id'])
        self.assertEqual(after['capture_started_mono'], 100.25)
        self.assertEqual(after['expires_mono'], 101.25)
        self.assertEqual(after['continuity_revision'], before['continuity_revision'])
        self.assertEqual(after['freshness'], 'fresh')

    def test_player_refresh_does_not_update_other_section_samples(self):
        self.publish(sections())
        old = self.current('terrain')
        self.clock.step(.25)
        self.publish(capture=self.capture(tick=11))
        self.assertEqual(self.current('terrain'), old)

    def test_content_change_increments_even_with_same_capture(self):
        self.publish()
        old = self.current()
        self.publish({'player': player(1.5)})
        new = self.current()
        self.assertGreater(new['content_revision'], old['content_revision'])
        self.assertEqual(new['revision'], new['content_revision'])
        self.assertEqual(new['sample_id'], old['sample_id'])
        self.assertEqual(new['expires_mono'], old['expires_mono'])

    def test_ignored_raw_fields_do_not_invalidate_content(self):
        self.publish()
        before = self.current()
        raw = player(); raw.update(chat='discarded', password='discarded', config={})
        self.clock.step(.25)
        self.publish({'player': raw}, capture=self.capture(tick=11))
        after = self.current()
        self.assertEqual(after['data'], before['data'])
        self.assertEqual(after['content_revision'], before['content_revision'])
        self.assertGreater(after['sample_id'], before['sample_id'])
        self.assertNotIn('discarded', str(after))

    def test_quality_only_change_changes_content_revision(self):
        # Action payload remains identical, but an import without original owner
        # interval is effectively unknown rather than fresh.
        self.publish()
        old = self.current()
        unknown = Acquisition(self.store.epoch, None, None, 1700000000001, 11)
        self.publish(capture=unknown)
        bad = self.current()
        self.assertEqual(bad['data'], old['data'])
        self.assertEqual(bad['quality'], 'unknown')
        self.assertGreater(bad['content_revision'], old['content_revision'])
        self.assertIsNone(bad['expires_mono'])
        self.clock.step(.25)
        self.publish(capture=self.capture(tick=12, wall=1700000000002))
        fresh = self.current()
        self.assertEqual(fresh['data'], old['data'])
        self.assertEqual(fresh['quality'], 'fresh')
        self.assertGreater(fresh['content_revision'], bad['content_revision'])
        self.assertGreater(fresh['continuity_revision'], bad['continuity_revision'])

    def test_sanitized_quality_only_change_is_content_change(self):
        raw = sections()['terrain']; raw['complete'] = False
        self.publish({'terrain': raw})
        before = self.current('terrain')
        # Duplicate invalid coordinate is discarded, leaving identical data but
        # changing sanitized quality from truncated to unknown.
        raw['cells'].append(copy.deepcopy(raw['cells'][0]))
        self.publish({'terrain': raw})
        after = self.current('terrain')
        self.assertEqual(after['data'], before['data'])
        self.assertEqual(before['quality'], 'truncated')
        self.assertEqual(after['quality'], 'unknown')
        self.assertGreater(after['content_revision'], before['content_revision'])

    def test_repeated_unknown_content_is_stable(self):
        self.publish({'player': None})
        old = self.current()
        self.clock.step(.25)
        self.publish({'player': []}, capture=self.capture(tick=11))
        new = self.current()
        self.assertEqual(new['content_revision'], old['content_revision'])
        self.assertGreater(new['sample_id'], old['sample_id'])
        self.assertEqual(new['freshness'], 'unknown')
        self.assertGreater(new['continuity_revision'], old['continuity_revision'])

    def test_same_source_cannot_change_ttl_or_sample(self):
        capture = self.capture()
        self.publish(capture=capture, source='original', ttl=50)
        before = self.current()
        self.clock.step(.049)
        self.publish(capture=capture, source='original', ttl=3000)
        self.assertEqual(self.current(), before)
        self.clock.step(.001)
        self.assertEqual(self.current()['freshness'], 'stale')

    def test_renamed_original_capture_cannot_extend_ttl(self):
        capture = self.capture()
        self.publish(capture=capture, ttl=50)
        before = self.current()
        self.clock.step(.049)
        self.publish(capture=capture, ttl=3000)
        self.assertEqual(self.current(), before)
        self.clock.step(.001)
        self.assertEqual(self.current()['freshness'], 'stale')

    def test_renamed_original_capture_cannot_extend_ttl_via_new_section(self):
        capture = self.capture()
        self.publish(capture=capture, ttl=50)
        old = self.current()
        self.clock.step(.1)
        self.publish({'terrain': sections()['terrain']}, capture=capture, ttl=3000)
        new = self.current('terrain')
        self.assertEqual(new['expires_mono'], old['expires_mono'])
        self.assertEqual(new['source_id'], old['source_id'])
        self.assertEqual(new['freshness'], 'stale')

    def test_rewritten_owner_time_cannot_extend_ttl_via_new_section(self):
        self.publish(ttl=50)
        old = self.current()
        self.clock.step(.1)
        self.publish({'terrain': sections()['terrain']}, ttl=3000)
        new = self.current('terrain')
        self.assertEqual(new['capture_started_mono'], old['capture_started_mono'])
        self.assertEqual(new['expires_mono'], old['expires_mono'])
        self.assertEqual(new['freshness'], 'stale')

    def test_unknown_capture_cannot_be_upgraded_via_new_section(self):
        self.publish(capture=Acquisition(self.store.epoch, None, None, 1700000000000, 10))
        self.clock.step(.1)
        self.publish({'terrain': sections()['terrain']})
        new = self.current('terrain')
        self.assertIsNone(new['capture_started_mono'])
        self.assertIsNone(new['expires_mono'])
        self.assertEqual(new['freshness'], 'unknown')

    def test_same_source_new_capture_is_payload_conflict(self):
        self.publish(source='original')
        self.clock.step(.1)
        self.assert_atomic_rejection('source_id_payload_conflict', {'player': player()},
                                     self.capture(tick=11), source='original')

    def test_relabeled_later_owner_times_cannot_refresh_same_native_source(self):
        self.publish(ttl=50)
        before = self.current()
        self.clock.step(.1)
        self.publish(ttl=3000)
        after = self.current()
        for key in ('sample_id', 'source_id', 'capture_started_mono', 'capture_finished_mono',
                    'source_time_ms', 'source_tick', 'expires_mono', 'content_revision'):
            self.assertEqual(after[key], before[key], key)
        self.assertEqual(after['freshness'], 'stale')

    def test_new_source_stamps_alone_do_not_refresh_same_original_interval(self):
        capture = self.capture()
        self.publish(capture=capture, ttl=50)
        before = self.current()
        self.clock.step(.1)
        self.publish(capture=replace(capture, source_tick=11, source_time_ms=1700000000001), ttl=3000)
        after = self.current()
        self.assertEqual(after['sample_id'], before['sample_id'])
        self.assertEqual(after['expires_mono'], before['expires_mono'])
        self.assertEqual(after['capture_started_mono'], before['capture_started_mono'])
        self.assertEqual(after['freshness'], 'stale')

    def test_advancing_only_finish_cannot_refresh_original_start(self):
        self.publish(ttl=50)
        before = self.current()
        self.clock.step(.1)
        self.publish(capture=self.capture(start=100, end=100.1, tick=11), ttl=3000)
        self.assertEqual(self.current()['sample_id'], before['sample_id'])
        self.assertEqual(self.current()['expires_mono'], before['expires_mono'])

    def test_wall_progress_can_certify_new_capture_without_tick_progress(self):
        self.publish()
        old = self.current()
        self.clock.step(.1)
        self.publish(capture=self.capture(wall=1700000000001))
        self.assertGreater(self.current()['sample_id'], old['sample_id'])
        self.assertGreater(self.current()['expires_mono'], old['expires_mono'])
        self.assertEqual(self.current()['content_revision'], old['content_revision'])

    def test_owner_interval_alone_can_identify_capture_when_sources_absent(self):
        self.publish(capture=self.capture(tick=None, wall=None, source_clock='unknown'))
        old = self.current()
        self.clock.step(.1)
        self.publish(capture=self.capture(tick=None, wall=None, source_clock='unknown'))
        self.assertGreater(self.current()['sample_id'], old['sample_id'])
        self.assertGreater(self.current()['expires_mono'], old['expires_mono'])

    def test_missing_source_stamps_cannot_erase_capture_identity(self):
        self.publish(ttl=50)
        old = self.current()
        self.clock.step(.1)
        self.publish(capture=self.capture(tick=None, wall=None, source_clock='unknown'), ttl=3000)
        self.assertEqual(self.current()['sample_id'], old['sample_id'])
        self.assertEqual(self.current()['expires_mono'], old['expires_mono'])
        self.assertEqual(self.current()['freshness'], 'stale')

    def test_relabeling_source_clock_cannot_refresh_old_capture(self):
        self.publish(capture=self.capture(tick=None), ttl=50)
        old = self.current()
        self.clock.step(.1)
        self.publish(capture=self.capture(tick=None, wall=1700000000001,
                                         source_clock='resident_result_finished_wall'), ttl=3000)
        self.assertEqual(self.current()['sample_id'], old['sample_id'])
        self.assertEqual(self.current()['source_time_clock'], 'fixture_wall')
        self.assertEqual(self.current()['expires_mono'], old['expires_mono'])

    def test_unknown_import_cannot_be_upgraded_with_relabelled_read_time(self):
        unknown = Acquisition(self.store.epoch, None, None, 1700000000000, 10)
        self.publish(capture=unknown)
        before = self.current()
        self.clock.step(.1)
        self.publish(capture=self.capture(), ttl=3000)
        after = self.current()
        self.assertEqual(after['sample_id'], before['sample_id'])
        self.assertEqual(after['content_revision'], before['content_revision'])
        self.assertIsNone(after['capture_started_mono'])
        self.assertIsNone(after['expires_mono'])
        self.assertEqual(after['freshness'], 'unknown')

    def test_read_expiry_changes_neither_revision_nor_sample(self):
        self.publish(ttl=50)
        old = self.current()
        self.clock.step(.1)
        for _ in range(3):
            new = self.current()
            self.assertEqual(new['freshness'], 'stale')
            for key in ('content_revision', 'revision', 'sample_id', 'continuity_revision', 'expires_mono'):
                self.assertEqual(new[key], old[key])

    def test_exact_expiry_boundary_breaks_continuity_without_intermediate_read(self):
        self.publish(ttl=1000)
        old = self.current()
        self.clock.step(1)
        self.publish(capture=self.capture(tick=11))
        new = self.current()
        self.assertEqual(new['freshness'], 'fresh')
        self.assertEqual(new['content_revision'], old['content_revision'])
        self.assertEqual(new['continuity_revision'], old['continuity_revision'] + 1)

    def test_just_before_expiry_preserves_continuity(self):
        self.publish(ttl=1000)
        old = self.current()
        self.clock.step(.999)
        self.publish(capture=self.capture(tick=11))
        self.assertEqual(self.current()['continuity_revision'], old['continuity_revision'])

    def test_delayed_delivery_breaks_continuity_even_if_capture_overlapped(self):
        self.publish(ttl=1000)
        old = self.current()
        self.clock.step(1.1)
        self.publish(capture=self.capture(start=100.9, end=100.9, tick=11), ttl=1000)
        new = self.current()
        self.assertEqual(new['freshness'], 'fresh')
        self.assertEqual(new['continuity_revision'], old['continuity_revision'] + 1)

    def test_already_expired_new_sample_does_not_become_fresh(self):
        self.publish(ttl=50)
        old = self.current()
        self.clock.step(1)
        self.publish(capture=self.capture(start=100.1, end=100.1, tick=11), ttl=50)
        self.assertEqual(self.current()['freshness'], 'stale')
        self.assertGreater(self.current()['continuity_revision'], old['continuity_revision'])

    def test_same_sample_bad_quality_recovery_marks_continuity(self):
        self.publish()
        old = self.current()
        self.publish({'player': {}})
        bad = self.current()
        self.assertEqual(bad['freshness'], 'unknown')
        self.publish()
        new = self.current()
        self.assertEqual(new['sample_id'], old['sample_id'])
        self.assertEqual(new['freshness'], 'fresh')
        self.assertGreater(new['content_revision'], bad['content_revision'])
        self.assertGreater(new['continuity_revision'], old['continuity_revision'])

    def test_terrains_bad_quality_recovery_has_new_generation(self):
        self.publish(sections())
        old = self.current('terrain')
        bad = sections()['terrain']; bad['complete'] = False
        self.publish({'terrain': bad})
        self.clock.step(.1)
        self.publish({'terrain': sections()['terrain']}, capture=self.capture(tick=11))
        new = self.current('terrain')
        self.assertGreater(new['continuity_revision'], old['continuity_revision'])
        self.assertEqual(self.current('player')['continuity_revision'], 1)

    def test_start_regression_atomic_even_if_first_section_would_change(self):
        self.publish()
        self.clock.step(1)
        self.assert_atomic_rejection('observation_time_reversed',
                                     {'scan': {}, 'player': player(1.5)},
                                     self.capture(start=99.9, end=101, tick=11))

    def test_finish_regression_atomic_even_when_start_advances(self):
        self.clock.step(.5)
        self.publish(capture=self.capture(start=100, end=100.5))
        self.assert_atomic_rejection('observation_time_reversed',
                                     {'scan': {}, 'player': player(1.5)},
                                     self.capture(start=100.1, end=100.4, tick=11))

    def test_source_wall_regression_atomic(self):
        self.publish()
        self.clock.step(.5)
        self.assert_atomic_rejection('source_time_reversed',
                                     {'scan': {}, 'player': player(1.5)},
                                     self.capture(tick=11, wall=1699999999999))

    def test_source_tick_regression_atomic(self):
        self.publish()
        self.clock.step(.5)
        self.assert_atomic_rejection('source_tick_reversed',
                                     {'scan': {}, 'player': player(1.5)}, self.capture(tick=9))

    def test_unknown_import_does_not_erase_source_regression_guards(self):
        self.publish()
        self.publish(capture=Acquisition(self.store.epoch, None, None, None, None, 'unknown'))
        self.clock.step(.5)
        self.assert_atomic_rejection('source_tick_reversed', {'player': player()}, self.capture(tick=9))
        self.assert_atomic_rejection('source_time_reversed', {'player': player()},
                                     self.capture(tick=11, wall=1699999999999))

    def test_unknown_import_does_not_erase_capture_regression_guards(self):
        self.publish()
        self.publish(capture=Acquisition(self.store.epoch, None, None, None, None, 'unknown'))
        self.assert_atomic_rejection('observation_time_reversed', {'player': player()},
                                     self.capture(start=99.9, end=100, tick=11))

    def test_failed_publication_identity_can_be_used_for_corrected_retry(self):
        self.publish()
        self.assert_atomic_rejection('source_tick_reversed', {'player': player()}, self.capture(tick=9))
        self.clock.step(.5)
        self.publish(capture=self.capture(tick=11), source='rejected')
        self.assertEqual(self.current()['source_id'], 'rejected')

    def test_sample_and_content_events_have_distinct_sections(self):
        sub = self.store.subscribe()
        self.publish(sections())
        first = self.store.poll(sub)['events'][0]
        self.assertEqual(set(first['content_changed_sections']), set(sections()))
        self.assertEqual(set(first['sampled_sections']), set(sections()))
        self.clock.step(.1)
        self.publish({'player': player(), 'terrain': sections()['terrain']}, capture=self.capture(tick=11))
        event = self.store.poll(sub)['events'][0]
        self.assertEqual(event['content_changed_sections'], [])
        self.assertEqual(set(event['sampled_sections']), {'player', 'terrain'})
        self.assertEqual(event['continuity_changed_sections'], [])
        self.publish({'player': player(1.5)}, capture=self.capture(tick=11))
        event = self.store.poll(sub)['events'][0]
        self.assertEqual(event['content_changed_sections'], ['player'])
        self.assertEqual(event['sampled_sections'], [])
        self.clock.step(2)
        self.publish(capture=self.capture(tick=12))
        event = self.store.poll(sub)['events'][0]
        self.assertEqual(event['sampled_sections'], ['player'])
        self.assertEqual(event['continuity_changed_sections'], ['player'])

    def test_duplicate_identity_produces_no_events(self):
        capture = self.capture()
        self.publish(capture=capture, source='fixed')
        sub = self.store.subscribe()
        self.publish(capture=capture, source='fixed', ttl=3000)
        self.assertEqual(self.store.poll(sub)['events'], [])

    def test_renamed_replay_event_reports_no_content_or_sampling_change(self):
        capture = self.capture()
        self.publish(capture=capture)
        sub = self.store.subscribe()
        self.publish(capture=capture, ttl=3000)
        event = self.store.poll(sub)['events'][0]
        self.assertEqual(event['sections'], ['player'])
        self.assertEqual(event['content_changed_sections'], [])
        self.assertEqual(event['sampled_sections'], [])
        self.assertEqual(event['continuity_changed_sections'], [])

    def test_reads_events_and_publish_returns_are_copy_isolated(self):
        sub = self.store.subscribe()
        result = self.publish()
        result['sections']['player']['content_revision'] = -1
        result['sections']['player']['data']['health'] = 0
        self.assertGreater(self.current()['content_revision'], 0)
        self.assertEqual(self.current()['data']['health'], 20)
        event = self.store.poll(sub)['events'][0]
        event['sampled_sections'].append('fake')
        self.assertEqual(self.store.poll(sub)['events'], [])

    def test_context_change_separates_provenance_and_never_reuses_content_serial(self):
        self.publish(sections())
        old = self.current()
        new_context = replace(CONTEXT, world_generation='world2')
        self.publish(capture=self.capture(tick=1, wall=100), context=new_context)
        new = self.current()
        self.assertGreater(new['content_revision'], old['content_revision'])
        self.assertGreater(new['sample_id'], old['sample_id'])
        self.assertEqual(new['continuity_revision'], 1)
        self.assertEqual(set(self.store.read()['sections']), {'player'})
        self.publish(context=CONTEXT)
        self.assertGreater(self.current()['content_revision'], new['content_revision'])

    def test_context_roundtrip_cannot_refresh_old_original_capture(self):
        original_capture = self.capture()
        self.publish(capture=original_capture, ttl=50)
        original = self.current()
        self.clock.step(.1)
        self.publish(context=replace(CONTEXT, world_generation='world2'))
        self.publish(capture=original_capture, ttl=3000)
        returned = self.current()
        self.assertEqual(returned['expires_mono'], original['expires_mono'])
        self.assertEqual(returned['source_id'], original['source_id'])
        self.assertEqual(returned['freshness'], 'stale')
        self.assertGreater(returned['content_revision'], original['content_revision'])

    def test_context_roundtrip_cannot_erase_provenance_high_watermarks(self):
        self.publish(capture=self.capture(tick=11, wall=1700000000001))
        self.publish(context=replace(CONTEXT, world_generation='world2'))
        self.clock.step(.1)
        self.assert_atomic_rejection('source_tick_reversed', {'player': player()},
                                     self.capture(tick=10, wall=1700000000001))
        self.assert_atomic_rejection('source_time_reversed', {'player': player()},
                                     self.capture(tick=12, wall=1700000000000))
        self.assert_atomic_rejection('observation_time_reversed', {'player': player()},
                                     self.capture(start=99.9, end=100, tick=12, wall=1700000000002))

    def test_capture_identity_mixing_is_rejected_atomically(self):
        self.publish()
        self.clock.step(.1)
        self.publish(capture=self.capture(tick=11, wall=1700000000001))
        # The start identifies the second capture, the native source identifies
        # the first. Their incompatible original metadata must not be merged.
        self.assert_atomic_rejection('capture_identity_conflict', {'scan': {}, 'player': player()},
                                     self.capture(start=100.1, end=100.1, tick=10))

    def test_ttl_bounds_unchanged_and_atomic(self):
        for ttl in (49, 3001, True, 100.0):
            with self.subTest(ttl=ttl), self.assertRaises(Rejected):
                self.publish(ttl=ttl)
        self.assertEqual(self.store.read()['sections'], {})
        self.publish(ttl=50)
        self.assertEqual(self.current()['expires_mono'], 100.05)
        self.clock.step(.1)
        self.publish(capture=self.capture(tick=11), ttl=3000)
        self.assertEqual(self.current()['expires_mono'], 103.1)

    def test_full_identity_table_never_evicts_replay_protection(self):
        # Exercise the original 4096-identity bound without dropping old IDs.
        capture = self.capture()
        for index in range(4096):
            self.publish(capture=capture, source='bound-' + str(index))
        before = self.current()
        self.assert_atomic_rejection('observation_identity_capacity', {'player': player()}, capture)
        self.publish(capture=capture, source='bound-0', ttl=3000)
        self.assertEqual(self.current(), before)


if __name__ == '__main__':
    unittest.main(verbosity=2)

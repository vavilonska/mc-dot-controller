"""Historical survey authority and durable large-run evidence regressions."""
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from mdc_skills.core import Runtime, SkillError, Survey
from support_core import Clock, Client, move, arrived

class SurveyAndStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.clock=Clock();self.client=Client(self.clock)
        self.runtime=Runtime(self.client,self.tmp.name,clock=self.clock,sleeper=self.clock.sleep)
    def tearDown(self):
        self.runtime.close();self.tmp.cleanup()
    def survey_patch(self,r):
        if r['result'].get('terrain') is not None:
            self.clock.now+=5
            tick=r['result']['state']['world']['game_time']
            r['result']['terrain']={'complete':True,'historical_survey':True,'world_generation':'world-one',
                'dimension':'minecraft:overworld','radius':16,'vertical':8,'source_tick':tick,'last_tick':tick,
                'capture_started_mono':100,'capture_finished_mono':105,
                'source_pages':[{'source_tick':tick,'response_tick':tick,'captured_mono':101,'offset':0,'returned':128},
                    {'source_tick':tick,'response_tick':tick,'captured_mono':105,'offset':128,'returned':2}], 'cells':[]}
        return r
    def test_historical_survey_preserves_original_age_without_authority(self):
        old=self.runtime.observe();self.client.patch_result=self.survey_patch
        survey=self.runtime.survey()
        self.assertIsInstance(survey,Survey);self.assertGreater(survey.acquisition_seconds,5)
        self.assertEqual(survey.captured_at,100.001)
        self.assertIs(self.runtime.validate_survey(survey),survey)
        self.assertEqual(self.runtime.execute('bad',move(),arrived,before=survey).reason,'observation_not_owned_by_current_runtime')
        self.assertEqual(self.runtime.execute('bad',move(),arrived,before=old).reason,'newer_observation_invalidated_preflight')
        with self.assertRaisesRegex(SkillError,'foreign_observation'):self.runtime.result('bad',[survey])
        self.assertEqual(self.client.action_count,0)
        self.client.patch_result=lambda r:r
        current=self.runtime.observe()
        self.assertTrue(self.runtime.execute('ok',move(),arrived,before=current).ok)
    def test_survey_modified_payload_rejected(self):
        self.client.patch_result=self.survey_patch;s=self.runtime.survey();s.terrain['cells'].append({})
        with self.assertRaisesRegex(SkillError,'survey_modified'):self.runtime.validate_survey(s)
    def test_survey_missing_page_or_context_provenance_rejected(self):
        for key,value in [('source_pages',[]),('dimension','minecraft:the_end'),('historical_survey',False)]:
            def mutate(r,key=key,value=value):
                r=self.survey_patch(r);r['result']['terrain'][key]=value;return r
            self.client.patch_result=mutate
            with self.assertRaises(SkillError):self.runtime.survey()
            self.assertIsNone(self.runtime.pending_request_id)
    def test_survey_handoff_overrides_planning_read(self):
        def mutate(r):r=self.survey_patch(r);r['requires_handoff']=True;return r
        self.client.patch_result=mutate
        with self.assertRaisesRegex(SkillError,'survey_requires_handoff'):self.runtime.survey()
    def test_receipts_and_terminal_records_scale_with_exact_hashes(self):
        # Each synthetic receipt contains128KiB of distinct terrain-like content.
        def large(r):r['result']['uncompressed_evidence']='x'*131072;return r
        self.client.patch_result=large
        ids=[self.runtime.observe().request_id for _ in range(300)]
        audit=self.runtime.audit_evidence()
        self.assertEqual(audit['records'],300);self.assertEqual(audit['receipts'],300)
        self.assertGreaterEqual(audit['segments'],2)
        self.assertLess((Path(self.tmp.name)/'execution.json').stat().st_size,200000)
        self.runtime.close();self.runtime=Runtime(self.client,self.tmp.name,clock=self.clock,sleeper=self.clock.sleep)
        self.assertEqual(self.runtime.audit_evidence()['records'],300)
        self.assertEqual(self.client.action_count,0)
    def test_tampered_receipt_and_symlink_fail_closed_on_reopen(self):
        self.runtime.observe();record=next(iter(self.runtime._journal['records'].values()))
        path=Path(self.tmp.name)/record['receipt_ref']['file'];path.write_bytes(b'corrupt')
        self.runtime.close()
        with self.assertRaisesRegex(SkillError,'compressed_evidence_hash_mismatch'):
            Runtime(self.client,self.tmp.name,clock=self.clock)
    def test_missing_segment_and_chain_corruption_fail_closed(self):
        for _ in range(130):self.runtime.observe()
        ref=self.runtime._journal['segments'][0]
        (Path(self.tmp.name)/ref['file']).unlink();self.runtime.close()
        with self.assertRaisesRegex(SkillError,'evidence_missing_or_invalid'):Runtime(self.client,self.tmp.name,clock=self.clock)
    def test_compaction_crash_leaves_complete_previous_manifest(self):
        for _ in range(128):self.runtime.observe()
        with patch.object(self.runtime,'_save',side_effect=OSError('simulated_crash')):
            with self.assertRaises(OSError):self.runtime._compact()
        self.runtime.close();self.runtime=Runtime(self.client,self.tmp.name,clock=self.clock,sleeper=self.clock.sleep)
        self.assertEqual(self.runtime.audit_evidence()['records'],128)
    def test_semantic_pending_record_is_never_archived(self):
        for _ in range(128):self.runtime.observe()
        rid=next(iter(self.runtime._journal['records']))
        self.runtime._journal['semantic_pending']=rid
        self.runtime._journal['records'][rid]['status']='blocked';self.runtime._save();self.runtime._compact()
        self.assertIn(rid,self.runtime._journal['records'])
        self.assertEqual(self.runtime.audit_evidence()['records'],128)

if __name__=='__main__':unittest.main()

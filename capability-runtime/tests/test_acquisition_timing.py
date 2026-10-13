"""Deterministic acquisition-stage timing; strict original0.8s fence remains authoritative."""
import json
from pathlib import Path
import tempfile
import unittest
from mdc_skills.core import Runtime,SkillError
from support_core import Clock,Client,move,arrived

class AcquisitionTimingTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.clock=Clock();self.client=Client(self.clock)
  self.runtime=Runtime(self.client,self.tmp.name,clock=self.clock,sleeper=self.clock.sleep);self.addCleanup(self.runtime.close)
 def record(self,rid):return json.loads((Path(self.tmp.name)/'execution.json').read_text())['records'][rid]
 def test_fresh_observation_retains_original_clock_and_phase_offsets(self):
  original=self.client.wait
  def wait(*args,**kwargs):self.clock.sleep(.2);return original(*args,**kwargs)
  self.client.wait=wait;o=self.runtime.observe();t=self.record(o.request_id)['observation_acquisition']
  self.assertEqual(t['started_monotonic'],o.captured_at);self.assertEqual(t['max_age_seconds'],.8)
  self.assertEqual(t['checkpoints_ms']['before_submit'],0);self.assertEqual(t['checkpoints_ms']['terminal_received'],201)
  self.assertGreaterEqual(t['checkpoints_ms']['freshness_checked'],t['checkpoints_ms']['receipt_archived'])
 def test_queue_delay_remains_blocked_and_failed_observation_id_is_visible(self):
  original=self.client.wait
  def wait(*args,**kwargs):self.clock.sleep(.81);return original(*args,**kwargs)
  self.client.wait=wait
  with self.assertRaisesRegex(SkillError,'observation_acquisition_stale') as caught:self.runtime.observe()
  r=self.record(caught.exception.request_id);self.assertEqual(r['status'],'blocked');self.assertEqual(r['observation_acquisition']['checkpoints_ms']['freshness_checked'],811)
  self.assertIsNone(self.runtime._preflight_request_id)
 def test_durable_receipt_cost_is_inside_original_freshness_fence(self):
  original=self.runtime._receipt
  def archive(*args,**kwargs):original(*args,**kwargs);self.clock.sleep(.85)
  self.runtime._receipt=archive
  with self.assertRaises(SkillError) as caught:self.runtime.observe()
  t=self.record(caught.exception.request_id)['observation_acquisition']['checkpoints_ms']
  self.assertEqual(t['terminal_received'],1);self.assertEqual(t['receipt_archived'],851);self.assertEqual(t['freshness_checked'],851)
 def test_post_action_stale_read_preserves_known_native_receipt_and_no_replay(self):
  before=self.runtime.observe();original=self.client.wait
  def wait(rid,timeout):
   if self.client.results[rid]['op']=='observe' and self.client.action_count:self.clock.sleep(.81)
   return original(rid,timeout)
  self.client.wait=wait;out=self.runtime.execute('walk',move(),arrived,before=before)
  self.assertEqual(out.status,'blocked');self.assertEqual(out.reason,'observation_acquisition_stale')
  self.assertEqual(out.evidence['native_status'],'succeeded');self.assertEqual(out.evidence['semantic_verification'],'incomplete')
  self.assertEqual(out.evidence['native_action_id'],self.client.native['action_id']);self.assertTrue(out.evidence['command_sha256'])
  self.assertEqual(len(out.request_ids),2);self.assertEqual(self.record(out.request_ids[-1])['kind'],'observation')
  again=self.runtime.execute('walk',move(),arrived,before=before);self.assertFalse(again.ok);self.assertEqual(self.client.action_count,1)

if __name__=='__main__':unittest.main()

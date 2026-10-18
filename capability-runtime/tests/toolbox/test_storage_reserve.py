"""Storage admission is pre-dispatch only; historical IDs and safety lanes survive."""
from copy import deepcopy
import errno,tempfile,unittest
from types import SimpleNamespace as NS
from unittest.mock import patch
from test_facade import Backend,PLUGIN,FacadeTests
from mdc_toolbox import ToolboxService,CapabilityCatalog
from mdc_toolbox.storage_reserve import StorageReserve
from mdc_toolbox.contracts import API_VERSION

class StorageTests(unittest.TestCase):
 submit=FacadeTests.submit
 op=FacadeTests.op
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.backend=Backend();self.free=2000
  self.probe=patch('mdc_toolbox.storage_reserve.os.statvfs',side_effect=lambda _:NS(f_bavail=self.free,f_frsize=1));self.probe.start();self.addCleanup(self.probe.stop)
  self.service=ToolboxService(self.backend,self.tmp.name,catalog=CapabilityCatalog(modules=[PLUGIN]),storage_reserve=StorageReserve(1000,500,100000))
 def tearDown(self):self.backend.release.set();self.service.close();self.tmp.cleanup()
 def test_low_disk_refuses_new_mutation_without_record_or_backend(self):
  self.free=499;r=self.submit();self.assertEqual(r['error']['code'],'low_disk_reserve');self.assertEqual(r['error']['effect_certainty'],'none_proven');self.assertEqual(self.service.store.all(),[]);self.assertEqual(self.backend.calls,[])
 def test_warn_only_and_existing_id_survive_lower_threshold(self):
  self.free=750;r=self.submit();self.assertEqual(r['state'],'succeeded');self.free=0
  self.assertEqual(self.submit()['job_id'],r['job_id']);self.assertEqual(self.op('status',r['job_id'])['state'],'succeeded');self.assertEqual(sum(c[0]=='execute'for c in self.backend.calls),1)
 def test_accept_to_dispatch_disk_race_refuses_before_backend(self):
  self.service._start_workers=False;r=self.submit(wait_ms=0);self.free=0;self.service._run(r['job_id'])
  got=self.op('status',r['job_id']);self.assertEqual(got['state'],'blocked');self.assertEqual(got['effect_certainty'],'none_proven');self.assertFalse(self.backend.calls)
 def test_existing_action_and_exact_cancel_are_not_disk_gated(self):
  self.backend.block=True;r=self.submit(wait_ms=0);self.assertTrue(self.backend.started.wait(1));self.free=0
  out=self.op('cancel',r['job_id'],cancel_request_id='cancel-original',wait_ms=1000)
  self.assertEqual(self.backend.cancel_count,1);self.assertIn(out['state'],('succeeded','cancelled'))
 def test_fresh_read_remains_available_at_zero_probe_free_space(self):
  self.free=0;r=self.service.call('mdc_observe',{'api_version':API_VERSION,'session_ref':'session_1','profile':'player','request_id':'read-low-space'})
  self.assertEqual(r['job_state'],'succeeded');self.assertEqual(self.backend.calls,[('observe','player')])
 def test_event_accounting_threshold_preserves_all_original_events(self):
  r=self.submit();before=self.service.store.event_page(r['job_id']);used=self.service.store.event_history_bytes();self.assertGreater(used,0)
  self.service.storage_reserve=StorageReserve(1000,500,used)
  out=self.submit(request_id='next');self.assertEqual(out['error']['code'],'event_history_admission_full');self.assertEqual(before,self.service.store.event_page(r['job_id']))
 def test_probe_enospc_fails_closed_but_old_status_is_readable(self):
  r=self.submit()
  with patch('mdc_toolbox.storage_reserve.os.statvfs',side_effect=OSError(errno.ENOSPC,'full')):
   out=self.submit(request_id='next');self.assertEqual(out['error']['code'],'storage_probe_unavailable');self.assertEqual(self.op('status',r['job_id'])['state'],'succeeded')
 def test_actual_create_enospc_never_dispatches_and_keeps_old_identity(self):
  old=self.submit()
  with patch.object(self.service.store,'create',side_effect=OSError(errno.ENOSPC,'full')):
   out=self.submit(request_id='next');self.assertIn('error',out);self.assertEqual(sum(c[0]=='execute'for c in self.backend.calls),1);self.assertEqual(self.op('status',old['job_id'])['request_id'],'request_1')
 def test_invalid_configuration_is_closed(self):
  for args in ((0,0,1),(100,200,1),(True,1,1),(100,50,-1)):
   with self.subTest(args=args),self.assertRaises(ValueError):StorageReserve(*args)
 def test_catalog_reports_warning_and_exemptions_without_new_work(self):
  self.free=750;r=self.service.call('mdc_catalog',{'api_version':API_VERSION});s=r['runtime_binding_availability']['storage_admission'];self.assertEqual(s['status'],'warning');self.assertTrue(s['read_status_reconcile_cancel_exempt']);self.assertEqual(self.backend.calls,[])
if __name__=='__main__':unittest.main()

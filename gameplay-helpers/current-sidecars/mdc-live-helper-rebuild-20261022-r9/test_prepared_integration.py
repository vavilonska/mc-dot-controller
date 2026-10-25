"""Narrow sidecar ordering test; no native request or live ledger file access."""
import sys,types,unittest
from pathlib import Path
from unittest.mock import patch
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE),str(HERE.parent/'MDC-RECOVERY-RESTORED-F1220-20261022T1433Z/C8-source/survival6-controller')]
import rebuilt_session as r
class Tests(unittest.TestCase):
 def test_preparation_is_after_plan_bind_before_final_fresh(self):
  log=[];s=object.__new__(r.RebuiltSession)
  prepared=types.SimpleNamespace(prepare=lambda:log.append('prepare-history'))
  def observe():log.append('fresh-native-observe');return {'fresh':'frame'}
  s.c=types.SimpleNamespace(_prepared_history=prepared,observe=observe,ledger=types.SimpleNamespace(data={'unknown_lock':False,'actions':{}}))
  s.clock=lambda:0.;s.last_clock=None;s.stop_requested=lambda:False;s.sleep=lambda n:None;s.pending=[];s.check_context=lambda o:None
  def original(self,nav=None,survival=None):log.append(('bind-plan',nav,survival));return 'plan'
  for kwargs in (dict(nav={'target':'local'}),dict(survival={'kind':'select_hotbar'}),dict(survival={'kind':'consume_bread'}),dict(survival={'kind':'attack_blaze'})):
   log.clear()
   with patch.object(r.Session,'bind',original):self.assertEqual(s.bind(**kwargs),'plan')
   self.assertEqual(s.fresh(),{'fresh':'frame'})
   self.assertEqual([x if isinstance(x,str) else x[0] for x in log],['bind-plan','prepare-history','fresh-native-observe'])
 def test_failed_prepare_never_fetches_or_dispatches_ticket(self):
  log=[];s=object.__new__(r.RebuiltSession)
  def prepare():log.append('prepare');raise r.Refused('stale preparation')
  s.c=types.SimpleNamespace(_prepared_history=types.SimpleNamespace(prepare=prepare))
  with patch.object(r.Session,'bind',lambda self,**kw:'plan'):
   with self.assertRaises(r.Refused):s.bind(nav={})
  self.assertEqual(log,['prepare'])
if __name__=='__main__':unittest.main(verbosity=2)

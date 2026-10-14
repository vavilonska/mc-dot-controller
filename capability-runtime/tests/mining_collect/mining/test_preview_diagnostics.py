from copy import deepcopy
from pathlib import Path
import unittest
from resident_controller.controller import scoped_uncertain_diagnostics
from resident_controller.movement_wire import valid_size_diagnostic,decode,MARKER,ENCODING,BINDINGS,REFERENCE,TARGET
from resident_controller.transport import BridgeError
from .mining_fixture import mining_fixture
from mining_collect.bootstrap import JAVA_ROOT

def size_diagnostic():
 return dict(schema_version=2,profile='mining-local-observed-v2',standalone_bytes=100000,capability_bytes=250000,response_limit=262144,standalone_reserve_bytes=8192,capability_reserve_bytes=24576,witness_bytes=60000,entity_frame_bytes=20000,enumerated_count=22,cell_count=60)

class PreviewTests(unittest.TestCase):
 def test_profile_aware_size_and_legacy_unchanged(self):
  d=size_diagnostic();self.assertTrue(valid_size_diagnostic(d))
  for change in ({'cell_count':0},{'cell_count':513},{'profile':'unknown'},{'cell_count':True}):self.assertFalse(valid_size_diagnostic({**d,**change}))
  d.pop('profile');d.update(schema_version=1,cell_count=150);self.assertTrue(valid_size_diagnostic(d))
  d['cell_count']=60;self.assertFalse(valid_size_diagnostic(d))
 def test_preview_diagnostic_never_proves_effect_free_or_releases(self):
  e=BridgeError('scoped_movement_response_evidence_too_large',status=409,scoped_movement_response_size=size_diagnostic())
  d=scoped_uncertain_diagnostics(e);self.assertFalse(d['effect_free_proven']);self.assertFalse(d['input_release_proven']);self.assertNotIn('admitted',d)
  self.assertEqual(d['scoped_movement_response_size'],size_diagnostic())
  self.assertIsNone(scoped_uncertain_diagnostics(BridgeError('transport_failed',uncertain=True)))
 def bundle(self):
  native=mining_fixture()[0];w=native['result']['scoped_native_preflight'];ref={'schema_version':1,'path':TARGET,**{k:w[k] for k in BINDINGS}}
  b={'action':deepcopy(native),MARKER:ENCODING}
  for n in ('state','status'):
   a=deepcopy(native);a['result'].pop('scoped_native_preflight');a['result'][REFERENCE]=deepcopy(ref);b[n]={'client_action':a}
  return b
 def test_exact_mining_refs_resolve_to_semantic_witness(self):
  b=self.bundle();d=decode(b);self.assertEqual(d['action'],d['state']['client_action']);self.assertEqual(d['action'],d['status']['client_action']);self.assertIn(MARKER,b)
 def test_wrong_owner_path_missing_marker_and_inline_duplicate_rejected(self):
  for case in range(4):
   b=self.bundle();r=b['state']['client_action']['result']
   if case==0:r[REFERENCE]['owner_generation']+=1
   if case==1:r[REFERENCE]['path']='/state/other'
   if case==2:b.pop(MARKER)
   if case==3:r['scoped_native_preflight']=deepcopy(b['action']['result']['scoped_native_preflight'])
   with self.assertRaises(ValueError):decode(b)
 def test_size_formatter_cannot_erase_known_size_refusal(self):
  j=JAVA_ROOT
  s=(j/'BridgeServer.java').read_text();a=s.index('catch(IllegalArgumentException oversized)');b=s.index('} catch(ClientActionRequest.Rejected known)',a)
  fragment=s[a:b];self.assertIn('catch(RuntimeException unavailable)',fragment);self.assertIn('oversized.getMessage(),null,diagnostic',fragment)
  p=(j/'ScopedNativePreflight.java').read_text();self.assertLess(p.index('capture.requireMovementResponseBudget(parsed)'),p.index('return ClientActions.start(parsed, capture)'))

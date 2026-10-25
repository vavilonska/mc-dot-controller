"""Actual production codec synthetic fixtures. No game/native world observations."""
from pathlib import Path
import tempfile
import unittest
from maintenance5_controller.controller import Controller
from maintenance5_controller.schema import request_valid,receipt_valid,payload_digest
from maintenance5_controller.legacy import strict_json,RawReply,Refused,MAX_RESPONSE
from support import clone,ENDPOINT
F=Path(__file__).parent/'wire-r5';O=Path(__file__).parent/'observations-r5'
class NativeWireTests(unittest.TestCase):
 def test_all_actual_kind_and_place_enum_bytes(self):
  total=0
  for f in F.glob('*-request.json'):
   q=strict_json(f.read_bytes());request_valid(q);stem=f.name[:-13]
   for state in ('queued','settled','status'):
    rfile=F/(stem+'-'+state+'.json')
    if rfile.exists():
     r=strict_json(rfile.read_bytes());receipt_valid(r,q);self.assertEqual(r['payload_digest'],payload_digest(q));total+=1
  self.assertEqual(total,34)
 def test_actual_obs_strict_complete_nulls_primed_and_budget(self):
  class Transport:
   endpoint=ENDPOINT
   def request(self,*_):return RawReply(200,self.raw)
  with tempfile.TemporaryDirectory() as tmp:
   d=Path(tmp)/'ledger';clone(d);t=Transport()
   with Controller(d,t) as c:
    manifest=strict_json((O/'manifest.json').read_bytes());names={r['file'] for r in manifest['cases']}
    self.assertEqual({f.name for f in O.glob('*.json')},names|{'manifest.json','task-station-model-scope.json'})
    for name in sorted(names):
     f=O/name
     t.raw=f.read_bytes()
     if len(t.raw)>MAX_RESPONSE:
      with self.assertRaises(Refused):c.observe()
     else:self.assertEqual(c.observe(),strict_json(t.raw))

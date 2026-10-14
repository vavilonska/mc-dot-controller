"""Synthetic encodings only; contains no live receipts, IDs or saved-world data."""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import struct
import unittest
import encoding_checks as v

class EncodingTests(unittest.TestCase):
 def terminal(self):
  return {'protocol':'mineclient-bridge','schema_version':2,'action':'combat_entity','action_id':'synthetic-action','action_session':'synthetic-session','status':'cancelled','reason':'cancel_requested','result':{'combat':{'attack_dispatches':1,'threat_gate':{'health_diagnostics':{'latched':False,'latch_triggered_now':False}}}},'ticks':20,'action_schema_version':1,'input_owner':None,'movement_budget':None,'ok':True,'server_confirmed':False}
 def pair(self):
  native=self.terminal();observed=deepcopy(native)
  del observed['protocol'];del observed['schema_version'];v.no_latch(observed)['latch_trigger']=None
  return native,observed
 def test_optional_null_only_and_no_original_mutation(self):
  n,o=self.pair();before=deepcopy((n,o));self.assertTrue(v.exact_terminal_with_optional_null(n,o));self.assertEqual((n,o),before)
 def test_nonnull_trigger_and_nonfalse_flags_reject(self):
  for value in ({},False,0,'none'):
   n,o=self.pair();v.no_latch(n)['latch_trigger']=value;v.no_latch(o)['latch_trigger']=value
   with self.assertRaises(ValueError):v.exact_terminal_with_optional_null(n,o)
  for key in ('latched','latch_triggered_now'):
   for value in (None,0,True,'false'):
    n,o=self.pair();v.no_latch(o)[key]=value
    with self.assertRaises(ValueError):v.exact_terminal_with_optional_null(n,o)
 def test_all_other_fields_and_types_remain_exact(self):
  for key,value in [('action_id','other'),('ticks',20.),('status','succeeded'),('server_confirmed',0)]:
   n,o=self.pair();o[key]=value
   with self.assertRaises(ValueError):v.exact_terminal_with_optional_null(n,o)
  n,o=self.pair();o['result']['another_optional']=None
  with self.assertRaises(ValueError):v.exact_terminal_with_optional_null(n,o)
  n,o=self.pair();del o['action_session']
  with self.assertRaises(ValueError):v.exact_terminal_with_optional_null(n,o)
 def test_exact_float32_not_tolerance(self):
  value=struct.unpack('>f',bytes.fromhex('41808312'))[0]
  self.assertEqual(v.exact_target_health_float32(value,16.064)['binary32_hex'],'41808312')
  for bits in ('41808311','41808313'):
   with self.assertRaises(ValueError):v.exact_target_health_float32(value,struct.unpack('>f',bytes.fromhex(bits))[0])
  for bad in (True,float('nan'),float('inf'),0,20,-1,'16.064'):
   with self.assertRaises(ValueError):v.exact_target_health_float32(value,bad)
  with self.assertRaises(ValueError):v.exact_target_health_float32(16.064,16.064)
 def test_same_target_identity_required(self):
  combat={'target_uuid':'synthetic-target','target_entity_id':7,'target_type':'minecraft:zombie','target_health':16.06399917602539}
  row={'uuid':'synthetic-target','entity_id':7,'type':'minecraft:zombie','alive':True,'health':16.064}
  self.assertTrue(v.same_target_health(combat,[row])['same_binary32'])
  for key,value in [('uuid','other'),('entity_id',8),('entity_id',True),('type','minecraft:skeleton'),('alive',False),('health',16.065)]:
   changed={**row,key:value}
   with self.assertRaises(ValueError):v.same_target_health(combat,[changed])
  with self.assertRaises(ValueError):v.same_target_health(combat,[row,row])
 def test_source_provenance_pins(self):
  here=Path(__file__).resolve().parent;root=here.parents[2]
  provenance=json.loads((here/'SOURCE-PROVENANCE.json').read_text())
  compatible={r['path']:r for r in provenance.get('current_compatibility',{}).get('files',[])}
  for record in provenance['files']:
   raw=(root/record['path']).read_bytes()
   if record['path'] in compatible:
    current=compatible[record['path']];self.assertEqual(current['historical_sha256'],record['sha256'])
    self.assertEqual(hashlib.sha256(raw).hexdigest(),current['sha256'])
    line=current['exact_additive_line'].encode();self.assertEqual(raw.count(line),1)
    raw=raw.replace(line,b'')
   self.assertEqual(hashlib.sha256(raw).hexdigest(),record['sha256'],record['path'])
if __name__=='__main__':unittest.main(verbosity=2)

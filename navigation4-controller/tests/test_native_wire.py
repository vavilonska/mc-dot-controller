import base64
from pathlib import Path
import tempfile
import unittest
from navigation4_controller.controller import Controller
from navigation4_controller.schema import request_valid,receipt_valid,payload_digest
from navigation4_controller.legacy import strict_json,RawReply
from support import clone,ENDPOINT,ORIGINAL
F=Path(__file__).parent/'wire-final-r3'
class NativeWireTests(unittest.TestCase):
 def test_actual_v4_kind_stage_digest_refusal_bytes(self):
  requests=list(F.glob('*-request.json'));self.assertEqual(len(requests),5)
  for path in requests:
   q=strict_json(path.read_bytes());request_valid(q);stem=path.name[:-len('-request.json')]
   for phase in ('queued','settled'):
    r=F/(stem+'-'+phase+'.json')
    if r.exists():
     r=strict_json(r.read_bytes());receipt_valid(r,q);self.assertEqual(r['payload_digest'],payload_digest(q));self.assertEqual(r['stage_id'],q['stage_id'])
 def test_actual_no_world_and_original_raw_status_durable(self):
  class Transport:
   endpoint=ENDPOINT
   raw=(F/'observe-no-world.json').read_bytes()
   def request(self,method,path,body=None):
    if method!='GET':raise AssertionError('wire fixtures never issue effect')
    return RawReply(200,self.raw)
  with tempfile.TemporaryDirectory() as tmp:
   d=Path(tmp)/'ledger';clone(d);t=Transport()
   with Controller(d,t) as c:
    self.assertIsNone(c.observe()['step_height'])
    for stem in ('move','look','admit','first_input','first_interaction_tick'):
     q=strict_json((F/(stem+'-request.json')).read_bytes());t.raw=(F/(stem+'-settled.json')).read_bytes()
     c.ledger.data['actions'][q['id']]=dict(request=q,state='PENDING',evidence=[],unknown_reasons=[],latest_native=None,terminal_native=None,stop_attempted=False)
     r=c.status(q['id']);self.assertEqual(r['state'],'CLOSED');self.assertEqual(base64.b64decode(r['evidence'][0]['raw_base64']),t.raw)
    for aid,old in ORIGINAL['actions'].items():self.assertEqual(c.report(aid),old)

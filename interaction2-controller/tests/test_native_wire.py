"""Production Java parse/digest/serializer output; fixtures are offline, not live proof."""
import base64
from pathlib import Path
import tempfile
import unittest
from interaction2_controller.controller import Controller
from interaction2_controller.schema import request_valid,receipt_valid,payload_digest
from interaction2_controller.policy import hotbar
from interaction2_controller.legacy import strict_json,RawReply,Refused
from support import clone,ORIGINAL,ENDPOINT,observation

FIXTURES=Path(__file__).parent/'fixtures'

class NativeWireTests(unittest.TestCase):
    def test_all_kinds_zero_plan_echo_digest_actual_bytes(self):
        for kind in ('move','look','select_hotbar','break_block','zero'):
            q=strict_json((FIXTURES/(kind+'-request.json')).read_bytes());request_valid(q)
            for phase in ('queued','settled'):
                path=FIXTURES/(kind+'-'+phase+'.json')
                if not path.exists():continue
                r=strict_json(path.read_bytes());receipt_valid(r,q)
                self.assertEqual(r['payload_digest'],payload_digest(q));self.assertEqual(r['plan_sha256'],q['plan_sha256'])
                with self.assertRaises(Refused):receipt_valid(dict(r,plan_sha256='0'*64),q)
    def test_entered_stop_unknown_release_are_not_terminal(self):
        q=strict_json((FIXTURES/'entered-request.json').read_bytes())
        for name in ('entered-stop.json','unknown-released.json'):
            r=strict_json((FIXTURES/name).read_bytes());receipt_valid(r,q);self.assertFalse(r['protocol_terminal'])
        self.assertTrue(r['unknown_lock']);self.assertTrue(r['release_proven'])
    def test_actual_no_world_nullable(self):
        class Transport:
            endpoint=ENDPOINT
            def request(self,*_):return RawReply(200,(FIXTURES/'observe-no-world.json').read_bytes())
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'ledger';clone(path)
            with Controller(path,Transport()) as c:
                obs=c.observe();self.assertIsNone(obs['world_generation']);self.assertEqual(obs['hotbar'],[])
    def test_production_hotbar_formatter_requires_actual_max_damage(self):
        obs=observation();obs['hotbar'][2]=strict_json((FIXTURES/'hotbar-v2-synthetic-input.json').read_bytes());hotbar(obs)
        obs['hotbar'][2]=strict_json((FIXTURES/'hotbar-v1-synthetic-input.json').read_bytes())
        with self.assertRaises(Refused):hotbar(obs)
    def test_production_raw_receipt_durable_path_without_effect_dispatch(self):
        # Isolated original94 clone; injected transport record solely exercises reader/save path.
        # Native fixture owner/session/PLAN e*64 are not an operator PLAN; never submit/reopen it.
        for kind in ('move','look','select_hotbar','break_block'):
            q=strict_json((FIXTURES/(kind+'-request.json')).read_bytes());raw=(FIXTURES/(kind+'-settled.json')).read_bytes()
            class Transport:
                endpoint=ENDPOINT
                def request(self,method,path,body=None):
                    if method!='GET':raise AssertionError('no effects in wire test')
                    return RawReply(200,raw)
            with tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/'ledger';clone(path)
                with Controller(path,Transport()) as c:
                    c.ledger.data['actions'][q['id']]=dict(request=q,state='PENDING',evidence=[],unknown_reasons=[],latest_native=None,terminal_native=None,stop_attempted=False)
                    r=c.status(q['id']);self.assertEqual(r['state'],'CLOSED')
                    self.assertEqual(base64.b64decode(r['evidence'][0]['raw_base64']),raw)
                    for aid,old in ORIGINAL['actions'].items():self.assertEqual(c.report(aid),old)

if __name__=='__main__':unittest.main()

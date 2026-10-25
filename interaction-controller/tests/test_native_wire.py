"""Actual Java production serializer bytes -> strict reader/digest -> durable receipts."""
import base64
from pathlib import Path
import tempfile
import unittest
from interaction_controller.controller import Controller
from interaction_controller.schema import request_valid,receipt_valid,payload_digest
from interaction_controller.legacy import strict_json,Refused,RawReply
from interaction_controller.__main__ import assess
from test_legacy import synthetic_legacy,ENDPOINT

FIXTURES=Path(__file__).parent/'fixtures'


class NativeWireTests(unittest.TestCase):
    def test_actual_all_four_kinds_and_known_zero_digest_and_schema(self):
        for kind in ('move','look','select_hotbar','break_block','zero'):
            req=strict_json((FIXTURES/(kind+'-request.json')).read_bytes());request_valid(req)
            for phase in ('queued','settled'):
                path=FIXTURES/(kind+'-'+phase+'.json')
                if not path.exists():continue
                receipt=strict_json(path.read_bytes());receipt_valid(receipt,req)
                self.assertEqual(receipt['payload_digest'],payload_digest(req));self.assertEqual(receipt['settlement_state'],'not_observed')
            terminal=strict_json((FIXTURES/(kind+'-settled.json')).read_bytes())
            if kind=='break_block':self.assertEqual(assess({'request':req,'state':'CLOSED','terminal_native':terminal})[0],4)
            if kind=='zero':self.assertEqual(assess({'request':req,'state':'CLOSED','terminal_native':terminal})[0],3)
    def test_actual_minus180_accept_plus180_local_refusal(self):
        req=strict_json((FIXTURES/'look-request.json').read_bytes());self.assertEqual(req['yaw'],-180.);request_valid(req)
        with self.assertRaises(Refused):request_valid(dict(req,yaw=180.))
    def test_actual_no_world_nullable_observation(self):
        raw=(FIXTURES/'observe-no-world.json').read_bytes()
        class Transport:
            endpoint=ENDPOINT
            def request(self,*_):return RawReply(200,raw)
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)/'ledger';synthetic_legacy(directory)
            with Controller(directory,Transport()) as c:
                obs=c.observe()
                for key in ('client_tick','player_bbox','selected_slot','ray','world_generation','pose'):self.assertIn(key,obs);self.assertIsNone(obs[key])
                self.assertEqual(obs['hotbar'],[]);self.assertFalse(obs['ready'])
    def test_actual_raw_receipts_persist_byte_identically_with_old57(self):
        for kind in ('move','look','select_hotbar','break_block'):
            req=strict_json((FIXTURES/(kind+'-request.json')).read_bytes());raw=(FIXTURES/(kind+'-settled.json')).read_bytes()
            class Transport:
                endpoint=ENDPOINT
                def request(self,method,path,body=None):
                    if method!='GET':raise AssertionError('fixture validation cannot send effect')
                    return RawReply(200,raw)
            with tempfile.TemporaryDirectory() as tmp:
                directory=Path(tmp)/'ledger';old=synthetic_legacy(directory)
                with Controller(directory,Transport()) as c:
                    record=dict(request=req,state='PENDING',unknown_reasons=[],evidence=[],latest_native=None,terminal_native=None,stop_attempted=False)
                    c.ledger.data['actions'][req['id']]=record;c.ledger.save()
                    result=c.status(req['id']);self.assertEqual(result['state'],'CLOSED')
                    self.assertEqual(base64.b64decode(result['evidence'][0]['raw_base64']),raw)
                    for aid,original in old['actions'].items():self.assertEqual(c.report(aid),original)
    def test_actual_entered_stop_and_unknown_release_keep_unknown(self):
        req=strict_json((FIXTURES/'entered-request.json').read_bytes())
        for name in ('entered-stop.json','unknown-released.json'):
            receipt=strict_json((FIXTURES/name).read_bytes());receipt_valid(receipt,req)
            self.assertFalse(receipt['protocol_terminal'])
        unknown=strict_json((FIXTURES/'unknown-released.json').read_bytes())
        self.assertTrue(unknown['release_proven']);self.assertTrue(unknown['unknown_lock']);self.assertEqual(unknown['state'],'UNKNOWN')

if __name__=='__main__':unittest.main()

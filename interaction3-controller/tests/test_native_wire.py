"""Actual production Java codec bytes, offline harness, not game captures."""
import base64
from pathlib import Path
import tempfile
import unittest
from interaction3_controller.controller import Controller
from interaction3_controller.schema import request_valid,receipt_valid,payload_digest
from interaction3_controller.legacy import strict_json,RawReply
from support import clone,ORIGINAL,ENDPOINT

FIXTURES=Path(__file__).parent/'fixtures'

class NativeWireTests(unittest.TestCase):
    def test_all_actual_requests_digest_receipts_and_diagnostic_prefixes(self):
        paths=list(FIXTURES.glob('*-request.json'));self.assertGreaterEqual(len(paths),30)
        for path in paths:
            q=strict_json(path.read_bytes());request_valid(q);stem=path.name[:-len('-request.json')]
            phases=0
            for phase in ('queued','settled'):
                response=FIXTURES/(stem+'-'+phase+'.json')
                if response.exists():
                    r=strict_json(response.read_bytes());receipt_valid(r,q);self.assertEqual(r['payload_digest'],payload_digest(q));phases+=1
            self.assertGreater(phases,0)
    def test_actual_no_world_nullable_observation(self):
        class Transport:
            endpoint=ENDPOINT
            def request(self,*_):return RawReply(200,(FIXTURES/'observe-no-world.json').read_bytes())
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'ledger';clone(path)
            with Controller(path,Transport()) as c:
                o=c.observe();self.assertIsNone(o['world_generation']);self.assertIsNone(o['observation_refusal'])
    def test_actual_raw_settled_saved_original_id_status_no_effect(self):
        for stem in ('look','break_block','move','select_hotbar','admit-1','first_input-63','first_interaction_tick-127','missing-1','missing-2'):
            q=strict_json((FIXTURES/(stem+'-request.json')).read_bytes());raw=(FIXTURES/(stem+'-settled.json')).read_bytes()
            class Transport:
                endpoint=ENDPOINT
                def request(self,method,path,body=None):
                    if method!='GET':raise AssertionError('no native effect in fixture readback')
                    return RawReply(200,raw)
            with tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/'ledger';clone(path)
                with Controller(path,Transport()) as c:
                    # Harness PLAN identity is not an executable operator PLAN. Status path only.
                    c.ledger.data['actions'][q['id']]=dict(request=q,state='PENDING',evidence=[],unknown_reasons=[],latest_native=None,terminal_native=None,stop_attempted=False)
                    r=c.status(q['id']);self.assertEqual(r['state'],'CLOSED');self.assertEqual(base64.b64decode(r['evidence'][0]['raw_base64']),raw)
                    for aid,old in ORIGINAL['actions'].items():self.assertEqual(c.report(aid),old)

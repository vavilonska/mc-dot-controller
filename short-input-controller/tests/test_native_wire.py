"""Consume actual native serializer bytes, not a Python-rebuilt receipt schema."""
import base64
import copy
from pathlib import Path
import tempfile
import unittest
from short_input_controller.controller import Controller, PROFILE, payload_digest, request_valid
from short_input_controller.storage import Refused, strict_json
from short_input_controller.transport import RawReply
from short_input_controller.__main__ import assess_step

FIXTURES=Path(__file__).parent/'fixtures'


class NativeWireTests(unittest.TestCase):
    def test_actual_native_status_reader_digest_and_semantics(self):
        request=strict_json((FIXTURES/'request.json').read_bytes())
        request_valid(request)
        for filename in ('status-queued.json','status-settled.json'):
            raw=(FIXTURES/filename).read_bytes();receipt=strict_json(raw)
            Controller._validate_receipt(receipt,request)
            self.assertEqual(payload_digest(request),receipt['payload_digest'])
            self.assertEqual(receipt['settlement_state'],'not_observed')
            self.assertEqual(receipt['gameplay_outcome'],'not_assessed')
        terminal=strict_json((FIXTURES/'status-settled.json').read_bytes())
        self.assertEqual(assess_step({'state':'CLOSED','latest_native':terminal})[0],4)
        changed=dict(request,observation_id='55555555-5555-4555-8555-555555555555')
        with self.assertRaises(Refused):Controller._validate_receipt(terminal,changed)

    def test_actual_native_known_zero_terminal(self):
        request=strict_json((FIXTURES/'request-zero.json').read_bytes())
        receipt=strict_json((FIXTURES/'status-zero.json').read_bytes())
        request_valid(request);Controller._validate_receipt(receipt,request)
        self.assertEqual(receipt['applied_samples'],0)
        self.assertEqual(receipt['release_state'],'not_needed')
        self.assertTrue(receipt['protocol_terminal'])
        self.assertEqual(assess_step({'state':'CLOSED','terminal_native':receipt})[0],3)

    def test_actual_null_observation_schema(self):
        raw=(FIXTURES/'observe-no-world.json').read_bytes()
        class FixtureTransport:
            endpoint='http://127.0.0.1:1'
            def request(self,*_):return RawReply(200,raw)
        with tempfile.TemporaryDirectory() as d,Controller(Path(d)/'ledger',FixtureTransport()) as controller:
            obs=controller.observe()
            for name in ('active_id','world_generation','player_uuid','pose','velocity','on_ground','health','client_tick'):
                self.assertIn(name,obs);self.assertIsNone(obs[name])
            self.assertFalse(obs['ready'])

    def test_actual_native_raw_bytes_retained_by_public_exchange(self):
        request=strict_json((FIXTURES/'request.json').read_bytes())
        raw=(FIXTURES/'status-settled.json').read_bytes()
        class FixtureTransport:
            endpoint='http://127.0.0.1:1'
            calls=[]
            def request(self,method,path,body=None):
                self.calls.append(method)
                if method!='GET':raise AssertionError('wire fixture must not dispatch')
                return RawReply(200,raw)
        with tempfile.TemporaryDirectory() as d,Controller(Path(d)/'ledger',FixtureTransport()) as controller:
            # Offline retained-origin fixture, not a call through gameplay admission.
            record={'request':request,'state':'PENDING','unknown_reasons':[],'evidence':[],
                    'latest_native':None,'terminal_native':None,'stop_attempted':False}
            controller.ledger.data['actions'][request['id']]=record
            controller.ledger.save()
            result=controller.status(request['id'])
            self.assertEqual(result['state'],'CLOSED')
            self.assertEqual(base64.b64decode(result['evidence'][0]['raw_base64']),raw)
            self.assertEqual(controller.transport.calls,['GET'])

if __name__=='__main__':unittest.main()

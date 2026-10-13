"""Bytes emitted by the real BridgeJson serializer in CoordinationStepGuardTest."""
import json
from pathlib import Path
import unittest
from mdcoord.publisher import step_evidence
from mdcoord.schema import Rejected

WIRE=Path(__file__).resolve().parents[1]/'fixtures/native_coordination_step_wire.json'

class NativeStepWireTests(unittest.TestCase):
    def state(self,key):
        e=json.loads(WIRE.read_text())[key]['coordination_step']
        return dict(coordination_step=e,world=dict(world_generation=e['world_generation'],game_time=e['source_tick']),
                    player=dict(uuid=e['player_uuid']),client_action=dict(action_session=e['action_session']),
                    nearby=dict(radius=8,total=0,returned=0,truncated=False,entities=[]))
    def test_success_signed_long_string_survives_actual_java_to_python_encoding(self):
        evidence,clear=step_evidence(self.state('success'))
        self.assertEqual(evidence['source_nano'],'-9223372036854775808');self.assertTrue(clear)
    def test_encoded_unavailable_sample_does_not_authorize_a_step(self):
        with self.assertRaises(Rejected):step_evidence(self.state('unavailable'))
    def test_missing_or_numeric_clock_is_never_filled_or_retimestamped(self):
        for value in (None, -9223372036854775808, 'NaN','9223372036854775808'):
            state=self.state('success');state['coordination_step']['source_nano']=value
            with self.assertRaises(Rejected):step_evidence(state)

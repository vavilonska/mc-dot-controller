"""Java-produced closed receipt wire plus negative identity/proof transformations."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from resident_controller import fall_rescue_adjudication_wire as wire
from test_fall_rescue_evidence import ROWS
class AdjudicationEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.fixture=json.loads((Path(__file__).parent/'fixtures/fall-adjudication-java-wire.json').read_text())
        self.body=self.fixture['request'];p=self.fixture['receipt'];n=deepcopy(ROWS[4]);b=self.body
        for k in ('arm_id','owner_id'):n[k]=b[k]
        for k in ('action_session','world_generation','player_uuid'):n[k]=b['expected_'+k]
        n.update(status='disarmed',reason='operator_adjudicated_original_effects_unknown',automation_blocked=False,unknown_outcome_quarantined=False)
        n['last_episode']['episode_id']=b['episode_id'];n['last_episode']['interrupted_action']={
            'action_id':b['original_action_id'],'action':'follow_path','effect_outcome':'unknown_interrupted',
            'no_auto_resume':True,'requires_reconciliation_before_retry':True}
        self.seal={'sha256':b['original_receipt_sha256'],'binding':{'arm_id':b['arm_id'],'owner_id':b['owner_id'],
            'action_id':b['original_action_id'],'ttl_ms':5000,'context':{'dimension':'minecraft:overworld',
                **{k:b['expected_'+k] for k in ('action_session','world_generation','player_uuid')}}},'native_status':deepcopy(n)}
        self.value={'adjudication_schema_version':1,'receipt':p,'inspection':{'adjudication_schema_version':1,
            'arbiter_revision':9,'current_neutral_context_proven':True,'native_status':n}}
    def test_java_receipt_and_request(self):
        self.assertEqual(wire.native_request(self.body),self.body)
        self.assertEqual(wire.native_result(self.value,self.body,self.seal),self.value)
    def test_missing_null_altered_proof_fields(self):
        for key in self.value['receipt']:
            for mode in ('missing','null','changed'):
                value=deepcopy(self.value)
                if mode=='missing':value['receipt'].pop(key)
                elif mode=='null':value['receipt'][key]=None
                else:value['receipt'][key]=not value['receipt'][key] if type(value['receipt'][key]) is bool else 'foreign'
                with self.subTest(key=key,mode=mode):
                    with self.assertRaises(ValueError):wire.native_result(value,self.body,self.seal)
    def test_matching_forged_body_and_receipt_still_need_original_binding(self):
        mapping={'arm_id':'arm_id','owner_id':'owner_id','episode_id':'episode_id','original_action_id':'original_action_id',
            'original_receipt_sha256':'original_receipt_sha256','expected_action_session':'action_session',
            'expected_world_generation':'world_generation','expected_player_uuid':'player_uuid'}
        for key,proofkey in mapping.items():
            body=deepcopy(self.body);value=deepcopy(self.value);body[key]='b'*64 if key=='original_receipt_sha256' else 'foreign'
            value['receipt'][proofkey]=body[key]
            with self.subTest(key=key):
                with self.assertRaises(ValueError):wire.native_result(value,body,self.seal)
    def test_current_proof_and_episode_must_not_regress(self):
        for key,bad in [('current_neutral_context_proven',False),('arbiter_revision',8),('adjudication_schema_version',True)]:
            value=deepcopy(self.value);value['inspection'][key]=bad
            with self.assertRaises(ValueError):wire.native_result(value,self.body,self.seal)
        for key in ('armed','input_owned','unknown_outcome_quarantined','automation_blocked'):
            value=deepcopy(self.value);value['inspection']['native_status'][key]=True
            with self.assertRaises(ValueError):wire.native_result(value,self.body,self.seal)
    def test_native_route_and_serializer_source_parity(self):
        root=Path(__file__).resolve().parents[2]/'client-mod/src/main/java/io/github/campione01/mineclientbridge'
        source=(root/'FallRescueAdjudication.java').read_text();bridge=(root/'BridgeServer.java').read_text()
        for key in self.fixture['receipt']:self.assertIn('"'+key+'"',source)
        self.assertIn(wire.ACK,source);self.assertIn('"'+wire.ROOT+'"',bridge)
if __name__=='__main__':unittest.main()

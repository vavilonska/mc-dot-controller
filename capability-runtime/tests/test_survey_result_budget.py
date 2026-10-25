from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from resident_controller.ipc import QueueClient, atomic_json
from resident_controller import survey_result as contract
from mdc_toolbox.survey_display import project, cell_limit
from mdc_toolbox.contracts import json_data
from mdc_skills.core import Runtime
from mdc_toolbox.runtime_adapter import OwnerRuntimeBackend
from mdc_toolbox.service import ToolboxService
from test_capability_ownership import ActualGatewayOwnershipTests

COMMAND = {'op':'observe','terrain':True,'radius':16,'vertical':8,'entity_radius':48,
           'capability_observation':True,'capability_survey':True}


def receipt(command=COMMAND, padding=''):
    count=(2*command['radius']+1)**2*(2*command['vertical']+1)
    cells=[{'x':i,'y':64,'z':0,'id':'minecraft:stone','properties':{}} for i in range(count)]
    value={'request_id':'original','session_id':'resident','status':'succeeded','finished_at':1.,
           'result':{'state':{'padding':padding},'terrain':{'radius':command['radius'],
               'vertical':command['vertical'],'cells':cells,'complete':True,'historical_survey':True}}}
    return contract.finish_receipt(command,value)


class SurveyResultBoundsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        (self.root/'results').mkdir();self.q=QueueClient(self.root)
    def tearDown(self):self.temp.cleanup()
    def save(self,value):atomic_json(self.root/'results/original.json',value)
    def test_large_valid_read_selected_by_original_command_only(self):
        value=receipt(padding='界'*800000);self.save(value)
        self.assertGreater((self.root/'results/original.json').stat().st_size,2*1024*1024)
        with self.assertRaisesRegex(ValueError,'mailbox_file_too_large'):self.q.result('original')
        self.assertEqual(self.q.survey_result('original',COMMAND,'resident'),value)
        for changed in ({**COMMAND,'op':'action'},{**COMMAND,'capability_survey':1},
                        {**COMMAND,'radius':17},{**COMMAND,'vertical':True},
                        {**COMMAND,'extra':1}):
            with self.subTest(changed=changed),self.assertRaises(ValueError):
                self.q.survey_result('original',changed,'resident')
    def test_wrong_identity_digest_and_types_refused(self):
        for change in (lambda v:v.update(request_id='other'),lambda v:v.update(session_id='other'),
                       lambda v:v['survey_result'].update(command_sha256='0'*64),
                       lambda v:v['survey_result'].update(execution_authority=0),
                       lambda v:v['survey_result'].update(maximum_bytes=float(contract.MAX_BYTES)),
                       lambda v:v['result']['terrain'].update(radius=True),
                       lambda v:v['result']['terrain']['cells'].pop()):
            value=receipt();change(value);self.save(value)
            with self.assertRaises(ValueError):self.q.survey_result('original',COMMAND,'resident')
    def test_pre_read_cap_and_malformed_duplicate_nonfinite_refused(self):
        path=self.root/'results/original.json'
        for raw in (b' '* (contract.MAX_BYTES+1),b'{',b'{"x":1,"x":2}',b'{"x":NaN}'):
            path.write_bytes(raw)
            with self.assertRaises(ValueError):self.q.survey_result('original',COMMAND,'resident')
    def test_exact_utf8_bound_and_producer_known_read_failure(self):
        value=receipt(padding='x'*(contract.MAX_BYTES+1))
        self.assertEqual(value['status'],'failed');self.assertNotIn('result',value)
        self.assertGreater(value['survey_diagnostic']['encoded_bytes'],contract.MAX_BYTES)
        self.save(value);self.assertEqual(self.q.survey_result('original',COMMAND,'resident'),value)
        self.assertLess(len(contract.encode(value)),2048)
    def test_exact_limit_is_accepted_and_next_utf8_byte_is_refused(self):
        value=receipt();remaining=contract.MAX_BYTES-len(contract.encode(value))
        value['result']['state']['padding']='x'*remaining
        self.assertEqual(len(contract.encode(value)),contract.MAX_BYTES)
        sealed=contract.finish_receipt(COMMAND,value);self.assertEqual(sealed['status'],'succeeded')
        self.save(sealed);self.assertEqual(self.q.survey_result('original',COMMAND,'resident')['status'],'succeeded')
        value['result']['state']['padding']+='x'
        self.assertEqual(contract.finish_receipt(COMMAND,value)['status'],'failed')

    def test_display_projection_preserves_state_and_disclaims_physics(self):
        value=receipt()['result'];value.update(profile='survey',execution_authority=False,coverage={},provenance={})
        before=deepcopy(value);out=project(value,{'max_cells':2048})
        self.assertEqual(value,before);self.assertEqual(out['state'],value['state'])
        self.assertEqual(len(out['terrain']['cells']),2048)
        self.assertIs(out['terrain']['complete'],False);self.assertTrue(out['terrain']['source_complete'])
        self.assertTrue(out['terrain']['physics_omitted']);self.assertTrue(out['terrain']['cells_truncated'])
        self.assertLess(len(json_data(out)),1024*1024)
        for count in (True,0,2049,1.0):
            with self.assertRaises(ValueError):cell_limit({'max_cells':count})


class SurveyActualOwnerChainTests(unittest.TestCase):
    setUp=ActualGatewayOwnershipTests.setUp
    tearDown=ActualGatewayOwnershipTests.tearDown
    until=ActualGatewayOwnershipTests.until

    def test_survey_cannot_refresh_authority_or_clear_prior_action_barrier(self):
        ActualGatewayOwnershipTests.claim(self)
        old_latest=self.dog.latest;old_clock=self.dog.observed_at
        self.dog.capability_lease['post_observation_required']=True
        rid=self.client.submit({**COMMAND,'radius':3,'_capability_owner_id':self.owner,
                                '_navigation_defense_epoch':self.epoch})
        result=self.client.wait(rid,timeout=5)
        self.assertEqual(result['status'],'succeeded',result)
        self.assertIs(self.dog.latest,old_latest);self.assertEqual(self.dog.observed_at,old_clock)
        self.assertTrue(self.dog.capability_lease['post_observation_required'])
        self.assertFalse(self.bridge.posts)

    def test_public_large_survey_and_exact_cleanup_no_native_posts(self):
        runtime=Runtime(self.client,self.root/'runtime',wait_timeout=20)
        backend=OwnerRuntimeBackend(runtime);service=ToolboxService(backend,self.root/'toolbox')
        try:
            ref=backend.describe()['session_ref']
            result=service.call('mdc_observe',{'api_version':'mdc.toolbox/1','session_ref':ref,
                'request_id':'large_survey_once','profile':'survey','bounds':{'radius':16,'max_cells':1024}})
            self.assertEqual(result.get('job_state'),'succeeded',result)
            self.assertEqual(result['cleanup_certainty'],'confirmed')
            self.assertIsNone(self.dog.capability_lease);self.assertIsNone(self.dog.owner)
            self.assertIsNone(runtime._preflight_request_id)
            self.assertEqual(result['terrain']['cells_total'],18513)
            self.assertEqual(result['terrain']['cells_returned'],1024)
            self.assertLess(len(json_data(result)),1024*1024)
            originals=[p for p in (self.root/'resident/results').glob('*.json')
                       if p.stat().st_size>2*1024*1024]
            self.assertEqual(len(originals),1)
            original=json.loads(originals[0].read_text());self.assertEqual(original['status'],'succeeded')
            self.assertEqual(len(original['result']['terrain']['cells']),18513)
            self.assertFalse(self.bridge.posts)
            count=len(list((self.root/'resident/results').glob('*.json')))
            replay=service.call('mdc_observe',{'api_version':'mdc.toolbox/1','session_ref':ref,
                'request_id':'large_survey_once','profile':'survey','bounds':{'radius':16,'max_cells':1024}})
            self.assertEqual(replay,result)
            self.assertEqual(len(list((self.root/'resident/results').glob('*.json'))),count)
        finally:service.shutdown();runtime.close()

    def test_malformed_original_is_published_unknown_once_and_owner_retained(self):
        from unittest.mock import patch
        runtime=Runtime(self.client,self.root/'runtime',wait_timeout=5)
        service=ToolboxService(OwnerRuntimeBackend(runtime),self.root/'toolbox')
        original=contract.finish_receipt
        def forged(command,value):
            result=original(command,value);result['survey_result']['command_sha256']='0'*64;return result
        try:
            ref=service.backend.describe()['session_ref']
            with patch.object(contract,'finish_receipt',forged):
                result=service.call('mdc_observe',{'api_version':'mdc.toolbox/1','session_ref':ref,
                    'request_id':'malformed_survey_once','profile':'survey','bounds':{'radius':3}})
            self.assertEqual(result['state'],'unknown',result)
            self.assertEqual(result['cleanup_certainty'],'unknown')
            self.assertIsNotNone(self.dog.owner);self.assertTrue(self.dog.owner['reported'])
            self.assertEqual(self.dog.reason,'survey_original_receipt_unreadable')
            queue=self.dog.owner['request_id'];path=self.root/'resident/results'/f'{queue}.json'
            original_hash=hashlib.sha256(path.read_bytes()).hexdigest()
            before=len(list((self.root/'resident/results').glob('*.json')))
            again=service.call('mdc_observe',{'api_version':'mdc.toolbox/1','session_ref':ref,
                    'request_id':'malformed_survey_once','profile':'survey','bounds':{'radius':3}})
            self.assertEqual(again['state'],'unknown')
            self.assertEqual(len(list((self.root/'resident/results').glob('*.json'))),before)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),original_hash)
            self.assertFalse(self.bridge.posts)
        finally:service.shutdown();runtime.close()


class SurveyNodeChainTests(unittest.TestCase):
    import test_route_local_frontdoor as _front
    setUp=_front.RouteLocalFrontdoorTests.setUp
    tearDown=_front.RouteLocalFrontdoorTests.tearDown
    until=_front.RouteLocalFrontdoorTests.until
    rpc=_front.RouteLocalFrontdoorTests.rpc
    call=_front.RouteLocalFrontdoorTests.call
    def test_large_survey_real_node_frontdoor(self):
        catalog=self.call('mdc_catalog',{'api_version':'mdc.toolbox/1','limit':1})
        ref=catalog['runtime_binding_availability']['session_ref']
        args={'api_version':'mdc.toolbox/1','session_ref':ref,'request_id':'node_large_survey',
              'profile':'survey','bounds':{'radius':16,'max_cells':1024}}
        result=self.call('mdc_observe',args)
        self.assertEqual(result.get('job_state'),'succeeded',result)
        self.assertEqual(result['cleanup_certainty'],'confirmed')
        self.assertEqual(result['terrain']['cells_total'],18513)
        self.assertEqual(result['terrain']['cells_returned'],1024)
        self.assertIsNone(self.dog.capability_lease);self.assertFalse(self.bridge.posts)
        self.assertLess(len(json_data(result)),1024*1024)
        self.assertEqual(self.call('mdc_observe',args),result)

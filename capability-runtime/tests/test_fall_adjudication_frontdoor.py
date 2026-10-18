"""Actual Node MCP front door, modeled native adjudication only."""
import unittest
from unittest.mock import patch
import test_attached_fall_frontdoor as attached
from test_fall_adjudication_owner_chain import AdjudicationEndpointMixin
from resident_controller.fall_rescue_adjudication_wire import ACK
class Endpoint(AdjudicationEndpointMixin,attached.Endpoint):pass
class AdjudicationFrontdoorTests(unittest.TestCase):
    until=attached.AttachedFrontdoorTests.until
    rpc=attached.AttachedFrontdoorTests.rpc
    call=attached.AttachedFrontdoorTests.call
    finish=attached.AttachedFrontdoorTests.finish
    posts=attached.AttachedFrontdoorTests.posts
    submit=attached.AttachedFrontdoorTests.submit
    def setUp(self):
        with patch.object(attached,'Endpoint',Endpoint):attached.AttachedFrontdoorTests.setUp(self)
    def tearDown(self):attached.AttachedFrontdoorTests.tearDown(self)
    def test_adjudication(self):
        self.bridge.rescue_mode='confirmed';r=self.finish(self.submit());self.assertEqual(r['state'],'unknown',r)
        base={'api_version':'mdc.toolbox/1','job_id':r['job_id'],'session_ref':r['session_ref']}
        p=self.call('mdc_job',{**base,'operation':'adjudication_prepare'})
        self.assertTrue(p.get('adjudication',{}).get('eligible'),p)
        args={**base,'operation':'adjudicate','adjudication_request_id':'node-adjudication-one',
            'original_receipt_sha256':p['adjudication']['selector']['original_receipt_sha256'],'acknowledgment':ACK}
        bad=self.call('mdc_job',{**args,'acknowledgment':True});self.assertIn('error',bad)
        result=self.call('mdc_job',args);self.assertTrue(result['adjudication']['authority_released'],result)
        self.assertEqual(result['state'],'unknown');self.assertEqual(result['effect_certainty'],'unknown')
        replay=self.call('mdc_job',{**args,'operation':'adjudication_status'})
        self.assertTrue(replay['adjudication']['authority_released']);self.assertEqual(len(self.posts()),1)
        self.assertEqual(sum(m=='POST' for m,p,b in self.bridge.adjudication_calls),1)
        self.assertIsNone(self.client.session()['capability_lease'])
if __name__=='__main__':unittest.main()

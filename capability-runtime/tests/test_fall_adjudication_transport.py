"""Production Bridge schema admission and actual bounded HTTP loopback."""
from copy import deepcopy
from test_fall_rescue_transport import FallTransportTests
from resident_controller.transport import BridgeError
from resident_controller.fall_rescue_adjudication_wire import ACK,ROOT
class AdjudicationTransportTests(FallTransportTests):
    def test_adjudication_routes(self):
        body={'adjudication_schema_version':1,'adjudication_id':'a','arm_id':'arm','owner_id':'owner','episode_id':'episode',
            'original_action_id':'action','original_receipt_sha256':'a'*64,'expected_action_session':'session',
            'expected_world_generation':'world','expected_player_uuid':'player','expected_arbiter_revision':8,'acknowledgment':ACK}
        for method,path,b in [('GET',ROOT+'/prepare',None),('GET',ROOT+'/status?adjudication_id=a',None),('POST',ROOT,body)]:
            self.assertEqual(self.bridge.request(method,path,b),{'observed':True})
        self.assertEqual(len(self.calls),3)
        bad=[('POST',ROOT+'/prepare',{}),('GET',ROOT,None),('GET',ROOT+'/prepare?x=1',None),
            ('GET',ROOT+'/status?adjudication_id=a&adjudication_id=a',None),('GET',ROOT+'/status?%61djudication_id=a',None),
            ('GET',ROOT+'/status?adjudication_id=a',{}),('POST',ROOT+'?x=1',body)]
        for key in body:
            b=deepcopy(body);b.pop(key);bad.append(('POST',ROOT,b))
            b=deepcopy(body);b[key]=None;bad.append(('POST',ROOT,b))
        for key,val in [('acknowledgment',True),('expected_arbiter_revision',True),('expected_arbiter_revision',2**53-1),
            ('adjudication_schema_version',1.0),('original_receipt_sha256','bad')]:bad.append(('POST',ROOT,{**body,key:val}))
        for method,path,b in bad:
            with self.subTest(path=path,body=b):
                with self.assertRaises(BridgeError):self.bridge.request(method,path,b)
        self.assertEqual(len(self.calls),3)

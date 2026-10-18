"""Actual Node MCP → Python → serialized owner → Resident; modeled native endpoint."""
from copy import deepcopy
import unittest
from unittest.mock import patch
import test_route_local_frontdoor as route
from test_fall_rescue_owner_chain import Endpoint as FallEndpoint
from test_attached_fall_owner_chain import RescueEndpointMixin

class Endpoint(RescueEndpointMixin,FallEndpoint,route.Endpoint):
    pass

class AttachedFrontdoorTests(unittest.TestCase):
    until=route.RouteLocalFrontdoorTests.until
    rpc=route.RouteLocalFrontdoorTests.rpc
    call=route.RouteLocalFrontdoorTests.call
    finish=route.RouteLocalFrontdoorTests.finish
    posts=route.RouteLocalFrontdoorTests.posts
    def setUp(self):
        with patch.object(route,'Endpoint',Endpoint):route.RouteLocalFrontdoorTests.setUp(self)
    def tearDown(self):route.RouteLocalFrontdoorTests.tearDown(self)
    def submit(self,policy=None):
        return route.RouteLocalFrontdoorTests.submit(self,arguments={'goal':{'x':1,'y':64,'z':0},'radius':2,'max_segments':1},
            policy=policy or {'version':1,'execution_mode':'request_only','reactions':'stop',
                             'fall_rescue':{'schema_version':1,'water_bucket':True}},
            budgets={'deadline_seconds':40,'max_actions':8,'max_observations':256,'cleanup_reserve_actions':1})
    def test_attached_flat(self):
        result=self.finish(self.submit());self.assertEqual(result['state'],'succeeded',result)
        self.assertEqual(len(self.posts()),1);self.assertEqual(len(self.bridge.moves),1)
        self.assertEqual(self.bridge.allowed_ids,[self.posts()[0]['intent']['action_id']])
        self.assertEqual([x for x,_ in self.bridge.fall_calls].count('arm'),1)
        self.assertEqual([x for x,_ in self.bridge.fall_calls].count('disarm'),1)
        self.assertEqual(self.bridge.fall_calls[0][1]['ttl_ms'],18000)
        self.assertEqual(result['evidence']['budget']['used']['ordinary']['actions'],3)
        self.assertIsNone(self.client.session()['capability_lease'])
    def test_attached_preempt(self):
        self.expected_mcp_exit=2;self.bridge.rescue_mode='confirmed'
        result=self.finish(self.submit());self.assertEqual(result['state'],'unknown',result)
        self.assertEqual(len(self.posts()),1);self.assertEqual(self.bridge.moves,[])
        self.assertNotIn('disarm',[x for x,_ in self.bridge.fall_calls]);self.assertIsNotNone(self.client.session()['capability_lease'])
    def test_attached_schema(self):
        result=self.submit({'version':1,'execution_mode':'request_only','reactions':'stop',
            'fall_rescue':{'schema_version':1,'water_bucket':True,'permitted_action_ids':['foreign']}})
        self.assertIn('error',result);self.assertEqual(self.bridge.fall_calls,[]);self.assertEqual(self.posts(),[])

if __name__=='__main__':unittest.main()

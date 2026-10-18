"""Actual compact Java codec, strict wire faults and public owner-chain lifecycle. Offline only."""
from copy import deepcopy
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs,urlsplit
from resident_controller.compact_observation import validate
from resident_controller.transport import Bridge,BridgeError
import test_route_local_frontdoor as route


def wire():
    path=os.environ.get('MDC_COMPACT_OBSERVATION_WIRE')
    if not path: raise unittest.SkipTest('explicit production compact Java wire required')
    return json.loads(Path(path).read_text())


class CompactWireTests(unittest.TestCase):
    def test_original_production_codec_is_bounded_display_only(self):
        original=wire();copy,stamp=validate(original,'compact-one',1)
        self.assertEqual(copy,original);self.assertEqual(stamp.count,5)
        self.assertFalse(copy['execution_authority']);self.assertFalse(copy['coverage']['inventory_recovery_complete'])
        copy['terrain']['cells'][0]['id']='changed';self.assertNotEqual(copy,original)
    def test_wire_fault_matrix(self):
        mutations=[lambda v:v.update(schema_version=True),lambda v:v.update(execution_authority=True),
            lambda v:v.update(server_confirmed=True),lambda v:v.update(request_id='other'),
            lambda v:v.update(extra=True),lambda v:v.update(native_elapsed_nanos='100000001'),
            lambda v:v['bounds'].update(radius=True),lambda v:v['context'].update(action_session='other'),
            lambda v:v['observation_clock'].update(count=True),lambda v:v['terrain']['source_clock'].update(count=6),
            lambda v:v['terrain']['response_clock'].update(count=4),lambda v:v['terrain'].update(game_time=101),
            lambda v:v['terrain'].update(response_game_time=101),lambda v:v['terrain'].update(complete=False),
            lambda v:v['terrain']['cells'].__setitem__(0,deepcopy(v['terrain']['cells'][1])),
            lambda v:v['terrain']['cells'][0].update(x=True),lambda v:v['coverage'].update(menu_slots_captured=True),
            lambda v:v['action'].update(action_session='wrong'),lambda v:v['player'].update(uuid='wrong'),
            lambda v:v['terrain'].update(world_generation='wrong'),lambda v:v['player'].update(vehicle='x'*65536)]
        for mutate in mutations:
            bad=wire();mutate(bad)
            with self.subTest(bad=repr(mutate)),self.assertRaises((ValueError,TypeError,KeyError)):validate(bad,'compact-one',1)
    def test_prior_epoch_context_and_native_identity(self):
        original=wire();_,prior=validate(original,'compact-one',1)
        for mutate in (lambda v:v['observation_clock'].update(count=4),
                       lambda v:v['observation_clock'].update(clock_generation='55555555-6666-4777-8888-999999999999')):
            bad=wire();mutate(bad)
            with self.assertRaises(ValueError):validate(bad,'compact-one',1,prior=prior)
        with self.assertRaises(ValueError):validate(original,'compact-one',1,identity={'run_id':'other'})
        with self.assertRaises(ValueError):validate(original,'compact-one',1,context={'player_uuid':'other'})
    def test_http_duplicate_rejected_one_read_no_retry(self):
        original=wire();raw=json.dumps(original).replace('"request_id": "compact-one"','"request_id":"wrong","request_id":"compact-one"').encode()
        class Response:
            status=200
            def read(self,limit):return raw[:limit]
            def getheader(self,name):return None
        class Connection:
            calls=[]
            def __init__(self,*a,**k):pass
            def request(self,*a,**k):self.calls.append((a,k))
            def getresponse(self):return Response()
            def close(self):pass
        bridge=Bridge('http://127.0.0.1:12345','offline')
        with patch('resident_controller.transport.http.client.HTTPConnection',Connection),self.assertRaises(BridgeError):
            bridge.request('GET','/control/compact-observation?request_id=compact-one&radius=1')
        self.assertEqual(len(Connection.calls),1)


class CompactEndpoint(route.Endpoint):
    def __init__(self):super().__init__();self.compact_reads=[]
    def request(self,method,path,body=None):
        if path.startswith('/control/compact-observation?'):
            self.compact_reads.append(path)
            if self.mode_name=='lost':raise BridgeError('compact_reply_lost',uncertain=True)
            value=wire();query=parse_qs(urlsplit(path).query);state=self.snapshot()
            ctx=value['context'];ctx.update(run_id='fixture',process_id=123,
                world_generation=state['world']['world_generation'],dimension=state['world']['dimension'],
                integrated_server_instance=state['world']['integrated_server_instance'],
                player_uuid=state['player']['uuid'],action_session=state['client_action']['action_session'])
            value['observation_clock']['context']=deepcopy(ctx);value['observation_clock']['count']=self.tick
            for key in ('source_clock','response_clock'):value['terrain'][key]=deepcopy(value['observation_clock'])
            value['request_id']=query['request_id'][0]
            if 'native_timing' in value:value['native_timing']['request_id']=value['request_id']
            value['world'].update({k:ctx[k] for k in ('world_generation','dimension','integrated_server_instance')})
            value['world']['game_time']=self.tick;value['player'].update(uuid=ctx['player_uuid'],dimension=ctx['dimension'])
            value['action']['action_session']=ctx['action_session']
            value['terrain'].update(world_generation=ctx['world_generation'],dimension=ctx['dimension'],game_time=self.tick,response_game_time=self.tick)
            if self.mode_name=='page_ahead':value['terrain']['response_game_time']=self.tick+1
            return value
        return super().request(method,path,body)


class CompactFrontdoorTests(unittest.TestCase):
    until=route.RouteLocalFrontdoorTests.until
    rpc=route.RouteLocalFrontdoorTests.rpc
    call=route.RouteLocalFrontdoorTests.call
    finish=route.RouteLocalFrontdoorTests.finish
    def setUp(self):
        wire()
        with patch.object(route,'Endpoint',CompactEndpoint):route.RouteLocalFrontdoorTests.setUp(self)
    def tearDown(self):route.RouteLocalFrontdoorTests.tearDown(self)
    def observe(self):
        catalog=self.call('mdc_catalog',{'api_version':'mdc.toolbox/1'})
        self.session_ref=catalog['runtime_binding_availability']['session_ref']
        self.args={'api_version':'mdc.toolbox/1','request_id':'compact-'+self.mode,'profile':'compact','session_ref':self.session_ref,'bounds':{'radius':1},'wait_ms':10000}
        return self.call('mdc_observe',self.args)
    def test_success(self):
        result=self.observe();self.assertEqual(result.get('profile'),'compact',result)
        self.assertFalse(result['execution_authority']);self.assertFalse(result['compact']['coverage']['menu_slots_captured'])
        self.assertEqual(result['job_state'],'succeeded');self.assertIsNone(self.client.session()['capability_lease'])
        repeated=self.call('mdc_observe',self.args);self.assertEqual(repeated['job_id'],result['job_id'])
        self.assertEqual(len(self.bridge.compact_reads),1);self.assertFalse(self.bridge.posts)
        self.assertNotIn('compact_observation',self.dog.latest)
    def test_page_ahead(self):
        result=self.observe();self.assertNotEqual(result.get('job_state'), 'succeeded',result)
        self.assertEqual(len(self.bridge.compact_reads),1);self.assertFalse(self.bridge.posts)
        self.assertNotIn('compact_observation',self.dog.latest)
    def test_lost(self):
        self.expected_mcp_exit=2
        result=self.observe();self.assertEqual(result.get('state'),'unknown',result)
        self.assertEqual(len(self.bridge.compact_reads),1);self.assertFalse(self.bridge.posts)
        repeated=self.call('mdc_observe',self.args);self.assertEqual(repeated['job_id'],result['job_id'])
        self.assertEqual(repeated['state'],'unknown');self.assertEqual(len(self.bridge.compact_reads),1)

if __name__=='__main__':unittest.main()

"""Real Resident -> mailbox -> v5 Watchdog -> cursor; native boundary alone is fake."""
import copy
import unittest
from resident_controller.transport import BridgeError
import test_release_safety_chain as chain


class NavigationBindingChainTests(unittest.TestCase):
    setUp=chain.ReleaseChainTests.setUp
    tearDown=chain.ReleaseChainTests.tearDown
    pump=chain.ReleaseChainTests.pump
    posts=chain.ReleaseChainTests.posts
    start_path=chain.ReleaseChainTests.start_path
    finish_native=chain.ReleaseChainTests.finish_native
    def guarded(self,epoch=3,x=.5):
        o=copy.deepcopy(self.bridge.observed);s=o['state']
        s['world']['navigation_guard']={'schema_version':1,'epoch':epoch,'fresh_binding_required':True,
            'rebind_ready':True,'stable_ticks':3,'reason':'position_discontinuity'}
        s['player'].update(uuid='chain-player',x=x)
        s['client_action']={'action_session':'test-session','status':'idle'}
        self.bridge.observed=o;self.dog.latest=copy.deepcopy(o)
        return copy.deepcopy(o)
    def reject_once(self,status=409,uncertain=False,reason='navigation_origin_changed'):
        old=self.bridge.request;rejected=False
        def request(method,path,body=None):
            nonlocal rejected
            if method=='POST' and path=='/control/action' and not rejected:
                rejected=True;self.bridge.calls.append((method,path,copy.deepcopy(body)))
                raise BridgeError(reason,status=status,uncertain=uncertain)
            return old(method,path,body)
        self.bridge.request=request
    def test_definite_unadmitted_request_gets_new_plan_without_rewriting_first_body(self):
        self.guarded();self.reject_once();self.start_path();self.pump(3)
        first=copy.deepcopy(self.posts()[0][2]);request_id=self.nav.data['pending']['id']
        queued=self.gateway.result(request_id)
        self.assertEqual(409,queued['action_admission']['http_status'])
        self.assertEqual('progress',self.nav.tick(chain.GOAL)['status'])
        self.assertEqual([],self.nav.data['forbidden'])
        self.assertEqual('pending',self.nav.process_observation(self.guarded(epoch=4,x=.611))['status'])
        self.pump()
        self.assertEqual(2,len(self.posts()));second=self.posts()[1][2]
        self.assertNotEqual(first['action_id'],second['action_id'])
        self.assertEqual(first,self.posts()[0][2]);self.assertEqual(4,second['expected_navigation_epoch'])
        self.assertEqual(.611,second['expected_origin']['x']);self.assertEqual(1,self.nav.data['replans'])
    def test_400_context_change_and_unknown_post_never_create_second_dispatch(self):
        # Each scenario gets a fresh legitimate owner context, never a retry.
        scenarios=[(400,False,'expected_origin_required'),(409,False,'player_changed'),
                   (500,True,'navigation_origin_changed'),(409,True,'navigation_origin_changed')]
        for status,uncertain,reason in scenarios:
            with self.subTest(status=status,uncertain=uncertain,reason=reason):
                if self.posts():self.tearDown();self.setUp()
                self.guarded();self.reject_once(status,uncertain,reason);self.start_path();self.pump(3)
                self.assertEqual('blocked',self.nav.tick(chain.GOAL)['status'])
                for _ in range(4):self.pump();self.nav.tick(chain.GOAL)
                self.assertEqual(1,len(self.posts()))
    def test_discontinuity_cleanup_failure_retains_raw_requested_cancel_and_latches(self):
        for failed_stage in ('attack_key_up','stop_destroy_block'):
            with self.subTest(stage=failed_stage):
                if self.posts():self.tearDown();self.setUp()
                self.guarded();self.start_path()
                self.bridge.action.update(status='failed',reason='input_release_unconfirmed',result={
                    'input_release_confirmed':False,'requested_terminal_status':'cancelled',
                    'requested_terminal_reason':'position_discontinuity_rebind_required'})
                raw=copy.deepcopy(self.bridge.action);self.pump(4)
                rid=self.nav.data['pending']['id'];self.assertEqual(raw,self.gateway.result(rid)['action'])
                self.assertEqual('blocked',self.nav.tick(chain.GOAL)['status'])
                self.assertTrue(self.dog.input_release_latched);self.assertTrue(self.resident.paused)
                for _ in range(4):self.pump();self.nav.tick(chain.GOAL)
                self.assertEqual(1,len(self.posts()))

    def test_new_discontinuity_missing_release_latches_resident_watchdog_and_cursor(self):
        self.guarded();self.start_path()
        raw=self.finish_native('missing',status='cancelled',reason='position_discontinuity_rebind_required')
        rid=self.nav.data['pending']['id'];queued=self.gateway.result(rid)
        self.assertEqual(raw,queued['action']);self.assertEqual('failed',queued['status'])
        self.assertTrue(self.resident.paused);self.assertTrue(self.dog.input_release_latched)
        self.assertEqual('blocked',self.nav.tick(chain.GOAL)['status'])
        self.assertFalse(self.dog.submit_owner('bypass',{'op':'action','action':'follow_path','waypoints':[]}))
        self.assertEqual(1,len(self.posts()))

    def test_confirmed_new_discontinuity_allows_bounded_fresh_plan(self):
        self.guarded();self.start_path()
        self.finish_native(True,status='cancelled',reason='position_discontinuity_rebind_required')
        self.assertFalse(self.resident.paused);self.assertFalse(self.dog.input_release_latched)
        self.assertEqual('progress',self.nav.tick(chain.GOAL)['status'])
        self.assertEqual(1,self.nav.data['replans'])
        self.assertEqual('pending',self.nav.process_observation(self.guarded(epoch=4))['status'])
        self.pump();self.assertEqual(2,len(self.posts()))

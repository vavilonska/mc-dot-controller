"""Local polling never changes deadline, ownership or submission semantics."""
import tempfile
import unittest
from unittest.mock import patch

from base_watchdog import Watchdog
from intent_client import IntentClient


class Clock:
    def __init__(self):self.now=0.;self.sleeps=[]
    def monotonic(self):return self.now
    def sleep(self,seconds):self.sleeps.append(seconds);self.now+=seconds


class CapabilityPollingTests(unittest.TestCase):
    def client(self):
        return IntentClient(tempfile.gettempdir())

    def test_legacy_result_wait_retains_100ms_poll(self):
        c=self.client();clock=Clock()
        c.result=lambda rid: {'status':'succeeded','request_id':rid} if clock.now>=.021 else None
        with patch('intent_client.time.monotonic',clock.monotonic),patch('intent_client.time.sleep',clock.sleep):
            self.assertEqual(c.wait('one',1)['status'],'succeeded')
        self.assertEqual(clock.sleeps,[.1])

    def test_confirmed_owner_reads_result_at_10ms_without_submit(self):
        c=self.client();c._capability_owner='a'*32;clock=Clock()
        c.submit=lambda *a,**k:self.fail('wait must never submit')
        c.result=lambda rid: {'status':'succeeded','request_id':rid} if clock.now>=.021 else None
        with patch('intent_client.time.monotonic',clock.monotonic),patch('intent_client.time.sleep',clock.sleep):
            self.assertEqual(c.wait('one',1)['request_id'],'one')
        self.assertEqual(clock.sleeps,[.01]*3)

    def test_owner_timeout_keeps_original_deadline_and_exact_pending_id(self):
        c=self.client();c._capability_owner='a'*32;clock=Clock();c.result=lambda _:None
        with patch('intent_client.time.monotonic',clock.monotonic),patch('intent_client.time.sleep',clock.sleep):
            result=c.wait('exact-original',.025)
        self.assertEqual(result,{'request_id':'exact-original','status':'pending','reason':'wait_timeout_not_action_failure'})
        self.assertAlmostEqual(clock.now,.025)
        self.assertEqual(len(clock.sleeps),3)

    def test_faulted_or_stopped_owner_does_not_get_fast_poll(self):
        for fault,stopped in [('unknown',False),(None,True)]:
            with self.subTest(fault=fault,stopped=stopped):
                c=self.client();c._capability_owner='a'*32;c._capability_fault=fault
                if stopped:c._capability_stop.set()
                clock=Clock();c.result=lambda _:None
                with patch('intent_client.time.monotonic',clock.monotonic),patch('intent_client.time.sleep',clock.sleep):c.wait('id',.2)
                self.assertEqual(clock.sleeps,[.1,.1])

    def dog(self):
        dog=Watchdog(None,clock=lambda:10.)
        dog.capability_lease={'owner_id':'a'*32,'state':'active','deadline':20.,'heartbeat':11.}
        return dog

    def test_watchdog_only_confirmed_live_lease_changes_loop_sleep(self):
        d=self.dog();before=dict(d.capability_lease)
        self.assertEqual(d.poll_interval(),.01)
        self.assertEqual(d.capability_lease,before)
        d.capability_lease=None;self.assertEqual(d.poll_interval(),.05)

    def test_watchdog_stop_handoff_unknown_and_expiry_retain_legacy_cadence(self):
        for flag,value in [('armed',False),('stop_requested',True),('stopped',True),('handoff_latched',True),('input_release_latched',True)]:
            with self.subTest(flag=flag):
                d=self.dog();setattr(d,flag,value);self.assertEqual(d.poll_interval(),.05)
        for key,value in [('state','paused'),('owner_id',''),('deadline',10.),('heartbeat',9.),('deadline',True),('heartbeat',float('nan')),('deadline',None)]:
            with self.subTest(key=key,value=value):
                d=self.dog();d.capability_lease[key]=value;self.assertEqual(d.poll_interval(),.05)

    def test_gateway_poll_does_not_run_native_or_modify_owner(self):
        d=self.dog();d.owner={'id':'exact','request_id':'queue-original'}
        d.tick=lambda:self.fail('poll selector must not tick')
        self.assertEqual(d.poll_interval(),.01)
        self.assertEqual(d.owner,{'id':'exact','request_id':'queue-original'})


if __name__=='__main__':unittest.main()

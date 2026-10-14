"""Request-only real mailbox chain; synthetic endpoint, no live combat proof."""
from copy import deepcopy
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import base_watchdog
import test_scoped_combat_chain as chain
import test_noncombat_watchdog as noncombat
from mdc_toolbox.contracts import POLICY, validate_schema
from mdc_skills.__main__ import parser

class RequestOnlyCombat(chain.PublicCombatChainTests):
    def setUp(self):
        original=base_watchdog.run
        def run(*args,**kwargs):
            kwargs['execution_policy']='request_only'
            return original(*args,**kwargs)
        with patch.object(base_watchdog,'run',run):
            super().setUp()
        self.runtime.required_execution_policy='request_only'
    def submit(self):
        original=self.service.call
        def call(name,args):
            args=deepcopy(args)
            if args.get('operation')=='submit':args['policy']['execution_mode']='request_only'
            return original(name,args)
        with patch.object(self.service,'call',call):return super().submit()
    def test_initial_hostile_and_post_release_no_autonomy(self):
        self.assertEqual(self.client.session()['execution_policy'],'request_only')
        before=self.bridge.tick
        self.until(lambda:self.bridge.tick>=before+2)
        self.assertFalse(self.bridge.posts)
        result=self.finish(self.submit());self.assertEqual(result['state'],'succeeded',result)
        self.bridge.action['status']='idle'
        self.bridge.entities[0]['alive']=True
        before=self.bridge.tick
        self.until(lambda:self.bridge.tick>=before+2)
        self.assertEqual(len([p for p,b in self.bridge.posts if p=='/control/scoped-action']),1)
        self.assertFalse([p for p,b in self.bridge.posts if p=='/control/action'])
        self.assertFalse(self.resident.combat.active)
    def test_expired_owner_never_reopens_autonomous_producers(self):
        self.client.acquire_capability(self.owner,duration_ms=100)
        self.until(lambda:self.dog.handoff_latched)
        self.assertEqual(self.dog.reason,'capability_deadline_expired')
        self.assertFalse(self.bridge.posts)
        self.assertFalse(self.resident.combat.active)
        self.assertFalse(self.dog.environment.active)
        self.assertIsNone(self.dog.ranged_move)
    def test_missing_wrong_and_malformed_scope_never_dispatch(self):
        self.client.acquire_capability(self.owner,duration_ms=10000)
        source=self.client.session()['capability_context']
        # Exercise native gateway admission independently of the public adapter.
        lease=self.dog.capability_lease
        state=self.dog.latest['state']
        body={'op':'action','action':'combat_entity','timeout_ms':1000,
              '_capability_owner_id':self.owner,'_navigation_defense_epoch':self.epoch,
              'capability_guard':deepcopy(state['capability_guard']),
              **{'expected_'+k:v for k,v in lease['context'].items()}}
        scope={'version':'scoped-native-preflight/1','profile':'combat-local-observed-v1',
               'owner_id':self.owner,'owner_generation':1,'job_id':'test','defense_epoch':self.epoch}
        for value in (None,{},dict(scope,profile=[]),dict(scope,profile='missing'),dict(scope,owner_id='wrong'),dict(scope,defense_epoch=self.epoch+1)):
            command=deepcopy(body)
            if value is not None:command['scoped_native_preflight']=value
            result=self.client.wait(self.client.submit(command),timeout=3)
            self.assertEqual(result['status'],'cancelled',result)
        command=dict(body,action='break_block',scoped_native_preflight=scope)
        self.assertEqual(self.client.wait(self.client.submit(command),timeout=3)['status'],'cancelled')
        self.assertFalse(self.bridge.posts)

class RequestOnlyPin(unittest.TestCase):
    def test_pin_exact_no_policy_switch(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);base_watchdog.enforce_execution_policy(p,'request_only')
            base_watchdog.enforce_execution_policy(p,'request_only')
            for policy in ('standard','noncombat'):
                with self.assertRaises(ValueError):base_watchdog.enforce_execution_policy(p,policy)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);base_watchdog.enforce_execution_policy(p,'noncombat')
            with self.assertRaises(ValueError):base_watchdog.enforce_execution_policy(p,'request_only')
    def test_cli_and_public_contract(self):
        validate_schema({'version':1,'execution_mode':'request_only','reactions':'stop'},POLICY)
        a=parser().parse_args(['run-goal','--control','c','--journal','j','--file','f','--require-request-only'])
        self.assertTrue(a.require_request_only)

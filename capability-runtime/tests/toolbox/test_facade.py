"""Bounded deterministic façade tests. These are not native or live acceptance."""
from copy import deepcopy
from pathlib import Path
import tempfile
import threading
import types
import unittest
from mdc_toolbox import ToolboxService, CapabilityCatalog
from mdc_toolbox.contracts import API_VERSION, TOOL_SCHEMAS, validate_call, ToolboxError
from mdc_toolbox.serialization import serialize_outcome
from mdc_toolbox.jobs import JobStore

DEFINITION={'capability':'select_hotbar','capability_version':1,'group':'inventory','level':'primitive',
 'input_schema':{'type':'object','properties':{'slot':{'type':'integer','minimum':0,'maximum':8}},'required':['slot'],'additionalProperties':False},
 'result_schema':{'type':'object'},'observation_profile':'inventory','native_features':['capability_guard/1'],
 'bounds':{},'prerequisites':[],'cancel_granularity':'native_action_boundary','resume_supported':False,
 'implementation_status':'implemented','adapter_status':'implemented','known_limits':[],
 'source_fingerprints':[],'validation':{'offline':'unit_fake_only','live':'not_run'}}
PLUGIN=types.SimpleNamespace(definitions=lambda:[deepcopy(DEFINITION)])

class Backend:
    def __init__(self):
        self.calls=[];self.started=threading.Event();self.release=threading.Event();self.block=False;self.uncertain=False;self.clean=True;self.cancel_count=0
    def describe(self):
        return {'available':True,'private_singleplayer':True,'session_ref':'session_1','context_ref':'context_1',
         'supported_capabilities':['select_hotbar'],'native_features':['capability_guard/1'],
         'supported_budget_metrics':['max_actions','max_observations','reflex_reserve_actions','cleanup_reserve_actions'],
         'cancellation_supported':True,'supported_policies':{'reactions':['stop']}}
    def observe(self,profile,selectors,bounds):
        self.calls.append(('observe',profile));return {'facts':{},'coverage':{'status':'complete'},'source_clock':{'tick':10}}
    def execute(self,capability,arguments,context):
        self.calls.append(('execute',capability));self.context=context
        context['emit']('owner_context',{'owner_context':{'owner_id':'owner_1','original_request_ids':['native_1']}})
        self.started.set()
        if self.block:self.release.wait(3)
        if self.uncertain:raise TimeoutError('lost acknowledgement')
        return {'state':'succeeded','effect_certainty':'known','cleanup_certainty':'confirmed' if self.clean else 'unknown',
         'result':{'status':'succeeded','slot':arguments['slot']},'request_ids':['native_1'],'evidence':{'semantic_goal':True}}
    def cancel_exact(self,context,cancel_id):
        self.cancel_count+=1;self.calls.append(('cancel',deepcopy(context)));self.release.set()
        return {'state':'cancelled','effect_certainty':'known','cleanup_certainty':'confirmed','request_ids':['native_1'],'evidence':{'neutral':True,'lease_released':True}}
    def reconcile_original(self,context):
        self.calls.append(('reconcile',deepcopy(context)))
        return {'state':'unknown','effect_certainty':'unknown','cleanup_certainty':'unknown','request_ids':['native_1'],'evidence':{'receipt_only':True}}

class FacadeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.backend=Backend();self.service=self.make()
    def make(self,start=True):return ToolboxService(self.backend,self.tmp.name,catalog=CapabilityCatalog(modules=[PLUGIN]),start_workers=start)
    def tearDown(self):self.backend.release.set();self.service.close();self.tmp.cleanup()
    def submit(self,**updates):
        request={'api_version':API_VERSION,'operation':'submit','request_id':'request_1','session_ref':'session_1','expected_context_ref':'context_1',
         'capability':'select_hotbar','capability_version':1,'arguments':{'slot':0},'policy':{'version':1,'execution_mode':'noncombat'},
         'budgets':{'max_actions':2,'deadline_seconds':10},'wait_ms':1000}
        request.update(updates);return self.service.call('mdc_job',request)
    def op(self,operation,job_id,**fields):return self.service.call('mdc_job',{'api_version':API_VERSION,'operation':operation,'job_id':job_id,'session_ref':'session_1',**fields})
    def test_duplicate_stable_and_changed_wait_not_effect(self):
        a=self.submit();b=self.submit(wait_ms=0)
        self.assertEqual(a['job_id'],b['job_id']);self.assertEqual(len([c for c in self.backend.calls if c[0]=='execute']),1)
    def test_conflict_no_second_dispatch(self):
        self.submit();answer=self.submit(arguments={'slot':1});self.assertEqual(answer['error']['code'],'request_conflict')
    def test_bad_domain_arg_rejected_before_dispatch(self):
        answer=self.submit(arguments={'slot':True});self.assertEqual(answer['error']['code'],'invalid_request');self.assertFalse(self.backend.calls)
    def test_unknown_field_rejected(self):
        self.assertEqual(self.submit(endpoint='http://bad')['error']['code'],'invalid_request');self.assertFalse(self.backend.calls)
    def test_context_rejected(self):
        self.assertEqual(self.submit(expected_context_ref='other')['error']['code'],'context_changed');self.assertFalse(self.backend.calls)
    def test_status_pure(self):
        r=self.submit();before=len(self.backend.calls)
        for _ in range(3):self.op('status',r['job_id'])
        self.assertEqual(before,len(self.backend.calls))
    def test_unknown_never_replayed_and_blocks_competitor(self):
        self.backend.uncertain=True;r=self.submit();self.assertEqual(r['state'],'unknown')
        self.assertEqual(self.submit(request_id='replacement')['error']['code'],'owner_busy')
        self.submit();self.assertEqual(sum(c[0]=='execute' for c in self.backend.calls),1)
        self.op('reconcile',r['job_id']);self.assertEqual(sum(c[0]=='execute' for c in self.backend.calls),1)
    def test_known_goal_survives_unknown_cleanup(self):
        self.backend.clean=False;r=self.submit()
        self.assertEqual(r['state'],'unknown');self.assertEqual(r['effect_certainty'],'known');self.assertEqual(r['goal_result']['slot'],0)
    def test_cancel_before_dispatch(self):
        self.service.close();self.service=self.make(False);r=self.submit(wait_ms=0)
        out=self.op('cancel',r['job_id'],cancel_request_id='cancel_1')
        self.assertEqual(out['state'],'cancelled');self.assertEqual(out['effect_certainty'],'none_proven');self.assertEqual(self.backend.cancel_count,0)
    def test_cancel_running_exact_once(self):
        self.backend.block=True;r=self.submit(wait_ms=0);self.assertTrue(self.backend.started.wait(1))
        self.op('cancel',r['job_id'],cancel_request_id='cancel_1',wait_ms=1000)
        self.op('cancel',r['job_id'],cancel_request_id='cancel_1')
        self.assertEqual(self.backend.cancel_count,1)
        self.assertEqual([c for c in self.backend.calls if c[0]=='cancel'][0][1]['owner_context']['original_request_ids'],['native_1'])
    def test_restart_unknown_no_resume(self):
        self.backend.uncertain=True;r=self.submit();self.service.close();self.service=self.make()
        out=self.op('status',r['job_id']);self.assertEqual(out['state'],'unknown')
        self.assertEqual(sum(c[0]=='execute' for c in self.backend.calls),1)
    def test_recovery_raw_accepted_is_frozen(self):
        self.service.close();store=JobStore(self.tmp.name)
        # Only the durable pre-dispatch state is simulated; no Runtime involved.
        store.create({'job_id':'recover','request_id':'recover','state':'accepted','dispatch_started':False,'event_cursor':0,
                      'effect_certainty':'none_proven','cleanup_certainty':'not_needed','request_ids':[]})
        store.close();store=JobStore(self.tmp.name)
        self.assertEqual(store.get(job_id='recover')['state'],'interrupted');store.close()
        self.service=self.make()
    def test_catalog_keeps49_and_truthful_absent(self):
        r=self.service.call('mdc_catalog',{'api_version':API_VERSION,'limit':128})
        self.assertEqual(r['baseline_capability_count'],49);self.assertEqual(r['total'],49)
        self.assertFalse(next(c for c in r['capabilities'] if c['capability']=='end_battle')['runtime_available'])
    def test_plan_optional_no_dispatch(self):
        r=self.service.call('mdc_plan',{'api_version':API_VERSION,'capability':'select_hotbar','capability_version':1,'arguments':{'slot':0}})
        self.assertFalse(r['executable_authority']);self.assertEqual(r['status'],'preview_unsupported');self.assertFalse(self.backend.calls)
    def test_observation_does_not_invent_clock(self):
        r=self.service.call('mdc_observe',{'api_version':API_VERSION,'session_ref':'session_1','profile':'inventory'})
        self.assertEqual(r['source_clock'],{'tick':10});self.assertFalse(r['executable_authority'])
    def test_journal_owner_exclusive(self):
        with self.assertRaises(ToolboxError):self.make()
    def test_unsupported_budget_and_policy_fail(self):
        self.assertEqual(self.submit(budgets={'max_actions':2,'deadline_seconds':3,'distance':100})['error']['code'],'invalid_request')
        self.assertEqual(self.submit(policy={'version':1,'execution_mode':'noncombat','reactions':'defend'})['error']['code'],'policy_violation')
    def test_default_cleanup_reserve_is_explicit(self):
        r=self.submit();self.assertEqual(r['budgets']['cleanup_reserve_actions'],1)
        self.assertEqual(r['budgets']['reflex_reserve_actions'],0);self.assertEqual(r['budgets']['max_observations'],1024)
    def test_no_mutation_without_cleanup_headroom(self):
        r=self.submit(budgets={'max_actions':1,'deadline_seconds':10})
        self.assertEqual(r['error']['code'],'budget_exhausted');self.assertFalse(self.backend.calls)
        r=self.submit(budgets={'max_actions':3,'deadline_seconds':10,'cleanup_reserve_actions':0})
        self.assertEqual(r['error']['code'],'budget_exhausted');self.assertFalse(self.backend.calls)
    def test_shutdown_uncertainty_is_reported_and_persisted(self):
        self.backend.uncertain=True;r=self.submit();stopped=self.service.shutdown()
        self.assertFalse(stopped['cleanup_confirmed']);self.assertIn(r['job_id'],stopped['unresolved_job_ids'])
        self.service=self.make();self.assertEqual(self.op('status',r['job_id'])['state'],'unknown')
    def test_compact_outcome_hides_private_observation(self):
        from dataclasses import dataclass
        @dataclass
        class Outcome:
            status:str='succeeded'
            reason:str='verified'
            request_ids:tuple=('r',)
            evidence:object=None
            last_observation:object=None
        value=serialize_outcome(Outcome(evidence={'count':1},last_observation=object()))
        self.assertEqual(set(value),{'status','reason','request_ids','evidence','server_confirmed'})
    def test_invalid_tool_name_is_typed(self):
        r=self.service.call([],{});self.assertEqual(r['error']['code'],'invalid_request')
    def test_schema_has_four_plain_object_top_levels(self):
        self.assertEqual(len(TOOL_SCHEMAS),4)
        self.assertTrue(all(s['type']=='object' and s['additionalProperties'] is False for s in TOOL_SCHEMAS.values()))

if __name__=='__main__':unittest.main()

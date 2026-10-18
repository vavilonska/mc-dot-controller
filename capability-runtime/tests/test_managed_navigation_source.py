"""Real owner-chain regressions for one original authoritative managed-start read."""
from copy import deepcopy
from unittest.mock import patch
import unittest
import test_managed_navigation_owner as managed
from mdc_skills.core import SkillError
from mdc_skills.managed_navigation import _source,_start_binding
from types import SimpleNamespace

class ManagedSourceTests(unittest.TestCase):
    setUp=managed.ManagedOwnerTests.setUp
    tearDown=managed.ManagedOwnerTests.tearDown
    submit=managed.ManagedOwnerTests.submit
    finish=managed.ManagedOwnerTests.finish
    until=managed.ManagedOwnerTests.until

    def records(self):return list(self.runtime._journal['records'].values())

    def test_stale_published_cache_is_replaced_by_one_owned_read(self):
        original=self.runtime._session
        def cached(*a,**kw):
            value=deepcopy(original(*a,**kw));source=value.get('managed_navigation_source')
            if source:source.update(source_tick=0,source_nano='1')
            return value
        with patch.object(self.runtime,'_session',cached):result=self.finish(self.submit())
        self.assertEqual(result['state'],'succeeded',result)
        reads=[r for r in self.records() if r['kind']=='observation']
        starts=[r for r in self.records() if r['kind']=='managed_navigation_control' and r['command']['operation']=='start']
        self.assertEqual(len(reads),1);self.assertEqual(len(starts),1)
        read,start=reads[0],starts[0]
        self.assertEqual(read['command']['_capability_owner_id'],start['command']['control_owner']['owner_id'])
        self.assertEqual(start['before_tick'],self.bridge.route_calls[0][2]['source_tick'])
        self.assertNotEqual(start['command']['source'],{'source_tick':0,'source_nano':'1'})
        self.assertEqual(len([r for r in self.records() if r['kind']=='capability_acquire']),1)
        self.assertEqual([r[1] for r in self.bridge.route_calls].count('start'),1)

    def test_failed_owned_read_never_sends_start(self):
        original=self.runtime.observe;calls=[]
        def fail_once(*a,**kw):
            calls.append(1)
            if len(calls)==1:raise SkillError('test_owned_source_read_failed')
            return original(*a,**kw)
        with patch.object(self.runtime,'observe',fail_once):result=self.finish(self.submit())
        self.assertEqual(result['state'],'blocked',result)
        self.assertEqual(result['effect_certainty'],'none_proven');self.assertEqual(self.bridge.route_calls,[])

    def test_changed_observation_bytes_never_send_start(self):
        original=self.runtime.observe;calls=[]
        def changed(*a,**kw):
            value=original(*a,**kw);calls.append(1)
            if len(calls)==1:value.state['external_controller']['source_nano']='1'
            return value
        with patch.object(self.runtime,'observe',changed):result=self.finish(self.submit())
        self.assertEqual(result['state'],'blocked',result)
        self.assertEqual(result['effect_certainty'],'none_proven');self.assertEqual(self.bridge.route_calls,[])

    def test_final_reservation_delay_blocks_before_dispatch(self):
        original=self.runtime._reserve;clock=self.runtime.clock;offset=[0]
        def reserve(*a,**kw):
            record=original(*a,**kw)
            if record['kind']=='managed_navigation_control':offset[0]=1
            return record
        with patch.object(self.runtime,'clock',lambda:clock()+offset[0]),patch.object(self.runtime,'_reserve',reserve):
            result=self.finish(self.submit())
        self.assertEqual(result['state'],'blocked',result);self.assertEqual(result['effect_certainty'],'none_proven')
        self.assertEqual(self.bridge.route_calls,[])
        record=next(r for r in self.records() if r['kind']=='managed_navigation_control')
        self.assertEqual(record['evidence']['submission_outcome'],'stopped_before_dispatch')

    def test_final_exchange_age_guard_restores_known_unsubmitted_certainty(self):
        original=self.runtime._exchange;clock=self.runtime.clock;offset=[0]
        def exchange(record,**kw):
            if record['kind']=='managed_navigation_control':offset[0]=1
            return original(record,**kw)
        with patch.object(self.runtime,'clock',lambda:clock()+offset[0]),patch.object(self.runtime,'_exchange',exchange):
            result=self.finish(self.submit())
        self.assertEqual(result['state'],'blocked',result);self.assertEqual(result['effect_certainty'],'none_proven')
        self.assertEqual(self.bridge.route_calls,[])

    def test_unknown_owned_read_is_retained_without_read_or_start_retry(self):
        original=self.runtime._exchange;calls=[]
        def exchange(record,**kw):
            if record['kind']=='observation':
                calls.append(record['request_id']);self.runtime._unknown(record,'test_original_read_unknown')
            return original(record,**kw)
        with patch.object(self.runtime,'_exchange',exchange):
            first=self.submit();result=self.finish(first)
            self.assertEqual(result['state'],'unknown',result)
            self.assertIn('error',self.submit('second-route'))
        self.assertEqual(self.runtime.pending_request_id,calls[0]);self.assertEqual(len(calls),1)
        self.assertEqual(self.bridge.route_calls,[])

    def test_start_rejects_source_owner_epoch_or_context_rebinding(self):
        self.runtime.required_execution_policy='request_only'
        before=self.runtime.observe();context=deepcopy(self.runtime._lease_info['context'])
        owner=self.runtime.owner_context();control=SimpleNamespace(job_id='original_job')
        binding={'control_owner':{k:owner[k] for k in ('owner_id','owner_generation')}|{'job_id':control.job_id},
            'expected_context':context,'source':_source(self.runtime,before,context)}
        session=self.runtime._session()
        _start_binding(self.runtime,control,binding,before,session)
        cases=[]
        bad=deepcopy(binding);bad['source']['source_nano']='1';cases.append((bad,session))
        bad=deepcopy(binding);bad['source']['source_tick']+=1;cases.append((bad,session))
        bad=deepcopy(binding);bad['control_owner']['owner_generation']+=1;cases.append((bad,session))
        bad=deepcopy(binding);bad['control_owner']['job_id']='foreign_job';cases.append((bad,session))
        bad=deepcopy(binding);bad['expected_context']['world_generation']='foreign_world';cases.append((bad,session))
        cases.append((binding,{**session,'defense_epoch':session['defense_epoch']+1}))
        for index,(bad,current) in enumerate(cases):
            with self.subTest(index=index),self.assertRaises(SkillError):
                _start_binding(self.runtime,control,bad,before,current)
        with self.assertRaisesRegex(SkillError,'owned_source_required'):
            _start_binding(self.runtime,control,binding,None,session)

    def test_closed_source_proof_rejects_contradiction_even_with_idle_flag(self):
        with self.runtime._mutex:
            self.runtime.required_execution_policy='request_only'
            before=self.runtime.observe();context=deepcopy(self.runtime._lease_info['context'])
            # Exercise the proof validator independently of Runtime's fingerprint.
            bad=deepcopy(before);bad.state['external_controller']['facts']['planning']=True
            with patch.object(self.runtime,'_fresh',lambda x:None),self.assertRaisesRegex(SkillError,'source_proof_invalid'):
                _source(self.runtime,bad,context)
            with patch.object(self.runtime,'_fresh',lambda x:None),patch.object(self.runtime,'clock',lambda:before.captured_at+.750001),self.assertRaisesRegex(SkillError,'source_acquisition_stale'):
                _source(self.runtime,before,context)
            with patch.object(self.runtime,'_fresh',lambda x:None),patch.object(self.runtime,'clock',lambda:before.captured_at+.75):
                self.assertEqual(_source(self.runtime,before,context)['source_tick'],before.tick)

if __name__=='__main__':unittest.main()

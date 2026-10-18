"""Real Runtime/gateway/Resident owner chain; only the native endpoint is modeled."""
from copy import deepcopy
from unittest.mock import patch
import unittest
import test_attached_fall_owner_chain as attached
from resident_controller import fall_rescue_adjudication_wire as wire
from resident_controller.transport import BridgeError

class AdjudicationEndpointMixin:
    def __init__(self):
        super().__init__();self.adjudication_calls=[];self.adjudications={};self.arbiter_revision=8
        self.lose_adjudication=False;self.neutral_proven=True
    def view(self):
        return {'adjudication_schema_version':1,'arbiter_revision':self.arbiter_revision,
            'current_neutral_context_proven':self.neutral_proven,'native_status':deepcopy(self.fall)}
    def request(self,method,path,body=None):
        if path.startswith(wire.ROOT):
            self.adjudication_calls.append((method,path,deepcopy(body)))
            if path==wire.ROOT+'/prepare':return {'protocol':'mineclient-bridge','schema_version':2,**self.view()}
            if method=='POST':
                wire.native_request(body);identity=body['adjudication_id']
                if identity in self.adjudications:raise BridgeError('already_applied_read_original_id')
                if not self.neutral_proven:raise BridgeError('neutral_unproven')
                self.arbiter_revision+=1
                self.fall.update(status='disarmed',reason='operator_adjudicated_original_effects_unknown',
                    automation_blocked=False,unknown_outcome_quarantined=False)
                p={'adjudication_schema_version':1,'adjudication_id':identity,'status':'authority_released_original_unknown',
                    **{k:body[k] for k in ('arm_id','owner_id','episode_id','original_action_id','original_receipt_sha256')},
                    **{k:body['expected_'+k] for k in ('action_session','world_generation','player_uuid')},
                    'arbiter_revision_before':body['expected_arbiter_revision'],'arbiter_revision_after':self.arbiter_revision,
                    'acknowledgment':wire.ACK,'original_effects':'unknown','input_neutral_observed':True,'rescue_ended':True,
                    'authority_released':True,'no_auto_resume':True,'physical_safety_guaranteed':False}
                self.adjudications[identity]=p
                if self.lose_adjudication:raise BridgeError('lost_native_adjudication_reply',uncertain=True)
            else:identity=path.split('=')[1]
            return {'protocol':'mineclient-bridge','schema_version':2,'adjudication_schema_version':1,'receipt':deepcopy(self.adjudications.get(identity,{})),'inspection':self.view()}
        return super().request(method,path,body)

class Endpoint(AdjudicationEndpointMixin,attached.Endpoint):pass

class AdjudicationTests(attached.AttachedChainTests):
    def setUp(self):
        with patch.object(attached,'Endpoint',Endpoint):super().setUp()
    def unknown(self):
        self.bridge.rescue_mode='confirmed';r=self.finish(self.submit());self.assertEqual(r['state'],'unknown',r)
        self.until(lambda:not self.service._workers[r['job_id']].is_alive())
        return r
    def adjudicate(self,r,operation='adjudicate',sha=None):
        prep=self.service.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'adjudication_prepare',
            'job_id':r['job_id'],'session_ref':r['session_ref']})
        self.assertTrue(prep.get('adjudication',{}).get('eligible'),prep)
        self.selected=prep['adjudication']['selector']
        args={'api_version':'mdc.toolbox/1','operation':operation,'job_id':r['job_id'],'session_ref':r['session_ref'],
            'adjudication_request_id':'adjudication-one','original_receipt_sha256':sha or self.selected['original_receipt_sha256'],
            'acknowledgment':wire.ACK}
        self.ack_args=args
        return self.service.call('mdc_job',args)
    def test_confirmed_rescue_explicit_ack_keeps_original_unknown(self):
        r=self.unknown();old=deepcopy(self.runtime._journal['records'][self.runtime.pending_request_id]);result=self.adjudicate(r)
        self.assertTrue(result['adjudication'].get('authority_released'),result)
        self.assertEqual(result['state'],'unknown');self.assertEqual(result['effect_certainty'],'unknown')
        self.assertIsNone(self.runtime.pending_request_id);self.assertIsNone(self.dog.capability_lease)
        self.assertTrue(self.dog.explicit_after_adjudication);self.assertFalse(self.resident.paused)
        kept=self.runtime._journal['records'][old['request_id']]
        self.assertEqual(kept['status'],'unknown');self.assertEqual(kept['receipt_ref'],old['receipt_ref'])
        self.assertEqual(sum(m=='POST' for m,p,b in self.bridge.adjudication_calls),1)
    def test_ack_allows_separate_new_job_without_replaying_original(self):
        r=self.unknown();result=self.adjudicate(r);self.assertTrue(result['adjudication'].get('authority_released'),result)
        self.bridge.rescue_mode='none';self.bridge.rescue_polls=0
        self.until(lambda:self.client.session().get('capability_context')==self.selected['expected_context'])
        new=deepcopy(self.service.store.get(job_id=r['job_id'])['intent']);new['request_id']='separate-new-job'
        new['expected_context_ref']=self.backend.describe()['context_ref']
        admitted=self.service.call('mdc_job',new);self.assertIn('job_id',admitted,admitted)
        done=self.finish(admitted);self.assertEqual(done['state'],'succeeded',done)
        self.assertEqual(self.service.store.get(job_id=r['job_id'])['state'],'unknown')
        self.assertEqual(len([p for p,b in self.bridge.posts if p=='/control/scoped-action']),2)
        duplicate=self.service.call('mdc_job',{**self.ack_args,'operation':'adjudication_status'})
        self.assertTrue(duplicate['adjudication']['authority_released']);self.assertEqual(sum(m=='POST' for m,p,b in self.bridge.adjudication_calls),1)

    def test_lost_native_response_reads_same_id_no_second_post(self):
        r=self.unknown();self.bridge.lose_adjudication=True;result=self.adjudicate(r)
        self.assertFalse(result['adjudication']['authority_released']);self.assertIsNotNone(self.dog.capability_lease)
        args={**self.ack_args,'operation':'adjudication_status'};result=self.service.call('mdc_job',args)
        self.assertTrue(result['adjudication'].get('authority_released'),result)
        self.assertEqual(sum(m=='POST' for m,p,b in self.bridge.adjudication_calls),1)
        self.assertTrue(any('/status?adjudication_id=adjudication-one' in p for m,p,b in self.bridge.adjudication_calls))
    def test_lost_gateway_response_recovers_original_control_read(self):
        r=self.unknown();real=self.client.wait;lost=[False]
        def wait(identity,timeout=30):
            value=real(identity,timeout=timeout)
            if value.get('gateway_authority_released') is True and not lost[0]:
                lost[0]=True;raise OSError('modeled_lost_gateway_response')
            return value
        with patch.object(self.client,'wait',side_effect=wait):result=self.adjudicate(r)
        self.assertFalse(result['adjudication']['authority_released'])
        result=self.service.call('mdc_job',{**self.ack_args,'operation':'adjudication_status'})
        self.assertTrue(result['adjudication']['authority_released'],result)
        self.assertEqual(sum(m=='POST' for m,p,b in self.bridge.adjudication_calls),1)
    def test_lost_backend_response_keeps_recoverable_same_id(self):
        r=self.unknown();real=self.backend.adjudicate_original;lost=[False]
        def reply(context,args):
            value=real(context,args)
            if value.get('authority_released') is True and not lost[0]:
                lost[0]=True;raise OSError('modeled_lost_backend_response')
            return value
        with patch.object(self.backend,'adjudicate_original',side_effect=reply):result=self.adjudicate(r)
        self.assertFalse(result['adjudication']['authority_released'])
        result=self.service.call('mdc_job',{**self.ack_args,'operation':'adjudication_status'})
        self.assertTrue(result['adjudication']['authority_released'],result)
        self.assertEqual(result['state'],'unknown');self.assertEqual(sum(m=='POST' for m,p,b in self.bridge.adjudication_calls),1)
    def test_partial_rescue_is_not_adjudication_v1_scope(self):
        self.bridge.rescue_mode='partial';r=self.finish(self.submit())
        self.until(lambda:not self.service._workers[r['job_id']].is_alive())
        prep=self.service.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'adjudication_prepare',
            'job_id':r['job_id'],'session_ref':r['session_ref']})
        self.assertFalse(prep['adjudication']['authority_released']);self.assertEqual(self.bridge.adjudication_calls,[])

    def test_non_neutral_never_posts_or_releases(self):
        r=self.unknown();self.bridge.neutral_proven=False;result=self.adjudicate(r)
        self.assertFalse(result['adjudication']['authority_released'])
        self.assertEqual(sum(m=='POST' for m,p,b in self.bridge.adjudication_calls),0)
        self.assertIsNotNone(self.dog.capability_lease);self.assertTrue(self.resident.paused)
    def test_proven_preparation_refusal_can_continue_first_write_same_id(self):
        r=self.unknown();self.bridge.neutral_proven=False;result=self.adjudicate(r)
        self.assertTrue(result['adjudication'].get('native_write_never_attempted'),result)
        self.assertEqual(sum(m=='POST' for m,p,b in self.bridge.adjudication_calls),0)
        status=self.service.call('mdc_job',{**self.ack_args,'operation':'adjudication_status'})
        self.assertTrue(status['adjudication']['native_write_never_attempted'])
        self.assertEqual(sum(m=='POST' for m,p,b in self.bridge.adjudication_calls),0)
        self.bridge.neutral_proven=True
        result=self.service.call('mdc_job',self.ack_args)
        self.assertTrue(result['adjudication']['authority_released'],result)
        self.assertEqual(sum(m=='POST' for m,p,b in self.bridge.adjudication_calls),1)

    def test_slow_gateway_persistence_cannot_release_stale_proof(self):
        import fall_rescue_adjudication as gateway
        import time
        r=self.unknown();real=gateway.save;delayed=[False]
        def save(dog):
            real(dog)
            if not delayed[0] and any(e.get('state')=='release_prepared' for e in dog._fall_adjudications.values()):
                delayed[0]=True;time.sleep(1.05)
        with patch.object(gateway,'save',side_effect=save):result=self.adjudicate(r)
        self.assertTrue(delayed[0]);self.assertFalse(result['adjudication']['authority_released'],result)
        self.assertIsNotNone(self.dog.capability_lease);self.assertIsNotNone(self.dog.owner)
        result=self.service.call('mdc_job',{**self.ack_args,'operation':'adjudication_status'})
        self.assertTrue(result['adjudication']['authority_released'],result)
        self.assertEqual(sum(m=='POST' for m,p,b in self.bridge.adjudication_calls),1)

    def test_gateway_persistence_callback_cannot_clear_replacement_owner(self):
        import fall_rescue_adjudication as gateway
        r=self.unknown();old=self.dog.owner;replacement=deepcopy(old);real=gateway.atomic_json;replaced=[False]
        def write(path,value):
            real(path,value)
            if path.name=='explicit-after-adjudication.json':
                self.dog.owner=replacement;replaced[0]=True
        with patch.object(gateway,'atomic_json',side_effect=write):result=self.adjudicate(r)
        self.assertTrue(replaced[0]);self.assertFalse(result['adjudication']['authority_released'],result)
        self.assertIs(self.dog.owner,replacement);self.assertIsNotNone(self.dog.capability_lease)
        self.assertEqual(sum(m=='POST' for m,p,b in self.bridge.adjudication_calls),1)
        self.dog.owner=old

    def test_wrong_gateway_epoch_never_releases(self):
        r=self.unknown();self.dog.defense_epoch+=1;result=self.adjudicate(r)
        self.assertFalse(result['adjudication']['authority_released']);self.assertEqual(self.bridge.adjudication_calls,[])
    def test_unrelated_resident_pause_never_releases(self):
        r=self.unknown();self.resident.reason='operator_pause';result=self.adjudicate(r)
        self.assertFalse(result['adjudication']['authority_released']);self.assertEqual(self.bridge.adjudication_calls,[])
    def test_different_adjudication_id_cannot_replace_unknown_attempt(self):
        r=self.unknown();self.bridge.lose_adjudication=True;self.adjudicate(r)
        result=self.service.call('mdc_job',{**self.ack_args,'adjudication_request_id':'new-id'})
        self.assertEqual(result['error']['code'],'request_conflict');self.assertEqual(sum(m=='POST' for m,p,b in self.bridge.adjudication_calls),1)
    def test_late_duplicate_does_not_release_replacement_owner(self):
        r=self.unknown();self.adjudicate(r)
        replacement={'context':{'job_id':'replacement'}};self.backend._active=replacement;self.backend._quarantined=True
        result=self.service.call('mdc_job',{**self.ack_args,'operation':'adjudication_status'})
        self.assertTrue(result['adjudication']['authority_released']);self.assertIs(self.backend._active,replacement)
        self.assertTrue(self.backend._quarantined)
        self.backend._active=None;self.backend._quarantined=False
    def test_post_ack_automatic_mutations_stay_suppressed(self):
        r=self.unknown();self.adjudicate(r);before=len(self.bridge.posts)
        self.dog.send('start_combat',{'op':'combat','target_uuid':attached.TARGET})
        self.assertEqual(len(self.bridge.posts),before);self.assertTrue(self.dog.explicit_after_adjudication)
        self.assertTrue((self.dog.capability_directory/'explicit-after-adjudication.json').exists())

    def test_wrong_digest_never_contacts_native(self):
        r=self.unknown();result=self.adjudicate(r,sha='a'*64)
        self.assertEqual(result['error']['code'],'invalid_request');self.assertEqual(self.bridge.adjudication_calls,[])
        self.assertNotIn('adjudication_claim',self.service.store.get(job_id=r['job_id']))
        result=self.adjudicate(r);self.assertTrue(result['adjudication']['authority_released'],result)

if __name__=='__main__':unittest.main()

"""Actual mailbox/owner chain, synthetic native endpoint. Never contacts a game."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import test_cancel_terminal_race as prior
from resident_controller.queued_cancel_terminal import REASON

class QueuedContainerRaceTests(prior.PublicContainerRaceTests):
    # Do not inherit/rerun the prior race test as new evidence.
    test_second_click_terminal_then_cancel_does_not_claim_transfer_success=None
    def race(self,when='after',corrupt=None,recover=False):
        read=self.dog.q.result;native=self.bridge.request;commands=self.resident.read_commands
        injected=[];queued=[];originals=[]
        def request(method,path,body=None):
            value=native(method,path,body)
            if when=='before' and path=='/control/scoped-action' and len(self.bridge.model.commands)==2 and not injected:
                injected.append('before_original_terminal');self.runtime._job_control.request_cancel('queued_cancel')
            return value
        def result(rid):
            value=read(rid)
            if (value and value.get('status')=='succeeded' and self.dog.owner and rid==self.dog.owner.get('request_id')
                    and self.dog.owner.get('capability_op')=='action' and len(self.bridge.model.commands)==2):
                if not originals:originals.append(rid)
                if not injected:
                    injected.append('after_original_terminal');self.runtime._job_control.request_cancel('queued_cancel')
                control=(self.dog.capability_lease or {}).get('cancel_control')
                if not control:return None
                if not queued:queued.append(deepcopy(control))
            if value and 'exact_cancel_no_native_dispatch' in value and corrupt:
                if corrupt=='missing':return None
                if corrupt=='old':value.pop('exact_cancel_no_native_dispatch');value.update(status='failed',reason='exact_cancel_target_not_active')
                elif corrupt=='hash':value['exact_cancel_no_native_dispatch']['original_result_sha256']='0'*64
                elif corrupt=='attempted':value['exact_cancel_no_native_dispatch']['native_cancel_dispatched']=True
            return value
        def read_commands():
            # A queued control may wait one recipe turn: complete the original first.
            if self.resident.active and injected:
                for path in (self.resident.root/'inbox').glob('*.json'):
                    if json.loads(path.read_text()).get('op')=='capability_cancel_exact':return
            return commands()
        if corrupt == 'runtime_hash':
            public_read=self.client.result
            def public_result(rid):
                value=public_read(rid)
                if value and 'exact_queued_cancel_terminal' in value:
                    value['exact_queued_cancel_terminal']['original_result_sha256']='0'*64
                return value
            self.client.result=public_result
        self.bridge.request=request;self.dog.q.result=result;self.resident.read_commands=read_commands
        args={'container_id':7,'menu_state_id':11,'source_slot':54,'destination_slot':0,'quantity':3}
        first=self.submit('container_deposit',args,'queued-deposit');value=self.finish(first)
        self.assertEqual(len(injected),1);self.assertEqual(len(originals),1);self.assertEqual(len(queued),1)
        self.assertEqual(len(self.bridge.model.commands),2);self.assertFalse([p for p,b in self.bridge.posts if p=='/control/action/cancel'])
        record=self.runtime._journal['records'][self.dog.capability_lease['last_mutation']['intent_id'] if self.dog.capability_lease else next(k for k,v in self.runtime._journal['records'].items() if v.get('cancel_control'))]
        self.assertIn('receipt_ref',record)
        if corrupt:
            self.assertEqual(value['state'],'unknown',value);self.assertIsNotNone(self.client.session()['capability_lease'])
        else:
            self.assertEqual(value['state'],'cancelled',value);self.assertEqual(value['cleanup_certainty'],'confirmed',value)
            self.assertEqual(value['effect_certainty'],'known');self.assertIsNone(self.client.session()['capability_lease'])
            self.assertEqual(record['cancel_control']['receipt']['reason'],REASON)
            self.assertEqual(value['result']['evidence']['semantic_verification'],'incomplete')
            again=self.submit('container_deposit',args,'queued-deposit');self.assertEqual(again['job_id'],first['job_id']);self.assertEqual(len(self.bridge.model.commands),2)
        if recover:
            evidence=value['result']['evidence']
            self.assertEqual(evidence['completed_clicks'],1)
            self.assertEqual(evidence['stages'][1]['evidence']['semantic_verification'],'incomplete')
            self.assertNotIn('total_conserved',evidence);self.assertNotIn('cursor_empty',evidence)
            self.assertEqual(evidence['last_observed_carried']['count'],16)
            self.assertEqual(self.bridge.model.current.state['menu']['carried']['count'],15)
            self.assertEqual(self.bridge.model.current.state['menu']['slots'][0]['item']['count'],1)
            # Stop race-injection hooks before separately requested fresh work.
            self.bridge.request=native;self.dog.q.result=read;self.resident.read_commands=commands
            fresh=self.service.call('mdc_observe',{'api_version':'mdc.toolbox/1','request_id':'fresh-after-queued-cancel',
                'session_ref':first['session_ref'],'profile':'menu','bounds':{'radius':1}})
            self.assertEqual(fresh['job_state'],'succeeded',fresh);self.assertEqual(fresh['cleanup_certainty'],'confirmed')
            self.assertEqual(fresh['state']['menu']['carried']['count'],15);self.assertEqual(len(self.bridge.model.commands),2)
            recovered=self.finish(self.submit('recover_cursor',prior.recovery_model.cursor_args(self.bridge.model.current),'recover-after-queued-cancel'))
            self.assertEqual(recovered['state'],'succeeded',recovered);self.assertEqual(recovered['cleanup_certainty'],'confirmed')
            self.assertTrue(self.bridge.model.current.state['menu']['carried']['empty']);self.assertEqual(len(self.bridge.model.commands),3)
        return value
    def test_separate_fresh_menu_and_recovery_after_confirmed_cleanup(self):self.race(recover=True)
    def test_runtime_independently_rejects_public_original_hash(self):self.race(corrupt='runtime_hash')
    def test_complete_before_public_cancel_then_queued(self):self.race('after')
    def test_complete_after_public_cancel_before_resident_consumes_queue(self):self.race('before')
    def test_old_target_missing_is_still_unknown(self):self.race(corrupt='old')
    def test_malformed_terminal_hash_is_unknown(self):self.race(corrupt='hash')
    def test_possibly_posted_cancel_is_unknown(self):self.race(corrupt='attempted')
    def test_lost_proof_is_unknown_without_replay(self):self.race(corrupt='missing')


import tempfile
import uuid
from types import SimpleNamespace
from resident_controller.controller import Resident
from resident_controller.queued_cancel_terminal import attempt, validate_resident, validate, public_proof
from resident_controller.cancel_terminal import normalized
from resident_controller.ipc import read_json

class NoBridge:
    base_url='http://127.0.0.1:1'
    def __init__(self):self.calls=[]
    def request(self,*args,**kwargs):self.calls.append((args,kwargs));raise AssertionError('proof may not call native endpoint')

class QueuedProofTests(unittest.TestCase):
    def fixture(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);root=Path(temp.name)
        (root/'watchdog').mkdir();dog,c,_=prior.setup_gateway(root/'watchdog');ctx=dog.capability_lease['context'];bridge=NoBridge()
        resident=Resident(bridge,root/'resident');resident.session_id=prior.RESIDENT;resident.initialized=True
        resident.bridge_identity={'action_session':ctx['action_session'],'run_id':'same-run','process_id':10}
        native=deepcopy(dog.q.original['result']['action']);native['result']['scoped_native_preflight']={
            'version':'scoped-native-preflight/1','owner_id':prior.OWNER,'defense_epoch':0,'context':deepcopy(ctx),
            'action_id':native['action_id'],'action_session':ctx['action_session']}
        command={'op':'action','action':'click_slot','request_id':prior.QID,'session_id':prior.RESIDENT,
            'submitted_at':98.,'capability_guard':{},'scoped_native_preflight':{'owner_id':prior.OWNER,'defense_epoch':0},
            **{'expected_'+k:v for k,v in ctx.items()}}
        task=SimpleNamespace(command=command,step_number=1,capability_cancel_attempted=False,capability_unknown=False,
            fall_rescue=None,encounter_request=None,last_action_result=deepcopy(native))
        resident.active=task;resident.end_active('succeeded',result={'action':native})
        body={'op':'capability_cancel_exact','expected_request_id':prior.QID,'expected_resident_session':prior.RESIDENT,
            'expected_action_session':ctx['action_session'],'expected_action_id':native['action_id'],
            'terminal_proof_binding':{'schema_version':1,'request_id':prior.CANCEL,'gateway_session':dog.session_id,
                'command':c,'context':deepcopy(ctx)}}
        cancel={**deepcopy(body),'request_id':'cancel_queue','session_id':prior.RESIDENT,'submitted_at':100.}
        return dog,c,resident,task,body,cancel,bridge
    def ready(self):
        dog,c,resident,task,body,cancel,bridge=self.fixture();resident.capability_cancel_exact(cancel)
        receipt=read_json(resident.root/'results/cancel_queue.json');original=read_json(resident.root/'results'/(prior.QID+'.json'),2*1024*1024)
        dog.q.original=original
        dog.capability_lease['cancel_control']={'intent_id':prior.CANCEL,'queue_request_id':'cancel_queue',
            'original_intent_id':prior.RID,'state':'submitted','command':deepcopy(c),'resident_command':deepcopy(body),
            'gateway_session':dog.session_id}
        return dog,c,resident,task,body,cancel,bridge,receipt,original
    def test_same_original_resident_proof_no_native_calls_and_duplicate_no_reentry(self):
        dog,c,r,t,b,cmd,bridge,receipt,original=self.ready()
        self.assertTrue(validate_resident(receipt,b,'cancel_queue',original=original));self.assertEqual(bridge.calls,[])
        again={**cmd,'request_id':'second_cancel'}
        with self.assertRaisesRegex(ValueError,'target_not_active'):r.capability_cancel_exact(again)
        self.assertEqual(read_json(r.root/'results/cancel_queue.json'),receipt);self.assertEqual(bridge.calls,[])
    def test_original_missing_or_unsafe_and_prior_attempt_never_proven(self):
        for fault in ('missing','uncertain','release','quarantine','automation','context','native_id','already_cancelled','attempted'):
            with self.subTest(fault=fault):
                dog,c,r,t,b,cmd,bridge=self.fixture();path=r.root/'results'/(prior.QID+'.json');o=read_json(path,2*1024*1024);n=o['result']['action']
                if fault=='missing':path.unlink()
                elif fault=='attempted':t.capability_cancel_attempted=True
                else:
                    if fault=='uncertain':o['status']='uncertain'
                    elif fault=='release':n['result']['input_release_confirmed']=False
                    elif fault=='quarantine':n['result']['unknown_outcome_quarantined']=True
                    elif fault=='automation':n['result']['automation_blocked']=True
                    elif fault=='context':n['result']['scoped_native_preflight']['context']['dimension']='other'
                    elif fault=='native_id':n['action_id']='f'*32
                    elif fault=='already_cancelled':o['exact_cancel']={}
                    path.write_text(json.dumps(o))
                self.assertFalse(attempt(r,cmd));self.assertEqual(bridge.calls,[])
                self.assertFalse((r.root/'results/cancel_queue.json').exists())
    def test_resident_after_receipt_read_replacement_and_stop_fences(self):
        for fault in ('active','pending','token','session','identity','task_command','native','attempted','paused','stopped','cancel_command'):
            with self.subTest(fault=fault):
                dog,c,r,t,b,cmd,bridge=self.fixture();old=read_json
                replacement=SimpleNamespace(command={'request_id':'replacement'})
                def reading(*args,**kwargs):
                    value=old(*args,**kwargs)
                    if fault=='active':r.active=replacement
                    elif fault=='pending':r.pending.append({'request_id':'foreign'})
                    elif fault=='token':r._capability_terminal_candidate=dict(r._capability_terminal_candidate)
                    elif fault=='session':r.session_id='replacement'
                    elif fault=='identity':r.bridge_identity['action_session']='other'
                    elif fault=='task_command':t.command['expected_dimension']='other'
                    elif fault=='native':t.last_action_result['status']='running'
                    elif fault=='attempted':t.capability_cancel_attempted=True
                    elif fault=='paused':r.paused=True
                    elif fault=='stopped':r.running=False
                    else:cmd['expected_action_session']='other'
                    return value
                with patch('resident_controller.queued_cancel_terminal.read_json',reading):self.assertFalse(attempt(r,cmd))
                self.assertEqual(bridge.calls,[]);self.assertFalse((r.root/'results/cancel_queue.json').exists())
                if fault=='active':self.assertIs(r.active,replacement)
    def test_cached_original_without_current_completion_marker_has_no_authority(self):
        dog,c,r,t,b,cmd,bridge=self.fixture()
        with self.assertRaisesRegex(ValueError,'reserved_reconciliation_request_id'):
            r.command({'op':'action','request_id':'reconcile_other'})
        self.assertIsNone(r._capability_terminal_candidate)
        self.assertTrue((r.root/'results'/(prior.QID+'.json')).exists())
        self.assertFalse(attempt(r,cmd));self.assertEqual(bridge.calls,[])
        r.session_id=str(uuid.uuid4())
        with self.assertRaisesRegex(ValueError,'identity_mismatch'):r.capability_cancel_exact(cmd)
        self.assertEqual(bridge.calls,[])
    def test_closed_native_proof_negatives(self):
        dog,c,r,t,b,cmd,bridge,good,original=self.ready()
        for change in [lambda x:x.update(status='uncertain'),lambda x:x.update(request_id='other'),
            lambda x:x.update(extra=True),lambda x:x.update(finished_at=True),
            lambda x:x['exact_cancel_no_native_dispatch'].update(schema_version=True),
            lambda x:x['exact_cancel_no_native_dispatch'].update(original_result_sha256='0'*64),
            lambda x:x['exact_cancel_no_native_dispatch'].update(native_cancel_dispatched=True),
            lambda x:x['exact_cancel_no_native_dispatch'].update(input_release_confirmed=False),
            lambda x:x['exact_cancel_no_native_dispatch']['resident_command']['terminal_proof_binding']['command'].update(expected_defense_epoch=1)]:
            bad=deepcopy(good);change(bad);self.assertFalse(validate_resident(bad,b,'cancel_queue',original=original))
    def test_gateway_exact_proof_no_queue_write_and_normalized_runtime_binding(self):
        dog,c,r,t,b,cmd,bridge,proof,original=self.ready();lease=dog.capability_lease
        dog.capability_cancel_queued_terminal(lease,lease['cancel_control'],proof);a=prior.ack(dog)
        value=normalized(original,prior.RID,dog.session_id,prior.QID)
        self.assertTrue(validate(a,c,prior.CANCEL,dog.session_id,original=value,context=lease['context']))
        self.assertEqual(dog.q.writes,[]);self.assertIs(dog.capability_lease,lease);self.assertEqual(lease['state'],'active')
        for change in [lambda x:x.update(queue_request_id='other'),lambda x:x.update(queue_session_id='other'),
            lambda x:x['exact_queued_cancel_terminal'].update(schema_version=True),
            lambda x:x['exact_queued_cancel_terminal'].update(original_result_sha256='0'*64),
            lambda x:x['exact_queued_cancel_terminal'].update(native_cancel_dispatched=True)]:
            bad=deepcopy(a);change(bad);self.assertFalse(validate(bad,c,prior.CANCEL,dog.session_id,original=value))
    def test_gateway_after_io_and_persistence_current_authority(self):
        for fault in ('owner','lease','last','session','epoch','context','deadline','heartbeat','cancel','rpc','checkpoint_owner','checkpoint_lease','checkpoint_error','last_clock'):
            with self.subTest(fault=fault):
                dog,c,r,t,b,cmd,bridge,proof,original=self.ready();lease=dog.capability_lease;cancel=lease['cancel_control']
                replacement={'id':'foreign','capability_owner':'f'*32}
                def change():
                    if fault=='owner':dog.owner=replacement
                    elif fault=='lease':dog.capability_lease=deepcopy(lease)
                    elif fault=='last':lease['last_mutation']['intent_id']='other'
                    elif fault=='session':dog.session_id='other'
                    elif fault=='epoch':dog.defense_epoch+=1
                    elif fault=='context':dog.latest['state']['world']['dimension']='other'
                    elif fault in ('deadline','heartbeat'):lease[fault]=99.
                    elif fault=='cancel':lease['cancel_control']=deepcopy(cancel)
                    elif fault=='rpc':dog.rpc={'id':'foreign'}
                dog.q.hook=change
                if fault.startswith('checkpoint'):
                    def checkpoint(value):
                        if fault=='checkpoint_owner':dog.owner=replacement
                        elif fault=='checkpoint_lease':dog.capability_lease=deepcopy(lease)
                        else:raise OSError('injected')
                    dog.capability_checkpoint=checkpoint
                if fault=='last_clock':
                    calls=[]
                    def clock():
                        calls.append(1)
                        if len(calls)==3:dog.owner=replacement
                        return 100.
                    dog.clock=clock
                dog.capability_cancel_queued_terminal(lease,cancel,proof)
                self.assertEqual(prior.ack(dog)['status'],'uncertain');self.assertEqual(dog.q.writes,[])
                if fault in ('owner','checkpoint_owner','last_clock'):self.assertIs(dog.owner,replacement)


    def test_public_client_closed_proof_wrapper(self):
        from intent_client import IntentClient
        dog,c,r,t,b,cmd,bridge,proof,original=self.ready();lease=dog.capability_lease
        dog.capability_cancel_queued_terminal(lease,lease['cancel_control'],proof)
        result=deepcopy(dog.completed[-1]);directory=r.root.parent/'public';(directory/'results').mkdir(parents=True)
        path=directory/'results'/(prior.CANCEL+'.json');client=IntentClient(directory)
        path.write_text(json.dumps(result));self.assertEqual(client.result(prior.CANCEL)['reason'],REASON)
        for fault in ('wrapper','schema','queue','proof_stage'):
            bad=deepcopy(result)
            if fault=='wrapper':bad['intent_id']='other'
            elif fault=='queue':bad['queue_request_id']='other'
            elif fault=='schema':bad['result']['exact_queued_cancel_terminal']['schema_version']=True
            else:bad['result']['exact_queued_cancel_terminal']['resident_proof']['exact_cancel_no_native_dispatch']['stage']='after_post'
            path.write_text(json.dumps(bad))
            with self.assertRaises(ValueError):client.result(prior.CANCEL)

if __name__=='__main__':unittest.main()

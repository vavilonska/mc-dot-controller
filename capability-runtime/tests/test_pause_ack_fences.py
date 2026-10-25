from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest.mock import patch
import pause_acknowledgment as lane
from resident_controller import pause_acknowledgment as proof
from capability_ownership import CapabilityOwnership


def payload(tick=10,paused=True):
    return {'resident_policy':{'schema_version':1,'requires_handoff':False,'input_release_unconfirmed':False},
      'state':{'paused':paused,'screen_open':paused,'focused':True,'private_singleplayer':True,
        'world':{'world_generation':'world','dimension':'minecraft:overworld','game_time':tick,'integrated_server_instance':'33333333-3333-4333-8333-333333333333'},
        'player':{'uuid':'player','alive':True,'health':20,'dimension':'minecraft:overworld'},
        'client_action':{'action_session':'native','status':'idle'},'held_inputs':{'neutral':True}},
      'action':{'status':'idle'},'combat':{'active':False},'status':{'held_mappings':[]}}

class FenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        for n in ('inbox','working','results'):(self.root/n).mkdir()
        self.now=1.;self.d=SimpleNamespace(execution_policy='request_only',stop_requested=False,stopped=False,
            handoff_latched=False,input_release_latched=False,owner=None,capability_lease=None,started_target=None,rpc=None,
            armed=False,reason=proof.REASON,defense_epoch=1,session_id='watchdog',clock=lambda:self.now,latest=payload(),
            capability_directory=self.root,completed=[])
        self.d.capability_complete=lambda *a,**k:CapabilityOwnership.capability_complete(self.d,*a,**k)
        self.resident={'session_id':'resident','bridge_identity':{'action_session':'native'},'state':'ready','active_request_id':None,'pending':0,
            'resident_policy':deepcopy(self.d.latest['resident_policy'])}
        self.d.q=SimpleNamespace(session=lambda:deepcopy(self.resident))
        lane.observation(self.d,{'id':'origin','resident_session':'resident','resident_bridge':self.resident['bridge_identity'],'started':0.},
            {'status':'succeeded','request_id':'origin','session_id':'resident'})
        lane.remember(self.d,proof.REASON,True)
        self.assertTrue(lane.status(self.d)['eligible'])
        now=time.time();self.command={'op':proof.OP,'schema_version':1,'pause_ref':lane.status(self.d)['pause_ref'],
            'expected_defense_epoch':1,'acknowledgment':proof.ACK,'created_at':now,'expires_at':now+5}
    def tearDown(self):self.tmp.cleanup()
    def submit(self):lane.submit(self.d,'ack',self.command)
    def sample(self,rid,tick):
        self.now+=.1;self.d.latest=payload(tick,False)
        lane.observation(self.d,{'id':rid,'resident_session':'resident','resident_bridge':self.resident['bridge_identity'],'started':self.now},
            {'status':'succeeded','request_id':rid,'session_id':'resident'});lane.tick(self.d)
    def result(self):
        v=self.d.completed[-1];return {**v['result'],'request_id':v['intent_id'],'session_id':v['session_id'],'queue_request_id':v['queue_request_id']}
    def test_two_new_increasing_reads_rearm_without_input(self):
        self.submit();self.sample('one',11);self.assertFalse(self.d.armed);self.sample('two',12)
        self.assertTrue(self.d.armed);self.assertEqual(self.d.defense_epoch,2)
        self.assertTrue(proof.validate(self.result(),self.command,'ack','watchdog')['rearmed'])
    def test_no_ack_no_automatic_rearm(self):
        self.sample('one',11);self.sample('two',12);self.assertFalse(self.d.armed);self.assertEqual(self.d.completed,[])
    def test_repeated_tick_does_not_count(self):
        self.submit();self.sample('one',11);self.sample('two',11);self.assertFalse(self.d.armed)
        self.sample('three',12);self.assertTrue(self.d.armed)
    def test_request_must_start_after_ack(self):
        self.submit();self.d._pause_ack_sample['started']=0;lane.tick(self.d);self.assertEqual(self.d._pause_ack_pending['samples'],[])
    def test_pause_cause_and_uncertainty_exclusions(self):
        for field,value in [('owner',{}),('capability_lease',{}),('handoff_latched',True),('input_release_latched',True),
            ('started_target','mob'),('rpc',{'kind':'cancel'}),('_fall_rescue_owner',{}),('_external_navigation_owner',{}),
            ('_managed_navigation_owner',{}),('stop_requested',True),('stopped',True),('reason','unknown')]:
            with self.subTest(field=field):
                old=getattr(self.d,field,None);setattr(self.d,field,value)
                self.assertFalse(lane.status(self.d)['eligible']);setattr(self.d,field,old)
    def test_only_real_safe_pause_origin_is_recorded(self):
        for edit in (lambda d:setattr(d,'owner',{}),lambda d:d.latest['state']['player'].update(health=0),
            lambda d:d.latest['resident_policy'].update(requires_handoff=True),lambda d:d.latest['state'].update(paused=False)):
            saved=deepcopy(self.d.latest);edit(self.d);lane.remember(self.d,proof.REASON,True)
            self.assertIsNone(self.d._pause_ack_origin);self.d.latest=saved;self.d.owner=None
    def test_deadline_and_stale_ref_refuse(self):
        self.command['pause_ref']='0'*64;self.submit();self.assertFalse(self.d.armed)
        self.assertFalse(proof.validate(self.result(),self.command,'ack','watchdog')['rearmed'])
    def test_expiry_never_installs_authority(self):
        self.submit();self.now=20;lane.tick(self.d);self.assertFalse(self.d.armed);self.assertEqual(self.result()['status'],'failed')
    def test_context_or_server_replacement_refuses(self):
        for field in ('world_generation','integrated_server_instance'):
            with self.subTest(field=field):
                self.tmp.cleanup();self.setUp();self.submit();self.sample('one',11)
                self.d.latest=payload(12,False);self.d.latest['state']['world'][field]='replacement'
                self.now+=.1;lane.observation(self.d,{'id':'two','resident_session':'resident','resident_bridge':self.resident['bridge_identity'],'started':self.now},
                  {'status':'succeeded','request_id':'two','session_id':'resident'});lane.tick(self.d)
                self.assertFalse(self.d.armed);self.assertEqual(self.result()['status'],'failed')
    def test_post_read_replacement_stop_and_expiry_fail_closed(self):
        for mutate in (lambda d:setattr(d,'owner',{}),lambda d:setattr(d,'defense_epoch',2),lambda d:setattr(d,'stop_requested',True),
                       lambda d:setattr(d,'latest',deepcopy(d.latest)),lambda d:d.latest['state'].update(screen_open=True),
                       lambda d:d.latest['resident_policy'].update(requires_handoff=True),
                       lambda d:d.latest['state']['world'].update(game_time=999),
                       lambda d:d._pause_ack_sample.update(request_id='changed'),
                       lambda d:d._pause_ack_sample.update(started=0),
                       lambda d:d._pause_ack_sample.update(received=0),
                       lambda d:d._pause_ack_sample.update(resident_session='replacement'),
                       lambda d:d._pause_ack_sample['bridge_identity'].update(action_session='replacement'),
                       lambda d:d._pause_ack_pending['samples'][0].update(tick=0),lambda d:setattr(self,'now',20)):
            with self.subTest(mutate=mutate):
                self.tmp.cleanup();self.setUp();self.submit();self.sample('one',11)
                def session():mutate(self.d);return deepcopy(self.resident)
                self.d.q.session=session;self.sample('two',12);self.assertFalse(self.d.armed)
    def test_other_pending_command_and_resident_owner_refuse(self):
        self.submit();self.sample('one',11);(self.root/'inbox/other.json').write_text('{}');self.sample('two',12)
        self.assertFalse(self.d.armed);self.assertEqual(self.result()['status'],'failed')
    def test_strict_proof_rejects_boolean_numeric_and_identity_forgery(self):
        self.submit();self.sample('one',11);self.sample('two',12);r=self.result()
        for edit in (lambda v:v.update(request_id='other'),lambda v:v['pause_acknowledgment'].update(rearmed=1),
            lambda v:v['pause_acknowledgment']['samples'][1].update(tick=True),lambda v:v['pause_acknowledgment'].update(no_task_resume=False),
            lambda v:v['pause_acknowledgment']['origin'].update(resident_session='other')):
            forged=deepcopy(r);edit(forged)
            with self.assertRaises(ValueError):proof.validate(forged,self.command,'ack','watchdog')

class PublicLifecycleTests(unittest.TestCase):
    def test_shutdown_is_bounded_read_only_and_late_worker_cannot_write_closed_store(self):
        import threading
        from mdc_toolbox.service import ToolboxService
        submitted=threading.Event();finish=threading.Event();calls=[]
        class Client:
            _capability_owner=None;_capability_fault=None
            def session(self):return {'session_id':'wd','defense_epoch':1,'pause_acknowledgment':{'pause_ref':'a'*64}}
            def submit(self,cmd,request_id):calls.append((request_id,deepcopy(cmd)));submitted.set();return request_id
            def result(self,rid):
                if not finish.is_set():return None
                cmd=calls[0][1]
                return {'request_id':rid,'session_id':'wd','queue_request_id':None,'status':'failed','reason':'pause_ack_not_eligible',
                    'pause_acknowledgment':{'schema_version':1,'command':cmd,'request_sha256':proof.digest(cmd),'rearmed':False,
                        'origin':None,'samples':[],'no_task_resume':True,'no_native_mutation':True}}
        runtime=SimpleNamespace(client=Client(),has_unresolved_execution=False,_lease_active=False,_job_control=None)
        backend=SimpleNamespace(runtime=runtime,_active=None,_quarantined=False,_lock=threading.Lock(),
            describe=lambda:{'available':False,'private_singleplayer':True,'session_ref':'s','context_ref':'c',
                'pause_acknowledgment':{'version':proof.VERSION,'eligible':True,'pause_ref':'a'*64}})
        with tempfile.TemporaryDirectory() as root:
            service=ToolboxService(backend,root);results=[]
            args={'api_version':'mdc.toolbox/1','operation':'acknowledge_pause','request_id':'one','session_ref':'s',
                'pause_ref':'a'*64,'acknowledgment':proof.ACK}
            worker=threading.Thread(target=lambda:results.append(service.call('mdc_job',args)),daemon=True);worker.start()
            self.assertTrue(submitted.wait(2));start=time.monotonic();closed=service.shutdown(timeout=.03)
            self.assertLess(time.monotonic()-start,.3);self.assertFalse(closed['cleanup_confirmed']);self.assertEqual(len(calls),1)
            finish.set();worker.join(2);self.assertFalse(worker.is_alive());self.assertEqual(results[0]['state'],'unknown')
            self.assertEqual(len(calls),1)
    def test_canonical_and_standalone_schemas_keep_both_ack_literals_closed(self):
        import json
        from mdc_toolbox.contracts import validate_call,ToolboxError
        args={'api_version':'mdc.toolbox/1','operation':'acknowledge_pause','request_id':'one','session_ref':'s',
            'pause_ref':'a'*64,'acknowledgment':proof.ACK}
        self.assertEqual(validate_call('mdc_job',args),args)
        for change in ({'acknowledgment':'release_authority_keep_original_effects_unknown_no_resume'},{'pause_ref':True},{'extra':1}):
            with self.assertRaises(ToolboxError):validate_call('mdc_job',{**args,**change})
        adj={'api_version':'mdc.toolbox/1','operation':'adjudicate','session_ref':'s','job_id':'j','adjudication_request_id':'a',
             'original_receipt_sha256':'a'*64,'acknowledgment':'release_authority_keep_original_effects_unknown_no_resume'}
        self.assertEqual(validate_call('mdc_job',adj),adj)

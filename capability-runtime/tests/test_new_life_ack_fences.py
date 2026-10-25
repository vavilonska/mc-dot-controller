"""Exact death/new-instance and post-I/O acknowledgement fence negatives."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest.mock import patch
import new_life_acknowledgment as lane
from resident_controller import new_life_acknowledgment as proof
from capability_ownership import CapabilityOwnership
from test_pause_ack_fences import payload

OLD='11111111-1111-4111-8111-111111111111'
NEW='22222222-2222-4222-8222-222222222222'
OTHER='44444444-4444-4444-8444-444444444444'

class NewLifeFenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        for n in ('inbox','working','results'):(self.root/n).mkdir()
        self.now=1.;self.d=SimpleNamespace(execution_policy='request_only',stop_requested=False,stopped=False,
            handoff_latched=False,input_release_latched=False,owner=None,capability_lease=None,started_target=None,rpc=None,
            armed=False,reason=proof.REASON,defense_epoch=1,session_id='watchdog',clock=lambda:self.now,
            latest=None,capability_directory=self.root,completed=[])
        self.d.capability_complete=lambda *a,**k:CapabilityOwnership.capability_complete(self.d,*a,**k)
        self.resident={'session_id':'resident','bridge_identity':{'action_session':'native'},'state':'ready','active_request_id':None,'pending':0,
            'resident_policy':{'schema_version':1,'requires_handoff':False,'input_release_unconfirmed':False}}
        self.d.q=SimpleNamespace(session=lambda:deepcopy(self.resident))
        self.sample('death',10,alive=False,generation=OLD,run=False)
        lane.remember(self.d,proof.REASON);self.origin=deepcopy(self.d._new_life_ack_origin)
        self.sample('respawn',11,run=False);self.assertTrue(lane.status(self.d)['eligible'])
        now=time.time();self.command={'op':proof.OP,'schema_version':1,'death_ref':lane.status(self.d)['death_ref'],
            'expected_defense_epoch':1,'acknowledgment':proof.ACK,'created_at':now,'expires_at':now+5}
    def tearDown(self):self.tmp.cleanup()
    def sample(self,rid,tick,*,alive=True,generation=NEW,run=True,edit=None):
        self.now+=.1;self.d.latest=payload(tick,False)
        self.d.latest['state']['player'].update(alive=alive,health=20 if alive else 0,generation_schema_version=1,generation=generation)
        if edit:edit(self.d.latest)
        lane.observation(self.d,{'id':rid,'resident_session':'resident','resident_bridge':self.resident['bridge_identity'],'started':self.now},
            {'status':'succeeded','request_id':rid,'session_id':'resident'})
        if run:lane.tick(self.d)
    def submit(self):lane.submit(self.d,'ack',self.command)
    def result(self):
        v=self.d.completed[-1];return {**v['result'],'request_id':v['intent_id'],'session_id':v['session_id'],'queue_request_id':v['queue_request_id']}
    def test_two_new_reads_same_uuid_context_rearm(self):
        self.submit();self.sample('one',12);self.assertFalse(self.d.armed);self.sample('two',13)
        self.assertTrue(self.d.armed);self.assertEqual(self.d.defense_epoch,2)
        p=proof.validate(self.result(),self.command,'ack','watchdog');self.assertEqual(p['new_generation'],NEW)
    def test_changed_dimension_requires_one_exact_new_context(self):
        def destination(v):
            v['state']['world'].update(world_generation='new_world',dimension='minecraft:the_nether')
            v['state']['player']['dimension']='minecraft:the_nether'
        self.submit();self.sample('one',1,edit=destination);self.sample('two',2,edit=destination)
        self.assertTrue(self.d.armed);proof.validate(self.result(),self.command,'ack','watchdog')
    def test_dead_origin_is_retained_across_epochs_healthy_and_menu(self):
        for i in range(3):
            self.d.defense_epoch+=1;self.sample('dead'+str(i),12+i,alive=False,generation=OLD,run=False);lane.remember(self.d,proof.REASON)
            self.assertEqual(self.d._new_life_ack_origin,self.origin)
        self.sample('new',20,run=False,edit=lambda v:v['state'].update(paused=True,screen_open=True))
        lane.remember(self.d,proof.REASON);self.assertEqual(self.d._new_life_ack_origin,self.origin)
        self.assertTrue(lane.status(self.d)['eligible'])
        self.command['expected_defense_epoch']=self.d.defense_epoch;self.submit();self.sample('one',21);self.sample('two',22)
        self.assertTrue(self.d.armed);proof.validate(self.result(),self.command,'ack','watchdog')
    def test_dead_origin_requires_observed_dead_generation(self):
        for edit in (lambda p:p.update(health=True),lambda p:p.update(health=1),lambda p:p.update(alive=True),
                     lambda p:p.update(generation_schema_version=True),lambda p:p.pop('generation'),lambda p:p.update(generation='bad')):
            self.d._new_life_ack_origin=None;self.sample('dead',10,alive=False,generation=OLD,run=False,edit=lambda v:edit(v['state']['player']))
            lane.remember(self.d,proof.REASON);self.assertIsNone(self.d._new_life_ack_origin)
    def test_same_generation_cannot_rearm_even_with_restored_health(self):
        self.sample('same',12,generation=OLD,run=False);self.assertFalse(lane.status(self.d)['eligible']);self.submit()
        self.assertFalse(self.d.armed);self.assertFalse(proof.validate(self.result(),self.command,'ack','watchdog')['rearmed'])
    def test_no_automatic_rearm(self):
        self.sample('one',12);self.sample('two',13);self.assertFalse(self.d.armed);self.assertEqual(self.d.completed,[])
    def test_no_pre_request_duplicate_or_nonincreasing_samples(self):
        self.submit();lane.tick(self.d);self.assertEqual(self.d._new_life_ack_pending['samples'],[])
        self.sample('one',12);self.sample('two',12);self.sample('one',13);self.assertFalse(self.d.armed)
        self.sample('three',14);self.assertTrue(self.d.armed)
    def test_owner_uncertainty_other_cause_and_pending_pause_refuse(self):
        for field,value in [('owner',{}),('capability_lease',{}),('handoff_latched',True),('input_release_latched',True),
            ('started_target','mob'),('rpc',{'kind':'cancel'}),('_fall_rescue_owner',{}),('_external_navigation_owner',{}),
            ('_managed_navigation_owner',{}),('_coordination_owner',{}),('_pause_ack_pending',{}),
            ('stop_requested',True),('stopped',True),('reason','request_only_observation_not_safe_idle')]:
            with self.subTest(field=field):
                old=getattr(self.d,field,None);setattr(self.d,field,value);self.assertFalse(lane.status(self.d)['eligible']);setattr(self.d,field,old)
    def test_deadline_and_no_renewal(self):
        self.submit();self.now=20;lane.tick(self.d);self.assertFalse(self.d.armed);self.assertEqual(self.result()['status'],'failed')
    def test_lifecycle_or_generation_replacement_between_samples_refuses(self):
        for mutate in (lambda v:v['state']['player'].update(uuid='other'),lambda v:v['state']['client_action'].update(action_session='other'),
            lambda v:v['state']['world'].update(integrated_server_instance=OTHER),lambda v:v['state']['world'].update(world_generation='other'),
            lambda v:v['state']['player'].update(generation=OTHER)):
            self.tmp.cleanup();self.setUp();self.submit();self.sample('one',12);self.sample('two',13,edit=mutate)
            self.assertFalse(self.d.armed);self.assertEqual(self.result()['status'],'failed')
    def test_unsafe_sample_cannot_erase_first_new_instance_pin(self):
        self.submit();self.sample('one',12)
        self.sample('unsafe_replacement',13,generation=OTHER,edit=lambda v:v['state'].update(screen_open=True))
        self.assertFalse(self.d.armed);self.assertEqual(self.result()['status'],'failed')
        self.sample('three',14,generation=OTHER);self.sample('four',15,generation=OTHER);self.assertFalse(self.d.armed)
    def test_same_instance_unsafe_sample_resets_only_consecutive_evidence(self):
        self.submit();self.sample('one',12);self.sample('unsafe',13,edit=lambda v:v['state'].update(screen_open=True))
        self.assertEqual(self.d._new_life_ack_pending['new_generation'],NEW)
        self.assertEqual(self.d._new_life_ack_pending['samples'],[])
        self.sample('three',14);self.assertFalse(self.d.armed);self.sample('four',15);self.assertTrue(self.d.armed)
    def test_final_io_mutations_stop_without_rearm(self):
        mutations=(lambda d:setattr(d,'owner',{}),lambda d:setattr(d,'defense_epoch',2),lambda d:setattr(d,'stop_requested',True),
            lambda d:setattr(d,'latest',deepcopy(d.latest)),lambda d:d.latest['state'].update(screen_open=True),
            lambda d:d.latest['resident_policy'].update(requires_handoff=True),lambda d:d.latest['state']['world'].update(game_time=999),
            lambda d:d.latest['state']['player'].update(generation=OTHER),lambda d:d.latest['state']['player'].update(generation_schema_version=True),
            lambda d:d._new_life_ack_sample.update(request_id='changed'),lambda d:d._new_life_ack_sample.update(started=0),
            lambda d:d._new_life_ack_sample.update(received=0),lambda d:d._new_life_ack_sample.update(resident_session='other'),
            lambda d:d._new_life_ack_sample['bridge_identity'].update(action_session='other'),
            lambda d:d._new_life_ack_pending['samples'][0].update(tick=0),lambda d:d._new_life_ack_origin.update(death_health=-1),
            lambda d:setattr(self,'now',20))
        for mutate in mutations:
            self.tmp.cleanup();self.setUp();self.submit();self.sample('one',12)
            def session():mutate(self.d);return deepcopy(self.resident)
            self.d.q.session=session;self.sample('two',13);self.assertFalse(self.d.armed)
    def test_final_clock_callback_cannot_replace_owner(self):
        self.submit();self.sample('one',12)
        original_clock=self.d.clock
        def session():
            def changed_clock():self.d.owner={};return original_clock()
            self.d.clock=changed_clock
            return deepcopy(self.resident)
        self.d.q.session=session;self.sample('two',13);self.assertFalse(self.d.armed)
    def test_wall_expiry_is_retained_after_final_io(self):
        self.submit();self.sample('one',12)
        self.d.q.session=lambda:deepcopy(self.resident)
        with patch.object(lane.time,'time',return_value=self.command['expires_at']+1):
            self.sample('two',13)
        self.assertFalse(self.d.armed)
    def test_closed_proof_rejects_typed_and_identity_forgery(self):
        self.submit();self.sample('one',12);self.sample('two',13);original=self.result()
        for edit in (lambda v:v.update(request_id='other'),lambda v:v['new_life_acknowledgment'].update(rearmed=1),
            lambda v:v['new_life_acknowledgment'].update(new_generation=OLD),lambda v:v['new_life_acknowledgment']['samples'][1].update(tick=True),
            lambda v:v['new_life_acknowledgment']['new_context'].update(player_uuid='other'),
            lambda v:v['new_life_acknowledgment'].update(no_task_resume=False)):
            v=deepcopy(original);edit(v)
            with self.assertRaises(ValueError):proof.validate(v,self.command,'ack','watchdog')
    def test_canonical_schema_keeps_controls_separate(self):
        from mdc_toolbox.contracts import validate_call,ToolboxError
        args={'api_version':'mdc.toolbox/1','operation':'acknowledge_new_life','request_id':'life','session_ref':'s','death_ref':'a'*64,'acknowledgment':proof.ACK}
        self.assertEqual(validate_call('mdc_job',args),args)
        for change in ({'acknowledgment':'allow_new_requests_only_no_task_resume'},{'death_ref':True},{'pause_ref':'a'*64},{'budgets':{}}):
            with self.assertRaises(ToolboxError):validate_call('mdc_job',{**args,**change})

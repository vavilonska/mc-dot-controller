"""Production gateway release method under exact checkpoint/read fault injection."""
from copy import deepcopy
import unittest
from capability_ownership import CapabilityOwnership


class Queue:
    def __init__(self):self.calls=0;self.callback=None;self.session_id='resident'
    def session(self):
        self.calls+=1
        if self.callback:self.callback(self.calls)
        return {'session_id':self.session_id,'state':'ready','pending':0,'active_request_id':None,
            'resident_policy':{'schema_version':1,'requires_handoff':False,'input_release_unconfirmed':False}}


class Gateway(CapabilityOwnership):
    def __init__(self, paused=True):
        self.now=10.;self.clock=lambda:self.now;self.q=Queue();self.completed=[];self.session_id='gateway';self.defense_epoch=1
        self.owner=self.rpc=None;self.stop_requested=self.stopped=False;self.input_release_latched=self.handoff_latched=False
        self.armed=True;self.phase='watching';self.reason='test';self.latest={};self.checkpoints=[];self.callback=None
        self.old={'owner_id':'a'*32,'state':'active','context':{'world_generation':'world','dimension':'minecraft:overworld',
            'player_uuid':'player','action_session':'native'},'resident_session':'resident','defense_epoch':1,
            'deadline':100.,'heartbeat':100.,'post_observation_required':False,'cleanup_started':True}
        self.proof={'observed_at':10.,'context':deepcopy(self.old['context']),'paused':paused,
            'intent_id':'cleanup-read','queue_request_id':'resident-cleanup-read'}
        self.old['cleanup_observation']=self.proof;self.capability_lease=self.old
        self.replacement={**deepcopy(self.old),'owner_id':'b'*32}
    def attention(self,reason):
        self.armed=False;self.phase='needs_operator';self.reason=reason;self.defense_epoch+=1
    def capability_checkpoint(self,lease):
        self.checkpoints.append(deepcopy(lease))
        if self.callback:self.callback(lease)
    def release(self):
        self.capability_control('release-original',{'op':'capability_release','owner_id':'a'*32,'expected_defense_epoch':1})
        return self.completed[-1]['result']


class CleanupReleaseFenceTests(unittest.TestCase):
    def test_delayed_prepare_does_not_clear_old_lease(self):
        g=Gateway();g.callback=lambda lease:setattr(g,'now',g.now+1)
        r=g.release();self.assertEqual(r['status'],'uncertain');self.assertIs(g.capability_lease,g.old)
        self.assertEqual(len(g.checkpoints),1);self.assertTrue(g.handoff_latched)
    def test_replacement_during_prepare_is_preserved(self):
        g=Gateway();g.callback=lambda lease:setattr(g,'capability_lease',g.replacement)
        r=g.release();self.assertEqual(r['status'],'uncertain');self.assertIs(g.capability_lease,g.replacement)
        self.assertEqual(g.replacement['state'],'active');self.assertEqual(len(g.checkpoints),1)
    def test_stop_during_prepare_is_preserved(self):
        g=Gateway();g.callback=lambda lease:setattr(g,'stop_requested',True)
        r=g.release();self.assertEqual(r['status'],'uncertain');self.assertIs(g.capability_lease,g.old)
        self.assertTrue(g.stop_requested);self.assertEqual(len(g.checkpoints),1)
    def test_session_read_delays_or_replaces_after_checkpoint_are_fenced(self):
        for change in ('age','lease','epoch','context','session','deadline','heartbeat','owner','rpc','stop','proof'):
            with self.subTest(change=change):
                g=Gateway()
                def callback(call):
                    if call!=1:return
                    if change=='age':g.now+=1
                    elif change=='lease':g.capability_lease=g.replacement
                    elif change=='epoch':g.defense_epoch+=1
                    elif change=='context':g.old['context']['world_generation']='foreign'
                    elif change=='session':g.q.session_id='other'
                    elif change=='deadline':g.old['deadline']=g.now
                    elif change=='heartbeat':g.old['heartbeat']=g.now
                    elif change=='owner':g.owner={'id':'replacement-action'}
                    elif change=='rpc':g.rpc={'id':'replacement-read'}
                    elif change=='stop':g.stop_requested=True
                    elif change=='proof':g.old['cleanup_observation']=deepcopy(g.proof)
                g.q.callback=callback;r=g.release()
                self.assertEqual(r['status'],'uncertain');self.assertIsNotNone(g.capability_lease)
                self.assertEqual(len(g.checkpoints),1)
    def test_read_boundary_replacement_or_stop_cannot_overwrite_new_durable_checkpoint(self):
        for change in ('replacement','stop'):
            with self.subTest(change=change):
                g=Gateway();g.durable=None
                checkpoint=g.capability_checkpoint
                def persist(lease):
                    g.durable=deepcopy(lease)
                    checkpoint(lease)
                g.capability_checkpoint=persist
                replacement_checkpoint={'new_owner':'b'*32,'stopped':change=='stop'}
                def boundary(call):
                    if call!=1:return
                    if change=='replacement':g.capability_lease=g.replacement
                    else:g.stop_requested=True
                    g.durable=deepcopy(replacement_checkpoint)
                g.q.callback=boundary;r=g.release()
                self.assertEqual(r['status'],'uncertain')
                self.assertEqual(g.durable,replacement_checkpoint)
                self.assertEqual(len(g.checkpoints),1)
                if change=='replacement':self.assertIs(g.capability_lease,g.replacement)
                else:self.assertTrue(g.stop_requested);self.assertIs(g.capability_lease,g.old)
    def test_prepare_failure_keeps_original_and_never_tombstones(self):
        g=Gateway()
        def fail(lease):raise OSError('prepare_failed')
        g.callback=fail;r=g.release();self.assertEqual(r['status'],'uncertain')
        self.assertIs(g.capability_lease,g.old);self.assertEqual(len(g.checkpoints),1)
    def test_commit_failure_never_reenables_admission(self):
        g=Gateway(paused=False)
        def fail(lease):
            if lease is None:raise OSError('commit_failed')
        g.callback=fail;r=g.release();self.assertEqual(r['status'],'uncertain')
        self.assertFalse(g.armed);self.assertTrue(g.handoff_latched);self.assertIsNone(g.capability_lease)
    def test_commit_callback_replacement_or_stop_is_not_overwritten(self):
        for change in ('lease','stop','epoch','session','handoff','owner'):
            with self.subTest(change=change):
                g=Gateway(paused=False)
                def changed(lease):
                    if lease is not None:return
                    if change=='lease':g.capability_lease=g.replacement
                    elif change=='stop':g.stop_requested=True
                    elif change=='epoch':g.defense_epoch+=1
                    elif change=='session':g.q.session_id='other'
                    elif change=='handoff':g.reason='external_handoff'
                    elif change=='owner':g.owner={'id':'replacement-action'}
                g.callback=changed;r=g.release();self.assertEqual(r['status'],'uncertain')
                self.assertFalse(g.armed);self.assertTrue(g.handoff_latched)
                if change=='lease':self.assertIs(g.capability_lease,g.replacement)
                if change=='owner':self.assertEqual(g.owner,{'id':'replacement-action'})
    def test_success_commits_original_then_tombstone_and_keeps_pause(self):
        g=Gateway();r=g.release();self.assertEqual(r['status'],'succeeded')
        self.assertEqual(len(g.checkpoints),2);self.assertIsNotNone(g.checkpoints[0]);self.assertIsNone(g.checkpoints[1])
        self.assertEqual(g.checkpoints[0]['cleanup_release_pending']['intent_id'],'release-original')
        self.assertIsNone(g.capability_lease);self.assertFalse(g.armed);self.assertTrue(g.handoff_latched)
    def test_pause_decision_uses_immutable_consumed_proof_after_commit(self):
        g=Gateway(paused=True)
        def changed(lease):
            if lease is None:g.proof['paused']=False
        g.callback=changed;r=g.release();self.assertEqual(r['status'],'succeeded')
        self.assertFalse(g.armed);self.assertTrue(g.handoff_latched)
    def test_active_success_only_reopens_after_durable_commit(self):
        g=Gateway(paused=False)
        def check(lease):
            if lease is None:self.assertFalse(g.armed);self.assertTrue(g.handoff_latched)
        g.callback=check;r=g.release();self.assertEqual(r['status'],'succeeded')
        self.assertTrue(g.armed);self.assertFalse(g.handoff_latched)
    def test_second_release_attempt_after_unknown_is_not_reissued(self):
        g=Gateway();g.callback=lambda lease:setattr(g,'now',g.now+1)
        self.assertEqual(g.release()['status'],'uncertain');count=len(g.checkpoints)
        self.assertNotEqual(g.release()['status'],'succeeded');self.assertEqual(len(g.checkpoints),count)


if __name__=='__main__':unittest.main()

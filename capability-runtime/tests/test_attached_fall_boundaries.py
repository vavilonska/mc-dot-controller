"""Production attached-policy boundary faults; no Minecraft or network required."""
from copy import deepcopy
from types import SimpleNamespace as NS
import time
import unittest
from resident_controller import fall_rescue_attached as f
from resident_controller.transport import BridgeError
from test_fall_rescue_evidence import ROWS

SESSION='11111111-2222-4333-8444-555555555555'

class Boundaries(unittest.TestCase):
    def setUp(self):
        scope={'profile':'combat-local-observed-v1','owner_id':'owner-one','owner_generation':1,'job_id':'job-one','defense_epoch':3}
        self.command={'request_id':'request-one','action':'combat_entity','timeout_ms':1000,'scoped_native_preflight':scope,
            **{'expected_'+k:v for k,v in {'world_generation':ROWS[0]['world_generation'],'dimension':'minecraft:overworld',
                  'player_uuid':ROWS[0]['player_uuid'],'action_session':ROWS[0]['action_session']}.items()},
            'fall_rescue_policy':{'version':f.VERSION,**{k:scope[k] for k in ('owner_id','owner_generation','job_id','defense_epoch')},
                'ttl_ms':11000,'rescue_reserve_ms':10000,'authorization_deadline_monotonic_ms':int(time.monotonic()*1000)+30000}}
        self.binding=f.binding_for(self.command,'request-one',SESSION);self.command['fall_rescue_binding']=deepcopy(self.binding)
        self.task=NS(command=self.command,step_number=1,action_id=self.binding['action_id'],fall_rescue=None,
                     last_action_result=None,capability_unknown=False,capability_cancel_attempted=False,wake_at=0)
        self.writes=[];self.receipts=[];self.callback=lambda method,path,body:None
        self.resident=NS(active=self.task,session_id=SESSION,paused=False,reason=None,pending=[],
            combat=NS(active=False,held=False),aim=NS(active=False),bridge_identity={'action_session':self.binding['context']['action_session']},
            publish=lambda:None,finish=lambda command,status,**fields:self.receipts.append((deepcopy(command),status,deepcopy(fields))))
        self.value=self.status(0)
        def request(method,path,body=None):
            self.writes.append((method,path,deepcopy(body)));self.callback(method,path,body)
            return deepcopy(self.value)
        self.resident.bridge=NS(request=request)
        self.resident.observation_policy=lambda:{'schema_version':1,'requires_handoff':self.resident.paused,'input_release_unconfirmed':self.resident.paused}
        self.resident.discard_pending=lambda reason:None
    def status(self,index):
        v=deepcopy(ROWS[index]);v.update(arm_id=self.binding['arm_id'],owner_id=self.binding['owner_id'])
        if v['armed']:v['remaining_ms']=11000
        e=v.get('episode') or v.get('last_episode')
        if e:
            e['episode_id']=self.binding['arm_id']+':1'
            e['interrupted_action']={'action_id':self.binding['action_id'],'action':'combat_entity',
                'effect_outcome':'unknown_interrupted','no_auto_resume':True,'requires_reconciliation_before_retry':True}
        if index==4:v.update(unknown_outcome_quarantined=True,automation_blocked=True,status='quarantined')
        return v
    def native(self):
        return {'action_id':self.binding['action_id'],'action_session':self.binding['context']['action_session'],
            'action_schema_version':1,'action':'combat_entity','status':'cancelled',
            'result':{k:True for k in ('preempted_by_native_fall_rescue','unknown_outcome','requires_handoff','no_auto_resume','input_release_confirmed')}}
    def replaced(self,*args):self.resident.active=NS(replacement=True)
    def assert_old_only(self):
        self.assertTrue(self.resident.active.replacement);self.assertFalse(self.resident.paused)
        self.assertTrue(self.task.capability_unknown);self.assertEqual(len(self.receipts),1)
        self.assertEqual(self.receipts[0][0]['request_id'],'request-one')
    def test_arm_callback_replacement_never_dispatches_or_stops_replacement(self):
        self.callback=self.replaced
        with self.assertRaises(BridgeError) as caught:f.arm(self.resident,self.task)
        f.unknown(self.resident,self.task,caught.exception);self.assert_old_only();self.assertEqual(len(self.writes),1)
    def test_status_callback_replacement_retains_original_unknown(self):
        f.arm(self.resident,self.task);self.callback=self.replaced
        with self.assertRaises(BridgeError) as caught:f.status(self.resident,self.task)
        f.unknown(self.resident,self.task,caught.exception);self.assert_old_only()
    def test_disarm_callback_replacement_is_not_retried(self):
        f.arm(self.resident,self.task);self.callback=self.replaced;self.value.update(armed=False,status='disarmed',remaining_ms=0)
        with self.assertRaises(BridgeError) as caught:f.disarm(self.resident,self.task)
        f.unknown(self.resident,self.task,caught.exception);self.assert_old_only()
        with self.assertRaises(BridgeError):f.disarm(self.resident,self.task)
        self.assertEqual(len(self.writes),2)
    def test_finish_callback_cannot_clear_replacement(self):
        f.arm(self.resident,self.task);self.task.last_action_result=self.native();self.value=self.status(4)
        finish=self.resident.finish
        def replace(*a,**kw):finish(*a,**kw);self.replaced()
        self.resident.finish=replace;f.settle(self.resident,self.task,self.value)
        self.assertTrue(self.resident.active.replacement);self.assertEqual(self.receipts[0][1],'uncertain')
    def test_pause_during_arm_blocks_original_dispatch(self):
        self.callback=lambda *args:setattr(self.resident,'paused',True)
        with self.assertRaises(BridgeError):f.arm(self.resident,self.task)
        self.assertEqual(len(self.writes),1);self.assertTrue(self.resident.paused)
    def test_expired_authorization_has_no_native_write(self):
        self.command['fall_rescue_policy']['authorization_deadline_monotonic_ms']=1
        self.command['fall_rescue_binding']=f.binding_for(self.command,'request-one',SESSION)
        with self.assertRaises(ValueError):f.arm(self.resident,self.task)
        self.assertEqual(self.writes,[])
    def test_attempt_evidence_regression_is_unknown(self):
        f.arm(self.resident,self.task);self.value=self.status(2);f.status(self.resident,self.task);self.value=self.status(0)
        with self.assertRaises(BridgeError):f.status(self.resident,self.task)
        self.assertTrue(self.task.fall_rescue['last_status']['episode']['dispatch_attempted'])
    def test_exact_seal_binding_and_partial_proof_cannot_be_promoted(self):
        f.arm(self.resident,self.task);self.task.last_action_result=self.native();v=f.seal(self.task,self.status(4))
        f.verify_seal(v,self.command,'request-one',SESSION)
        for key,new in [('action_id','foreign'),('action','follow_path'),('action_schema_version',True),('status','succeeded')]:
            changed=deepcopy(v);changed['original_action'][key]=new;changed['sha256']=f.digest({k:x for k,x in changed.items() if k!='sha256'})
            with self.subTest(key=key),self.assertRaises((ValueError,BridgeError)):f.verify_seal(changed,self.command,'request-one',SESSION)
        for key in ('rescue_confirmed','dispatch_attempted','server_landed_alive_observed'):
            changed=deepcopy(v);changed['native_status']['last_episode'][key]=False;changed['sha256']=f.digest({k:x for k,x in changed.items() if k!='sha256'})
            with self.subTest(key=key),self.assertRaises((ValueError,BridgeError)):f.verify_seal(changed,self.command,'request-one',SESSION)
    def test_generic_interrupt_retains_old_unknown_without_native_write(self):
        from resident_controller.controller import Resident
        f.arm(self.resident,self.task)
        with self.assertRaises(BridgeError):Resident.interrupt_local(self.resident,'direct_takeover')
        self.assertIs(self.resident.active,self.task);self.assertTrue(self.task.capability_unknown)
        self.assertEqual(self.receipts[0][1],'uncertain');self.assertEqual(len(self.writes),1)
    def test_unexpected_end_active_cannot_publish_cancelled(self):
        from resident_controller.controller import Resident
        f.arm(self.resident,self.task);Resident.end_active(self.resident,'cancelled')
        self.assertIs(self.resident.active,self.task);self.assertEqual(self.receipts[0][1],'uncertain')
    def test_legacy_takeover_and_resume_refused_without_write(self):
        f.arm(self.resident,self.task)
        for op in ('direct','action','resume','combat_start','aim_lock'):
            self.assertTrue(f.lifecycle_command(self.resident,{'op':op,'request_id':'control-'+op,'endpoint':'look'}))
        self.assertTrue(f.lifecycle_command(self.resident,{'op':'cancel','request_id':'automatic','watchdog_observation_fallback':True}))
        self.assertIs(self.resident.active,self.task);self.assertEqual(len(self.writes),1)
        self.assertTrue(all(row[1]=='failed' for row in self.receipts))
    def test_legacy_stop_disarms_once_retains_original_unknown(self):
        f.arm(self.resident,self.task);self.task.last_action_result=self.native();self.value=self.status(4)
        self.assertTrue(f.lifecycle_command(self.resident,{'op':'cancel','request_id':'stop-one'}))
        self.assertEqual([path for method,path,body in self.writes].count('/control/fall-rescue/disarm'),1)
        self.assertFalse(any(path=='/control/release-all' for method,path,body in self.writes))
        self.assertEqual(self.receipts[0][1],'uncertain');self.assertIsNone(self.resident.active)
        self.assertTrue(self.resident.paused)
    def test_shutdown_stops_bound_guard_without_global_takeover(self):
        f.arm(self.resident,self.task);self.task.last_action_result=self.native();self.value=self.status(4)
        f.lifecycle_command(self.resident,{'op':'shutdown','request_id':'shutdown-one'})
        self.assertFalse(self.resident.running);self.assertTrue(self.resident.paused)
        self.assertFalse(any(path=='/control/release-all' for method,path,body in self.writes))

    def test_ctrl_c_finally_never_sends_global_release(self):
        from resident_controller.controller import Resident
        f.arm(self.resident,self.task);self.task.last_action_result=self.native();self.value=self.status(4)
        self.resident.start=lambda:None
        def interrupt():raise KeyboardInterrupt()
        self.resident.tick=interrupt;self.resident.running=True
        self.resident.combat.stop=lambda *args,**kwargs:None
        self.resident.aim.release=lambda reason:None
        self.resident.initialized=True;self.resident.owns_lock=False;self.resident.lock=None
        Resident.serve(self.resident)
        self.assertFalse(self.resident.running);self.assertTrue(self.resident.paused)
        self.assertEqual([p for m,p,b in self.writes],['/control/fall-rescue/arm','/control/fall-rescue/disarm'])
        self.assertEqual(self.receipts[0][1],'uncertain')

    def test_closed_envelope_and_gateway_binding(self):
        for key,new in [('ttl_ms',1000),('rescue_reserve_ms',True),('owner_generation',True),('permitted_action_ids',['foreign'])]:
            c=deepcopy(self.command);c['fall_rescue_policy'][key]=new
            with self.subTest(key=key),self.assertRaises(ValueError):f.validate_envelope(c)
        for key in self.binding:
            c=deepcopy(self.command);c['fall_rescue_binding'][key]=None
            with self.subTest(key=key),self.assertRaises(ValueError):f.validate_binding(c,SESSION)

if __name__=='__main__':unittest.main()

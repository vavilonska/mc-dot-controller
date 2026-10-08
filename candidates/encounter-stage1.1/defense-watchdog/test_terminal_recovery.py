"""Regression against real Resident.cancel semantics plus the actual watchdog classes."""
import copy
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from watchdog import Watchdog
from test_ranged_tactics import RangedQueue
from test_watchdog import TARGET
from resident_controller.controller import Resident

ROOT=Path(__file__).resolve().parents[1]

class MinimalBridge:
    base_url='http://127.0.0.1:1'
    def request(self,method,path,body=None):
        action={'action_session':'test-session','action_schema_version':1,'status':'idle'}
        if path=='/control/status':return {'protocol':'mineclient-bridge','schema_version':2,'run_id':'r','process_id':1,'client_action':action}
        if path=='/control/action/status':return action
        if path=='/control/release-all':return {'ok':True}
        raise AssertionError(path)

class TerminalChecks(unittest.TestCase):
    def queue(self):
        q=RangedQueue();q.terrain={'complete':False,'cells':[]}
        q.obs['state']['nearby']['entities'][0]['type']='minecraft:zombie'
        q.obs['combat']={'active':False,'phase':'stopped','reason':'combat_flat_approach_blocked',
             'request_id':'owned-combat','target_uuid':TARGET,'target_type':'minecraft:zombie',
             'attack_dispatches':0,'melee_closing_schema_version':2}
        return q
    def run_loop(self,cls,steps=75):
        now=[0.0];q=self.queue();dog=cls(q,clock=lambda:now[0]);dog.latest=copy.deepcopy(q.obs)
        dog.started_target=TARGET;dog.targeting.lock(TARGET,0)
        dog.ranged_memory.begin(q.obs['state'],q.obs['state']['nearby']['entities'][0],0)
        for _ in range(steps):dog.tick();now[0]+=.1
        return dog,q,now
    def test_real_resident_cancel_preserves_already_stopped_combat_reason(self):
        with tempfile.TemporaryDirectory() as temp:
            resident=Resident(MinimalBridge(),temp);resident.start()
            try:
                resident.combat.active=True
                resident.combat.request_id='owned-combat';resident.combat.target_uuid=TARGET
                resident.combat.stop(resident,'combat_flat_approach_blocked')
                resident.command({'op':'cancel','request_id':'cancel-once'})
                self.assertEqual(resident.combat.reason,'combat_flat_approach_blocked')
                self.assertEqual(resident.combat.request_id,'owned-combat')
                self.assertFalse(resident.combat.active);self.assertEqual(resident.combat.held,set())
            finally:resident.lock.close()
    def test_old_v5_repeats_but_fixed_watchdog_handles_terminal_once(self):
        path=ROOT/'minecraft-hostile-melee-candidate/watchdog.py'
        if not path.is_file():self.skipTest('old frozen source unavailable')
        spec=importlib.util.spec_from_file_location('old_watchdog_v5',path)
        old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
        _,oldq,_=self.run_loop(old.Watchdog)
        new,newq,now=self.run_loop(Watchdog)
        old_cancels=sum(c['op']=='cancel' for _,c in oldq.calls)
        new_cancels=sum(c['op']=='cancel' for _,c in newq.calls)
        self.assertGreater(old_cancels,3);self.assertEqual(new_cancels,1)
        self.assertEqual(len(new.handled_terminal),1)
        self.assertLess(new.ranged_memory.records[TARGET]['suppressed_until'],now[0]+10)
    def test_new_real_entity_hit_recovers_same_uuid_without_approach(self):
        dog,q,now=self.run_loop(Watchdog,steps=35)
        target=q.obs['state']['nearby']['entities'][0]
        target.update(x=2.5,distance=2)
        target['bounding_box']={'min':{'x':2.2,'y':64,'z':.2},'max':{'x':2.8,'y':65.95,'z':.8}}
        q.obs['state']['crosshair']={'type':'entity','uuid':TARGET,'entity_id':target['entity_id'],
                                    'entity_type':target['type'],'location':{'x':2.2,'y':65,'z':.5}}
        for _ in range(12):dog.tick();now[0]+=.1
        starts=[c for _,c in q.calls if c['op']=='combat_start']
        self.assertEqual(len(starts),1);self.assertEqual(starts[0]['target_uuid'],TARGET)
        self.assertFalse(starts[0]['approach'])
        self.assertEqual(sum(c['op']=='cancel' for _,c in q.calls),2)
    def test_block_crosshair_never_rearms_from_small_body_distance_alone(self):
        dog,q,now=self.run_loop(Watchdog,steps=35)
        q.obs['state']['nearby']['entities'][0]['distance']=.68
        q.obs['state']['crosshair']={'type':'block','id':'minecraft:deepslate','location':{'x':.7,'y':65.4,'z':.5}}
        for _ in range(20):dog.tick();now[0]+=.1
        self.assertFalse(any(c['op']=='combat_start' for _,c in q.calls))
        self.assertEqual(sum(c['op']=='cancel' for _,c in q.calls),1)
    def test_recovery_lost_fresh_hit_preserves_history_and_never_opens_approach(self):
        dog,q,now=self.run_loop(Watchdog,steps=35)
        state=q.obs['state'];target=state['nearby']['entities'][0]
        state['crosshair']={'type':'entity','uuid':TARGET,'entity_id':target['entity_id'],
                            'entity_type':target['type'],'location':{'x':2.2,'y':65,'z':.5}}
        before=copy.deepcopy(dog.ranged_memory.records[TARGET])
        self.assertTrue(dog.recover_live_melee(state,target))
        state['crosshair']={'type':'block','id':'minecraft:deepslate'}
        dog.latest=copy.deepcopy(q.obs)
        self.assertTrue(dog.observe_tactics(state,q.obs['combat'],False,'fresh'))
        self.assertIsNone(dog.melee_recovery_target)
        self.assertEqual(dog.ranged_memory.records[TARGET],before)
        self.assertFalse(any(c['op']=='combat_start' for _,c in q.calls))
    def test_first_terminal_hit_then_fresh_loss_does_not_reopen_approach(self):
        now=[0.0];q=self.queue();dog=Watchdog(q,clock=lambda:now[0])
        state=q.obs['state'];target=state['nearby']['entities'][0]
        state['crosshair']={'type':'entity','uuid':TARGET,'entity_id':target['entity_id'],
                            'entity_type':target['type'],'location':{'x':2.2,'y':65,'z':.5}}
        dog.latest=copy.deepcopy(q.obs);dog.started_target=TARGET;dog.targeting.lock(TARGET,0)
        dog.ranged_memory.begin(state,target,0)
        self.assertTrue(dog.observe_tactics(state,q.obs['combat'],False,'observe'))
        state['crosshair']={'type':'block'}
        for _ in range(25):dog.tick();now[0]+=.1
        self.assertFalse(any(c['op']=='combat_start' for _,c in q.calls))
        self.assertGreater(dog.targeting.excluded[TARGET],now[0])
    def test_active_exact_hit_has_priority_over_old_no_attack_budget(self):
        dog,q,now=self.run_loop(Watchdog,steps=35)
        state=q.obs['state'];target=state['nearby']['entities'][0]
        state['crosshair']={'type':'entity','uuid':TARGET,'entity_id':target['entity_id'],
                            'entity_type':target['type'],'location':{'x':2.2,'y':65,'z':.5}}
        now[0]=8
        combat={**q.obs['combat'],'active':True,'phase':'acquiring','reason':'started','request_id':'new-combat'}
        before=len(q.calls)
        self.assertTrue(dog.observe_tactics(state,combat,False,'observe'))
        self.assertEqual(dog.reason,'verified_entity_hit_native_melee_priority')
        self.assertEqual(len(q.calls),before)
    def test_ranged_capture_records_death_before_context_error(self):
        dog,q,now=self.run_loop(Watchdog,steps=10)
        payload=copy.deepcopy(q.obs);payload['state']['player'].update(alive=False,health=0)
        with self.assertRaises(ValueError):dog.capture({'result':payload})
        self.assertTrue(dog.trace_frozen)
        self.assertEqual(dog.trace[-1]['player']['health'],0)
    def test_trace_freezes_at_death_instead_of_rolling_alive_samples_away(self):
        dog,q,now=self.run_loop(Watchdog,steps=10)
        payload=copy.deepcopy(q.obs);payload['state']['player'].update(alive=False,health=0)
        dog.observation_received(payload,'observe');count=len(dog.trace)
        for _ in range(200):dog.observation_received(payload,'observe')
        self.assertEqual(len(dog.trace),count);self.assertTrue(dog.trace_frozen)
        with tempfile.TemporaryDirectory() as temp:
            dog.persist_telemetry(Path(temp))
            self.assertTrue((Path(temp)/('combat-trace-'+dog.session_id+'.json')).is_file())

if __name__=='__main__':unittest.main()

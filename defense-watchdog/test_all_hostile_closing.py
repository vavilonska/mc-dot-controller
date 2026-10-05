"""Offline reproduction of the six-block zombie zero-dispatch queue lock."""
import copy
import unittest
from watchdog import Watchdog
from ranged_tactics import RangedMemory
from test_ranged_tactics import RangedQueue, witch
from test_watchdog import TARGET

class HostileChecks(unittest.TestCase):
    def setUp(self):
        self.now=0;self.q=RangedQueue()
        mob=witch();mob.update(type='minecraft:zombie',health=20,x=6.5,distance=6)
        mob['bounding_box']={'min':{'x':6.2,'y':64,'z':.2},'max':{'x':6.8,'y':65.95,'z':.8}}
        self.q.obs['state']['nearby']['entities']=[mob]
        self.d=Watchdog(self.q,clock=lambda:self.now)
    def tick(self,n=1):
        for _ in range(n):self.d.tick();self.now+=.1
    def until(self,predicate,n=120):
        for _ in range(n):
            if predicate():return
            self.tick()
        self.fail(str(self.d.status()))
    def commands(self,operation):return [body for _,body in self.q.calls if body['op']==operation]
    def test_six_block_zombie_gets_approach_not_stationary_combat(self):
        self.tick(8)
        command=self.commands('combat_start')[0]
        self.assertTrue(command['approach']);self.assertTrue(command['shield'])
        self.assertEqual(self.d.status()['engagement']['scope'],'all_observed_hostiles')
    def test_six_block_zero_dispatch_zombie_is_bounded_and_does_not_regrab(self):
        self.q.terrain={'complete':False,'cells':[]}
        self.tick(90)
        self.assertEqual(len(self.commands('combat_start')),1)
        self.assertEqual(self.commands('action'),[])
        self.assertTrue(self.d.armed);self.assertEqual(self.d.phase,'watching')
        self.assertIsNone(self.d.started_target)
        self.assertGreater(self.d.targeting.excluded[TARGET],self.now)
        self.assertEqual(self.d.ranged_memory.records[TARGET]['dispatches'],0)
    def test_mining_intent_is_admitted_after_unreachable_zombie_is_released(self):
        self.q.terrain={'complete':False,'cells':[]}
        self.until(lambda:self.d.ranged_memory.records.get(TARGET,{}).get('suppressed_until',0)>self.now
                         and self.d.phase=='watching' and self.d.rpc is None)
        self.assertTrue(self.d.submit_owner('mine-after-release',{'op':'action','action':'break_block',
                                                               'target':{'x':0,'y':63,'z':0}}))
        self.assertEqual(self.commands('action')[-1]['action'],'break_block')
    def test_observed_zombie_closing_and_attack_progress_keeps_same_target(self):
        self.tick(8)
        self.q.obs['state']['player'].update(x=3.5)
        self.q.obs['state']['player']['eye_position']['x']=3.5
        self.q.obs['state']['nearby']['entities'][0].update(distance=3,health=13)
        self.q.obs['combat'].update(phase='shielding',attack_dispatches=1)
        self.tick(15)
        self.assertEqual(len(self.commands('combat_start')),1)
        self.assertEqual(self.d.started_target,TARGET)
        self.assertEqual(self.d.ranged_memory.records[TARGET]['dispatches'],1)
    def test_all_selected_hostile_types_share_closing_policy(self):
        for kind in ('minecraft:zombie','minecraft:husk','minecraft:drowned','minecraft:creeper','minecraft:skeleton','minecraft:witch'):
            with self.subTest(kind=kind):
                q=RangedQueue();q.obs['state']['nearby']['entities'][0]['type']=kind
                dog=Watchdog(q,clock=lambda:self.now);dog.latest=copy.deepcopy(q.obs)
                dog.send('start_combat',{'op':'combat_start','target_uuid':TARGET,'approach':False,'shield':True})
                self.assertEqual(q.calls[-1][1]['approach'],True)
                self.assertEqual(q.calls[-1][1]['shield'],kind!='minecraft:witch')
    def test_unreachable_melee_and_ranged_have_distinct_short_exclusions(self):
        m=RangedMemory();state=self.q.obs['state'];zombie=state['nearby']['entities'][0]
        m.begin(state,zombie,0);self.assertEqual(m.suppress(TARGET,3,'no_progress'),13)
        target=witch();target['uuid']='witch-test';m.begin(state,target,0)
        self.assertEqual(m.suppress('witch-test',3,'no_progress'),33)
    def test_inherited_hostile_lock_missing_from_nearby_still_has_deadline(self):
        self.q.obs['state']['nearby']['entities']=[]
        self.q.obs['combat']={'active':True,'target_uuid':TARGET,'target_type':'minecraft:zombie',
                             'phase':'waiting_in_range','attack_dispatches':0,'request_id':'inherited',
                             'melee_closing_schema_version':2}
        self.q.terrain={'complete':False,'cells':[]}
        self.tick(80)
        self.assertIsNone(self.d.started_target)
        self.assertEqual(self.d.phase,'watching')
        self.assertEqual(self.commands('action'),[])
        self.assertEqual(len(self.commands('cancel')),1)
        self.assertIsNone(self.d.ranged_memory.records[TARGET]['best_distance'])

    def test_inherited_combat_with_explicit_health_progress_is_not_falsely_stalled(self):
        self.q.obs['state']['nearby']['entities']=[]
        self.q.obs['combat']={'active':True,'target_uuid':TARGET,'target_type':'minecraft:zombie',
                             'phase':'shielding','attack_dispatches':1,'request_id':'inherited',
                             'observed_target_health':20,'melee_closing_schema_version':2}
        self.tick(3)
        for health in range(19,5,-1):
            self.q.obs['combat']['observed_target_health']=health
            self.q.obs['combat']['attack_dispatches']+=1
            self.tick(6)
        self.assertTrue(self.d.armed);self.assertEqual(self.d.started_target,TARGET)
        self.assertEqual(self.commands('cancel'),[])

    def test_zombie_reentry_does_not_restart_progress_budget(self):
        m=RangedMemory();state=self.q.obs['state'];target=state['nearby']['entities'][0]
        m.begin(state,target,0);m.begin(state,target,2)
        reason=m.observe(state,target,{'active':True,'target_uuid':TARGET,'request_id':'second',
                                      'attack_dispatches':0},3,False)
        self.assertEqual(m.records[TARGET]['started_at'],0)
        self.assertEqual(reason,'no_observed_closing_progress')

if __name__=='__main__':unittest.main()

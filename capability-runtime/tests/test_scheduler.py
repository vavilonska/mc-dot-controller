import tempfile
import unittest
from mdc_skills.core import Runtime, Outcome, SkillError
from mdc_skills.scheduler import Registry, SkillSpec, Scheduler, KnowledgeStore
from support_core import Clock, Client, move, arrived

class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.clock = Clock()
        self.client = Client(self.clock)
        self.runtime = Runtime(self.client, self.tmp.name, clock=self.clock, sleeper=self.clock.sleep)
        self.registry = Registry()
        self.registry.register(SkillSpec('walk', lambda rt: rt.execute('walk', move(), arrived), lambda a: not a))
        self.scheduler = Scheduler(self.runtime, self.registry, wall_clock=self.clock)
    def tearDown(self):
        self.runtime.close(); self.tmp.cleanup()
    def test_json_end_battle_wrapper_constructs_concrete_crystal_goals(self):
        from unittest.mock import patch
        from mdc_skills.registry import default_registry
        from mdc_skills.dimensions import CrystalGoal
        source = {'uuid': 'loaded-crystal', 'firing_station': {'x': 1, 'y': 70, 'z': 2}}
        with patch('mdc_skills.dimensions.end_battle', return_value=Outcome('blocked','fixture')) as execute:
            default_registry().get('end_battle').run(self.runtime, 'loaded-dragon', crystals=[source])
        crystal = execute.call_args.kwargs['crystals'][0]
        self.assertIsInstance(crystal, CrystalGoal)
        self.assertEqual(crystal.uuid, 'loaded-crystal')
        crystal.firing_station['x'] = 99
        self.assertEqual(source['firing_station']['x'], 1)

    def test_dependency_order_and_completed_no_repeat(self):
        self.scheduler.add('first', 'walk', {})
        self.scheduler.add('second', 'walk', {}, dependencies=('first',), priority=20)
        self.assertTrue(self.scheduler.advance().ok)
        self.assertEqual(self.scheduler.status('first')['state'], 'succeeded')
        self.assertTrue(self.scheduler.advance().ok)
        self.assertEqual(self.scheduler.advance().reason, 'no_runnable_goal')
        self.assertEqual(self.client.action_count, 2)
    def test_priority_selects_ready_goal(self):
        self.scheduler.add('low', 'walk', {}, priority=-1)
        self.scheduler.add('high', 'walk', {}, priority=2)
        self.scheduler.advance()
        self.assertEqual(self.scheduler.status('high')['state'], 'succeeded')
        self.assertEqual(self.scheduler.status('low')['state'], 'ready')
    def test_missing_dependencies_rejected(self):
        with self.assertRaisesRegex(SkillError, 'dependencies'):
            self.scheduler.add('bad', 'walk', {}, dependencies=('missing',))
    def test_goal_identity_tombstone(self):
        self.scheduler.add('first', 'walk', {})
        self.scheduler.advance()
        with self.assertRaisesRegex(SkillError, 'consumed'):
            self.scheduler.add('first', 'walk', {})
    def test_deadline_does_not_submit(self):
        self.scheduler.add('first', 'walk', {}, deadline_seconds=1)
        self.clock.now += 2
        self.assertFalse(self.scheduler.advance().ok)
        self.assertEqual(self.client.action_count, 0)
    def test_action_must_fit_remaining_deadline(self):
        self.scheduler.add('first', 'walk', {}, deadline_seconds=1)
        self.clock.now += .1
        self.assertEqual(self.scheduler.advance().reason, 'action_exceeds_remaining_goal_deadline')
        self.assertEqual(self.client.action_count, 0)
    def test_failed_dependency_blocks_downstream(self):
        self.registry.register(SkillSpec('blocked', lambda rt: Outcome('blocked', 'no_material'), lambda a: True))
        self.scheduler.add('first', 'blocked', {})
        self.scheduler.add('second', 'walk', {}, dependencies=('first',))
        self.scheduler.advance(); self.scheduler.advance()
        self.assertEqual(self.scheduler.status('second')['reason'], 'dependency_not_succeeded')
        self.assertEqual(self.client.action_count, 0)
    def test_action_budget_not_refunded(self):
        def twice(rt):
            rt.require_success(rt.execute('walk', move(), arrived))
            return rt.execute('walk', move(), arrived)
        self.registry.register(SkillSpec('twice', twice, lambda a: True))
        self.scheduler.add('first', 'twice', {}, max_actions=1)
        self.assertEqual(self.scheduler.advance().reason, 'goal_action_budget_exhausted')
        self.assertEqual(self.client.action_count, 1)
        self.assertEqual(self.scheduler.status('first')['actions_reserved'], 1)
    def test_restart_freezes_ready_goals(self):
        self.scheduler.add('first', 'walk', {})
        later = Scheduler(self.runtime, self.registry, wall_clock=self.clock)
        self.assertEqual(later.status('first')['state'], 'interrupted')
        self.assertFalse(later.advance().ok)
        self.assertEqual(self.client.action_count, 0)
    def test_resume_without_predicate_is_denied(self):
        self.scheduler.add('first', 'walk', {})
        self.scheduler = Scheduler(self.runtime, self.registry, wall_clock=self.clock)
        with self.assertRaisesRegex(SkillError, 'manual_replanning'):
            self.scheduler.resume('first')
    def test_resume_predicate_observed_success_does_not_reexecute(self):
        self.registry.register(SkillSpec('observed', lambda rt: rt.execute('walk', move(), arrived),
            lambda a: True, lambda rt: rt.result('observed', (rt.observe(),), goal='already satisfied')))
        self.scheduler.add('first', 'observed', {})
        self.scheduler = Scheduler(self.runtime, self.registry, wall_clock=self.clock)
        result = self.scheduler.resume('first')
        self.assertEqual(result['state'], 'succeeded')
        self.assertEqual(self.client.action_count, 0)
    def test_resume_unmet_needs_explicit_fresh_safe_evidence(self):
        self.registry.register(SkillSpec('unsafe', lambda rt: Outcome('blocked', 'no'), lambda a: True,
            lambda rt: Outcome('blocked', 'unmet')))
        self.scheduler.add('first', 'unsafe', {})
        self.scheduler = Scheduler(self.runtime, self.registry, wall_clock=self.clock)
        with self.assertRaisesRegex(SkillError, 'safe_replanning'):
            self.scheduler.resume('first')
    def test_cancel_only_queued_and_no_native_cancel(self):
        self.scheduler.add('first', 'walk', {})
        self.scheduler.cancel('first')
        self.assertEqual(self.scheduler.status('first')['state'], 'cancelled')
        self.assertEqual(self.client.calls, [])
    def test_unknown_blocks_scheduler_and_no_next_action(self):
        self.client.mode = 'pending'
        self.scheduler.add('first', 'walk', {})
        self.scheduler.add('second', 'walk', {})
        self.assertEqual(self.scheduler.advance().status, 'unknown')
        with self.assertRaisesRegex(SkillError, 'unresolved_execution'):
            self.scheduler.advance()
        self.assertEqual(self.client.action_count, 1)
    def test_memory_is_historical_only_and_cannot_refresh(self):
        knowledge = KnowledgeStore(self.runtime)
        observed = self.runtime.observe()
        knowledge.remember('home', observed, kind='landmark', value={'x': 1, 'y': 64, 'z': 2})
        self.clock.now += 10
        remembered = knowledge.recall('home', context=observed.context)
        self.assertTrue(remembered['historical_only'])
        self.assertFalse(remembered['action_evidence'])
        self.assertTrue(remembered['requires_fresh_observation'])
        self.assertEqual(remembered['source_capture_monotonic'], observed.captured_at)
        self.assertIsNone(knowledge.recall('unknown'))
    def test_knowledge_rejects_stale_write(self):
        observed = self.runtime.observe()
        self.clock.now += 1
        with self.assertRaisesRegex(SkillError, 'stale'):
            KnowledgeStore(self.runtime).remember('home', observed, kind='landmark', value={})

if __name__ == '__main__': unittest.main()

class SchedulerScaleTests(unittest.TestCase):
    setUp=SchedulerTests.setUp
    tearDown=SchedulerTests.tearDown
    def test_large_goal_import_is_hash_bound_and_checkpoint_small(self):
        import json
        self.registry.register(SkillSpec('large',lambda rt, blueprint:rt.result('large',[rt.observe()],cells=len(blueprint)),lambda _:True))
        cells=[{'position':{'x':i,'y':64,'z':0},'block':'minecraft:stone','properties':{}} for i in range(8192)]
        status=self.scheduler.add('house','large',{'blueprint':cells},max_actions=16000)
        self.assertIsNone(status['arguments']);self.assertIn('arguments_ref',status)
        self.assertLess(self.scheduler.path.stat().st_size,5000)
        self.assertTrue(self.scheduler.advance().ok)
        later=Scheduler(self.runtime,self.registry,wall_clock=self.clock)
        self.assertEqual(later.status('house')['state'],'succeeded')
    def test_goal_import_tamper_rejected_on_reopen(self):
        self.registry.register(SkillSpec('large',lambda **_:None,lambda _:True))
        status=self.scheduler.add('house','large',{'text':'x'*40000},max_actions=4096)
        (self.runtime.journal_directory/status['arguments_ref']['file']).write_text('{}')
        with self.assertRaisesRegex(SkillError,'goal_input_hash_mismatch'):
            Scheduler(self.runtime,self.registry,wall_clock=self.clock)
    def test_bound_runtime_exposes_remaining_original_budget(self):
        seen=[]
        def run(rt):
            seen.append(rt.effective_remaining_budget())
            rt.require_success(rt.execute('walk',move(),arrived))
            seen.append(rt.effective_remaining_budget())
            return rt.result('done',[rt.observe()])
        self.registry.register(SkillSpec('budget',run,lambda _:True))
        self.scheduler.add('budget','budget',{},max_actions=4096,deadline_seconds=200)
        self.assertTrue(self.scheduler.advance().ok)
        self.assertEqual([v['remaining_actions'] for v in seen],[4096,4095])
        self.assertEqual(seen[0]['deadline_unix'],seen[1]['deadline_unix'])
    def test_late_goal_result_does_not_become_success(self):
        def run(rt):
            observation=rt.observe();self.clock.now+=2
            return Outcome('succeeded','late',(),{'server_confirmed':False},observation)
        self.registry.register(SkillSpec('late',run,lambda _:True))
        self.scheduler.add('late','late',{},deadline_seconds=1)
        self.assertEqual(self.scheduler.advance().reason,'goal_deadline_exceeded')
    def test_survey_return_after_original_deadline_blocks(self):
        from unittest.mock import patch
        def survey(*args,**kwargs):self.clock.now+=2;return object()
        def run(rt):rt.survey();return rt.result('bad',[rt.observe()])
        self.registry.register(SkillSpec('survey',run,lambda _:True))
        self.scheduler.add('survey','survey',{},deadline_seconds=1)
        with patch.object(self.runtime,'survey',survey):
            self.assertEqual(self.scheduler.advance().reason,'goal_deadline_exceeded')
        self.assertEqual(self.client.action_count,0)

class SchedulerRevalidationBoundaryTests(unittest.TestCase):
    setUp=SchedulerTests.setUp
    tearDown=SchedulerTests.tearDown
    def test_revalidation_predicate_cannot_dispatch_mutation(self):
        self.registry.register(SkillSpec('unsafe',lambda rt:None,lambda _:True,
            lambda rt:rt.execute('forbidden',move(),arrived)))
        self.scheduler.add('unsafe','unsafe',{})
        self.scheduler=Scheduler(self.runtime,self.registry,wall_clock=self.clock)
        with self.assertRaisesRegex(SkillError,'resume_revalidation_is_read_only'):self.scheduler.resume('unsafe')
        self.assertEqual(self.client.action_count,0)
    def test_revalidation_cannot_claim_stale_observation_success(self):
        old=self.runtime.observe();self.clock.now+=1
        self.registry.register(SkillSpec('stale',lambda rt:None,lambda _:True,
            lambda rt:Outcome('succeeded','old',(),{'server_confirmed':False},old)))
        self.scheduler.add('stale','stale',{})
        self.scheduler=Scheduler(self.runtime,self.registry,wall_clock=self.clock)
        with self.assertRaisesRegex(SkillError,'preflight_observation_stale'):self.scheduler.resume('stale')
        self.assertEqual(self.scheduler.status('stale')['state'],'interrupted')

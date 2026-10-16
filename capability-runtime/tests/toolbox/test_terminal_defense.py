import threading
import time
import unittest
from mdc_toolbox.control import ControlStop, JobControl
from mdc_toolbox.terminal_defense import TerminalDefensiveSupervisor


class TerminalDefenseTests(unittest.TestCase):
    def make(self, *, reaction='defend_once', reserve=1, handler=None):
        events, calls = [], []
        control = JobControl({'job_id':'job', 'request_id':'request',
            'deadline_at':time.time()+30, 'cancel_event':threading.Event(),
            'emit':lambda event, value: events.append((event, value)),
            'budget':{'max_actions':4, 'max_observations':10,
                'cleanup_reserve_actions':1, 'reflex_reserve_actions':reserve}})
        def defend(facts, owner):
            calls.append((facts, owner))
            self.assertIs(owner, control)
            self.assertEqual(owner.lane, 'reflex')
            owner.consume('actions')
            return handler(facts, owner) if handler else {'status':'succeeded', 'cleanup_confirmed':True}
        supervisor=TerminalDefensiveSupervisor(control, {'reactions':reaction}, reflexes={'defend_once':defend})
        return supervisor, control, calls, events

    def run_boundary(self, supervisor, **kwargs):
        args=dict(reason='capability_damage_observed', cleanup_confirmed=True,
                  owner_known=True, context_same=True, facts={'target_uuid':'explicit'})
        args.update(kwargs)
        with self.assertRaises(ControlStop) as caught:
            supervisor.defend_once(**args)
        return caught.exception

    def test_success_is_terminal_and_debits_original_reflex_lane(self):
        sup, control, calls, events=self.make()
        result=self.run_boundary(sup)
        self.assertEqual(result.reason, 'ordinary_task_interrupted_after_defense')
        self.assertEqual(len(calls), 1)
        self.assertEqual(control.budget.snapshot()['used']['reflex']['actions'], 1)
        self.assertEqual(control.lane, 'ordinary')
        self.assertFalse(events[-1][1]['ordinary_resume_allowed'])
        with self.assertRaises(ControlStop):
            with sup.ordinary(): self.fail('ordinary task resumed')
        self.assertEqual(self.run_boundary(sup).reason, 'supervisor_boundary_latched')
        self.assertEqual(len(calls), 1)

    def test_stop_default_and_missing_opt_in_do_not_dispatch(self):
        for reaction in ('stop', 'defend', 'avoid'):
            sup, _, calls, _=self.make(reaction=reaction)
            self.assertEqual(self.run_boundary(sup).reason, 'defense_not_opted_in')
            self.assertFalse(calls)

    def test_unknown_owner_or_cleanup_never_dispatch(self):
        for key in ('owner_known', 'cleanup_confirmed'):
            for value in (False, None, 1):
                sup, _, calls, _=self.make()
                self.assertEqual(self.run_boundary(sup, **{key:value}).status, 'unknown')
                self.assertFalse(calls)

    def test_changed_context_never_dispatch(self):
        sup, _, calls, _=self.make()
        self.assertEqual(self.run_boundary(sup, context_same=False).reason, 'defense_context_changed')
        self.assertFalse(calls)

    def test_environment_hazard_does_not_trigger_attack(self):
        sup, _, calls, _=self.make()
        self.assertEqual(self.run_boundary(sup, reason='capability_environment_hazard').reason, 'defense_trigger_unsupported')
        self.assertFalse(calls)

    def test_cancel_precedes_defense(self):
        sup, control, calls, _=self.make()
        control.cancel_event.set()
        self.assertEqual(self.run_boundary(sup).status, 'cancelled')
        self.assertFalse(calls)

    def test_no_reserve_never_dispatch(self):
        sup, _, calls, _=self.make(reserve=0)
        self.assertEqual(self.run_boundary(sup).reason, 'original_reflex_budget_exhausted')
        self.assertFalse(calls)

    def test_unknown_result_never_retries(self):
        sup, _, calls, _=self.make(handler=lambda *_: {'status':'unknown', 'cleanup_confirmed':True})
        self.assertEqual(self.run_boundary(sup).status, 'unknown')
        self.run_boundary(sup)
        self.assertEqual(len(calls), 1)

    def test_unconfirmed_cleanup_is_unknown(self):
        sup, _, _, _=self.make(handler=lambda *_: {'status':'succeeded', 'cleanup_confirmed':False})
        self.assertEqual(self.run_boundary(sup).status, 'unknown')

    def test_callback_exception_latches_before_dispatch(self):
        def fail(*_): raise RuntimeError('lost acknowledgement')
        sup, control, calls, _=self.make(handler=fail)
        with self.assertRaises(RuntimeError): sup.defend_once(reason='capability_damage_observed', cleanup_confirmed=True, owner_known=True, context_same=True)
        self.assertEqual(control.lane, 'ordinary')
        self.run_boundary(sup)
        self.assertEqual(len(calls), 1)


if __name__ == '__main__': unittest.main()

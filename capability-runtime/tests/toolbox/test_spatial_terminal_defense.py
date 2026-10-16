import unittest
if __package__:
    from . import test_terminal_defense as original
else:
    import test_terminal_defense as original


class SpatialTerminalDefenseTests(unittest.TestCase):
    make = original.TerminalDefenseTests.make
    run_boundary = original.TerminalDefenseTests.run_boundary

    def test_typed_threat_keeps_original_terminal_lane(self):
        sup, control, calls, events = self.make()
        result = self.run_boundary(sup, reason='capability_threat_observed')
        self.assertEqual(result.reason, 'ordinary_task_interrupted_after_defense')
        self.assertEqual(len(calls), 1)
        self.assertEqual(control.budget.snapshot()['used']['reflex']['actions'], 1)
        self.assertEqual(self.run_boundary(sup, reason='capability_threat_observed').reason,
                         'supervisor_boundary_latched')
        self.assertEqual(len(calls), 1)

    def test_stop_only_reports_no_motion_without_route_success(self):
        sup, _, calls, _ = self.make()
        result = self.run_boundary(sup, reason='capability_threat_observed',
                                   facts={'preempted_before_motion': True})
        self.assertEqual(result.status, 'interrupted')
        self.assertEqual(result.reason, 'preempted_before_motion')
        self.assertEqual(len(calls), 1)

    def test_unknown_release_precedes_new_typed_trigger(self):
        sup, _, calls, _ = self.make()
        result = self.run_boundary(sup, reason='capability_threat_observed', cleanup_confirmed=False)
        self.assertEqual(result.status, 'unknown')
        self.assertFalse(calls)


if __name__ == '__main__': unittest.main()

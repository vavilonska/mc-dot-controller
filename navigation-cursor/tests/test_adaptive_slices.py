"""Observed-route batching only; no sockets or live Minecraft fixtures."""
import unittest
from navigation_cursor import LocalTerrain, Navigator, RouteCursor
from test_navigation_cursor import Gateway, observation
from test_drop_policy import descent


class AdaptiveSliceTests(unittest.TestCase):
    def start(self, nodes, *, slice_size=None):
        gateway = Gateway()
        nav = Navigator(gateway, slice_size=slice_size)
        goal = nodes[-1]
        self.assertEqual(nav.tick(goal)['reason'], 'observe_submitted')
        gateway.finish(result=observation(nodes[0], nodes))
        self.assertEqual(nav.tick(goal)['reason'], 'action_submitted')
        return gateway, nav, goal

    def test_default_follows_whole_observed_detour_in_one_action(self):
        nodes = [(4,64,2),(3,64,2),(2,64,2),(2,64,1),
                 (2,64,0),(3,64,0),(4,64,0),(5,64,0),(6,64,0)]
        gateway, nav, goal = self.start(nodes)
        self.assertEqual(len(gateway.commands[-1][1]['waypoints']), 8)
        self.assertEqual(nav.route.nodes, nodes)
        self.assertEqual(nav.route.index, 1)
        gateway.finish()
        self.assertEqual(nav.tick(goal)['status'], 'progress')
        self.assertEqual(nav.route.index, 1)
        nav.tick(goal)
        gateway.finish(result=observation(goal, nodes))
        self.assertEqual(nav.tick(goal)['status'], 'complete')
        self.assertEqual(len([c for _, c in gateway.commands if c['op'] == 'action']), 1)

    def test_explicit_two_waypoints_preserves_old_contract(self):
        gateway, nav, goal = self.start([(x,64,0) for x in range(9)], slice_size=2)
        self.assertEqual(len(gateway.commands[-1][1]['waypoints']), 2)
        self.assertEqual(nav.data['pending']['end_index'], 3)

    def test_unknown_tail_is_retained_and_never_executed(self):
        nodes = [(x,64,0) for x in range(10)]
        route = RouteCursor(nodes)
        terrain = LocalTerrain(observation(nodes[0], nodes[:5]))
        way = route.observed_slice(terrain, nodes[0])
        self.assertEqual(len(way), 4)
        self.assertEqual(route.nodes, nodes)
        self.assertEqual(route.index, 1)

    def test_changed_later_edge_stops_prefix_without_discarding_tail(self):
        nodes = [(x,64,0) for x in range(10)]
        gateway, nav, goal = self.start(nodes, slice_size=2)
        gateway.finish()
        nav.tick(goal)
        nav.slice_size = None
        nav.tick(goal)
        observed = observation(nodes[2], nodes)
        next(c for c in observed['terrain']['cells'] if (c['x'],c['y'],c['z']) == (6,64,0))['known'] = False
        gateway.finish(result=observed)
        self.assertEqual(nav.tick(goal)['reason'], 'action_submitted')
        self.assertEqual(len(gateway.commands[-1][1]['waypoints']), 3)
        self.assertEqual(nav.route.nodes, nodes)
        self.assertEqual(nav.data['replans'], 0)
        self.assertEqual(nav.data['pending']['end_index'], 6)

    def test_drop_is_terminal_boundary_even_with_visible_safe_tail(self):
        observed, start, landing = descent(3)
        tail = (2,89,0)
        observed['terrain']['cells'].extend(observation(landing, [tail])['terrain']['cells'])
        route = RouteCursor([start, landing, tail])
        self.assertEqual(len(route.observed_slice(LocalTerrain(observed), start)), 1)
        self.assertEqual(route.index, 1)

    def test_waypoint_bound_keeps_pending_id_and_tail(self):
        nodes = [(x,64,0) for x in range(42)]
        gateway, nav, goal = self.start(nodes)
        command = gateway.commands[-1][1]
        self.assertEqual(len(command['waypoints']), 32)
        self.assertGreater(command['timeout_ms'], 15000)
        self.assertEqual(nav.data['pending']['end_index'], 33)
        request_id = nav.data['pending']['id']
        count = len(gateway.commands)
        for _ in range(4):
            self.assertEqual(nav.tick(goal)['request_id'], request_id)
        self.assertEqual(len(gateway.commands), count)
        self.assertEqual(nav.route.nodes, nodes)

    def test_adaptive_action_still_carries_observation_defense_epoch(self):
        gateway, nav, goal = self.start([(x,64,0) for x in range(8)])
        self.assertEqual(gateway.commands[-1][1]['_navigation_defense_epoch'], 0)
        gateway.state['defense_epoch'] = 1
        gateway.finish('cancelled', reason='navigation_defense_epoch_changed')
        nav.tick(goal)
        self.assertEqual(nav.tick(goal)['reason'], 'observe_submitted')
        gateway.finish(result=observation((3,64,0), [(x,64,0) for x in range(8)]))
        self.assertEqual(nav.tick(goal)['reason'], 'action_submitted')
        self.assertEqual(gateway.commands[-1][1]['_navigation_defense_epoch'], 1)
        self.assertEqual(nav.data['forbidden'], [])

    def test_invalid_explicit_slice_sizes_fail_before_io(self):
        for value in (0, 33, True, 2.5, 'auto'):
            gateway = Gateway()
            with self.assertRaises(ValueError):
                Navigator(gateway, slice_size=value)
            self.assertEqual(gateway.commands, [])


if __name__ == '__main__':
    unittest.main()

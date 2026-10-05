import copy
import json
import tempfile
import unittest
from pathlib import Path
from navigation_cursor import DropPolicy, LocalTerrain, Navigator, RouteCursor


def observation(position, floor_nodes):
    cells = {}
    for x, y, z in floor_nodes:
        for h in range(y - 1, y + 4):
            key = (x, h, z)
            cells[key] = {'x': x, 'y': h, 'z': z, 'status': 'loaded', 'known': True,
                          'collision_known': True, 'id_truncated': False,
                          'fluid_truncated': False, 'properties_truncated': False,
                          'fluid': 'minecraft:empty', 'hazards': [],
                          'collision_empty': h >= y, 'full_top_support': h == y - 1}
    x, y, z = position
    return {'state': {'world': {'world_generation': 'world-a', 'dimension': 'overworld'},
                      'player': {'x': x + .5, 'y': y, 'z': z + .5, 'on_ground': True,
                                 'alive': True, 'health': 20, 'food': 20}},
            'terrain': {'complete': True, 'world_generation': 'world-a', 'cells': list(cells.values())},
            'action': {'status': 'idle'}, 'combat': {'active': False}}


class Gateway:
    def __init__(self):
        self.state = {'implementation': 'native-defense-watchdog-v2', 'session_id': 'gateway-a',
                      'state': 'ready', 'phase': 'watching', 'defense_epoch': 0}
        self.commands = []
        self.results = {}
    def session(self): return self.state.copy()
    def submit(self, command, request_id=None):
        self.commands.append((request_id, copy.deepcopy(command)))
        return request_id
    def result(self, request_id): return self.results.get(request_id)
    def finish(self, status='succeeded', result=None, **extra):
        self.results[self.commands[-1][0]] = {'status': status, 'result': result or {}, **extra}


class CursorTests(unittest.TestCase):
    def test_slicing_does_not_advance_or_discard_tail(self):
        c = RouteCursor([(x, 92, 0) for x in range(7)])
        self.assertEqual(len(c.slice(2)), 2)
        self.assertEqual((c.index, len(c.nodes)), (1, 7))
        p = observation((2, 92, 0), [])['state']['player']
        c.reconcile(p)
        self.assertEqual(c.index, 3)
        self.assertEqual(c.slice()[0]['x'], 3.5)

    def test_airborne_and_wrong_height_do_not_advance(self):
        c = RouteCursor([(0, 92, 0), (1, 92, 0)])
        p = observation((1, 92, 0), [])['state']['player']
        p['on_ground'] = False
        c.reconcile(p)
        self.assertEqual(c.index, 1)
        p['on_ground'], p['y'] = True, 91
        c.reconcile(p)
        self.assertEqual(c.index, 1)

    def test_cursor_never_rewinds_at_old_prefix(self):
        c = RouteCursor([(x, 92, 0) for x in range(7)], 5)
        c.reconcile(observation((1, 92, 0), [])['state']['player'])
        self.assertEqual(c.index, 5)


class NavigatorTests(unittest.TestCase):
    def setUp(self):
        # Reproduction geometry: the route starts by moving AWAY from its goal.
        self.nodes = [(-115,92,-8),(-116,92,-8),(-117,92,-8),(-117,92,-9),
                      (-117,92,-10),(-116,92,-10),(-115,92,-10),(-114,92,-10),(-113,92,-10)]
        self.gateway = Gateway()
        self.nav = Navigator(self.gateway)
        self.goal = self.nodes[-1]

    def observe(self, position, nodes=None):
        r = self.nav.tick(self.goal)
        self.assertEqual(r['reason'], 'observe_submitted')
        self.gateway.finish(result=observation(position, nodes or self.nodes))
        return self.nav.tick(self.goal)

    def finish_action(self, status='succeeded'):
        self.gateway.finish(status)
        r = self.nav.tick(self.goal)
        self.assertEqual(r['reason'], 'action_terminal_reobserve_before_cursor_advance')
        return r

    def test_two_waypoint_slices_keep_reverse_detour_until_arrival(self):
        r = self.observe(self.nodes[0])
        self.assertEqual(r['status'], 'pending')
        original = self.nav.route.nodes
        for end in (2, 4, 6, 8):
            sent = self.gateway.commands[-1][1]['waypoints']
            self.assertEqual((sent[-1]['x']-.5, sent[-1]['y'], sent[-1]['z']-.5), self.nodes[end])
            before = self.nav.route.index
            self.finish_action()
            self.assertEqual(self.nav.route.index, before)  # Result alone is not arrival.
            r = self.observe(self.nodes[end])
            if end < 8:
                self.assertEqual(self.nav.route.nodes, original)
                self.assertEqual(self.nav.route.index, end + 1)
            else:
                self.assertEqual(r['status'], 'complete')
        self.assertEqual(len([c for _, c in self.gateway.commands if c['op']=='action']), 4)
        self.assertEqual(self.nav.data['replans'], 0)

    def test_pending_is_polled_never_replayed(self):
        self.observe(self.nodes[0])
        count, rid = len(self.gateway.commands), self.nav.data['pending']['id']
        for _ in range(10):
            r = self.nav.tick(self.goal)
            self.assertEqual(r['request_id'], rid)
        self.assertEqual(len(self.gateway.commands), count)

    def test_checkpoint_restart_keeps_tail_and_same_pending_id(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'route.json'
            self.nav = Navigator(self.gateway, path)
            self.observe(self.nodes[0])
            old_id = self.nav.data['pending']['id']
            count = len(self.gateway.commands)
            self.nav = Navigator(self.gateway, path)
            self.assertEqual(self.nav.tick(self.goal)['request_id'], old_id)
            self.assertEqual(len(self.gateway.commands), count)
            self.finish_action()
            self.observe(self.nodes[2])
            self.assertEqual(self.nav.route.index, 3)

    def test_combat_cancellation_waits_then_fresh_observation_and_replans(self):
        self.observe(self.nodes[0])
        self.gateway.state.update(state='busy', phase='combat')
        self.finish_action('cancelled')
        count = len(self.gateway.commands)
        self.assertEqual(self.nav.tick(self.goal)['status'], 'waiting')
        self.assertEqual(len(self.gateway.commands), count)
        self.gateway.state.update(state='ready', phase='watching')
        self.observe(self.nodes[1])
        self.assertEqual(self.nav.route.nodes[0], self.nodes[1])
        self.assertEqual(self.nav.route.nodes[-1], self.goal)
        self.assertEqual(self.nav.data['replans'], 0)
        self.assertEqual(self.nav.data['forbidden'], [])

    def test_failed_edge_is_excluded_not_recomputed_forever(self):
        self.observe(self.nodes[0])
        self.finish_action('failed')
        r = self.observe(self.nodes[0])
        self.assertEqual(r['status'], 'blocked')
        self.assertEqual(self.nav.data['forbidden'], [[list(self.nodes[0]),list(self.nodes[1])]])
        count = len(self.gateway.commands)
        for _ in range(3): self.nav.tick(self.goal)
        self.assertEqual(len(self.gateway.commands), count)

    def test_stuck_selects_alternative_without_same_failed_edge(self):
        nodes = [(x,92,z) for x in range(3) for z in range(2)]
        self.goal = (2,92,0)
        self.observe((0,92,0), nodes)
        self.finish_action('failed')
        self.observe((0,92,0), nodes)
        self.assertEqual(self.nav.route.nodes[1], (0,92,1))
        self.assertNotEqual(self.nav.route.nodes[1], (1,92,0))

    def test_dynamic_obstacle_replans_before_writing_action(self):
        nodes = [(x,92,z) for x in range(5) for z in range(2)]
        self.goal = (4,92,0)
        self.observe((0,92,0), nodes)
        self.finish_action()
        changed = [n for n in nodes if n != (3,92,0)]
        self.observe((2,92,0), changed)
        self.assertEqual(self.nav.route.nodes[1], (2,92,1))
        self.assertEqual(self.nav.data['replans'], 1)

    def test_success_without_arrival_is_not_progress(self):
        self.observe(self.nodes[0])
        self.finish_action()
        r = self.observe(self.nodes[0])
        self.assertEqual(r['status'], 'blocked')

    def test_uncertain_result_blocks_no_new_id(self):
        self.observe(self.nodes[0])
        self.gateway.finish('uncertain')
        count = len(self.gateway.commands)
        self.assertEqual(self.nav.tick(self.goal)['status'], 'blocked')
        self.assertEqual(self.nav.tick(self.goal)['status'], 'blocked')
        self.assertEqual(len(self.gateway.commands), count)

    def test_resident_queue_is_rejected(self):
        self.gateway.state.pop('implementation')
        self.assertEqual(self.nav.tick(self.goal)['reason'], 'watchdog_gateway_required_no_direct_queue')
        self.assertEqual(self.gateway.commands, [])

    def test_watchdog_restart_cannot_replay(self):
        self.observe(self.nodes[0])
        self.gateway.state['session_id'] = 'gateway-b'
        self.assertEqual(self.nav.tick(self.goal)['reason'], 'gateway_restarted_resolve_old_navigation_explicitly')

    def test_expired_observation_is_not_executed(self):
        self.nav.tick(self.goal)
        self.gateway.finish(result=observation(self.nodes[0],self.nodes),finished_at=1)
        self.assertEqual(self.nav.tick(self.goal)['reason'], 'observation_expired_reobserve')
        self.assertEqual(len(self.gateway.commands), 1)

    def test_world_change_blocks_before_action(self):
        self.observe(self.nodes[0])
        self.finish_action()
        self.nav.tick(self.goal)
        o=observation(self.nodes[2],self.nodes)
        o['state']['world']['world_generation']='world-b'
        self.gateway.finish(result=o)
        self.assertEqual(self.nav.tick(self.goal)['status'], 'blocked')

    def test_unknown_floor_and_fluid_are_not_routes(self):
        o=observation((0,92,0),[(0,92,0),(1,92,0)])
        t=LocalTerrain(o)
        self.assertTrue(t.edge((0,92,0),(1,92,0)))
        t.cells[(1,91,0)]['known']=False
        self.assertFalse(t.edge((0,92,0),(1,92,0)))
        t.cells[(1,91,0)]['known']=True
        t.cells[(1,92,0)]['fluid']='minecraft:water'
        self.assertFalse(t.edge((0,92,0),(1,92,0)))

    def test_horizontal_goal_uses_observed_landing_height(self):
        self.goal = (self.nodes[-1][0], self.nodes[-1][2])
        self.observe(self.nodes[0])
        self.assertEqual(self.nav.route.nodes[-1],self.nodes[-1])
        self.finish_action()
        r=self.observe(self.nodes[-1])
        self.assertEqual(r['status'],'complete')

    def test_failed_result_at_slice_endpoint_does_not_block_unattempted_tail(self):
        self.observe(self.nodes[0])
        self.finish_action('failed')
        self.observe(self.nodes[2])
        self.assertEqual(self.nav.data['forbidden'],[])
        self.assertEqual(self.nav.route.index,3)

    def test_v2_without_atomic_defense_epoch_is_explicitly_blocked(self):
        self.gateway.state.pop('defense_epoch')
        self.assertEqual(self.nav.tick(self.goal)['reason'],'watchdog_v3_defense_epoch_required')
        self.assertEqual(self.gateway.commands,[])

    def test_route_guard_uses_epoch_of_the_fresh_observation(self):
        self.observe(self.nodes[0])
        self.assertEqual(self.gateway.commands[-1][1]['_navigation_defense_epoch'],0)

    def test_combat_between_observation_and_action_discards_old_observation(self):
        self.nav.tick(self.goal)
        self.gateway.finish(result=observation(self.nodes[0],self.nodes))
        self.gateway.state['defense_epoch']=1
        r=self.nav.tick(self.goal)
        self.assertEqual(r['reason'],'defense_epoch_changed_reobserve')
        self.assertEqual(len(self.gateway.commands),1)
        self.observe(self.nodes[0])
        self.assertEqual(self.gateway.commands[-1][1]['_navigation_defense_epoch'],1)

    def test_atomic_gateway_rejection_reobserves_instead_of_replaying(self):
        self.observe(self.nodes[0])
        old_id=self.nav.data['pending']['id']
        self.gateway.state['defense_epoch']=1
        self.gateway.finish('cancelled',reason='navigation_defense_epoch_changed')
        self.nav.tick(self.goal)
        self.observe(self.nodes[0])
        self.assertNotEqual(self.nav.data['pending']['id'],old_id)
        self.assertEqual(self.gateway.commands[-1][1]['_navigation_defense_epoch'],1)
        self.assertEqual(self.nav.data['forbidden'],[])

    def test_old_checkpoint_is_rejected_before_any_intent(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'v1.json'
            path.write_text(json.dumps({'schema':1,'pending':{'id':'old-id','kind':'observe'}}))
            with self.assertRaisesRegex(ValueError,'unsupported_navigation_checkpoint'):
                Navigator(self.gateway,path)
        self.assertEqual(self.gateway.commands,[])

    def test_unimplemented_gap_jump_is_not_admitted(self):
        o=observation((0,92,0),[(0,92,0),(3,92,0)])
        self.assertFalse(LocalTerrain(o).edge((0,92,0),(3,92,0)))

if __name__ == '__main__': unittest.main()

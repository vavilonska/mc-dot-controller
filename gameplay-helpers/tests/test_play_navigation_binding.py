"""Pure fake-client contracts for play's observation-bound route producers.

No mailbox, socket, subprocess or Minecraft connection is created. These tests
were authored, but intentionally not run, during the live-test quiet window.
"""
import contextlib
import copy
from collections import deque
import io
import unittest
from unittest.mock import patch

import play


WORLD_ID = "00000000-0000-4000-8000-000000000001"
PLAYER_ID = "00000000-0000-4000-8000-000000000003"
ACTION_SESSION = "00000000-0000-4000-8000-000000000004"
ABSENT = object()
BINDING_FIELDS = ("expected_navigation_epoch", "expected_origin",
                  "expected_world_generation", "expected_player_uuid",
                  "expected_action_session")


def guard(epoch=7, ready=True):
    return {"schema_version": 1, "epoch": epoch, "fresh_binding_required": True,
            "rebind_ready": ready, "stable_ticks": 3 if ready else 1,
            "reason": "position_discontinuity", "large_displacement_threshold": 16,
            "detects_all_teleports": False}


def observation(*, x=0.371234567891, y=64, z=0.712345678912,
                epoch=7, ready=True, missing=False, navigation_guard=ABSENT,
                minimum_x=0, maximum_x=2):
    state = {"world": {"world_generation": WORLD_ID, "game_time": 100,
                       "dimension": "minecraft:overworld"},
             "player": {"uuid": PLAYER_ID, "dimension": "minecraft:overworld",
                        "x": x, "y": y, "z": z, "on_ground": True, "inventory": []},
             "client_action": {"action_session": ACTION_SESSION}}
    if not missing:
        state["world"]["navigation_guard"] = (
            guard(epoch, ready) if navigation_guard is ABSENT
            else copy.deepcopy(navigation_guard))
    cells = [{"x": xx, "y": yy, "z": 0, "collision_empty": yy > 63,
              "full_top_support": yy == 63, "fluid": "minecraft:empty", "hazards": []}
             for xx in range(minimum_x, maximum_x + 1) for yy in range(63, 67)]
    return {"state": state, "terrain": {"cells": cells}}


class MemoryClient:
    def __init__(self, observations):
        self.observations = deque(copy.deepcopy(observations))
        self.commands, self.waits = [], []

    def submit(self, command):
        self.commands.append(copy.deepcopy(command))
        return str(len(self.commands))

    def wait(self, request, timeout):
        self.waits.append((request, timeout))
        command = self.commands[int(request) - 1]
        if command["op"] == "observe":
            if not self.observations:
                raise AssertionError("Unexpected reobservation or unbounded helper loop")
            result = self.observations.popleft()
        elif command["op"] == "action":
            result = {"reason": "offline_action_result"}
        else:
            raise AssertionError("Unexpected helper operation: " + repr(command))
        return {"status": "succeeded", "result": result}

    def actions(self):
        return [command for command in self.commands if command["op"] == "action"]


class PlayBindingChecks(unittest.TestCase):
    def setUp(self):
        play.configure(None)
        self.addCleanup(play.configure, None)
        quiet = contextlib.redirect_stdout(io.StringIO())
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)

    def client(self, observations):
        client = MemoryClient(observations)
        play.configure(client)
        return client

    def assert_binding(self, command, observed):
        state = observed["state"]
        self.assertEqual(command["expected_navigation_epoch"],
                         state["world"]["navigation_guard"]["epoch"])
        self.assertEqual(command["expected_origin"],
                         {key: state["player"][key] for key in ("x", "y", "z")})
        self.assertEqual(command["expected_world_generation"], state["world"]["world_generation"])
        self.assertEqual(command["expected_player_uuid"], state["player"]["uuid"])
        self.assertEqual(command["expected_action_session"],
                         state["client_action"]["action_session"])

    def test_go_carries_exact_raw_planning_position_and_context(self):
        observed = observation(epoch=17)
        original = copy.deepcopy(observed)
        client = self.client([observed])
        play.go((2, 64, 0))
        self.assertEqual(len(client.actions()), 1)
        command = client.actions()[0]
        self.assert_binding(command, original)
        self.assertNotEqual(command["expected_origin"], command["waypoints"][0])
        self.assertEqual(command["waypoints"][-1], {"x": 2.5, "y": 64, "z": 0.5, "jump": False})
        self.assertEqual(observed, original)

    def test_read_action_race_does_not_replace_only_old_plan_binding(self):
        planning = observation(epoch=17)
        newer = observation(epoch=18, x=0.812345678912, z=0.231234567891)
        client = self.client([planning, newer])
        actual_path = play.path

        def plan_then_observe(o, target):
            planned = actual_path(o, target)
            play.obs()
            return planned

        with patch.object(play, "path", side_effect=plan_then_observe):
            play.go((2, 64, 0))
        self.assertEqual([command["op"] for command in client.commands],
                         ["observe", "observe", "action"])
        self.assert_binding(client.actions()[0], planning)

    def test_travel_binds_each_leg_to_that_legs_observation(self):
        first = observation(epoch=3, maximum_x=1)
        second = observation(epoch=4, x=1.278912345678, z=0.678912345678,
                             minimum_x=1, maximum_x=2)
        arrival = observation(epoch=4, x=2.612345678912, minimum_x=2, maximum_x=2)
        client = self.client([first, second, arrival])
        result = play.travel((2, 64, 0))
        self.assertEqual(len(client.actions()), 2)
        self.assert_binding(client.actions()[0], first)
        self.assert_binding(client.actions()[1], second)
        self.assertEqual(result, arrival)
        self.assertEqual([len(command["waypoints"]) for command in client.actions()], [1, 1])

    def test_missing_guard_on_next_travel_leg_stops_before_second_action(self):
        client = self.client([observation(maximum_x=1),
                              observation(missing=True, x=1.3, minimum_x=1, maximum_x=2)])
        with self.assertRaisesRegex(ValueError, "navigation_guard_missing_after_seen"):
            play.travel((2, 64, 0))
        self.assertEqual(len(client.actions()), 1)

    def test_seen_capability_survives_separate_go_calls(self):
        client = self.client([observation(), observation(missing=True)])
        play.go((1, 64, 0))
        with self.assertRaisesRegex(ValueError, "navigation_guard_missing_after_seen"):
            play.go((2, 64, 0))
        self.assertEqual(len(client.actions()), 1)

    def test_reconfiguring_same_client_does_not_reset_seen(self):
        client = self.client([observation(), observation(missing=True)])
        play.obs()
        play.configure(client)
        with self.assertRaisesRegex(ValueError, "navigation_guard_missing_after_seen"):
            play.go((1, 64, 0))
        self.assertEqual(client.actions(), [])

    def test_nonmovement_observation_records_capability_before_first_go(self):
        client = self.client([observation(), observation(missing=True)])
        play.obs()
        with self.assertRaisesRegex(ValueError, "navigation_guard_missing_after_seen"):
            play.go((1, 64, 0))
        self.assertEqual(client.actions(), [])

    def test_explicit_null_or_bad_schema_then_missing_cannot_become_legacy(self):
        malformed = [None, [], {}, {**guard(), "schema_version": 2},
                     {**guard(), "epoch": "7"}, {**guard(), "rebind_ready": 1}]
        for value in malformed:
            with self.subTest(guard=value):
                client = self.client([observation(navigation_guard=value), observation(missing=True)])
                with self.assertRaisesRegex(ValueError, "navigation_guard_invalid"):
                    play.obs()
                play.configure(client)
                with self.assertRaisesRegex(ValueError, "navigation_guard_missing_after_seen"):
                    play.go((1, 64, 0))
                self.assertEqual(client.actions(), [])

    def test_unready_observation_is_readable_but_go_does_not_move(self):
        client = self.client([observation(ready=False), observation(ready=False)])
        read = play.obs()
        self.assertIs(read["state"]["world"]["navigation_guard"]["rebind_ready"], False)
        with self.assertRaises(ValueError):
            play.go((1, 64, 0))
        self.assertEqual(client.actions(), [])

    def test_go_rejects_nonfinite_raw_origin_before_submitting_movement(self):
        for field, value in (("x", float("nan")), ("y", float("inf")),
                             ("z", float("-inf")), ("x", True), ("x", "0.5")):
            with self.subTest(field=field, value=value):
                invalid = observation()
                invalid["state"]["player"][field] = value
                client = self.client([invalid])
                with self.assertRaisesRegex(ValueError, "navigation_guard_invalid"):
                    play.go((1, 64, 0))
                self.assertEqual(client.actions(), [])

    def test_legacy_go_keeps_legacy_wire_body(self):
        client = self.client([observation(missing=True)])
        play.go((1, 64, 0))
        self.assertEqual(len(client.actions()), 1)
        for key in BINDING_FIELDS:
            self.assertNotIn(key, client.actions()[0])

    def test_raw_run_preserves_explicit_stale_binding_without_a_new_read(self):
        client = self.client([observation(epoch=27)])
        play.obs()
        command = {"op": "action", "action": "follow_path",
                   "waypoints": [{"x": 31.5, "y": 88, "z": -17.5}],
                   "expected_navigation_epoch": 3,
                   "expected_origin": {"x": 31.123456789123, "y": 88, "z": -17.123456789123},
                   "expected_world_generation": "earlier-world",
                   "expected_player_uuid": "earlier-player",
                   "expected_action_session": "earlier-session"}
        original = copy.deepcopy(command)
        play.run(command)
        self.assertEqual(client.commands, [{"op": "observe"}, original])
        self.assertEqual(command, original)

    def test_raw_run_does_not_fill_in_a_partial_pair(self):
        client = self.client([observation(epoch=27)])
        play.obs()
        for fields in ({"expected_origin": {"x": 31.25, "y": 88, "z": -17.75}},
                       {"expected_navigation_epoch": 3}):
            command = {"op": "action", "action": "follow_path", "waypoints": [], **fields}
            original = copy.deepcopy(command)
            play.run(command)
            self.assertEqual(client.commands[-1], original)
            self.assertEqual(command, original)
        self.assertEqual(sum(command["op"] == "observe" for command in client.commands), 1)

    def test_raw_observe_uses_the_same_capability_context_as_obs(self):
        client=self.client([observation(),observation(missing=True)])
        play.run({'op':'observe'})
        with self.assertRaisesRegex(ValueError,'navigation_guard_missing_after_seen'):
            play.go((1,64,0))
        self.assertEqual([],client.actions())

    def test_raw_invalid_observe_marks_seen_before_raising(self):
        client=self.client([observation(navigation_guard=None),observation(missing=True)])
        with self.assertRaisesRegex(ValueError,'navigation_guard_invalid_schema'):
            play.run({'op':'observe'})
        with self.assertRaisesRegex(ValueError,'navigation_guard_missing_after_seen'):
            play.go((1,64,0))
        self.assertEqual([],client.actions())

    def test_definite_native_rejection_remembers_capability_without_retry(self):
        client=self.client([observation(missing=True),observation(missing=True)])
        old_wait=client.wait
        def wait(request,timeout):
            if client.commands[int(request)-1]['op']=='action':
                return {'status':'failed','reason':'navigation_rebind_required','action_admission':{
                    'schema_version':1,'http_status':409,'admitted':False,'uncertain':False,
                    'reason':'navigation_rebind_required'}}
            return old_wait(request,timeout)
        client.wait=wait
        with self.assertRaisesRegex(RuntimeError,'navigation_rebind_required'):
            play.go((1,64,0))
        self.assertEqual(1,len(client.actions()))
        with self.assertRaisesRegex(ValueError,'navigation_guard_missing_after_seen'):
            play.go((1,64,0))
        self.assertEqual(1,len(client.actions()))

    def test_travel_cannot_rebind_the_same_goal_across_world_player_or_session(self):
        for section,key in [('world','world_generation'),('world','dimension'),('player','uuid'),('client_action','action_session')]:
            first=observation(maximum_x=1);second=observation(x=1.5,minimum_x=1,maximum_x=2)
            second['state'][section][key]='new-context'
            if section=='world' and key=='dimension':second['state']['player']['dimension']='new-context'
            client=self.client([first,second])
            with self.assertRaisesRegex(ValueError,'navigation_context_changed'):
                play.travel((2,64,0))
            self.assertEqual(1,len(client.actions()))



if __name__ == "__main__":
    unittest.main()

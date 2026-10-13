"""Offline state-machine/geometry regressions; no physical game is simulated."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from mdc_skills.core import Outcome, SkillError
from mdc_skills.building import build, plan_build, CellBlueprint, reconcile_build_progress
from building_controller.model import Pos

_source = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("_existing_building_fixture", _source / "building-controller/tests/helpers.py")
_fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixture)


def generic(cells, region=None):
    positions = [Pos(*pos) for pos, _ in cells]
    if region is None:
        region = {"min": {k: min(getattr(p, k) for p in positions) for k in ("x", "y", "z")},
                  "max": {k: max(getattr(p, k) for p in positions) for k in ("x", "y", "z")}}
    return {"schema_version": 2, "region": region, "cells": [
        {"position": pos.json(), "block": block, "properties": {}} for pos, (_, block) in zip(positions, cells)]}


class BuildingRuntime:
    def __init__(self, *, stock=None, overrides=None, radius=4):
        self.directory = tempfile.TemporaryDirectory()
        self.journal_directory = Path(self.directory.name)
        self.state = _fixture.state(stock)
        self.state.update(screen_open=False)
        self.state["player"].update(health=20., uuid="offline-player", on_ground=True,
            eye_position={"x": -2.5, "y": 65.62, "z": -2.5}, block_interaction_range=4.5,
            velocity={"x": 0., "y": 0., "z": 0.}, selected_slot=0)
        self.context = (_fixture.WORLD, "minecraft:overworld", "offline-player", "native-session")
        self.cells = {Pos.parse(c): deepcopy(c) for page in _fixture.pages(overrides=overrides, radius=radius)
                      for c in page["cells"]}
        self.radius = radius
        self.time = 0.
        self.clock = lambda: self.time
        self.sleeper = lambda seconds: setattr(self, "time", self.time + seconds)
        self.actions = []
        self.place_count = 0
        self.fail_place = None
        self.lost_reply_applies = False
        self.consume = True
        self.corrupt_after = None
        self.serial = 0

    def close(self):
        self.directory.cleanup()

    def observe(self, **kwargs):
        self.serial += 1
        self.state["world"]["game_time"] += 1
        state = deepcopy(self.state)
        for row in state["player"]["inventory"]:
            row["item_fingerprint"] = repr((row["id"], row["count"]))
            row["component_fingerprint"] = row["id"] or "empty"
        terrain = {"complete": True, "origin": {"x": 0, "y": 64, "z": 0}, "radius": self.radius,
                   "vertical": 4, "world_generation": _fixture.WORLD, "dimension": "minecraft:overworld",
                   "scan_generation": _fixture.SCAN, "source_tick": state["world"]["game_time"],
                   "last_tick": state["world"]["game_time"], "capture_started_mono": self.time,
                   "capture_finished_mono": self.time, "cells": deepcopy(list(self.cells.values()))}
        return SimpleNamespace(state=state, player=state["player"], terrain=terrain,
                               context=self.context, tick=state["world"]["game_time"],
                               captured_at=self.time, request_id="obs-" + str(self.serial))

    def execute(self, skill, command, verify, *, before, **kwargs):
        self.actions.append(deepcopy(command))
        rid = "native-" + str(len(self.actions))
        action = command["action"]
        if action == "follow_path":
            target = command["waypoints"][-1]
            self.state["player"].update(target)
            self.state["player"]["eye_position"] = dict(target, y=target["y"] + 1.62)
        elif action == "select_hotbar":
            self.state["player"]["selected_slot"] = command["hotbar_slot"]
        elif action == "place_block":
            self.place_count += 1
            from mdc_skills.building import FACES
            support = Pos.parse(command["support"])
            dx, dy, dz = FACES[command["face"]]
            target = support.offset(dx, dy, dz)
            assert self.cells[support]["id"] == command["expected_support_id"]
            assert self.cells[target]["id"] == command["expected_target_id"]
            assert self.cells[support]["properties"] == command["expected_support_properties"]
            assert command["expected_block_properties"] == {}
            fail = self.place_count == self.fail_place
            if not fail or self.lost_reply_applies:
                self.cells[target] = _fixture.cell(target, command["expected_block_id"])
                if self.corrupt_after:
                    self.cells[target].update(self.corrupt_after)
                if self.consume:
                    source = self.state["player"]["inventory"][command["hotbar_slot"]]
                    assert source["id"] == command["expected_block_id"]
                    source["count"] -= 1
                    if source["count"] == 0:
                        source.update(id="", empty=True)
            if fail:
                return Outcome("unknown", "transport_lost_no_replay", (rid,))
        else:
            raise AssertionError("unexpected " + action)
        for _ in range(2):
            after = self.observe(terrain=True)
            if not verify(before, after):
                return Outcome("blocked", "semantic_postcondition_failed", (rid,), {}, after)
        return Outcome("succeeded", "client_observed_stable", (rid,), {}, after)

    @staticmethod
    def require_success(outcome):
        if not outcome.ok:
            raise SkillError(outcome.reason, status=outcome.status,
                             request_id=outcome.request_ids[-1] if outcome.request_ids else None)
        return outcome.last_observation

    @staticmethod
    def result(skill, observations=(), **evidence):
        return Outcome("succeeded", "goal_observed", tuple(o.request_id for o in observations),
                       dict(evidence, server_confirmed=False), observations[-1])


class BuildingTests(unittest.TestCase):
    def runtime(self, **kwargs):
        runtime = BuildingRuntime(**kwargs)
        self.addCleanup(runtime.close)
        return runtime

    def test_legacy_template_actual_place_and_verify(self):
        runtime = self.runtime()
        result = build(runtime, _fixture.blueprint(width=2, extent=1), job_id="legacy")
        self.assertTrue(result.ok)
        self.assertEqual(result.evidence["placements_this_call"], 2)
        self.assertEqual(runtime.place_count, 2)
        self.assertFalse(result.evidence["server_confirmed"])
        checkpoint = json.loads((runtime.journal_directory / "building-legacy.json").read_text())
        self.assertEqual(checkpoint["status"], "complete")
        self.assertEqual(len(checkpoint["completed"]), 2)
        self.assertIsNone(checkpoint["pending"])

    def test_generic_three_dimensional_support_order(self):
        runtime = self.runtime()
        spec = generic([((0, 65, 0), "minecraft:stone_bricks"),
                        ((0, 64, 0), "minecraft:oak_planks"),
                        ((1, 65, 0), "minecraft:oak_planks")])
        result = build(runtime, spec, job_id="three-d")
        self.assertEqual(result.evidence["exact_cells_verified"], 3)
        calls = [c for c in runtime.actions if c["action"] == "place_block"]
        self.assertEqual(calls[0]["expected_block_id"], "minecraft:oak_planks")
        self.assertTrue(any(c["hotbar_slot"] == 1 for c in calls))

    def test_plan_has_material_support_stand_and_no_actions(self):
        runtime = self.runtime()
        proposal = plan_build(runtime, _fixture.blueprint(width=2, extent=1))
        self.assertFalse(proposal["executed"])
        self.assertFalse(proposal["executable"])
        self.assertTrue(proposal["material_plan"])
        self.assertTrue(all(all(k in p for k in ("support", "stand", "route", "face")) for p in proposal["placements"]))
        self.assertEqual(runtime.actions, [])

    def test_completed_cells_are_reobserved_not_replayed(self):
        runtime = self.runtime()
        spec = _fixture.blueprint(width=2, extent=1)
        build(runtime, spec, job_id="again")
        prior = len(runtime.actions)
        result = build(runtime, spec, job_id="again")
        self.assertEqual(result.evidence["placements_this_call"], 0)
        self.assertEqual(len(runtime.actions), prior)

    def test_interrupted_second_cell_persists_and_blocks_replay(self):
        runtime = self.runtime()
        runtime.fail_place = 2
        spec = _fixture.blueprint(width=2, extent=1)
        with self.assertRaisesRegex(SkillError, "transport_lost"):
            build(runtime, spec, job_id="interrupted")
        count = len(runtime.actions)
        data = json.loads((runtime.journal_directory / "building-interrupted.json").read_text())
        self.assertEqual(len(data["completed"]), 1)
        self.assertEqual(data["pending"]["status"], "unknown")
        with self.assertRaisesRegex(SkillError, "read_only_reconciliation"):
            build(runtime, spec, job_id="interrupted")
        self.assertEqual(len(runtime.actions), count)

    def test_read_only_reconcile_adopts_presence_without_causation(self):
        runtime = self.runtime()
        runtime.fail_place, runtime.lost_reply_applies = 1, True
        spec = _fixture.blueprint(width=1, extent=1)
        with self.assertRaises(SkillError):
            build(runtime, spec, job_id="lost")
        count = len(runtime.actions)
        result = reconcile_build_progress(runtime, spec, job_id="lost")
        self.assertFalse(result.evidence["causation_confirmed"])
        self.assertEqual(len(runtime.actions), count)
        self.assertEqual(build(runtime, spec, job_id="lost").evidence["placements_this_call"], 0)

    def test_reconcile_wrong_target_does_not_replay(self):
        runtime = self.runtime()
        runtime.fail_place = 1
        spec = _fixture.blueprint(width=1, extent=1)
        with self.assertRaises(SkillError):
            build(runtime, spec, job_id="absent")
        count = len(runtime.actions)
        with self.assertRaisesRegex(SkillError, "target_not_exact"):
            reconcile_build_progress(runtime, spec, job_id="absent")
        self.assertEqual(len(runtime.actions), count)

    def test_initially_existing_completed_goal_not_rebuilt_after_removal(self):
        target = Pos(0, 64, 0)
        runtime = self.runtime(overrides={target: _fixture.cell(target, "minecraft:oak_planks")})
        spec = _fixture.blueprint(width=1, extent=1)
        self.assertEqual(build(runtime, spec, job_id="existing").evidence["placements_this_call"], 0)
        runtime.cells[target] = _fixture.cell(target)
        with self.assertRaisesRegex(SkillError, "completed_blueprint_changed"):
            build(runtime, spec, job_id="existing")
        self.assertEqual(runtime.actions, [])

    def test_removed_completed_cell_not_automatically_rebuilt(self):
        runtime = self.runtime()
        spec = _fixture.blueprint(width=1, extent=1)
        build(runtime, spec, job_id="removed")
        runtime.cells[Pos(0, 64, 0)] = _fixture.cell(Pos(0, 64, 0))
        count = len(runtime.actions)
        with self.assertRaisesRegex(SkillError, "previously_completed"):
            build(runtime, spec, job_id="removed")
        self.assertEqual(len(runtime.actions), count)

    def test_property_or_consumption_mismatch_is_not_success(self):
        for changes in ({"consume": False}, {"corrupt_after": {"properties": {"axis": "x"}}}):
            with self.subTest(changes=changes):
                runtime = self.runtime()
                for key, value in changes.items():
                    setattr(runtime, key, value)
                with self.assertRaisesRegex(SkillError, "semantic_postcondition"):
                    build(runtime, _fixture.blueprint(width=1, extent=1), job_id="bad")
                data = json.loads((runtime.journal_directory / "building-bad.json").read_text())
                self.assertIsNotNone(data["pending"])
                self.assertEqual(data["completed"], [])

    def test_material_shortage_conflict_and_floating_fail_before_actions(self):
        cases = [(dict(stock={"minecraft:oak_planks": 1}), _fixture.blueprint(width=2, extent=1)),
                 (dict(overrides={Pos(0, 64, 0): _fixture.cell(Pos(0, 64, 0), "minecraft:stone")}),
                  _fixture.blueprint(width=1, extent=1)),
                 ({}, generic([((0, 66, 0), "minecraft:oak_planks")]))]
        for kwargs, spec in cases:
            with self.subTest(kwargs=kwargs):
                runtime = self.runtime(**kwargs)
                with self.assertRaisesRegex(SkillError, "preflight_blocked"):
                    build(runtime, spec, job_id="reject")
                self.assertEqual(runtime.actions, [])

    def test_requested_stateful_and_duplicate_cells_rejected(self):
        spec = generic([((0, 64, 0), "minecraft:oak_planks")])
        spec["cells"][0]["properties"] = {"axis": "x"}
        with self.assertRaisesRegex(SkillError, "unsupported"):
            CellBlueprint.parse(spec)
        spec["cells"][0]["properties"] = {}
        spec["cells"].append(deepcopy(spec["cells"][0]))
        with self.assertRaisesRegex(SkillError, "duplicate"):
            CellBlueprint.parse(spec)

    def test_job_path_traversal_or_blueprint_change_rejected(self):
        runtime = self.runtime()
        spec = _fixture.blueprint(width=1, extent=1)
        with self.assertRaisesRegex(SkillError, "job_id"):
            build(runtime, spec, job_id="../../oops")
        build(runtime, spec, job_id="same")
        with self.assertRaisesRegex(SkillError, "checkpoint_blueprint"):
            build(runtime, _fixture.blueprint(width=2, extent=1), job_id="same")

    def test_uncovered_unknown_support_or_entity_fails(self):
        runtime = self.runtime()
        runtime.state["nearby"]["entities"] = [{"type": "minecraft:cow"}]
        with self.assertRaisesRegex(SkillError, "entities_present"):
            build(runtime, _fixture.blueprint(width=1, extent=1), job_id="entity")
        self.assertEqual(runtime.actions, [])



class GuardedBuildingClient:
    """Real Runtime + synthetic state/native endpoint responses, no game I/O."""
    def __init__(self, model, clock):
        from support_core import SESSION, NATIVE
        self.model, self.clock = model, clock
        self.session_id, self.native_id = SESSION, NATIVE
        self.saved, self.commands = {}, []
        self.action = {"action_session": self.native_id, "action_id": None, "status": "idle"}

    def session(self):
        return {"session_id": self.session_id, "state": "ready", "pending": 0}

    def submit(self, command, request_id):
        import uuid
        self.commands.append(deepcopy(command))
        self.saved[request_id] = deepcopy(command)
        if command["op"] == "action":
            before = self.model.observe()
            result = self.model.execute("fixture", command, lambda a, b: True, before=before)
            self.action = {"action_session": self.native_id,
                "action_id": uuid.uuid5(uuid.UUID(self.session_id), request_id + ":1").hex,
                "action": command["action"], "status": result.status, "reason": "fixture_dispatched",
                "result": {"input_release_confirmed": True}}
        return request_id

    def wait(self, request_id, timeout=30):
        from support_core import state as safe_state
        self.clock.sleep(.001)
        self.model.time = self.clock()
        observation = self.model.observe()
        base = safe_state(observation.tick)
        value = {**base, **observation.state}
        value["player"] = {**base["player"], **observation.player}
        value["client_action"] = deepcopy(self.action)
        value["world"]["navigation_guard"] = {"schema_version": 1, "epoch": 0, "rebind_ready": True,
            "fresh_binding_required": False, "stable_ticks": 3}
        payload = {"state": value}
        command = self.saved[request_id]
        if command.get("terrain"):
            payload["terrain"] = observation.terrain
        if command["op"] == "action":
            payload["action"] = deepcopy(self.action)
        return {"request_id": request_id, "session_id": self.session_id, "status": "succeeded", "result": payload}


class BuildingRealRuntimeTests(unittest.TestCase):
    def test_build_uses_real_runtime_exact_guard_and_durable_placement_records(self):
        from support_core import Clock
        from mdc_skills.core import Runtime
        clock = Clock()
        model = BuildingRuntime()
        self.addCleanup(model.close)
        client = GuardedBuildingClient(model, clock)
        with tempfile.TemporaryDirectory() as directory, Runtime(client, directory, clock=clock, sleeper=clock.sleep) as runtime:
            result = build(runtime, _fixture.blueprint(width=2, extent=1), job_id="core-chain")
            self.assertTrue(result.ok)
            self.assertEqual(result.evidence["placements_this_call"], 2)
            actions = [c for c in client.commands if c["op"] == "action"]
            placements = [c for c in actions if c["action"] == "place_block"]
            self.assertEqual(len(placements), 2)
            self.assertTrue(all(c["expected_held_item"]["id"] == c["expected_block_id"] for c in placements))
            self.assertTrue(all(c["capability_guard"]["schema_version"] == 1 for c in placements))
            records = json.loads((Path(directory) / "execution.json").read_text())["records"]
            self.assertEqual(len([r for r in records.values() if r["kind"] == "mutation"]), len(actions))
            self.assertIsNone(runtime.pending_request_id)


if __name__ == "__main__":
    unittest.main()

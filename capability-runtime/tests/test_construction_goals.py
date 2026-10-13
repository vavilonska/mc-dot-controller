"""Offline composed material/build contracts; no game or private blueprint I/O."""
from copy import deepcopy
import json
from unittest.mock import patch
import unittest

from mdc_skills import building, building_v3, construction
from mdc_skills.core import Outcome, SkillError
from building_controller.model import Pos
from test_building_v3 import OrientedRuntime, blueprint, door, navigate_stub
from test_production_capability import ProductionRuntime, bind_snapshot, item
from test_supply_goals import MaterialClient


class ConstructionRuntime(OrientedRuntime):
    """Independent slot-output model joined to the existing synthetic block model."""
    def __init__(self, stock=None):
        stock = {"minecraft:oak_log": 1} if stock is None else stock
        super().__init__(stock=stock)
        self.client = MaterialClient(width=2, stock={i: (key, count) for i, (key, count) in enumerate(stock.items())})
        self.world_action = False
        self.has_unresolved_execution = False
        self.pending_request_id = None
        self.failure_at = None
        self.action_delay = 0
        self._sync()

    def _sync(self):
        if self.world_action:
            for row in self.state["player"]["inventory"]:
                self.client.slots[self.client.storage[row["slot"]]] = item(row["id"], row["count"])
        snapshot = self.client.snapshot()
        self.state["player"]["inventory"] = deepcopy(snapshot["player"]["inventory"])
        self.state["player"]["inventory_total"] = 36
        self.state["menu"] = deepcopy(snapshot["menu"])
        self.state["menu"]["state_id"] = self.serial
        for row in self.state["player"]["inventory"]:
            row["max_stack_size"] = 0 if row["empty"] else 64

    def observe(self, **kwargs):
        self._sync()
        result = super().observe(**kwargs)
        result.state["menu"]["state_id"] = self.serial
        bind_snapshot(result.state)
        return result

    def execute(self, skill, command, verify, *, before, **kwargs):
        if self.failure_at == len(self.actions) + 1:
            self.actions.append(deepcopy(command))
            self.has_unresolved_execution = True
            self.pending_request_id = "unknown-" + str(len(self.actions))
            return Outcome("unknown", "synthetic_lost_reply_no_retry", (self.pending_request_id,))
        if command["action"] == "click_slot":
            self.actions.append(deepcopy(command))
            rid = "native-" + str(len(self.actions))
            ProductionRuntime.assert_binding(command, before)
            self.client.submit(command, request_id=rid)
            for _ in range(2):
                after = self.observe(allow_menu=True)
                if not verify(before, after):
                    return Outcome("blocked", "synthetic_click_postcondition_failed", (rid,), {}, after)
            outcome = Outcome("succeeded", "synthetic_slot_change", (rid,), {}, after)
        else:
            self.world_action = True
            try:
                outcome = super().execute(skill, command, verify, before=before, **kwargs)
            finally:
                self.world_action = False
        self.time += self.action_delay
        return outcome


class ConstructionGoalTests(unittest.TestCase):
    def runtime(self, **kwargs):
        runtime = ConstructionRuntime(**kwargs)
        self.addCleanup(runtime.close)
        return runtime

    @staticmethod
    def spec():
        return blueprint([((0, 64, 0), "minecraft:oak_planks", {})])

    def run_goal(self, runtime, spec=None, **kwargs):
        with patch("mdc_skills.mobility.navigate_loaded", navigate_stub):
            return construction.build_with_materials(runtime, spec or self.spec(), job_id="composed", **kwargs)

    def test_real_supply_crafting_then_real_oriented_build(self):
        runtime = self.runtime()
        result = self.run_goal(runtime)
        self.assertTrue(result.ok, result.reason)
        self.assertTrue(any(a["action"] == "click_slot" for a in runtime.actions))
        self.assertEqual(runtime.place_count, 1)
        self.assertEqual(runtime.cells[Pos(0, 64, 0)]["id"], "minecraft:oak_planks")
        self.assertEqual(result.evidence["material_bill"]["items"], {"minecraft:oak_planks": 1})
        self.assertEqual(result.evidence["capacity_preflight"]["missing_items"], {"minecraft:oak_planks": 1})
        self.assertEqual(result.evidence["capacity_before_build"]["observed_totals"]["minecraft:oak_planks"], 4)
        self.assertEqual(sum(r["count"] for r in runtime.observe().player["inventory"] if r["id"] == "minecraft:oak_planks"), 3)
        self.assertEqual(result.evidence["actions_reserved"], len(runtime.actions))
        self.assertEqual(result.evidence["blueprint_identity"], self.spec()["identity"])
        self.assertFalse(result.evidence["survey_authorizes_mutations"])
        self.assertFalse(result.evidence["server_confirmed"])
        self.assertTrue(all("native-" + str(i + 1) in result.request_ids for i in range(len(runtime.actions))))
        path = runtime.journal_directory / "building-composed.json"
        self.assertEqual(json.loads(path.read_text())["status"], "complete")

    def test_owned_materials_skip_supply_but_still_call_builder(self):
        runtime = self.runtime(stock={"minecraft:oak_planks": 8})
        with patch("mdc_skills.supply.ensure_items") as supply:
            result = self.run_goal(runtime)
        self.assertTrue(result.ok, result.reason)
        supply.assert_not_called()
        self.assertEqual(runtime.place_count, 1)
        self.assertNotIn("procurement_worksite_proposal", result.evidence)

    def test_bill_door_one_item_and_wall_torch_item_alias(self):
        spec = blueprint([((0,64,0),"minecraft:oak_door",door()),
                          ((0,65,0),"minecraft:oak_door",door("upper")),
                          ((2,64,0),"minecraft:wall_torch",{"facing":"east"})])
        self.assertEqual(building_v3.material_requirements(spec)["items"],
                         {"minecraft:oak_door":1,"minecraft:torch":1})

    def test_full_bill_overflow_fails_before_survey_or_procurement(self):
        runtime = self.runtime(stock={})
        spec = blueprint([((x,64+y,z),"minecraft:oak_planks",{})
                          for y in range(3) for z in range(32) for x in range(32)])
        with patch("mdc_skills.supply.ensure_items") as supplier:
            result = self.run_goal(runtime, spec)
        self.assertEqual(result.reason, "construction_materials_exceed_inventory_capacity_no_staging")
        self.assertEqual(runtime.actions, [])
        self.assertEqual(runtime.survey_count, 0)
        supplier.assert_not_called()

    def test_occupied_slots_preserved_no_assumed_partial_stack_merge(self):
        runtime = self.runtime(stock={})
        for i in range(36):
            runtime.client.slots[runtime.client.storage[i]] = item("oak_planks" if i == 0 else "dirt", 1)
        spec = blueprint([((0,64,0),"minecraft:oak_planks",{}),((1,64,0),"minecraft:oak_planks",{})])
        result = self.run_goal(runtime, spec)
        self.assertIn("inventory_capacity", result.reason)
        self.assertEqual(runtime.actions, [])

    def test_missing_real_stack_metadata_fails_before_mutation(self):
        runtime = self.runtime()
        original = runtime.observe
        def missing(**kwargs):
            observed = original(**kwargs)
            observed.player["inventory"][0].pop("max_stack_size")
            return observed
        runtime.observe = missing
        result = self.run_goal(runtime)
        self.assertEqual(result.reason, "construction_inventory_stack_capacity_missing")
        self.assertEqual(runtime.actions, [])

    def test_existing_build_checkpoint_never_runs_procurement(self):
        for state in ("ready", "in_progress"):
            with self.subTest(state=state):
                runtime = self.runtime()
                spec = self.spec()
                path = building._path(runtime, "composed")
                data = building_v3._load(path, building_v3.VersionedBlueprint.parse(spec), runtime.observe())
                data["status"] = state
                data["pending"] = {"request_ids":["original-pending"]} if state == "in_progress" else None
                path.write_text(json.dumps(data))
                with patch("mdc_skills.supply.ensure_items") as supplier, patch("mdc_skills.building.build") as builder:
                    result = self.run_goal(runtime)
                self.assertIn("existing_build_job", result.reason)
                self.assertEqual(runtime.actions, [])
                supplier.assert_not_called()
                builder.assert_not_called()
                if state == "in_progress":
                    self.assertIn("original-pending", result.request_ids)
                self.assertEqual(json.loads(path.read_text()), data)

    def test_completed_job_does_not_reprocure_or_rebuild(self):
        runtime = self.runtime(stock={"minecraft:oak_planks": 8})
        first = self.run_goal(runtime)
        self.assertTrue(first.ok, first.reason)
        count = len(runtime.actions)
        with patch("mdc_skills.supply.ensure_items") as supplier:
            second = self.run_goal(runtime)
        self.assertIn("existing_build_job", second.reason)
        self.assertEqual(len(runtime.actions), count)
        supplier.assert_not_called()

    def test_partial_grid_or_output_blocks_before_procurement(self):
        for slot in (0, 1, 4):
            with self.subTest(slot=slot):
                runtime = self.runtime()
                runtime.client.slots[slot] = item("oak_log", 1)
                with patch("mdc_skills.supply.ensure_items") as supplier:
                    result = self.run_goal(runtime)
                self.assertEqual(result.reason, "construction_partial_crafting_contents_require_explicit_recovery")
                self.assertEqual(runtime.actions, [])
                self.assertEqual(runtime.survey_count, 0)
                supplier.assert_not_called()

    def test_partial_known_procurement_retains_durable_job_no_reentry(self):
        runtime = self.runtime()
        runtime.action_delay = 200
        first = self.run_goal(runtime, timeout_seconds=500)
        self.assertFalse(first.ok)
        path = runtime.journal_directory / "construction-composed.json"
        checkpoint = json.loads(path.read_text())
        self.assertEqual(checkpoint["actions_reserved"], 3)
        self.assertIn("native-3", checkpoint["request_ids"])
        with patch("mdc_skills.supply.ensure_items") as supplier:
            second = self.run_goal(runtime)
        self.assertIn("started_job_requires_explicit_recovery", second.reason)
        self.assertEqual(len(runtime.actions), 3)
        self.assertEqual(json.loads(path.read_text()), checkpoint)
        self.assertIn("native-3", second.request_ids)
        supplier.assert_not_called()

    def test_unknown_runtime_stops_without_any_observation(self):
        runtime = self.runtime()
        runtime.has_unresolved_execution = True
        runtime.pending_request_id = "already-unknown"
        result = self.run_goal(runtime)
        self.assertEqual(result.status, "unknown")
        self.assertIn("already-unknown", result.request_ids)
        self.assertEqual(runtime.serial, 0)
        self.assertEqual(runtime.actions, [])

    def test_unknown_procurement_action_is_preserved_and_never_retried(self):
        runtime = self.runtime()
        runtime.failure_at = 2  # First real crafting click, after synthetic approach.
        first = self.run_goal(runtime)
        self.assertEqual(first.status, "unknown")
        self.assertEqual(len(runtime.actions), 2)
        self.assertIn("unknown-2", first.request_ids)
        second = self.run_goal(runtime)
        self.assertEqual(second.status, "unknown")
        self.assertEqual(len(runtime.actions), 2)
        self.assertEqual(runtime.place_count, 0)

    def test_insufficient_original_actions_stop_before_procurement(self):
        runtime = self.runtime()
        result = self.run_goal(runtime, max_actions=3)
        self.assertFalse(result.ok)
        self.assertEqual(runtime.actions, [])
        self.assertIn("action_budget_cannot_reserve_final_audit", result.reason)
        self.assertEqual(runtime.place_count, 0)
        self.assertFalse((runtime.journal_directory / "construction-composed.json").exists())

    def test_original_deadline_stops_nested_crafting_and_preserves_ids(self):
        runtime = self.runtime()
        runtime.action_delay = .6
        result = self.run_goal(runtime, timeout_seconds=9)
        self.assertFalse(result.ok)
        self.assertIn("deadline", result.reason)
        self.assertLessEqual(len(runtime.actions), 3)
        self.assertEqual(runtime.place_count, 0)
        self.assertTrue(all("native-" + str(i + 1) in result.request_ids for i in range(len(runtime.actions))))

    def test_complete_region_and_access_headroom_excluded(self):
        spec = blueprint([((0,64,0),"minecraft:oak_planks",{})],
            region={"min":{"x":0,"y":64,"z":0},"max":{"x":4,"y":68,"z":4}},
            access_points=[{"x":7,"y":64,"z":0}])
        protected = construction._protected_positions(building_v3.VersionedBlueprint.parse(spec))
        for pos in (Pos(2,66,2),Pos(0,63,0),Pos(7,65,0),Pos(7,63,0)):
            self.assertIn(pos, protected)

    def test_protected_mutation_guard_blocks_mining_station_and_interaction(self):
        for command in ({"action":"break_block","target":{"x":0,"y":64,"z":0}},
                        {"action":"place_block","support":{"x":0,"y":63,"z":0},"face":"up"},
                        {"action":"interact_block","target":{"x":0,"y":64,"z":0}}):
            with self.subTest(command=command):
                runtime = self.runtime()
                def adversarial_supply(rt, requirements, **kwargs):
                    self.assertIn({"x":0,"y":64,"z":0}, kwargs["excluded_positions"])
                    return rt.execute("bad_fake_supply", command, lambda a,b: True, before=rt.observe())
                with patch("mdc_skills.supply.ensure_items", adversarial_supply):
                    result = self.run_goal(runtime)
                self.assertEqual(result.reason, "construction_procurement_mutation_inside_protected_worksite")
                self.assertEqual([a["action"] for a in runtime.actions], ["follow_path"])

    def test_historical_outside_proposal_cannot_bypass_fresh_navigation(self):
        runtime = self.runtime()
        with patch("mdc_skills.mobility.navigate_loaded", side_effect=SkillError("fresh_route_now_blocked")), \
                patch("mdc_skills.supply.ensure_items") as supplier:
            result = construction.build_with_materials(runtime, self.spec(), job_id="composed")
        self.assertEqual(result.reason, "fresh_route_now_blocked")
        self.assertEqual(runtime.actions, [])
        supplier.assert_not_called()

    def test_context_change_during_survey_blocks_all_actions(self):
        runtime = self.runtime()
        original = runtime.survey
        def changed(**kwargs):
            survey = original(**kwargs)
            survey.context = ("different-world",) + survey.context[1:]
            return survey
        runtime.survey = changed
        result = self.run_goal(runtime)
        self.assertEqual(result.reason, "construction_context_changed")
        self.assertEqual(runtime.actions, [])


if __name__ == "__main__":
    unittest.main()

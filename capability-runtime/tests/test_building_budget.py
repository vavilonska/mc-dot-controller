"""Offline finite movement/admission regressions, without game observations."""
from copy import deepcopy
import math
import unittest
from unittest.mock import patch

from building_controller.model import Pos
from mdc_skills import building_v3, construction, mobility
from mdc_skills.core import SkillError
from test_building_capability import _fixture
from test_building_v3 import blueprint
from test_construction_goals import ConstructionRuntime
from test_production_capability import item


class FloorRuntime(ConstructionRuntime):
    """Same 13 by 15 pending floor, with real local navigation on synthetic cells."""
    def __init__(self, *, owned=True):
        super().__init__(stock={})
        if owned:
            for slot, count in enumerate((64, 64, 64, 3)):
                self.client.slots[self.client.storage[slot]] = item("oak_planks", count)
        else:
            self.client.slots[self.client.storage[0]] = item("oak_log", 49)
        self.cells = {Pos.parse(c): c for page in _fixture.pages(radius=16, vertical=8) for c in page["cells"]}
        self.state["player"].update(x=-7.5, y=64., z=.5)
        self.state["player"]["eye_position"] = dict(x=-7.5, y=65.62, z=.5)
        self.state["nearby"]["radius"] = 48

    def observe(self, **kwargs):
        # Clip before copying, just as the real local endpoint does. Unknown
        # distant cells are never supplied to navigation/placement verification.
        cells = self.cells
        p = self.state["player"]
        origin = Pos(*(math.floor(p[k]) for k in ("x", "y", "z")))
        r, v = kwargs.get("radius", 4), kwargs.get("vertical", 4)
        self.cells = {pos: cells[pos] for x in range(-r, r+1) for z in range(-r, r+1)
                      for y in range(-v, v+1) if (pos := origin.offset(x, y, z)) in cells}
        try:
            return super().observe(**kwargs)
        finally:
            self.cells = cells

    def survey(self, **kwargs):
        self._sync()
        survey = super().survey(**kwargs)
        if not kwargs:
            survey.terrain.update(radius=16, vertical=8)
        return survey


def floor_spec():
    return blueprint([((x, 64, z), "minecraft:oak_planks", {})
                      for x in range(-6, 7) for z in range(-7, 8)])


class BuildingBudgetTests(unittest.TestCase):
    def runtime(self, **kwargs):
        runtime = FloorRuntime(**kwargs)
        self.addCleanup(runtime.close)
        return runtime

    def test_default_wrapper_completes_195_cell_floor_with_real_fresh_navigation(self):
        runtime = self.runtime()
        result = construction.build_with_materials(runtime, floor_spec(), job_id="floor-budget")
        self.assertTrue(result.ok, result.reason)
        self.assertEqual(runtime.place_count, 195)
        self.assertEqual(result.evidence["final_audited_cells"], 195)
        self.assertEqual(len(result.evidence["final_audit_segments"]), 4)
        self.assertLess(result.evidence["build_budget_preflight"]["audit_seconds"], 3600)
        moves = [c for c in runtime.actions if c["action"] == "follow_path"]
        self.assertTrue(moves)
        # Procurement's already-at-anchor call issues no movement. Every actual
        # builder/audit native segment uses the same four-step bound as reserve.
        self.assertTrue(all(len(c["waypoints"]) <= 4 and c["timeout_ms"] <= 10200 for c in moves))
        self.assertTrue(all(c.get("capability_route") is True for c in moves))
        self.assertEqual(result.evidence["final_exit_stand"], dict(x=-8, y=64, z=0))
        self.assertFalse(result.evidence["server_confirmed"])

    def test_enclosing_budget_rejects_before_missing_material_procurement(self):
        for actions, seconds, expected in ((200, 3600, "action_budget"), (32768, 300, "deadline")):
            with self.subTest(actions=actions, seconds=seconds):
                runtime = self.runtime(owned=False)
                runtime.effective_remaining_budget = lambda: dict(remaining_actions=actions, remaining_seconds=seconds)
                with patch("mdc_skills.supply.ensure_items") as supplier, patch("mdc_skills.mobility.navigate_loaded") as navigation:
                    result = construction.build_with_materials(runtime, floor_spec(), job_id="floor-insufficient")
                self.assertIn(expected + "_cannot_reserve_final_audit", result.reason)
                self.assertEqual(runtime.actions, [])
                supplier.assert_not_called()
                navigation.assert_not_called()
                self.assertFalse((runtime.journal_directory / "construction-floor-insufficient.json").exists())

    def test_material_allowance_is_only_a_proposal_without_inventory_credit(self):
        runtime = ConstructionRuntime(stock={})
        self.addCleanup(runtime.close)
        spec = blueprint([((0,64,0), "minecraft:oak_planks", {})])
        survey = runtime.survey()
        original = deepcopy(survey.__dict__)
        proposal = building_v3.execution_plan(spec, survey, historical=True,
            planning_materials={"minecraft:oak_planks": 1})
        self.assertTrue(proposal["proposal_only"])
        self.assertTrue(proposal["materials_assumed_for_proposal"])
        self.assertEqual(proposal["material_plan"][0]["available"], 0)
        self.assertEqual(proposal["material_plan"][0]["shortage"], 1)
        self.assertEqual(survey.__dict__, original)
        with self.assertRaisesRegex(SkillError, "material_shortage"):
            building_v3.execution_plan(spec, survey, historical=True)
        with self.assertRaisesRegex(SkillError, "exact_historical_bill"):
            building_v3.execution_plan(spec, survey, historical=True, planning_materials={"minecraft:oak_planks": 2})
        self.assertEqual(runtime.actions, [])

    def test_reserve_matches_finite_segment_and_verification_bounds(self):
        runtime = self.runtime()
        runtime.wait_timeout, runtime.max_age = 30, .8
        route = [Pos(x,64,0).json() for x in range(14)]
        limits = building_v3._navigation_limits(route)
        self.assertEqual(limits, dict(max_steps=4, max_segments=6))
        actions, seconds = building_v3._navigation_budget(runtime, route)
        self.assertEqual(actions, 6)
        self.assertAlmostEqual(seconds, 6 * (.8 + 30 + 8 * (.8 + .05)))
        shorter = building_v3._navigation_limits(route, 2)
        self.assertEqual(shorter, dict(max_steps=2, max_segments=9))
        command = mobility._path_command(tuple(mobility.reach.Block(x,64,0) for x in range(5)), {})
        self.assertEqual(command["timeout_ms"], 10200)
        reserve = building_v3._audit_budget(runtime, [{"route": route}], route)
        self.assertEqual(reserve["audit_actions"], 12)
        self.assertAlmostEqual(reserve["audit_seconds"], 2 * seconds + 10 * .8 + 8 * .05 + 2 * .8)


if __name__ == "__main__":
    unittest.main()

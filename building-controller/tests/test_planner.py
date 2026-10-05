from copy import deepcopy
import unittest

from building_controller.model import Pos
from building_controller.planner import plan
from .helpers import blueprint, cell, state, terrain


def codes(output):
    return {item["code"] for item in output["blockers"]}


class PlannerTests(unittest.TestCase):
    def test_floor_provisional_with_ground_anchors(self):
        result = plan(blueprint(), terrain(), state())
        self.assertEqual(result["status"], "provisional_plan")
        self.assertEqual(len(result["proposed_placements"]), 9)
        self.assertTrue(all(step["anchor"]["face"] == "up" for step in result["proposed_placements"]))
        self.assertFalse(result["executable"])
        self.assertFalse(result["execution_enabled"])
        self.assertEqual(result["evidence"]["live_freshness"], "not_established")

    def test_wall_dependencies_are_earlier(self):
        result = plan(blueprint("wall"), terrain(), state())
        self.assertEqual(result["status"], "provisional_plan")
        steps = result["proposed_placements"]
        self.assertEqual(len(steps), 9)
        for step in steps:
            if step["position"]["y"] > 64:
                self.assertLess(step["anchor"]["depends_on_index"], step["index"])
                self.assertEqual(step["anchor"]["position"]["y"], step["position"]["y"] - 1)

    def test_correct_blocks_skipped_and_materials_reduced(self):
        pos = Pos(0, 64, 0)
        result = plan(blueprint(), terrain(overrides={pos: cell(pos, "minecraft:oak_planks")}), state())
        self.assertEqual(result["summary"]["already_correct"], 1)
        self.assertEqual(len(result["proposed_placements"]), 8)
        self.assertEqual(result["materials"][0]["remaining_upper_bound"], 8)
        self.assertNotIn(pos.json(), [p["position"] for p in result["proposed_placements"]])

    def test_conflict_suppresses_whole_plan(self):
        pos = Pos(1, 64, 1)
        result = plan(blueprint(), terrain(overrides={pos: cell(pos, "minecraft:bricks")}), state())
        self.assertIn("existing_block_must_not_be_broken_or_replaced", codes(result))
        self.assertEqual(result["proposed_placements"], [])
        self.assertEqual(result["status"], "blocked")

    def test_complete_blueprint_needs_no_actions_or_inventory(self):
        b = blueprint()
        t = terrain(overrides={pos: cell(pos, block) for pos, block in b.cells()})
        result = plan(b, t)
        self.assertEqual(result["status"], "already_complete")
        self.assertEqual(result["proposed_placements"], [])
        self.assertFalse(result["executable"])

    def test_unknown_target_is_not_air(self):
        pos = Pos(1, 64, 1)
        unknown = dict(**pos.json(), status="unloaded", known=False)
        result = plan(blueprint(), terrain(overrides={pos: unknown}), state())
        self.assertIn("terrain_not_known_loaded", codes(result))
        self.assertEqual(result["proposed_placements"], [])

    def test_unknown_adjacent_cell_blocks(self):
        pos = Pos(-1, 64, 0)
        unknown = dict(**pos.json(), status="read_failed", known=False)
        result = plan(blueprint(), terrain(overrides={pos: unknown}), state())
        self.assertIn("unsafe_or_unknown_adjacent_cell", codes(result))

    def test_fluid_and_hazard_targets_block(self):
        pos = Pos(1, 64, 1)
        for changes in ({"fluid": "minecraft:water", "fluid_source": True},
                        {"hazards": ["fire"]}, {"id_truncated": True},
                        {"collision_known": False}):
            result = plan(blueprint(), terrain(overrides={pos: cell(pos, **changes)}), state())
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["proposed_placements"], [])

    def test_adjacent_fluid_blocks(self):
        pos = Pos(-1, 64, 0)
        result = plan(blueprint(), terrain(overrides={pos: cell(pos, fluid="minecraft:lava")}), state())
        self.assertIn("unsafe_or_unknown_adjacent_cell", codes(result))

    def test_wrong_collision_on_same_block_not_skipped(self):
        pos = Pos(0, 64, 0)
        result = plan(blueprint(), terrain(overrides={pos: cell(pos, "minecraft:oak_planks",
                                                             collision_bounds=[0, 0, 0, 1, .5, 1])}), state())
        self.assertEqual(result["summary"]["already_correct"], 0)
        self.assertEqual(result["status"], "blocked")

    def test_no_replacement_of_replaceable_plants(self):
        pos = Pos(0, 64, 0)
        result = plan(blueprint(), terrain(overrides={pos: cell(pos, "minecraft:short_grass",
                                                            collision_empty=True)}), state())
        self.assertEqual(result["status"], "blocked")

    def test_floating_cycles_never_self_support(self):
        result = plan(blueprint(), terrain(floor_y=60), state())
        self.assertIn("unsupported_floating_cells", codes(result))
        self.assertEqual(result["proposed_placements"], [])

    def test_side_anchor_is_valid_geometric_dependency(self):
        pos = Pos(-1, 64, 0)
        result = plan(blueprint(width=2, extent=1),
                      terrain(floor_y=60, overrides={pos: cell(pos, "minecraft:stone")}), state())
        self.assertEqual(result["status"], "provisional_plan")
        self.assertEqual(result["proposed_placements"][0]["anchor"]["face"], "east")
        self.assertEqual(result["proposed_placements"][1]["anchor"]["depends_on_index"], 0)

    def test_missing_state_blocks(self):
        result = plan(blueprint(), terrain())
        self.assertIn("missing_or_invalid_state_evidence", codes(result))
        self.assertIn("inventory_evidence_unavailable", codes(result))

    def test_empty_inventory_is_shortage_never_permission(self):
        result = plan(blueprint(), terrain(), state({}))
        self.assertIn("insufficient_materials", codes(result))
        self.assertEqual(result["materials"][0]["shortage"], 9)
        self.assertEqual(result["proposed_placements"], [])

    def test_truncated_inventory_unknown_not_zero(self):
        s = state()
        s["player"]["inventory_truncated"] = True
        result = plan(blueprint(), terrain(), s)
        self.assertIn("inventory_evidence_unavailable", codes(result))
        self.assertIsNone(result["materials"][0]["observed_main_inventory"])

    def test_entity_scan_zero_radius_not_clearance(self):
        s = state()
        s["nearby"]["radius"] = 0
        result = plan(blueprint(), terrain(), s)
        self.assertIn("entity_scan_does_not_cover_blueprint", codes(result))

    def test_present_or_truncated_entities_block(self):
        for changes in ({"entities": [{"id": "minecraft:cow"}], "returned": 1, "total": 1},
                        {"truncated": True}, {"returned": True}):
            s = state()
            s["nearby"].update(changes)
            self.assertEqual(plan(blueprint(), terrain(), s)["status"], "blocked")

    def test_player_overlap_blocks(self):
        s = state()
        s["player"].update(x=.5, y=64., z=.5)
        self.assertIn("player_overlaps_blueprint", codes(plan(blueprint(), terrain(), s)))

    def test_world_change_blocks(self):
        s = state()
        s["world"]["world_generation"] = "00000000-0000-4000-8000-000000000099"
        self.assertIn("world_or_dimension_mismatch", codes(plan(blueprint(), terrain(), s)))

    def test_incoherent_state_ticks_block(self):
        for tick in (99, 141):
            s = state()
            s["world"]["game_time"] = tick
            self.assertIn("state_terrain_ticks_incoherent", codes(plan(blueprint(), terrain(), s)))

    def test_creative_mode_not_survival_plan(self):
        s = state()
        s["player"]["gamemode"] = "creative"
        self.assertIn("survival_state_required", codes(plan(blueprint(), terrain(), s)))

    def test_unknown_terrain_does_not_mutate_inputs(self):
        s = state()
        before = deepcopy(s)
        plan(blueprint(), terrain(), s)
        self.assertEqual(s, before)


if __name__ == "__main__":
    unittest.main()

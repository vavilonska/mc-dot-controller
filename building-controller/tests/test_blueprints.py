from copy import deepcopy
import unittest

from building_controller.model import Blueprint, PlanError, Pos
from .helpers import blueprint


class BlueprintTests(unittest.TestCase):
    def test_floor_preview_counts(self):
        output = blueprint(pattern="frame").preview()
        self.assertEqual(output["material_totals"], {"minecraft:oak_planks": 1, "minecraft:stone_bricks": 8})
        self.assertEqual(output["preview"]["rows"], ["AAA", "APA", "AAA"])
        self.assertFalse(output["executable"])

    def test_checker_counts(self):
        self.assertEqual(blueprint(width=4, extent=3, pattern="checker").preview()["material_totals"],
                         {"minecraft:oak_planks": 6, "minecraft:stone_bricks": 6})

    def test_wall_both_axes(self):
        for axis in ("x", "z"):
            result = blueprint("wall", width=3, extent=4, axis=axis)
            self.assertEqual(len(result.cells()), 12)
            self.assertEqual(max(p.y for p, _ in result.cells()), 67)
            self.assertEqual(len({getattr(p, axis) for p, _ in result.cells()}), 3)

    def test_wall_view_is_top_down(self):
        output = blueprint("wall", width=2, extent=2, pattern="checker").preview()
        self.assertEqual(output["preview"]["rows"], ["AP", "PA"])

    def test_same_primary_and_accent_consistent_legend(self):
        spec = blueprint(pattern="frame").spec()
        spec["palette"]["accent"] = spec["palette"]["primary"]
        result = Blueprint.parse(spec).preview()
        self.assertEqual(result["preview"]["rows"], ["PPP"] * 3)

    def test_round_trip(self):
        b = blueprint("wall", pattern="frame")
        self.assertEqual(Blueprint.parse(b.spec()), b)

    def test_out_of_region_rejected(self):
        spec = blueprint().spec()
        spec["region"]["max"]["x"] = 1
        with self.assertRaisesRegex(PlanError, "outside_explicit"):
            Blueprint.parse(spec)

    def test_region_required(self):
        spec = blueprint().spec()
        del spec["region"]
        with self.assertRaises(PlanError):
            Blueprint.parse(spec)

    def test_dimensions_strict_and_bounded(self):
        for value in (0, -1, True, 1.0, 33, "3"):
            spec = blueprint().spec()
            spec["size"]["width"] = value
            with self.subTest(value=value), self.assertRaises(PlanError):
                Blueprint.parse(spec)

    def test_block_budget(self):
        with self.assertRaisesRegex(PlanError, "block_budget"):
            blueprint(width=32, extent=32)

    def test_world_height_and_bounds(self):
        for pos in (Pos(0, -65, 0), Pos(0, 320, 0)):
            with self.assertRaises(PlanError):
                blueprint(origin=pos)

    def test_palette_rejects_physics_stateful_and_modded(self):
        for name in ("minecraft:sand", "minecraft:water", "minecraft:oak_stairs", "minecraft:oak_log", "mod:block"):
            spec = blueprint().spec()
            spec["palette"]["primary"] = name
            with self.subTest(name=name), self.assertRaisesRegex(PlanError, "unsupported_palette"):
                Blueprint.parse(spec)

    def test_extra_blueprint_fields_rejected(self):
        spec = blueprint().spec()
        spec["execute"] = True
        with self.assertRaises(PlanError):
            Blueprint.parse(spec)


if __name__ == "__main__":
    unittest.main()

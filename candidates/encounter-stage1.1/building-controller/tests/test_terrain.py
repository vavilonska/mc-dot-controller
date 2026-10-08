from copy import deepcopy
import unittest

from building_controller.model import PlanError, Pos
from building_controller.terrain import Cell, Terrain, parse_inventory
from .helpers import cell, pages, state


class TerrainTests(unittest.TestCase):
    def test_multiple_pages_complete(self):
        t = Terrain.parse(pages())
        self.assertEqual(len(t.cells), 729)
        self.assertEqual(t.get(Pos(0, 64, 0)).kind, "clear")
        self.assertEqual(t.get(Pos(0, 63, 0)).kind, "solid")

    def test_exact_page_order_and_coverage(self):
        p = pages()
        p[0]["cells"][0], p[0]["cells"][1] = p[0]["cells"][1], p[0]["cells"][0]
        with self.assertRaisesRegex(PlanError, "cell_order"):
            Terrain.parse(p)

    def test_incomplete_scan(self):
        with self.assertRaisesRegex(PlanError, "incomplete_scan"):
            Terrain.parse(pages()[:-1])

    def test_mixed_scan_generation(self):
        p = pages()
        p[1]["generation"] = "00000000-0000-4000-8000-000000000003"
        with self.assertRaisesRegex(PlanError, "mixed_scan"):
            Terrain.parse(p)

    def test_replayed_page(self):
        p = pages()
        with self.assertRaises(PlanError):
            Terrain.parse([p[0], p[0]] + p[1:])

    def test_tick_budget(self):
        p = pages()
        p[-1]["response_game_time"] = 141
        with self.assertRaisesRegex(PlanError, "incoherent_scan_ticks"):
            Terrain.parse(p)

    def test_regressed_response_tick(self):
        p = pages()
        p[0]["response_game_time"] = 101
        with self.assertRaisesRegex(PlanError, "incoherent_scan_ticks"):
            Terrain.parse(p)

    def test_metadata_type_confusions(self):
        for key, value in (("schema_version", True), ("terrain_schema_version", True),
                           ("returned", True), ("unknown_cells", False), ("complete", 0),
                           ("total_cells", 728), ("read_only", 1)):
            p = pages()
            p[0][key] = value
            with self.subTest(key=key), self.assertRaises(PlanError):
                Terrain.parse(p)

    def test_wrong_unknown_count(self):
        p = pages()
        p[0]["unknown_cells"] = 1
        with self.assertRaisesRegex(PlanError, "unknown_count"):
            Terrain.parse(p)

    def test_failed_http_wrapper(self):
        with self.assertRaisesRegex(PlanError, "not_successful"):
            Terrain.parse([{"status": 503, "body": pages()[0]}])

    def test_cells_immutable_and_source_changes_do_not_change_grid(self):
        p = pages()
        t = Terrain.parse(p)
        p[0]["cells"][0]["id"] = "minecraft:lava"
        self.assertEqual(t.get(Pos(-4, 60, -4)).block_id, "minecraft:stone")
        with self.assertRaises(TypeError):
            t.cells[Pos(0, 64, 0)] = None

    def test_empty_hazards_are_not_enough_for_modded_block(self):
        self.assertEqual(Cell.parse(cell(Pos(0, 64, 0), "mod:unsafe_full_cube")).kind, "unsupported")

    def test_nonempty_unknown_properties_block(self):
        self.assertEqual(Cell.parse(cell(Pos(0, 64, 0), "minecraft:oak_planks", properties={"x": "y"})).kind,
                         "unsupported")

    def test_grass_snowy_property_supported(self):
        self.assertEqual(Cell.parse(cell(Pos(0, 63, 0), "minecraft:grass_block",
                                        properties={"snowy": "false"})).kind, "solid")

    def test_inventory_main_slots_summed(self):
        s = state()
        s["player"]["inventory"][2] = {"slot": 2, "id": "minecraft:oak_planks", "count": 3, "empty": False}
        self.assertEqual(parse_inventory(s)["minecraft:oak_planks"], 67)

    def test_inventory_duplicates_missing_and_truncated_rejected(self):
        for mutate in (lambda p: p["inventory"].pop(),
                       lambda p: p["inventory"][1].update(slot=0),
                       lambda p: p.update(inventory_truncated=True),
                       lambda p: p["inventory"][2].update(count=1),
                       lambda p: p["inventory"][0].update(count=True)):
            s = state()
            mutate(s["player"])
            with self.assertRaises(PlanError):
                parse_inventory(s)


if __name__ == "__main__":
    unittest.main()

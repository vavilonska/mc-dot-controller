"""Offline compatibility checks against sanitized real bridge responses."""
import json
from pathlib import Path
import unittest

from building_controller.model import Pos
from building_controller.planner import plan
from building_controller.terrain import Terrain, parse_inventory
from .helpers import blueprint


class CapturedTerrainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.capture = json.loads((Path(__file__).parent / "fixtures" / "captured_terrain_schema1.json").read_text())

    def test_four_captured_response_shapes_parse(self):
        for key, count in (("one", 1), ("cube", 27), ("paging", 27), ("boundary", 17)):
            with self.subTest(key=key):
                self.assertEqual(len(Terrain.parse(self.capture[key]).cells), count)

    def test_actual_paged_and_unpaged_cells_equal(self):
        self.assertEqual(Terrain.parse(self.capture["cube"]).cells, Terrain.parse(self.capture["paging"]).cells)

    def test_actual_air_and_grass_floor(self):
        t = Terrain.parse(self.capture["cube"])
        self.assertEqual(t.get(Pos(0, -60, 0)).kind, "clear")
        self.assertEqual(t.get(Pos(0, -61, 0)).kind, "solid")

    def test_actual_boundary_cells_are_unknown(self):
        t = Terrain.parse(self.capture["boundary"])
        for cell in t.cells.values():
            if cell.position.y < -64:
                self.assertEqual(cell.kind, "unknown")

    def test_actual_inventory_is_empty_not_authorization(self):
        self.assertEqual(parse_inventory(self.capture["state_after"]), {})

    def test_actual_capture_must_not_propose_placements(self):
        b = blueprint(width=1, extent=1, origin=Pos(0, -60, 0))
        result = plan(b, Terrain.parse(self.capture["cube"]), self.capture["state_after"])
        codes = {error["code"] for error in result["blockers"]}
        self.assertEqual(result["status"], "blocked")
        self.assertIn("entity_scan_does_not_cover_blueprint", codes)
        self.assertIn("player_overlaps_blueprint", codes)
        self.assertIn("insufficient_materials", codes)
        self.assertEqual(result["proposed_placements"], [])
        self.assertFalse(result["executable"])


if __name__ == "__main__":
    unittest.main()

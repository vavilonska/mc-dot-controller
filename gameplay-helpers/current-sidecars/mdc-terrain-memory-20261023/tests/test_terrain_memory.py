import unittest

from terrain_memory import Context, MemoryError, TerrainMemory, MAX_CELLS
from example import ingest_complete_window, candidate_for_existing_planner

WORLD = "11111111-1111-4111-8111-111111111111"
SCAN = "22222222-2222-4222-8222-222222222222"
CLOCK = "33333333-3333-4333-8333-333333333333"
PLAYER = "44444444-4444-4444-8444-444444444444"
SESSION = "55555555-5555-4555-8555-555555555555"
CONTEXT = Context(WORLD, "minecraft:the_nether")


def stamp(count):
    return {"contract": "client-pre-tick-v1", "clock_generation": CLOCK, "origin_nano": "-10", "count": count,
            "context": {"run_id": "offline-fixture", "process_id": 123, "integrated_server_instance": "synthetic",
                        "world_generation": WORLD, "dimension": CONTEXT.dimension,
                        "player_uuid": PLAYER, "action_session": SESSION}}


def pages(*, radius=1, vertical=1, origin=(0, 64, 0), chunk=10, tick=10, schema=2, status="loaded"):
    """Synthetic native-shaped pages. No network/game reads and no real tokens."""
    width = 2*radius+1
    total = width*width*(2*vertical+1)
    out = []
    for offset in range(0, total, chunk):
        end = min(total, offset+chunk)
        cells = []
        for index in range(offset, end):
            p = {"x": origin[0]-radius+index % width, "y": origin[1]-vertical+index//(width*width),
                 "z": origin[2]-radius+(index//width) % width, "status": status, "known": status == "loaded"}
            if status == "loaded":
                p.update(id="minecraft:air", id_truncated=False, properties={}, properties_truncated=False,
                         air=True, fluid="minecraft:empty", fluid_truncated=False, fluid_source=False,
                         hazards=[], hazards_exhaustive=False, collision_known=True, collision_empty=True,
                         full_top_support=False)
            cells.append(p)
        source = tick+len(out)
        page = {"world_generation": WORLD, "dimension": CONTEXT.dimension, "terrain_schema_version": schema,
                "consistency": "live_pages", "order": "x_then_z_then_y", "read_only": True, "loaded_chunks_only": True,
                "generation": SCAN, "origin": dict(zip(("x", "y", "z"), origin)), "radius": radius, "vertical": vertical,
                "total_cells": total, "offset": offset, "next_offset": end, "returned": len(cells), "cells": cells,
                "unknown_cells": 0 if status == "loaded" else len(cells), "complete": end == total,
                "next_cursor": None if end == total else f"{SCAN}:{end}", "budget_exhausted": False,
                "read_elapsed_micros": 10, "game_time": source, "response_game_time": source}
        if schema == 2:
            page.update(observation_clock_profile="read_only", source_clock=stamp(source), response_clock=stamp(source))
        out.append(page)
    return out


def commit(memory, data, *, received_at=100):
    return ingest_complete_window(memory, [(p, received_at+i) for i, p in enumerate(data)])


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.memory = TerrainMemory(CONTEXT)

    def test_complete_pages_preserve_original_source_and_raw_facts(self):
        data = pages()
        report = commit(self.memory, data)
        self.assertEqual(report["merged"], 27)
        record = self.memory.lookup((-1, 63, -1))
        self.assertEqual(record.source_game_time, 10)
        self.assertEqual(record.context, CONTEXT)
        self.assertEqual(record.received_at, 100)
        self.assertEqual(record.facts(), data[0]["cells"][0])
        self.assertIn('"count":10', record.source_clock_json)
        self.assertFalse(report["execution_authority"])
        self.assertEqual(record.planning_state, "historical")

    def test_raw_input_and_lookup_are_detached(self):
        data = pages()
        commit(self.memory, data)
        data[0]["cells"][0]["id"] = "mutated"
        record = self.memory.lookup((-1, 63, -1))
        record.facts()["properties"]["mutated"] = True
        self.assertEqual(record.facts()["id"], "minecraft:air")
        self.assertEqual(record.facts()["properties"], {})

    def test_missing_pages_do_not_publish_partial_map(self):
        scan = self.memory.begin_scan(received_at=1)
        scan.add(pages()[0], received_at=1)
        with self.assertRaisesRegex(MemoryError, "incomplete"):
            scan.commit()
        self.assertEqual(len(self.memory.cells), 0)

    def test_missing_middle_page_poisoned(self):
        scan = self.memory.begin_scan(received_at=1)
        data = pages()
        scan.add(data[0], received_at=1)
        with self.assertRaisesRegex(MemoryError, "noncontiguous"):
            scan.add(data[2], received_at=2)
        with self.assertRaisesRegex(MemoryError, "scan_closed"):
            scan.add(data[1], received_at=3)
        self.assertEqual(len(self.memory.cells), 0)

    def test_reordered_first_page_rejected(self):
        with self.assertRaisesRegex(MemoryError, "noncontiguous"):
            commit(self.memory, [pages()[1]])

    def test_duplicate_page_not_silently_replayed(self):
        data = pages()
        with self.assertRaisesRegex(MemoryError, "noncontiguous"):
            commit(self.memory, [data[0], data[0]])
        self.assertEqual(len(self.memory.cells), 0)

    def test_bad_coordinates_rejected(self):
        data = pages()
        data[0]["cells"][0]["x"] += 1
        with self.assertRaisesRegex(MemoryError, "cell_order"):
            commit(self.memory, data)

    def test_bad_known_count_cursor_completion_total_rejected(self):
        edits = [("unknown_cells", 1), ("next_cursor", "bad"), ("complete", True), ("total_cells", 28)]
        for key, value in edits:
            with self.subTest(key=key):
                data = pages()
                data[0][key] = value
                with self.assertRaises(MemoryError):
                    commit(self.memory, data)
        self.assertEqual(len(self.memory.cells), 0)

    def test_clock_schema_context_and_order_rejected(self):
        for change in ("domain", "context", "order", "process_bool", "nan"):
            with self.subTest(change=change):
                data = pages()
                if change == "domain": data[1]["source_clock"]["origin_nano"] = "11"
                if change == "context": data[0]["source_clock"]["context"]["dimension"] = "minecraft:overworld"
                if change == "order": data[1]["source_clock"]["count"] = 9
                if change == "process_bool": data[0]["source_clock"]["context"]["process_id"] = True
                if change == "nan": data[0]["cells"][0]["extra"] = float("nan")
                with self.assertRaises(MemoryError):
                    commit(self.memory, data)

    def test_game_time_is_not_used_as_schema2_clock(self):
        data = pages()
        data[1]["game_time"] = data[1]["response_game_time"] = 0
        commit(self.memory, data)
        self.assertEqual(self.memory.lookup((0, 64, -1)).source_game_time, 0)

    def test_schema1_works_but_cannot_mix_with_schema2(self):
        commit(self.memory, pages(schema=1))
        self.assertEqual(self.memory.lookup((0, 64, 0)).source_clock_json, None)
        with self.assertRaisesRegex(MemoryError, "domain_changed"):
            commit(self.memory, pages())

    def test_new_clock_domain_needs_explicit_reset(self):
        commit(self.memory, pages())
        data = pages(tick=30)
        for p in data:
            p["source_clock"]["origin_nano"] = p["response_clock"]["origin_nano"] = "100"
        with self.assertRaisesRegex(MemoryError, "reset_required"):
            commit(self.memory, data)
        self.memory.reset(CONTEXT)
        commit(self.memory, data)

    def test_world_or_dimension_reset_clears_memory_routes_and_inflight(self):
        commit(self.memory, pages())
        self.memory.remember_walked([(0, 64, 0), (1, 64, 0)], context=CONTEXT, evidence_id="trace", observed_at=1)
        scan = self.memory.begin_scan(received_at=1)
        for i, page in enumerate(pages()): scan.add(page, received_at=i+1)
        self.memory.reset(Context(WORLD, "minecraft:overworld"))
        self.assertEqual(len(self.memory.cells), 0)
        self.assertEqual(len(self.memory.routes), 0)
        with self.assertRaisesRegex(MemoryError, "context_changed"): scan.commit()
        with self.assertRaisesRegex(MemoryError, "context_changed"):
            self.memory.remember_walked([(0, 64, 0), (1, 64, 0)], context=CONTEXT, evidence_id="late", observed_at=1)
        self.memory.reset(Context(PLAYER, "minecraft:overworld"))
        self.assertIsNone(self.memory.window)

    def test_wrong_world_page_never_resets_current_memory(self):
        commit(self.memory, pages())
        data = pages()
        data[0]["world_generation"] = PLAYER
        with self.assertRaisesRegex(MemoryError, "context_changed"): commit(self.memory, data)
        self.assertEqual(len(self.memory.cells), 27)

    def test_older_completed_scan_cannot_overwrite_newer_unknown(self):
        commit(self.memory, pages(tick=100, status="unloaded"))
        report = commit(self.memory, pages(tick=10), received_at=200)
        self.assertEqual(report["merged"], 0)
        self.assertEqual(report["ignored_older_or_same"], 27)
        self.assertEqual(self.memory.lookup((0, 64, 0)).planning_state, "unknown")
        self.assertEqual(self.memory.window.last_source, 102)

    def test_newer_unloaded_and_read_failed_replace_historical(self):
        for status in ("unloaded", "read_failed", "out_of_world"):
            self.memory.reset(CONTEXT)
            commit(self.memory, pages())
            commit(self.memory, pages(tick=20, status=status))
            self.assertEqual(self.memory.lookup((0, 64, 0)).planning_state, "unknown")

    def test_same_source_conflict_rejects_entire_commit(self):
        commit(self.memory, pages())
        before = dict(self.memory.cells)
        data = pages()
        data[0]["cells"][0]["id"] = "minecraft:stone"
        with self.assertRaisesRegex(MemoryError, "same_source_conflict"): commit(self.memory, data)
        self.assertEqual(before, self.memory.cells)

    def test_same_evidence_reuse_does_not_rewrite_received_at(self):
        commit(self.memory, pages())
        report = commit(self.memory, pages(), received_at=1000)
        self.assertEqual(report["merged"], 0)
        self.assertEqual(self.memory.lookup((-1, 63, -1)).received_at, 100)

    def test_compact_id_only_not_accepted_as_complete_terrain(self):
        data = pages()
        data[0]["cells"][0] = {k: data[0]["cells"][0][k] for k in ("x", "y", "z", "known", "status", "id")}
        with self.assertRaisesRegex(MemoryError, "incomplete_cell_facts"): commit(self.memory, data)

    def test_mixed_page_profile_and_missing_collision_refused(self):
        data = pages()
        data[1].update(capability_page_schema_version=1, page_limit=128, payload_budget_exhausted=False)
        with self.assertRaisesRegex(MemoryError, "mixed_scan"): commit(self.memory, data)
        data = pages()
        del data[0]["cells"][0]["collision_empty"]
        with self.assertRaisesRegex(MemoryError, "incomplete_collision"): commit(self.memory, data)

    def test_capability_profile_accepts_1024_cells_and_enforces_bytes(self):
        data = pages(radius=5, vertical=4, chunk=1024, status="unloaded")
        for p in data:
            p.update(capability_page_schema_version=1, page_limit=1024, payload_budget_exhausted=False)
        commit(self.memory, data)
        self.assertEqual(len(self.memory.cells), 1089)
        self.memory.reset(CONTEXT)
        # Native's payload cap can produce fewer records than page_limit.
        data = pages(radius=5, vertical=4, chunk=200)
        for p in data: p.update(capability_page_schema_version=1, page_limit=1024, payload_budget_exhausted=False)
        commit(self.memory, data)
        self.assertEqual(len(self.memory.cells), 1089)
        huge = pages()
        huge[0]["extra"] = "x" * 262144
        with self.assertRaisesRegex(MemoryError, "page_size"): commit(self.memory, huge)

    def test_commit_twice_closed_and_page_mutation_after_add_harmless(self):
        scan = self.memory.begin_scan(received_at=1)
        data = pages(radius=0, vertical=0)
        scan.add(data[0], received_at=1)
        data[0]["cells"][0]["id"] = "mutated"
        scan.commit()
        self.assertEqual(self.memory.lookup((0, 64, 0)).facts()["id"], "minecraft:air")
        with self.assertRaisesRegex(MemoryError, "closed"): scan.commit()

    def test_window_overlap_preserves_off_window_historical_cells(self):
        commit(self.memory, pages())
        commit(self.memory, pages(origin=(2, 64, 0), tick=30))
        self.assertEqual(len(self.memory.cells), 45)
        self.assertEqual(self.memory.lookup((-1, 63, -1)).source_game_time, 10)
        self.assertEqual(self.memory.lookup((1, 63, -1)).source_game_time, 30)
        self.assertEqual(self.memory.window.origin, (2, 64, 0))

    def test_fluid_change_is_retained_not_classified_safe(self):
        commit(self.memory, pages(radius=0, vertical=0))
        data = pages(radius=0, vertical=0, tick=30)
        data[0]["cells"][0].update(id="minecraft:lava", fluid="minecraft:lava", hazards=["lava"], fluid_source=True)
        commit(self.memory, data)
        self.assertEqual(self.memory.lookup((0, 64, 0)).facts()["hazards"], ["lava"])
        self.assertEqual(self.memory.lookup((0, 64, 0)).planning_state, "historical")
        self.assertFalse(self.memory.summary()["execution_authority"])

    def test_memory_cell_budget_is_bounded(self):
        memory = TerrainMemory(CONTEXT, max_cells=MAX_CELLS)
        for x in (0, 40):
            commit(memory, pages(radius=16, vertical=4, origin=(x, 64, 0), chunk=128, tick=1000+x*100))
        self.assertEqual(len(memory.cells), MAX_CELLS)
        self.assertIsNone(memory.lookup((-16, 60, -16)))

    def test_prefetch_inside_edge_and_latency_margin(self):
        data = pages(radius=16, vertical=4, chunk=128)
        commit(self.memory, data)
        inside = self.memory.prefetch_advice((0, 64, 0))
        edge = self.memory.prefetch_advice((10, 64, 0))
        early = self.memory.prefetch_advice((0, 64, 0), speed=5, scan_seconds=3, stopping_margin=2)
        self.assertFalse(inside["needed"])
        self.assertTrue(edge["needed"])
        self.assertTrue(early["needed"])
        self.assertAlmostEqual(edge["overlap_fraction"], 23/33)
        self.assertEqual(edge["read_mode"], "existing_api_player_centered_full_window")
        self.assertFalse(edge["execution_authority"])

    def test_prefetch_outside_vertical_and_negative_args(self):
        self.assertEqual(self.memory.prefetch_advice((0, 64, 0))["reason"], "no_complete_window")
        commit(self.memory, pages())
        self.assertTrue(self.memory.prefetch_advice((100, 64, 0))["needed"])
        self.assertTrue(self.memory.prefetch_advice((0, 65, 0))["needed"])
        with self.assertRaises(MemoryError): self.memory.prefetch_advice((0, 64, 0), speed=-1)

    def test_historical_route_forward_only_and_bounded(self):
        memory = TerrainMemory(CONTEXT, max_routes=1)
        trace = [(0, 64, 0), (1, 63, 0)]
        memory.remember_walked(trace, context=CONTEXT, evidence_id="first", observed_at=1)
        self.assertTrue(memory.candidate_routes(*trace)[0].revalidation_required)
        self.assertEqual(memory.candidate_routes(*reversed(trace)), ())
        memory.remember_walked(trace, context=CONTEXT, evidence_id="second", observed_at=2)
        self.assertEqual(list(memory.routes), ["second"])
        with self.assertRaisesRegex(MemoryError, "nonadjacent"):
            memory.remember_walked([(0, 64, 0), (10, 64, 0)], context=CONTEXT, evidence_id="bad", observed_at=2)

    def test_historical_route_never_bypasses_fresh_guard(self):
        commit(self.memory, pages())
        points = [(0, 64, 0), (1, 64, 0)]
        self.memory.remember_walked(points, context=CONTEXT, evidence_id="walked", observed_at=1)
        calls = []
        def refusing(candidate):
            calls.append(candidate.evidence_id)
            return False  # e.g. bridge removed / lava arrived / chunk unloaded.
        with self.assertRaisesRegex(MemoryError, "fresh_guard_refused"):
            candidate_for_existing_planner(self.memory, *points, fresh_guard=refusing)
        self.assertEqual(calls, ["walked"])
        candidate = candidate_for_existing_planner(self.memory, *points, fresh_guard=lambda route: True)
        self.assertTrue(candidate.revalidation_required)
        self.assertFalse(self.memory.summary()["execution_authority"])

    def test_fresh_guard_exception_propagates_no_retry(self):
        points = [(0, 64, 0), (1, 64, 0)]
        self.memory.remember_walked(points, context=CONTEXT, evidence_id="walked", observed_at=1)
        calls = []
        def uncertain(candidate):
            calls.append(1)
            raise RuntimeError("unknown")
        with self.assertRaisesRegex(RuntimeError, "unknown"):
            candidate_for_existing_planner(self.memory, *points, fresh_guard=uncertain)
        self.assertEqual(calls, [1])

    def test_receive_clock_reversal_and_boolean_tick_rejected(self):
        data = pages()
        with self.assertRaisesRegex(MemoryError, "receive_clock"):
            ingest_complete_window(self.memory, [(data[0], 2), (data[1], 1)])
        data[0]["game_time"] = True
        with self.assertRaises(MemoryError): commit(self.memory, data)


if __name__ == "__main__":
    unittest.main()

"""Offline policy fixtures; synthetic positives do not establish live safety."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
import math
from pathlib import Path
import unittest

from building_controller.ambient_entities import (
    AmbientPhase, AmbientPolicy, Box, classify_ambient_entities)
from building_controller.model import Pos
from building_controller.terrain import state_blockers
from tests.helpers import state as building_state, terrain


CONTEXT = ("00000000-0000-4000-8000-000000000001", "minecraft:overworld",
           "00000000-0000-4000-8000-000000000003", "offline-native-session")


def sample(rows=()):
    value = building_state()
    value.update(private_singleplayer=True, client_action={"action_session": CONTEXT[3]},
                 capability_guard={"schema_version": 1, "source_tick": 100, "source_nano": "1000000000"})
    value["player"].update(uuid=CONTEXT[2], x=0., y=64., z=0.,
        bounding_box={"min": {"x": -.3, "y": 64., "z": -.3}, "max": {"x": .3, "y": 65.8, "z": .3}})
    value["nearby"] = dict(radius=64., total=len(rows), returned=len(rows), truncated=False, entities=list(rows))
    return value


def policy(*boxes):
    return AmbientPolicy(CONTEXT, boxes or (Box((-2, 63, -2), (4, 68, 4)),))


def entity(kind="bee", x=24., ident=11):
    classes = {"bee": "animal.Bee", "sheep": "animal.Sheep", "boat": "vehicle.Boat",
               "item": "item.ItemEntity", "experience_orb": "ExperienceOrb"}
    row = dict(type="minecraft:" + kind, **{"class": "net.minecraft.world.entity." + classes[kind]},
        entity_id=ident, uuid=f"00000000-0000-4000-8000-{ident:012d}", x=x, y=64., z=0.,
        distance=abs(x), alive=True, on_ground=True, velocity={"x": 0., "y": 0., "z": 0.},
        bounding_box={"min": {"x": x-.4, "y": 64., "z": -.4},
                      "max": {"x": x+.4, "y": 65., "z": .4}})
    if kind == "boat":
        row.update(ordinary_boat=True, passenger_count=0, yaw_rate=0.)
    elif kind in ("bee", "sheep"):
        row.update(health=10., max_health=10., hurt_time=0, using_item=False,
            native_living=dict(schema_version=1, known=True, source="integrated_server_tick", reason="observed",
                entity_uuid=row["uuid"], entity_id=ident, entity_type=row["type"],
                world_generation=CONTEXT[0], dimension=CONTEXT[1], player_uuid=CONTEXT[2],
                source_tick=100, source_nano="950000000", sample_tick=100, sample_nano="1000000000",
                sample_age_ms=50., alive=True, coverage_complete=True, inspected=5,
                aggressive=False, current_target_known=True, current_target=None))
        if kind == "bee":
            row["native_living"]["bee"] = dict(angry=False, remaining_anger_ticks=0, persistent_anger_target_uuid=None)
    elif kind == "item":
        row["item"] = dict(id="minecraft:oak_log", count=1, empty=False, damage=0, max_damage=0,
            max_stack_size=64, item_fingerprint="synthetic-stack", component_fingerprint="synthetic-components")
    return row


class AmbientEntityTests(unittest.TestCase):
    def report(self, row, **kwargs):
        return classify_ambient_entities(sample([row]), policy(), **kwargs)

    def test_synthetic_distant_calm_entities_pass_and_all_raw_rows_are_preserved(self):
        rows = [entity("bee"), entity("sheep", ident=12), entity("boat", ident=13)]
        state = sample(rows); original = deepcopy(state)
        report = classify_ambient_entities(state, policy())
        self.assertTrue(report.ok, report.blockers)
        self.assertEqual(report.raw_entities, tuple(rows))
        self.assertTrue(all(raw is source for raw, source in zip(report.raw_entities, rows)))
        self.assertEqual([r.index for r in report.classifications], [0, 1, 2])
        self.assertEqual(state, original)

    def test_immutable_policy_and_no_predicate_or_string_opt_in(self):
        p = policy()
        with self.assertRaises(FrozenInstanceError): p.context = CONTEXT
        with self.assertRaises(ValueError): AmbientPolicy(CONTEXT, list(p.protected_boxes))
        for invalid in ({}, lambda *args: True, "ambient"):
            self.assertFalse(classify_ambient_entities(sample(), invalid).ok)
        self.assertFalse(classify_ambient_entities(sample(), p, phase="none").ok)

    def test_captured_paused_bees_with_missing_metadata_remain_blocked(self):
        raw = json.loads((Path(__file__).parent / "fixtures/paused_ambient_missing_living.json").read_text())
        rows = raw["entities"]
        self.assertEqual(len(rows), 5)
        self.assertTrue(all("native_living" not in row for row in rows))
        result = classify_ambient_entities(sample(rows), policy())
        self.assertFalse(result.ok)
        self.assertEqual(result.raw_entities, tuple(rows))
        for row, decision in zip(rows, result.classifications):
            if row["type"] == "minecraft:bee":
                self.assertEqual(decision.reason, "native_living_unknown")

    def test_unknown_aggressive_targeted_angry_and_incomplete_bees_fail(self):
        mutations = [lambda r:r.pop("native_living"),
            lambda r:r["native_living"].update(known=False),
            lambda r:r["native_living"].update(aggressive=True),
            lambda r:r["native_living"].update(current_target_known=False),
            lambda r:r["native_living"].pop("current_target"),
            lambda r:r["native_living"].update(current_target={"uuid": CONTEXT[2]}),
            lambda r:r["native_living"].update(coverage_complete=False),
            lambda r:r["native_living"].update(alive=False),
            lambda r:r["native_living"].update(inspected=4097),
            lambda r:r["native_living"]["bee"].update(angry=True),
            lambda r:r["native_living"]["bee"].update(remaining_anger_ticks=1),
            lambda r:r["native_living"]["bee"].update(remaining_anger_ticks=False),
            lambda r:r["native_living"]["bee"].update(persistent_anger_target_uuid=CONTEXT[2]),
            lambda r:r["native_living"]["bee"].pop("persistent_anger_target_uuid")]
        for change in mutations:
            with self.subTest(change=change):
                row=entity();change(row);self.assertFalse(self.report(row).ok)

    def test_native_age_tick_context_and_clock_contradictions_fail(self):
        for changes in ({"sample_age_ms": 251}, {"sample_age_ms": 1}, {"sample_age_ms": True},
                {"source_tick": 94}, {"sample_tick": 101}, {"source_nano": "1100000000"},
                {"sample_nano": "2000000000"}, {"sample_nano": 1000000000},
                {"source_nano": "-9223372036854775809"}, {"player_uuid": "other"},
                {"entity_id": True}, {"entity_uuid": CONTEXT[2]}, {"dimension": "minecraft:the_end"}):
            with self.subTest(changes=changes):
                row=entity();row["native_living"].update(changes);self.assertFalse(self.report(row).ok)
        state=sample([entity()]);state["capability_guard"]["source_tick"] = 99
        self.assertFalse(classify_ambient_entities(state,policy()).ok)

    def test_newer_than_header_source_is_valid_when_serialization_clock_proves_age(self):
        row=entity();row["native_living"].update(source_nano="1010000000", sample_nano="1020000000", sample_age_ms=10.)
        self.assertTrue(self.report(row).ok)

    def test_unknown_far_hostiles_projectiles_and_fake_vanilla_class_fail(self):
        for kind in ("minecraft:zombie", "minecraft:arrow", "minecraft:fireball", "minecraft:cow", "mod:bee"):
            row=entity(x=60.);row["type"]=kind;self.assertFalse(self.report(row).ok)
        row=entity();row["class"]="mod.CustomBee";self.assertFalse(self.report(row).ok)

    def test_near_fast_and_living_metadata_fail(self):
        for kind in ("sheep", "bee", "boat"):
            self.assertFalse(self.report(entity(kind,x=6.)).ok)
            row=entity(kind);row["velocity"]["x"]=.36;self.assertFalse(self.report(row).ok)
        for changes in ({"health": 0}, {"health": True}, {"hurt_time": True},
                        {"hurt_time": 1}, {"using_item": True}, {"max_health": float("nan")}):
            row=entity();row.update(changes);self.assertFalse(self.report(row).ok)

    def test_boat_passenger_unknown_or_nonordinary_fails(self):
        for changes in ({"passenger_count":1}, {"passenger_count":False},
                        {"ordinary_boat":False}, {"yaw_rate":float("nan")}, {"yaw_rate":2}):
            row=entity("boat");row.update(changes);self.assertFalse(self.report(row).ok)

    def test_malformed_coordinates_velocity_aabb_and_distance_fail(self):
        changes=[lambda r:r.update(x=True), lambda r:r.update(distance=100),
                 lambda r:r["velocity"].update(x=float("nan")),
                 lambda r:r["bounding_box"]["max"].update(x=float("inf")),
                 lambda r:r["bounding_box"]["min"].update(x=30),
                 lambda r:r["bounding_box"]["min"].update(x=False),
                 lambda r:r["bounding_box"]["max"].update(y=100)]
        for change in changes:
            row=entity();change(row);self.assertFalse(self.report(row).ok)

    def test_full_work_box_and_additional_targets_are_protected(self):
        state=sample([entity("sheep",x=24.)])
        far_work=Box((20,63,-2),(30,68,2))
        self.assertFalse(classify_ambient_entities(state,policy(far_work)).ok)
        self.assertFalse(classify_ambient_entities(state,policy(),additional_boxes=(far_work,)).ok)

    def test_complete_scan_exact_counts_radius_and_duplicate_identities(self):
        for changes in ({"truncated":True},{"total":2},{"returned":True},{"radius":True},{"entities":None}):
            state=sample([entity()]);state["nearby"].update(changes)
            self.assertFalse(classify_ambient_entities(state,policy()).ok)
        state=sample([entity(),entity()]);self.assertFalse(classify_ambient_entities(state,policy()).ok)
        state=sample();state["nearby"]["radius"]=16
        self.assertFalse(classify_ambient_entities(state,policy()).ok)
        state=sample([None, "unknown", entity()]);result=classify_ambient_entities(state,policy())
        self.assertEqual(len(result.raw_entities),3);self.assertEqual(len(result.classifications),3)
        self.assertFalse(result.ok)

    def test_position_filtered_scan_must_include_body_reach_beyond_clearance(self):
        state=sample();p=policy()
        farthest=max(math.dist((0,64,0),corner) for corner in ((4,68,4),(-2,63,-2)))
        state["nearby"]["radius"]=farthest+12
        self.assertFalse(classify_ambient_entities(state,p).ok)
        state["nearby"]["radius"]=farthest+17
        self.assertTrue(classify_ambient_entities(state,p).ok)

    def test_context_and_actual_player_aabb_required_even_when_empty(self):
        for key in ("uuid","dimension","bounding_box"):
            state=sample();state["player"].pop(key)
            self.assertFalse(classify_ambient_entities(state,policy()).ok)
        state=sample();state["private_singleplayer"]=False
        self.assertFalse(classify_ambient_entities(state,policy()).ok)

    def test_terrain_default_stays_strict_and_explicit_policy_works(self):
        state=sample([entity()]);scan=terrain();targets=[Pos(2,64,2)]
        self.assertIn("entities_present_or_scan_incomplete",state_blockers(state,scan,targets))
        self.assertEqual(state_blockers(state,scan,targets,ambient_policy=policy()),[])
        self.assertEqual(state_blockers(state,scan,[],ambient_policy=policy()),[])
        state["nearby"]["entities"][0]["native_living"]["bee"]["angry"]=True
        self.assertTrue(state_blockers(state,scan,[],ambient_policy=policy()))

    def test_narrow_oak_pickup_keeps_raw_rows_and_does_not_hide_other_items(self):
        row=entity("item",x=2.)
        self.assertFalse(self.report(row).ok)
        report=self.report(row,phase=AmbientPhase.OAK_LOG_PICKUP)
        self.assertTrue(report.ok,report.blockers);self.assertIs(report.raw_entities[0],row)
        falling=deepcopy(row);falling["velocity"]["y"]=-.6
        self.assertTrue(self.report(falling,phase=AmbientPhase.OAK_LOG_PICKUP).ok)
        falling["velocity"]["y"]=-1.1
        self.assertFalse(self.report(falling,phase=AmbientPhase.OAK_LOG_PICKUP).ok)
        for changes in ({"id":"minecraft:diamond"},{"count":True},{"max_stack_size":1},{"damage":1}):
            bad=deepcopy(row);bad["item"].update(changes)
            self.assertFalse(self.report(bad,phase=AmbientPhase.OAK_LOG_PICKUP).ok)
        self.assertFalse(self.report(entity("item",x=9.),phase=AmbientPhase.OAK_LOG_PICKUP).ok)

    def test_xp_requires_exact_native_furnace_phase_and_quiet_wait_rejects_it(self):
        row=entity("experience_orb",x=2.);state=sample([row])
        phase=AmbientPhase.FURNACE_OUTPUT_XP
        self.assertFalse(classify_ambient_entities(state,policy(),phase=phase).ok)
        state["movement_budget"]={"furnace_xp_allowed":True}
        self.assertTrue(classify_ambient_entities(state,policy(),phase=phase).ok)
        self.assertFalse(classify_ambient_entities(state,policy()).ok)
        state["movement_budget"]["furnace_xp_allowed"]=1
        self.assertFalse(classify_ambient_entities(state,policy(),phase=phase).ok)


if __name__ == "__main__":
    unittest.main()

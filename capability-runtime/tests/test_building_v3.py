"""Synthetic client-model tests, not Minecraft physics or live acceptance."""
from copy import deepcopy
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from mdc_skills.core import Outcome, SkillError
from mdc_skills import building
from mdc_skills.building_v3 import (VersionedBlueprint, seal_blueprint, execution_plan,
    stage_state, _door_hinge, _orientation_ok, _terrain, _routes, build, reconcile_build_progress, read_build_audit)
from building_controller.model import Pos
from test_building_capability import BuildingRuntime, _fixture


def blueprint(cells, *, clearance=(), light_checks=(), access_points=(), region=None):
    positions = [Pos(*p) for p, _, _ in cells] + [Pos.parse(p["position"]) for p in list(clearance) + list(light_checks)]
    region = region or {"min": {k: min(getattr(p, k) for p in positions) for k in ("x", "y", "z")}, "max": {k: max(getattr(p, k) for p in positions) for k in ("x", "y", "z")}}
    return seal_blueprint({"schema_version": 3, "identity": {"blueprint_id": "offline-test", "revision": "test-1", "source": "offline-generated-fixture"}, "region": region,
        "cells": [{"position": Pos(*p).json(), "block": b, "properties": props} for p, b, props in cells],
        "clearance": list(clearance), "light_checks": list(light_checks), "access_points": list(access_points)})


def stair(facing="south", shape="straight", half="bottom"):
    return dict(facing=facing, shape=shape, half=half, waterlogged="false")


def fence(**changes):
    return dict(dict.fromkeys(("north", "south", "east", "west", "waterlogged"), "false"), **changes)


def door(half="lower", facing="south", hinge="left"):
    return dict(half=half, facing=facing, hinge=hinge, open="false", powered="false")


class OrientedRuntime(BuildingRuntime):
    def __init__(self, **kwargs):
        super().__init__(radius=8, **kwargs)
        self.all_observations = []
        self.survey_count = 0
        self.corrupt_door_upper = False
        self.survey_duration = 7.3
        self.state["client_action"] = dict(action_session=self.context[3], action_id=None, status="idle")
        self.state["world"]["navigation_guard"] = dict(schema_version=1, epoch=0, rebind_ready=True,
            stable_ticks=3, fresh_binding_required=False)

    def observe(self, **kwargs):
        p = self.state["player"]
        p["bounding_box"] = {"min": dict(x=p["x"]-.3, y=p["y"], z=p["z"]-.3),
                             "max": dict(x=p["x"]+.3, y=p["y"]+1.8, z=p["z"]+.3)}
        result = super().observe(**kwargs)
        # Actual local scan is clipped around the player's current block. It
        # cannot observe distant cells simply because the fixture knows them.
        origin = Pos(*(math.floor(self.state["player"][k]) for k in ("x", "y", "z")))
        radius, vertical = kwargs.get("radius", 4), kwargs.get("vertical", 4)
        result.terrain.update(origin=origin.json(), radius=radius, vertical=vertical,
            cells=[c for c in result.terrain["cells"] if abs(c["x"]-origin.x) <= radius and abs(c["z"]-origin.z) <= radius and abs(c["y"]-origin.y) <= vertical])
        self.all_observations.append(("fresh", result))
        return result

    def validate_survey(self, survey):
        return survey

    def survey(self, **kwargs):
        self.survey_count += 1
        start = self.time
        first_tick = self.state["world"]["game_time"]
        self.time += self.survey_duration
        self.state["world"]["game_time"] += math.ceil(self.survey_duration * 20)
        result = self.observe(**kwargs)
        if kwargs:
            origin = Pos.parse(result.terrain["origin"])
            r, v = kwargs.get("radius",8), kwargs.get("vertical",4)
            result.terrain.update(radius=r, vertical=v, cells=[deepcopy(self.cells.get(pos,
                _fixture.cell(pos, "minecraft:stone" if pos.y <= 63 else "minecraft:air")))
                for x in range(-r,r+1) for z in range(-r,r+1) for y in range(-v,v+1)
                for pos in (origin.offset(x,y,z),)])
        else:
            # Legacy direct model probes remain fixed-origin geometry fixtures.
            result.terrain.update(origin=dict(x=0,y=64,z=0), radius=8, vertical=4,
                cells=deepcopy(list(self.cells.values())))
        result.terrain.update(source_tick=first_tick,
            capture_started_mono=start, capture_finished_mono=self.time)
        result.request_id = "survey-" + str(self.survey_count)
        self.all_observations.append(("survey", result))
        return result

    def execute(self, skill, command, verify, *, before, **kwargs):
        assert not before.request_id.startswith("survey-")
        if command["action"] != "place_block":
            return super().execute(skill, command, verify, before=before, **kwargs)
        self.actions.append(deepcopy(command))
        self.place_count += 1
        rid = "native-" + str(len(self.actions))
        fail = self.place_count == self.fail_place
        if not fail or self.lost_reply_applies:
            for row in command["placement_footprint"]:
                pos = Pos.parse(row["position"])
                assert self.cells[pos]["id"] == row["expected_id"]
                assert self.cells[pos]["properties"] == row["expected_properties"]
                self.cells[pos] = _fixture.cell(pos, row["block_id"], properties=deepcopy(row["properties"]))
                if self.corrupt_door_upper and row["properties"].get("half") == "upper":
                    self.cells[pos]["properties"]["hinge"] = "right" if row["properties"]["hinge"] == "left" else "left"
            # Model automatic neighbor updates. This is deliberately not an
            # independent engine proof, tested separately by native loader tests.
            states = {p: (raw["id"], raw["properties"]) for p, raw in self.cells.items()}
            for pos, raw in self.cells.items():
                raw["properties"] = stage_state(pos, states[pos], states)[1]
            item = self.state["player"]["inventory"][command["hotbar_slot"]]
            if self.consume:
                item["count"] -= 1
                if item["count"] == 0:
                    item.update(id="", empty=True)
        if fail:
            return Outcome("unknown", "transport_lost_no_replay", (rid,))
        for _ in range(2):
            after = self.observe(terrain=True)
            if not verify(before, after):
                return Outcome("blocked", "semantic_postcondition_failed", (rid,), {}, after)
        return Outcome("succeeded", "client_observed_stable", (rid,), {}, after)


def navigate_stub(runtime, goal, **kwargs):
    before = runtime.observe(terrain=True)
    return runtime.execute("offline_navigation", {"op": "action", "action": "follow_path", "waypoints": [dict(goal, x=goal["x"]+.5, z=goal["z"]+.5)]}, lambda a,b: True, before=before)


class VersionedBuildingTests(unittest.TestCase):
    def runtime(self, **kwargs):
        runtime = OrientedRuntime(**kwargs)
        self.addCleanup(runtime.close)
        return runtime

    def build(self, runtime, spec, **kwargs):
        with patch("mdc_skills.mobility.navigate_loaded", navigate_stub):
            return build(runtime, spec, job_id=kwargs.pop("job_id", "v3"), **kwargs)

    def test_sealed_revision_and_exact_state_validation(self):
        spec = blueprint([((0,64,0),"minecraft:oak_stairs",stair())])
        parsed = VersionedBlueprint.parse(spec)
        self.assertEqual(parsed.entries[0][2]["facing"], "south")
        changed = deepcopy(spec)
        changed["cells"][0]["properties"]["facing"] = "north"
        with self.assertRaisesRegex(SkillError, "content_hash"):
            VersionedBlueprint.parse(changed)
        changed_position=deepcopy(spec)
        changed_position["cells"][0]["position"]["ignored"]="not permitted"
        with self.assertRaisesRegex(SkillError,"exact_blueprint_position"):
            seal_blueprint(changed_position)
        changed["cells"][0]["properties"]["waterlogged"] = "true"
        with self.assertRaisesRegex(SkillError, "unsupported"):
            seal_blueprint(changed)

    def test_missing_door_half_duplicate_and_double_slab_rejected(self):
        for cells in ([((0,64,0),"minecraft:oak_door",door())],
                      [((0,64,0),"minecraft:oak_slab",dict(type="double",waterlogged="false"))],
                      [((0,64,0),"minecraft:oak_planks",{}),((0,64,0),"minecraft:oak_planks",{})]):
            with self.assertRaises(SkillError):
                blueprint(cells)

    def test_schema_covers_large_twofloor_region_without_design_inference(self):
        cells = [((x,y,z), "minecraft:oak_planks", {}) for y in (71,75,79) for x in range(-201,-188) for z in range(74,89)]
        spec = blueprint(cells)
        self.assertEqual(len(VersionedBlueprint.parse(spec).entries), 585)
        self.assertEqual(spec["region"]["max"], dict(x=-189,y=79,z=88))
        self.assertNotIn("approved", spec["identity"])

    def test_long_region_survey_is_never_mutation_freshness(self):
        runtime = self.runtime()
        spec = blueprint([((0,64,0),"minecraft:oak_planks",{})])
        survey = runtime.survey()
        with self.assertRaisesRegex(SkillError, "tick_mismatch|capture_interval"):
            _terrain(survey)
        result = self.build(runtime, spec)
        self.assertTrue(result.ok)
        self.assertFalse(result.evidence["simultaneous_region_snapshot"])
        self.assertEqual(result.evidence["final_verification"], "two_later_tick_fresh_local_samples_per_cell")
        for row in read_build_audit(runtime,job_id="v3")["cells"]:
            self.assertEqual(len(row["ticks"]),2)
            self.assertGreater(row["ticks"][1],row["ticks"][0])
            self.assertTrue(all(not rid.startswith("survey-") for rid in row["request_ids"]))

    def test_stair_slab_log_station_and_torch_actual_commands(self):
        cases = [("minecraft:oak_stairs",stair()), ("minecraft:oak_slab",dict(type="bottom",waterlogged="false")),
                 ("minecraft:oak_log",dict(axis="y")), ("minecraft:furnace",dict(facing="north",lit="false")), ("minecraft:torch",{})]
        for block, props in cases:
            with self.subTest(block=block):
                runtime = self.runtime(stock={block: 4})
                result = self.build(runtime, blueprint([((0,64,0),block,props)]))
                command = next(c for c in runtime.actions if c["action"] == "place_block")
                self.assertEqual(command["expected_block_properties"], props)
                self.assertIn("placement_yaw", command)
                self.assertIn("placement_hit", command)
                self.assertEqual(result.evidence["placements_this_call"], 1)

    def test_door_two_cells_consume_one_item_and_exact_upper(self):
        cells = [((0,64,0),"minecraft:oak_door",door()), ((0,65,0),"minecraft:oak_door",door("upper"))]
        runtime = self.runtime(stock={"minecraft:oak_door": 4})
        result = self.build(runtime, blueprint(cells))
        command = next(c for c in runtime.actions if c["action"] == "place_block")
        self.assertEqual(len(command["placement_footprint"]), 2)
        self.assertEqual(runtime.state["player"]["inventory"][0]["count"], 3)
        self.assertEqual(result.evidence["exact_cells_verified"], 2)
        bad = self.runtime(stock={"minecraft:oak_door": 4})
        bad.corrupt_door_upper = True
        with self.assertRaisesRegex(SkillError, "semantic_postcondition"):
            self.build(bad, blueprint(cells))

    def test_connected_fences_update_previously_placed_state(self):
        runtime = self.runtime(stock={"minecraft:oak_fence": 4})
        spec = blueprint([((0,64,0),"minecraft:oak_fence",fence(east="true")), ((1,64,0),"minecraft:oak_fence",fence(west="true"))])
        result = self.build(runtime, spec)
        self.assertEqual(result.evidence["placements_this_call"], 2)
        self.assertEqual(runtime.cells[Pos(0,64,0)]["properties"]["east"], "true")

    def test_wall_torch_top_slab_and_horizontal_log(self):
        for block, props, item in (("minecraft:wall_torch",dict(facing="south"),"minecraft:torch"),
                                   ("minecraft:oak_slab",dict(type="top",waterlogged="false"),"minecraft:oak_slab"),
                                   ("minecraft:oak_log",dict(axis="z"),"minecraft:oak_log")):
            with self.subTest(block=block):
                support=Pos(0,64,-1)
                runtime=self.runtime(stock={item:4},overrides={support:_fixture.cell(support,"minecraft:stone")})
                result=self.build(runtime,blueprint([((0,64,0),block,props)]))
                self.assertTrue(result.ok)
                command=next(c for c in runtime.actions if c["action"]=="place_block")
                self.assertEqual(command["face"],"south")
                self.assertEqual(runtime.state["player"]["inventory"][0]["count"],3)
                if block.endswith("slab"):
                    self.assertGreater(command["placement_hit"]["y"]-64,.5)

    def test_unknown_connected_fence_reconcile_accepts_expected_neighbor_update(self):
        runtime=self.runtime(stock={"minecraft:oak_fence":4})
        runtime.fail_place,runtime.lost_reply_applies=2,True
        spec=blueprint([((0,64,0),"minecraft:oak_fence",fence(east="true")),((1,64,0),"minecraft:oak_fence",fence(west="true"))])
        with self.assertRaisesRegex(SkillError,"transport_lost"):
            self.build(runtime,spec)
        count=len(runtime.actions)
        self.assertTrue(reconcile_build_progress(runtime,spec,job_id="v3").ok)
        self.assertEqual(len(runtime.actions),count)

    def test_physical_13_by_15_access_plan_uses_completed_floor(self):
        runtime=self.runtime(stock={"minecraft:oak_planks":195})
        runtime.state["player"].update(x=-7.5,z=.5)
        runtime.state["player"]["eye_position"]=dict(x=-7.5,y=65.62,z=.5)
        runtime.state["nearby"]["radius"]=48.
        survey=runtime.survey()
        survey.terrain.update(radius=16,vertical=8,cells=[c for page in _fixture.pages(radius=16,vertical=8) for c in page["cells"]])
        spec=blueprint([((x,64,z),"minecraft:oak_planks",{}) for x in range(-6,7) for z in range(-7,8)])
        proposal=execution_plan(spec,survey,historical=True)
        self.assertEqual(len(proposal["placements"]),195)
        self.assertTrue(any(p["stand"]["y"]==65 for p in proposal["placements"]))
        self.assertEqual(proposal["audit_stand"],dict(x=-8,y=64,z=0))

    def test_stair_corner_prediction(self):
        pos = Pos(0,64,0)
        states = {pos:("minecraft:oak_stairs",stair("north")), pos.offset(z=-1):("minecraft:oak_stairs",stair("west"))}
        self.assertEqual(stage_state(pos,states[pos],states)[1]["shape"], "outer_left")
        states = {pos:("minecraft:oak_stairs",stair("north")), pos.offset(z=1):("minecraft:oak_stairs",stair("east"))}
        self.assertEqual(stage_state(pos,states[pos],states)[1]["shape"], "inner_right")

    def test_door_hinge_hit_and_neighbor_solids(self):
        pos = Pos(0,64,0)
        self.assertEqual(_door_hinge(pos,"south",(.25,64,.5),{}), "right")
        self.assertEqual(_door_hinge(pos,"south",(.75,64,.5),{}), "left")
        self.assertEqual(_door_hinge(pos,"south",(.75,64,.5),{pos.offset(x=-1):("minecraft:stone",{})}), "right")

    def test_unknown_no_replay_and_readonly_reconciliation(self):
        runtime = self.runtime(stock={"minecraft:oak_door":4})
        runtime.fail_place, runtime.lost_reply_applies = 1, True
        spec = blueprint([((0,64,0),"minecraft:oak_door",door()),((0,65,0),"minecraft:oak_door",door("upper"))])
        with self.assertRaisesRegex(SkillError,"transport_lost"):
            self.build(runtime,spec)
        count = len(runtime.actions)
        with self.assertRaisesRegex(SkillError,"reconciliation"):
            self.build(runtime,spec)
        self.assertEqual(len(runtime.actions),count)
        result = reconcile_build_progress(runtime,spec,job_id="v3")
        self.assertFalse(result.evidence["causation_confirmed"])
        self.assertEqual(len(runtime.actions),count)

    def test_existing_cell_removed_never_rebuilt(self):
        runtime = self.runtime(overrides={Pos(0,64,0): _fixture.cell(Pos(0,64,0),"minecraft:oak_planks")})
        spec = blueprint([((0,64,0),"minecraft:oak_planks",{})])
        self.build(runtime,spec)
        runtime.cells[Pos(0,64,0)] = _fixture.cell(Pos(0,64,0))
        with self.assertRaisesRegex(SkillError,"previously_completed"):
            self.build(runtime,spec)
        self.assertEqual(runtime.place_count,0)

    def test_light_evidence_missing_or_low_fails_no_torch_inference(self):
        pos=Pos(0,64,0)
        for level in (None,0,1):
            runtime=self.runtime(overrides={pos:_fixture.cell(pos,"minecraft:torch")})
            if level is not None:
                runtime.cells[pos]["block_light"]=level
            spec=blueprint([((0,64,0),"minecraft:torch",{})],light_checks=[dict(position=pos.json(),min_block_light=1)])
            if level==1:
                self.assertTrue(self.build(runtime,spec).ok)
            else:
                with self.assertRaisesRegex(SkillError,"light_level"):
                    self.build(runtime,spec)

    def test_budget65_rejected_before_read_or_action(self):
        runtime=self.runtime()
        with self.assertRaisesRegex(SkillError,"movement_budget"):
            self.build(runtime,blueprint([((0,64,0),"minecraft:oak_planks",{})]),max_steps=65)
        self.assertEqual(runtime.all_observations,[])

    def test_distant_interruption_reconciles_only_local_pending_scope(self):
        runtime=self.runtime()
        runtime.fail_place,runtime.lost_reply_applies=2,True
        spec=blueprint([((-3,64,0),"minecraft:oak_planks",{}),((5,64,0),"minecraft:oak_planks",{})])
        with self.assertRaisesRegex(SkillError,"transport_lost"):
            self.build(runtime,spec)
        count=len(runtime.actions)
        runtime.state["player"].update(x=4.5,z=-1.5)
        runtime.state["player"]["eye_position"]=dict(x=4.5,y=65.62,z=-1.5)
        result=reconcile_build_progress(runtime,spec,job_id="v3")
        self.assertFalse(result.evidence["distant_completed_revalidated"])
        self.assertEqual(result.evidence["presence_scope"],"pending_footprint_and_expected_neighbor_updates")
        self.assertEqual(len(runtime.actions),count)
        runtime.cells[Pos(-3,64,0)]=_fixture.cell(Pos(-3,64,0))
        with self.assertRaisesRegex(SkillError,"previously_completed"):
            self.build(runtime,spec)
        self.assertEqual(len(runtime.actions),count)

    def test_audit_walk_has_fresh_per_cell_ticks_and_returns_to_exit(self):
        runtime=self.runtime()
        spec=blueprint([((-3,64,0),"minecraft:oak_planks",{}),((5,64,0),"minecraft:oak_planks",{})])
        result=self.build(runtime,spec)
        self.assertEqual({tuple(row["position"][k] for k in ("x","y","z")) for row in read_build_audit(runtime,job_id="v3")["cells"]},{(-3,64,0),(5,64,0)})
        for row in read_build_audit(runtime,job_id="v3")["cells"]:
            self.assertLess(row["ticks"][0],row["ticks"][1])
            self.assertTrue(all(rid.startswith("obs-") for rid in row["request_ids"]))
        self.assertEqual(result.evidence["final_exit_stand"],dict(x=-3,y=64,z=-3))
        self.assertEqual(runtime.state["player"]["x"],-2.5)

    def test_audit_movement_and_deadline_reserved_before_placement(self):
        runtime=self.runtime()
        runtime.effective_remaining_budget=lambda:dict(remaining_actions=4096,remaining_seconds=1)
        with self.assertRaisesRegex(SkillError,"reserve_final_audit"):
            self.build(runtime,blueprint([((0,64,0),"minecraft:oak_planks",{})]))
        self.assertEqual(runtime.actions,[])

    def test_stair_integer_treads_reach_upper_floor_without_scaffolds(self):
        runtime=self.runtime()
        runtime.state["player"].update(x=-2.5,z=.5)
        runtime.state["player"]["eye_position"]=dict(x=-2.5,y=65.62,z=.5)
        survey=runtime.survey()
        raw={Pos.parse(c):c for page in _fixture.pages(radius=8,vertical=8) for c in page["cells"]}
        for x in range(5):
            for y in range(64,64+x):
                pos=Pos(x,y,0)
                raw[pos]=_fixture.cell(pos,"minecraft:oak_planks")
            pos=Pos(x,64+x,0)
            raw[pos]=_fixture.cell(pos,"minecraft:oak_stairs",properties=stair("east"),full_top_support=False)
        survey.terrain.update(vertical=8,cells=list(raw.values()))
        terrain,_=_terrain(survey,historical=True)
        routes=_routes(terrain.cells,Pos(-3,64,0),set(),64)
        self.assertIn(Pos(4,69,0),routes)
        route=routes[Pos(4,69,0)]
        self.assertTrue(all(abs(b.x-a.x)+abs(b.z-a.z)==1 for a,b in zip(route,route[1:])))

    def test_fence_follows_stair_face_and_two_hop_corner_update(self):
        from mdc_skills.building_v3 import _stage_changes
        p=Pos(0,64,0)
        desired={p:("minecraft:oak_stairs",stair("east")),p.offset(x=1):("minecraft:oak_stairs",stair("south")),p.offset(z=-1):("minecraft:oak_fence",fence(south="true"))}
        states={Pos(x,64,z):("minecraft:air",{}) for x in range(-3,4) for z in range(-3,4)}
        states.update({q:("minecraft:air",{}) for q in (p.offset(x=1,y=-1),p.offset(x=1,y=1))})
        states[p]=("minecraft:oak_stairs",stair("east"))
        states[p.offset(z=-1)]=("minecraft:oak_fence",fence())
        projected,changed,required=_stage_changes((p.offset(x=1),),desired,states)
        self.assertEqual(projected[p][1]["shape"],"outer_right")
        # Exact final face support is independently pinned by loader tests.
        fenced=stage_state(p.offset(z=-1),desired[p.offset(z=-1)],projected)
        self.assertEqual(projected[p.offset(z=-1)],fenced)
        self.assertIn(p.offset(z=-2),required)

    def test_maximum_schema_lists_fit_segmented_main_checkpoint(self):
        from mdc_skills.building_v3 import _checkpoint_capacity
        positions=[(x,y,z) for y in (64,65) for x in range(64) for z in range(64)]
        cells=[(p,"minecraft:oak_stairs",stair("east","inner_right")) for p in positions]
        clear=[dict(position=Pos(x,y+2,z).json(),purpose="interior") for x,y,z in positions]
        light=[dict(position=Pos(*p).json(),min_block_light=1) for p in positions]
        access=[Pos(x,y+4,z).json() for x,y,z in positions]
        spec=blueprint(cells,clearance=clear,light_checks=light,access_points=access,region=dict(min=dict(x=0,y=64,z=0),max=dict(x=63,y=69,z=63)))
        parsed=VersionedBlueprint.parse(spec)
        data=dict(schema_version=3,blueprint=spec,blueprint_sha256="a"*64,context=["world","minecraft:overworld","player","native"],completed=[],pending=None,status="ready",placements=0)
        reserved=_checkpoint_capacity(data,parsed,[])
        self.assertLess(reserved,8*1024*1024)
        data["unexpected_padding"]="x"*(8*1024*1024)
        with self.assertRaisesRegex(SkillError,"capacity_insufficient_before_start"):
            _checkpoint_capacity(data,parsed,[])

    def test_audit_segment_written_before_manifest_and_no_replayed_placement(self):
        import mdc_skills.building_v3 as v3
        runtime=self.runtime()
        spec=blueprint([((0,64,0),"minecraft:oak_planks",{})])
        original=v3.atomic_write
        def crash(path,data):
            if path.name=="building-v3.json" and data.get("final_audit_segments"):
                raise OSError("synthetic manifest persistence interruption")
            return original(path,data)
        with patch("mdc_skills.building_v3.atomic_write",crash):
            with self.assertRaisesRegex(OSError,"manifest"):
                self.build(runtime,spec)
        self.assertEqual(runtime.place_count,1)
        self.assertTrue(list(runtime.journal_directory.glob("building-v3-audit-*.json")))
        result=self.build(runtime,spec)
        self.assertEqual(result.evidence["placements_this_call"],0)
        self.assertEqual(runtime.place_count,1)
        self.assertEqual(len(read_build_audit(runtime,job_id="v3")["cells"]),1)

    def test_completed_checkpoint_reopen_rejects_missing_or_tampered_audit(self):
        import json
        for missing in (False,True):
            runtime=self.runtime()
            spec=blueprint([((0,64,0),"minecraft:oak_planks",{})])
            result=self.build(runtime,spec)
            segment=runtime.journal_directory/result.evidence["final_audit_segments"][0]["file"]
            if missing:
                segment.unlink()
            else:
                value=json.loads(segment.read_text())
                value["ticks"][0]+=1
                segment.write_text(json.dumps(value))
            count=len(runtime.actions)
            with self.assertRaisesRegex(SkillError,"audit_segment"):
                self.build(runtime,spec)
            self.assertEqual(len(runtime.actions),count)

    def test_fullcube_access_can_ascend_and_descend(self):
        runtime=self.runtime(overrides={Pos(-1,64,-3):_fixture.cell(Pos(-1,64,-3),"minecraft:stone")})
        observed=runtime.survey()
        terrain,_=_terrain(observed,historical=True)
        routes=_routes(terrain.cells,Pos(-3,64,-3),set(),64)
        self.assertIn(Pos(-1,65,-3),routes)
        down=_routes(terrain.cells,Pos(-1,65,-3),set(),64)
        self.assertIn(Pos(-3,64,-3),down)


class OrientedGuardedClient:
    """Real Runtime gateway/native ID path with synthetic offline endpoint data."""
    def __init__(self, model, clock):
        from test_building_capability import GuardedBuildingClient
        self.base = GuardedBuildingClient(model, clock)
        self.model, self.clock = model, clock
        self.commands = self.base.commands
        self.reads = []

    def session(self):
        return self.base.session()

    def submit(self, command, request_id):
        return self.base.submit(command, request_id)

    def wait(self, request_id, timeout=30):
        from support_core import state as safe_state
        command = self.base.saved[request_id]
        is_survey = command.get("capability_survey") is True
        started = self.clock()
        first = self.model.state["world"]["game_time"]
        if is_survey:
            self.clock.sleep(7.3)
            self.model.state["world"]["game_time"] += 146
        self.model.time = self.clock()
        observation = self.model.observe(radius=command.get("radius",4),vertical=command.get("vertical",4))
        value = safe_state(observation.tick)
        value.update(observation.state)
        value["player"] = {**safe_state(observation.tick)["player"], **observation.player}
        value["client_action"] = deepcopy(self.base.action)
        value["world"]["navigation_guard"] = dict(schema_version=1,epoch=0,rebind_ready=True,fresh_binding_required=False,stable_ticks=3)
        payload = {"state":value}
        if command["op"] == "observe":
            self.reads.append((is_survey, observation.tick))
        if command.get("terrain"):
            terrain=deepcopy(observation.terrain)
            origin=Pos.parse(terrain["origin"])
            r,v=command["radius"],command["vertical"]
            positions=[origin.offset(x,y,z) for x in range(-r,r+1) for z in range(-r,r+1) for y in range(-v,v+1)]
            terrain.update(radius=r,vertical=v,cells=[deepcopy(self.model.cells.get(p,_fixture.cell(p,"minecraft:stone" if p.y<=63 else "minecraft:air"))) for p in positions])
            if is_survey:
                count=len(positions)
                pages=[]
                for offset in range(0,count,128):
                    fraction=(offset+min(128,count-offset))/count
                    pages.append(dict(offset=offset,returned=min(128,count-offset),source_tick=first,
                        response_tick=min(observation.tick,first+math.ceil(146*fraction)),captured_mono=started+7.3*fraction))
                terrain.update(historical_survey=True,source_tick=first,last_tick=observation.tick,
                    capture_started_mono=started,capture_finished_mono=self.clock(),source_pages=pages)
            payload["terrain"]=terrain
        if command["op"]=="action":
            payload["action"]=deepcopy(self.base.action)
        return dict(request_id=request_id,session_id=self.base.session_id,status="succeeded",result=payload)


class VersionedBuildingRealRuntimeTests(unittest.TestCase):
    def test_real_runtime_survey_fresh_local_guard_and_native_footprints(self):
        import tempfile
        from mdc_skills.core import Runtime
        from support_core import Clock
        model=OrientedRuntime(stock={"minecraft:oak_door":4})
        self.addCleanup(model.close)
        clock=Clock()
        client=OrientedGuardedClient(model,clock)
        spec=blueprint([((0,64,0),"minecraft:oak_door",door()),((0,65,0),"minecraft:oak_door",door("upper"))])
        with tempfile.TemporaryDirectory() as directory, Runtime(client,directory,clock=clock,sleeper=clock.sleep) as runtime:
            with patch("mdc_skills.mobility.navigate_loaded",navigate_stub):
                result=build(runtime,spec,job_id="real-v3")
        self.assertTrue(result.ok)
        placed=[c for c in client.commands if c.get("action")=="place_block"]
        self.assertEqual(len(placed),1)
        self.assertEqual(len(placed[0]["placement_footprint"]),2)
        self.assertIn("capability_guard",placed[0])
        self.assertIn(placed[0]["capability_guard"]["source_tick"], [tick for survey, tick in client.reads if not survey])
        self.assertNotIn(placed[0]["capability_guard"]["source_tick"], [tick for survey, tick in client.reads if survey])
        self.assertFalse(result.evidence["server_confirmed"])
        self.assertTrue(any(c.get("capability_survey") for c in client.commands))

if __name__ == "__main__":
    unittest.main()

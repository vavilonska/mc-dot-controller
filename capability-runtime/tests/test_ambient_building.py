"""Actual Runtime + generic v3 builder, synthetic endpoint facts, no game I/O."""
from copy import deepcopy
import math
import tempfile
import unittest
from unittest.mock import patch

from building_controller.ambient_entities import AmbientPolicy, Box, classify_ambient_entities
from mdc_skills.core import Runtime, SkillError, require
from mdc_skills.building_v3 import build
from support_core import Clock
from test_building_v3 import OrientedRuntime, OrientedGuardedClient, blueprint, door, navigate_stub


class AmbientClient(OrientedGuardedClient):
    def __init__(self, model, clock):
        super().__init__(model, clock)
        self.captured = []
        self.angry_after_place = False
        self.missing_metadata = False

    def wait(self, request_id, timeout=30):
        result = super().wait(request_id, timeout)
        state = result["result"]["state"]
        player, tick = state["player"], state["world"]["game_time"]
        player["bounding_box"] = {
            "min": {"x": player["x"]-.3, "y": player["y"], "z": player["z"]-.3},
            "max": {"x": player["x"]+.3, "y": player["y"]+1.8, "z": player["z"]+.3}}
        nano = int(state["capability_guard"]["source_nano"])
        row = dict(type="minecraft:bee", **{"class": "net.minecraft.world.entity.animal.Bee"},
            uuid="00000000-0000-4000-8000-000000000009", entity_id=9,
            x=24., y=64., z=0., alive=True, on_ground=False,
            velocity={"x": 0., "y": 0., "z": 0.}, health=10., max_health=10., hurt_time=0, using_item=False,
            distance=math.dist((player["x"],player["y"],player["z"]),(24.,64.,0.)),
            bounding_box={"min":{"x":23.65,"y":64.,"z":-.35},"max":{"x":24.35,"y":64.6,"z":.35}})
        if not self.missing_metadata:
            row["native_living"] = dict(schema_version=1, known=True, source="integrated_server_tick", reason="observed",
                entity_uuid=row["uuid"], entity_id=9, entity_type=row["type"],
                world_generation=state["world"]["world_generation"], dimension=state["world"]["dimension"],
                player_uuid=player["uuid"], source_tick=tick, sample_tick=tick,
                source_nano=str(nano-50_000_000), sample_nano=str(nano), sample_age_ms=50.,
                alive=True, coverage_complete=True, inspected=3, aggressive=False, current_target_known=True,
                current_target=None, bee=dict(angry=self.angry_after_place and self.model.place_count > 0,
                    remaining_anger_ticks=0, persistent_anger_target_uuid=None))
        state["nearby"] = dict(radius=48.,total=1,returned=1,truncated=False,entities=[row])
        self.captured.append(deepcopy(state))
        return result


class GuardedAmbientRuntime(Runtime):
    """Equivalent to a case-owned state guard; base Runtime remains unchanged."""
    def _validate_state(self, payload, **kwargs):
        result = super()._validate_state(payload, **kwargs)
        report = classify_ambient_entities(result[0], self.ambient_policy)
        require(report.ok, "ambient_case_guard:" + ",".join(report.blockers))
        return result


class AmbientBuildingRuntimeTests(unittest.TestCase):
    def fixture(self):
        model = OrientedRuntime(stock={"minecraft:oak_door":4})
        self.addCleanup(model.close)
        clock = Clock(); client = AmbientClient(model, clock)
        spec = blueprint([((0,64,0),"minecraft:oak_door",door()),
                          ((0,65,0),"minecraft:oak_door",door("upper"))])
        context = (model.state["world"]["world_generation"], "minecraft:overworld",
                   model.state["player"]["uuid"], client.base.native_id)
        # Full original corridor/work/door/audit envelope remains fixed.
        policy = AmbientPolicy(context, (Box((-6,63,-6),(4,69,4)),))
        return model,clock,client,spec,policy

    def test_real_runtime_generic_door_build_keeps_distant_bee_and_exact_receipts(self):
        model,clock,client,spec,policy=self.fixture()
        with tempfile.TemporaryDirectory() as directory, GuardedAmbientRuntime(
                client,directory,clock=clock,sleeper=clock.sleep) as runtime:
            runtime.ambient_policy=policy
            with patch("mdc_skills.mobility.navigate_loaded",navigate_stub):
                result=build(runtime,spec,job_id="ambient-real-v3")
            self.assertTrue(result.ok,result)
            self.assertIs(runtime.ambient_policy,policy)
            self.assertIsNone(runtime.pending_request_id)
        placed=[c for c in client.commands if c.get("action")=="place_block"]
        self.assertEqual(len(placed),1)
        self.assertEqual(len(placed[0]["placement_footprint"]),2)
        self.assertIn("capability_guard",placed[0])
        self.assertTrue(all(len(s["nearby"]["entities"])==1 for s in client.captured))
        self.assertFalse(result.evidence["server_confirmed"])

    def test_without_opt_in_generic_builder_still_rejects_nonempty_snapshot(self):
        model,clock,client,spec,policy=self.fixture()
        with tempfile.TemporaryDirectory() as directory, Runtime(
                client,directory,clock=clock,sleeper=clock.sleep) as runtime:
            with self.assertRaisesRegex(SkillError,"entities_present_or_scan_incomplete"):
                build(runtime,spec,job_id="ambient-default-strict")
        self.assertFalse(any(c.get("op")=="action" for c in client.commands))

    def test_unknown_bee_blocks_actual_runtime_before_first_mutation(self):
        model,clock,client,spec,policy=self.fixture();client.missing_metadata=True
        with tempfile.TemporaryDirectory() as directory, GuardedAmbientRuntime(
                client,directory,clock=clock,sleeper=clock.sleep) as runtime:
            runtime.ambient_policy=policy
            with self.assertRaisesRegex(SkillError,"native_living_unknown"):
                build(runtime,spec,job_id="ambient-unknown-bee")
        self.assertFalse(any(c.get("op")=="action" for c in client.commands))

    def test_angry_bee_on_internal_post_action_sample_stops_without_replay(self):
        model,clock,client,spec,policy=self.fixture();client.angry_after_place=True
        with tempfile.TemporaryDirectory() as directory, GuardedAmbientRuntime(
                client,directory,clock=clock,sleeper=clock.sleep) as runtime:
            runtime.ambient_policy=policy
            with patch("mdc_skills.mobility.navigate_loaded",navigate_stub):
                with self.assertRaises(SkillError):
                    build(runtime,spec,job_id="ambient-angry-after-place")
        self.assertEqual(len([c for c in client.commands if c.get("action")=="place_block"]),1)
        self.assertTrue(any(s["nearby"]["entities"][0]["native_living"]["bee"]["angry"] for s in client.captured))

    def test_plain_runtime_opt_in_checks_final_audit_after_last_placement(self):
        model,clock,client,spec,policy=self.fixture();client.angry_after_place=True
        # No case-owned _validate_state override: the generic builder itself
        # must retain the policy when every requested block is already placed.
        with tempfile.TemporaryDirectory() as directory, Runtime(
                client,directory,clock=clock,sleeper=clock.sleep) as runtime:
            runtime.ambient_policy=policy
            with patch("mdc_skills.mobility.navigate_loaded",navigate_stub):
                with self.assertRaisesRegex(SkillError,"building_ambient_observation_blocked"):
                    build(runtime,spec,job_id="ambient-final-audit")
            self.assertIsNone(runtime.pending_request_id)
        self.assertEqual(len([c for c in client.commands if c.get("action")=="place_block"]),1)


if __name__ == "__main__":
    unittest.main()

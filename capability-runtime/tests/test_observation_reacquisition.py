"""Offline Runtime/read enrollment tests; endpoint samples are synthetic.

The tiny fixture classifier exercises the exception contract only. Production
entity policy has its own strict classifier tests, and is never replaced here.
The final class uses actual IntentClient/Watchdog/Resident adapters.
"""
from copy import deepcopy
import json
import tempfile
import unittest

from mdc_skills.core import Runtime, SkillError, ObservationUnavailable, require
from mdc_skills.movement_budget import MovementBudgetRuntime
from mdc_skills.observation_reacquisition import read_with_reacquisition, reacquisition_enrolled
from support_core import Client, Clock, NATIVE, state, move, arrived
import test_movement_budget as budget_tests
from building_controller.ambient_entities import (AmbientPolicy, Box,
    classify_ambient_entities, reacquirable_entity_absence)


class FixtureClassifier:
    def _validate_state(self, payload, **kwargs):
        value, context, tick = super()._validate_state(payload, **kwargs)
        mode = value.get("fixture_entity_mode", "absent")
        if mode == "unavailable":
            if reacquisition_enrolled(self):
                raise ObservationUnavailable("ambient_entity_observation_unavailable", evidence={
                    "context": list(context), "game_tick": tick,
                    "missing_entities": [{"index": 0, "uuid": "fixture-bee", "entity_id": 11,
                        "type": "minecraft:bee", "reason": "entity_not_observed"}],
                    "classifier_blockers": ["native_living_binding_unknown"]})
            raise SkillError("native_living_binding_unknown")
        require(mode in ("absent", "known_calm"), "fixture_other_hazard")
        return value, context, tick


class ClassifiedRuntime(FixtureClassifier, Runtime):
    pass


class ClassifiedBudgetRuntime(MovementBudgetRuntime):
    """Real production entity classifier over the actual local adapter chain."""
    def _validate_state(self, payload, **kwargs):
        value, context, tick = super()._validate_state(payload, **kwargs)
        if not hasattr(self, "ambient_policy"):
            self.ambient_policy = AmbientPolicy(context, (Box((-2, 63, -2), (4, 68, 4)),))
        report = classify_ambient_entities(value, self.ambient_policy)
        if not report.ok:
            evidence = reacquirable_entity_absence(value, self.ambient_policy)
            if evidence is not None and reacquisition_enrolled(self):
                raise ObservationUnavailable("ambient_entity_observation_unavailable", evidence=evidence)
            raise SkillError(";".join(report.blockers))
        return value, context, tick


def endpoint_entities(value, mode="absent"):
    """Synthetic complete client rows with the actual native-living wire shape."""
    value["fixture_entity_mode"] = mode
    p, w = value["player"], value["world"]
    p["bounding_box"] = {"min": {"x": p["x"]-.3, "y": p["y"], "z": p["z"]-.3},
                         "max": {"x": p["x"]+.3, "y": p["y"]+1.8, "z": p["z"]+.3}}
    rows = []
    if mode != "absent":
        row = {"type": "minecraft:bee", "class": "net.minecraft.world.entity.animal.Bee",
            "entity_id": 11, "uuid": "00000000-0000-4000-8000-000000000011",
            "x": 24.5, "y": 64., "z": .5, "distance": 24., "alive": True, "on_ground": True,
            "velocity": {"x": 0., "y": 0., "z": 0.},
            "bounding_box": {"min": {"x": 24.1, "y": 64., "z": .1},
                             "max": {"x": 24.9, "y": 65., "z": .9}},
            "health": 10., "max_health": 10., "hurt_time": 0, "using_item": False}
        facts = {"schema_version": 1, "entity_uuid": row["uuid"], "entity_id": 11,
            "entity_type": row["type"], "dimension": w["dimension"],
            "world_generation": w["world_generation"], "player_uuid": p["uuid"],
            "known": False, "source": "unavailable", "reason": "entity_not_observed",
            "current_target_known": False, "coverage_complete": True, "inspected": 5}
        if mode == "known_calm":
            nano = int(value["capability_guard"]["source_nano"])
            facts.update(known=True, source="integrated_server_tick", reason="observed",
                current_target_known=True, current_target=None, aggressive=False, alive=True,
                source_tick=w["game_time"], sample_tick=w["game_time"], source_nano=str(nano-50_000_000),
                sample_nano=str(nano), sample_age_ms=50.,
                bee={"angry": False, "remaining_anger_ticks": 0, "persistent_anger_target_uuid": None})
        row["native_living"] = facts
        rows.append(row)
    value["nearby"].update(entities=rows, total=len(rows), returned=len(rows), truncated=False, radius=48)
    return value


class ReadReacquisitionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="offline-read-reacquisition-")
        self.clock = Clock()
        self.client = Client(self.clock)
        self.client.epoch = 4
        self.runtime = ClassifiedRuntime(self.client, self.temp.name,
            clock=self.clock, sleeper=self.clock.sleep)
        self.baseline = self.runtime.observe()
        self.reads = 0
        self.modes = ["unavailable", "absent"]
        self.deadlines = 0

    def tearDown(self):
        self.runtime.close()
        self.temp.cleanup()

    def deadline(self):
        self.deadlines += 1

    def read(self):
        mode = self.modes[min(self.reads, len(self.modes) - 1)]
        self.reads += 1
        self.client.patch_state = lambda s: {**s, "fixture_entity_mode": mode}
        return self.runtime.observe()

    def acquire(self, **kwargs):
        return read_with_reacquisition(self.runtime, self.read, deadline_check=self.deadline, **kwargs)

    def test_absent_later_frame_passes_without_rewriting_unavailable_frame(self):
        observed = self.acquire()
        self.assertEqual(self.reads, 2)
        self.assertEqual(observed.state["fixture_entity_mode"], "absent")
        self.assertEqual(self.runtime._preflight_request_id, observed.request_id)
        self.assertEqual(self.client.action_count, 0)
        summary = self.runtime._journal["observation_reacquisition"]
        self.assertEqual(summary["additional_reads"], 1)
        first = self.runtime._journal["records"][summary["attempts"][0]["request_id"]]
        self.assertEqual(first["status"], "blocked")
        self.assertFalse(first["evidence"]["preflight_eligible"])
        self.assertEqual(first["reacquisition_summary"], summary)
        raw = self.runtime._read_evidence(first["receipt_ref"], "receipt")
        self.assertEqual(raw["result"]["state"]["fixture_entity_mode"], "unavailable")
        self.assertEqual(self.runtime.audit_evidence()["receipts"], 3)
        self.assertGreaterEqual(self.deadlines, 7)

    def test_returned_known_calm_frame_is_normal_fresh_observation(self):
        self.modes = ["unavailable", "known_calm"]
        observed = self.acquire()
        self.assertEqual(observed.state["fixture_entity_mode"], "known_calm")
        self.runtime._fresh(observed)
        self.assertGreater(observed.tick, self.baseline.tick)

    def test_three_persistent_missing_frames_exhaust_exact_bound(self):
        self.modes = ["unavailable"]
        with self.assertRaises(ObservationUnavailable) as caught:
            self.acquire()
        self.assertEqual(self.reads, 3)
        self.assertAlmostEqual(self.clock.now, 100.104)
        self.assertIsNone(self.runtime._preflight_request_id)
        self.assertIsNone(self.runtime.pending_request_id)
        summary = self.runtime._journal["observation_reacquisition"]
        self.assertEqual(summary["additional_reads"], 2)
        self.assertEqual(len(summary["attempts"]), 3)
        self.assertEqual(caught.exception.request_id, summary["attempts"][-1]["request_id"])
        self.assertEqual(caught.exception.evidence["game_tick"], self.client.tick)
        self.assertTrue(all(attempt["eligible_unavailable"] for attempt in summary["attempts"]))

    def test_other_hazard_is_not_retried(self):
        self.modes = ["other"]
        with self.assertRaisesRegex(SkillError, "fixture_other_hazard"):
            self.acquire()
        self.assertEqual(self.reads, 1)
        self.assertIsNone(self.runtime._preflight_request_id)

    def test_direct_unavailable_observe_is_not_enrolled(self):
        self.client.patch_state = lambda s: {**s, "fixture_entity_mode": "unavailable"}
        with self.assertRaisesRegex(SkillError, "native_living_binding_unknown"):
            self.runtime.observe()
        self.assertEqual(len(self.client.calls), 2)

    def test_pending_and_semantic_pending_never_read_or_clear(self):
        for key in ("pending", "semantic_pending"):
            with self.subTest(key=key):
                self.runtime._journal[key] = self.baseline.request_id
                calls = len(self.client.calls)
                with self.assertRaises(SkillError):
                    self.acquire()
                self.assertEqual(len(self.client.calls), calls)
                self.assertEqual(self.runtime._journal[key], self.baseline.request_id)
                self.runtime._journal[key] = None

    def test_context_change_during_wait_blocks_before_next_observation(self):
        def sleep(seconds):
            self.clock.sleep(seconds)
            self.client.session_id = "changed-gateway"
        self.runtime.sleeper = sleep
        with self.assertRaisesRegex(SkillError, "gateway_session_changed"):
            self.acquire()
        self.assertEqual(self.reads, 1)

    def test_epoch_change_during_wait_blocks_before_next_observation(self):
        def sleep(seconds):
            self.clock.sleep(seconds)
            self.client.epoch += 1
        self.runtime.sleeper = sleep
        with self.assertRaisesRegex(SkillError, "observation_reacquisition_epoch_changed"):
            self.acquire()
        self.assertEqual(self.reads, 1)

    def test_changed_player_on_fresh_followup_still_blocks(self):
        original = self.read
        def read():
            if self.reads == 1:
                self.reads += 1
                def changed(s):
                    s["player"]["uuid"] = "other-player"
                    return s
                self.client.patch_state = changed
                return self.runtime.observe()
            return original()
        with self.assertRaisesRegex(SkillError, "world_dimension_player_or_action_session_changed"):
            read_with_reacquisition(self.runtime, read, deadline_check=self.deadline)
        self.assertEqual(self.reads, 2)
        self.assertIsNone(self.runtime._preflight_request_id)

    def test_deadline_expiry_during_wait_prevents_extra_read(self):
        end = self.clock.now + .02
        def check():
            require(self.clock.now < end, "original_goal_deadline")
        with self.assertRaisesRegex(SkillError, "original_goal_deadline"):
            read_with_reacquisition(self.runtime, self.read, deadline_check=check)
        self.assertEqual(self.reads, 1)

    def test_stale_acquisition_never_retries_or_restamps(self):
        original = self.client.wait
        def slow(*args, **kwargs):
            result = original(*args, **kwargs)
            self.clock.now += .81
            return result
        self.client.wait = slow
        with self.assertRaisesRegex(SkillError, "observation_acquisition_stale"):
            self.acquire()
        self.assertEqual(self.reads, 1)

    def test_unknown_read_stays_pending_and_no_retry(self):
        self.client.patch_result = lambda result: {**result, "request_id": "wrong-id"}
        with self.assertRaisesRegex(SkillError, "result_request_identity_mismatch") as caught:
            self.acquire()
        self.assertEqual(caught.exception.status, "unknown")
        self.assertEqual(self.reads, 1)
        self.assertIsNotNone(self.runtime.pending_request_id)

    def test_native_active_or_release_unconfirmed_never_retries(self):
        for action in ({"status": "running"}, {"status": "idle", "action_id": "not-idle"},
                       {"status": "succeeded", "action_id": "native-one", "result": {}}):
            with self.subTest(action=action):
                self.client.native = {"action_session": NATIVE, **action}
                self.reads = 0
                with self.assertRaises(SkillError):
                    self.acquire()
                self.assertEqual(self.reads, 1)

    def test_mutation_callback_cannot_dispatch(self):
        def not_a_read():
            return self.runtime.execute("walk", move(), arrived, before=self.baseline)
        with self.assertRaisesRegex(SkillError, "observation_reacquisition_requires_one_observe"):
            read_with_reacquisition(self.runtime, not_a_read, deadline_check=self.deadline)
        self.assertEqual(self.client.action_count, 0)

    def test_larger_budget_and_wait_rejected(self):
        for kwargs in ({"max_additional_reads": 3}, {"max_additional_reads": True},
                       {"wait_seconds": .101}, {"wait_seconds": float("nan")}):
            with self.subTest(kwargs=kwargs), self.assertRaises(SkillError):
                self.acquire(**kwargs)
        self.assertEqual(self.reads, 0)

    def test_safe_first_frame_keeps_ordinary_terminal_no_action_semantics(self):
        self.client.native = {"action_session": NATIVE, "status": "cancelled", "action_id": None}
        self.modes = ["absent"]
        observed = self.acquire()
        self.assertEqual(observed.state["client_action"]["status"], "cancelled")
        self.assertEqual(self.reads, 1)

    def test_constructed_exception_without_runtime_token_cannot_retry(self):
        calls = []
        def not_enrolled_evidence():
            calls.append(True)
            raise ObservationUnavailable("untrusted_unavailability", evidence={})
        with self.assertRaisesRegex(ObservationUnavailable, "untrusted_unavailability"):
            read_with_reacquisition(self.runtime, not_enrolled_evidence, deadline_check=self.deadline)
        self.assertEqual(len(calls), 1)
        self.assertIsNone(self.runtime._preflight_request_id)

    def test_deadline_after_safe_read_invalidates_new_preflight(self):
        self.modes = ["absent"]
        end = self.clock.now + .0005
        def check():
            require(self.clock.now < end, "original_goal_deadline")
        with self.assertRaisesRegex(SkillError, "original_goal_deadline"):
            read_with_reacquisition(self.runtime, self.read, deadline_check=check)
        self.assertEqual(self.reads, 1)
        self.assertIsNone(self.runtime._preflight_request_id)

    def test_native_action_identity_cannot_change_between_missing_and_safe(self):
        self.client.native = {"action_session": NATIVE, "status": "succeeded", "action_id": "first",
                              "result": {"input_release_confirmed": True}}
        def sleep(seconds):
            self.clock.sleep(seconds)
            self.client.native["action_id"] = "second"
        self.runtime.sleeper = sleep
        with self.assertRaisesRegex(SkillError, "observation_reacquisition_native_action_changed"):
            self.acquire()
        self.assertEqual(self.reads, 2)
        self.assertIsNone(self.runtime._preflight_request_id)

    def test_same_tick_followup_is_not_a_new_frame(self):
        original = self.read
        def read():
            if self.reads == 1:
                self.reads += 1
                tick = self.runtime._observation_reacquisition.last_tick
                def repeated(s):
                    s["world"]["game_time"] = tick
                    s["capability_guard"]["source_tick"] = tick
                    return s
                self.client.patch_state = repeated
                return self.runtime.observe()
            return original()
        with self.assertRaisesRegex(SkillError, "observation_reacquisition_tick_not_advanced"):
            read_with_reacquisition(self.runtime, read, deadline_check=self.deadline)
        self.assertEqual(self.reads, 2)
        self.assertIsNone(self.runtime._preflight_request_id)


class ActualChainReadReacquisitionTests(unittest.TestCase):
    until = budget_tests.MovementBudgetChainTests.until
    tearDown = budget_tests.MovementBudgetChainTests.tearDown

    def setUp(self):
        budget_tests.MovementBudgetChainTests.setUp(self)
        self.runtime.close()
        self.bridge.patch_snapshot = endpoint_entities
        self.runtime = ClassifiedBudgetRuntime(self.client, self.root / "reacquisition-runtime",
            bundle_id="read-only-reacquisition-case", wait_timeout=3)
        self.addCleanup(self.runtime.close)
        started = self.runtime.start(before=self.runtime.observe(entity_radius=48))
        self.assertTrue(started.ok, started)
        self.posts_before = deepcopy(self.bridge.posts)
        self.read_count = 0
        self.modes = ["unavailable", "absent"]

    def acquire(self):
        def read():
            mode = self.modes[min(self.read_count, len(self.modes) - 1)]
            self.read_count += 1
            self.bridge.patch_snapshot = lambda s: endpoint_entities(s, mode)
            return self.runtime.observe(entity_radius=48)
        return read_with_reacquisition(self.runtime, read, deadline_check=lambda: None)

    def assert_no_mutation(self):
        self.assertEqual(self.bridge.posts, self.posts_before)
        self.assertIsNone(self.runtime.pending_request_id)
        self.assertIsNone(self.runtime._journal["semantic_pending"])

    def test_actual_chain_disappeared_bee_passes_new_frame_without_budget_latch(self):
        observed = self.acquire()
        self.assertEqual(observed.state["fixture_entity_mode"], "absent")
        self.assertFalse(self.runtime.budget_failed)
        self.assertEqual(self.read_count, 2)
        self.assert_no_mutation()
        self.assertEqual(self.runtime._journal["observation_reacquisition"]["additional_reads"], 1)

    def test_actual_chain_bee_returns_known_without_budget_latch(self):
        self.modes = ["unavailable", "known_calm"]
        self.assertEqual(self.acquire().state["fixture_entity_mode"], "known_calm")
        self.assertFalse(self.runtime.budget_failed)
        self.assert_no_mutation()

    def test_actual_chain_persistent_missing_exhausts_then_latches(self):
        self.modes = ["unavailable"]
        with self.assertRaises(ObservationUnavailable):
            self.acquire()
        self.assertTrue(self.runtime.budget_failed)
        self.assertEqual(self.read_count, 3)
        self.assert_no_mutation()
        self.bridge.patch_snapshot = lambda s: s
        with self.assertRaisesRegex(SkillError, "ambient_entity_observation_unavailable"):
            self.runtime.observe()

    def test_actual_chain_native_identity_change_is_not_retried(self):
        original_sleep = self.runtime.sleeper
        def sleep(seconds):
            original_sleep(seconds)
            self.bridge.action["action_session"] = "other-native-session"
        self.runtime.sleeper = sleep
        with self.assertRaises(SkillError):
            self.acquire()
        self.assertTrue(self.runtime.budget_failed)
        self.assertLessEqual(self.read_count, 2)
        self.assertEqual(self.bridge.posts, self.posts_before)

    def test_actual_chain_rejected_frame_does_not_hide_meter_regression(self):
        self.bridge.meter.update(actual_distance=.5, remaining_distance=31.5, position_mutations=1)
        original_sleep = self.runtime.sleeper
        def sleep(seconds):
            original_sleep(seconds)
            self.bridge.meter.update(actual_distance=0., remaining_distance=32., position_mutations=0)
        self.runtime.sleeper = sleep
        with self.assertRaisesRegex(SkillError, "movement_budget_distance_regressed") as caught:
            self.acquire()
        self.assertEqual(caught.exception.status, "unknown")
        self.assertTrue(self.runtime.budget_failed)
        self.assertEqual(self.read_count, 2)
        self.assert_no_mutation()

    def test_actual_chain_semantic_pending_absence_never_gets_reacquisition(self):
        before = self.runtime.observe(entity_radius=48)
        original_count = sum(record["kind"] == "observation" for record in self.runtime._journal["records"].values())
        self.bridge.patch_snapshot = lambda s: endpoint_entities(s, "unavailable")
        outcome = self.runtime.execute("select", {"op": "action", "action": "select_hotbar",
            "hotbar_slot": 1, "entity_radius": 48, "timeout_ms": 1000},
            lambda old, new: new.player["selected_slot"] == 1, before=before)
        self.assertFalse(outcome.ok)
        self.assertTrue(self.runtime.budget_failed)
        self.assertIsNotNone(self.runtime._journal["semantic_pending"])
        observed_count = sum(record["kind"] == "observation" for record in self.runtime._journal["records"].values())
        self.assertEqual(observed_count - original_count, 1)
        self.assertEqual(len(self.bridge.posts) - len(self.posts_before), 1)
        self.assertEqual(self.bridge.posts[-1][1]["action"], "select_hotbar")


if __name__ == "__main__":
    unittest.main()

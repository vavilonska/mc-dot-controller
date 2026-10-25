"""Isolated state handoff tests: no network, game, production or large fixtures."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import session_state as ss


class FakePlanner:
    def __init__(self):
        self.state = {"schema_version": 1, "visited": [[1, 2]],
                      "pending": {"id": "nav.7", "max_moves": 8},
                      "blocked_edges": [[[0, 0], [1, 0]]]}

    def snapshot(self):
        return copy.deepcopy(self.state)

    @classmethod
    def restore(cls, state):
        obj = object.__new__(cls)
        obj.state = copy.deepcopy(state)
        return obj


class FakeController:
    def __init__(self, ledger, observation, directory):
        self.ledger = SimpleNamespace(data=copy.deepcopy(ledger), path=directory / "ledger.json")
        self.ledger.path.write_bytes(ss.encode(ledger))
        self.transport = SimpleNamespace(timeout=.25)
        self.owner_id = "owner-1"
        self.observation = copy.deepcopy(observation)
        self.observes = 0

    def observe(self):
        self.observes += 1
        result = copy.deepcopy(self.observation)
        result["observation_id"] = "fresh-read-" + str(self.observes)
        return result

    def start(self, *args, **kwargs):
        raise AssertionError("restore must not issue an action")

    def finish_one_step(self, *args, **kwargs):
        raise AssertionError("restore must not finish or retry an action")


class FakeSession:
    def __new__(cls, *args, **kwargs):
        raise AssertionError("restore must bypass custom __new__")

    def __init__(self, *args, **kwargs):
        raise AssertionError("restore must not call constructor")

    def now(self):
        value = self.clock()
        if self.last_clock is not None and value < self.last_clock:
            raise ss.StateError("regressing fake clock")
        self.last_clock = value
        return value

    def check_context(self, observation):
        for key, value in self.ctx.items():
            native = "bound_owner_id" if key == "owner_id" else key
            if observation.get(native) != value:
                raise ss.StateError("world or session changed")
        if (observation.get("unknown_lock") is not False
                or observation.get("active_id") is not None
                or observation.get("owner_generation") != len(self.c.ledger.data["actions"]) + 1):
            raise ss.StateError("not actually idle")
        if observation.get("paused") is not False:
            raise ss.StateError("paused")

    def stage_uses(self, stage_id):
        return sum(rec.get("request", {}).get("stage_id") == stage_id
                   for rec in self.c.ledger.data["actions"].values())


class StateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.time = 140.
        self.baseline = {"version": 6, "unknown_lock": False,
                         "actions": {"old-id": {"state": "CLOSED", "request": {"stage_id": "past"}}}}
        # Deliberately noncanonical originals: restore pins exact bytes, not JSON equivalence.
        self.baseline_raw = json.dumps(self.baseline, indent=2).encode() + b"\n"
        self.spec = {"baseline_sha256": hashlib.sha256(self.baseline_raw).hexdigest(),
                     "baseline_count": 1, "owner_id": "owner-1", "player_uuid": "player-1"}
        self.spec_raw = json.dumps(self.spec, indent=1).encode() + b"\n"
        history = copy.deepcopy(self.baseline)
        history["actions"]["used-id"] = {"state": "CLOSED", "request": {"stage_id": "nav.7"}}
        context = {"session": "native-session-1", "world_generation": 9,
                   "player_uuid": "player-1", "owner_id": "owner-1"}
        observation = {"session": context["session"], "world_generation": 9,
                       "player_uuid": "player-1", "bound_owner_id": "owner-1",
                       "unknown_lock": False, "active_id": None, "owner_generation": 3,
                       "paused": False}
        self.controller = FakeController(history, observation, self.root)
        self.history_raw = self.controller.ledger.path.read_bytes()
        self.session = s = object.__new__(FakeSession)
        s.c = self.controller
        s.clock = lambda: self.time
        s.sleep = lambda seconds: None
        s.last_clock = 139.
        s.timeout = .25
        s.stop_requested = lambda: False
        s.on_event = lambda event: None
        s.decision_reader = lambda checkpoint: None
        s.spec = copy.deepcopy(self.spec)
        s.baseline = copy.deepcopy(self.baseline)
        s.serial = "helper-session-same"
        s.ctx = context
        s.reserved = {"old-id", "used-id", "next-id", "last-id", "retired-unused-id"}
        s.batch = {"id": s.serial + ":b3", "start": 100., "deadline": 400.,
                   "ids": ["used-id", "next-id", "last-id"], "cursor": 1, "new_stages": 5}
        s.stage = {"id": "nav.7", "max_moves": 8, "max_looks": 0,
                   "target": {"x": -1.5, "y": 65., "z": 2.5}}
        s.stage_number = 7
        s.last_id = "used-id"
        s.finish_called = True
        s.pending = []
        s.attempted = ["used-id"]
        s.completed = ["nav.1", "nav.2"]
        s.batch_number = 3
        s.consume_state = ("fingerprint", 2, 18)
        s.checkpoint = {"state": "GAMEPLAY_CHECKPOINT", "reason": "choose", "signature": "signature"}
        s.jump_parent = {"id": "jump.5", "max_moves": 3, "used": 3}
        s.alignment_parent = {"id": "jump.6", "max_moves": 2, "used": 1}
        s.decision_token = {"token": "unused-token", "session_id": s.serial,
                            "context": copy.deepcopy(context), "history_count": 2,
                            "decision_serial": 4}
        s.accepted_decisions = {"previous-decision"}
        s.decision_serial = 4
        s.recovery_note = "same session, never world rollback"
        s.batch_expired = False
        s.planner = FakePlanner()
        s.out = self.root / "old-evidence"
        s.out.mkdir()
        s.trace = s.out / "trace.jsonl"
        s.trace.write_bytes(ss.encode({"event": "checkpoint", "session_id": s.serial}) + b"\n")
        self.extra_source = self.root / "dependency.py"
        self.extra_source.write_bytes(b"# fixed dependency\n")
        self.sources = {"dependency": self.extra_source}

    def capture(self, **kwargs):
        options = dict(history_raw=self.history_raw, session_spec_raw=self.spec_raw,
                       baseline_raw=self.baseline_raw, source_paths=self.sources, boot_id="boot-A")
        options.update(kwargs)
        return ss.snapshot_session(self.session, **options)

    def restore(self, snapshot, **kwargs):
        options = dict(controller=self.controller, history_raw=self.history_raw,
                       expected_context=copy.deepcopy(self.session.ctx),
                       outdir=self.root / "restored-evidence", planner_restore=FakePlanner.restore,
                       monotonic=lambda: self.time, sleep=lambda seconds: None,
                       source_paths=self.sources, boot_id="boot-A")
        options.update(kwargs)
        return ss.restore_session(FakeSession, snapshot, **options)

    def rehash(self, snapshot):
        snapshot["sha256"] = hashlib.sha256(ss.encode({k: v for k, v in snapshot.items() if k != "sha256"})).hexdigest()
        return snapshot

    def test_same_boot_round_trip_preserves_all_state_and_no_constructor(self):
        before = self.session.trace.read_bytes()
        snap = self.capture()
        encoded = ss.encode(snap)
        self.assertEqual(json.loads(encoded), snap)
        self.time = 190.
        events = []
        restored = self.restore(snap, on_event=events.append)
        for key in ss.STATE_KEYS - {"last_clock"}:
            self.assertEqual(getattr(restored, key), getattr(self.session, key), key)
        self.assertEqual(restored.planner.snapshot(), self.session.planner.snapshot())
        self.assertEqual(restored.last_clock, 190.)
        self.assertEqual(restored.batch["deadline"], 400.)
        self.assertEqual(restored.stage_uses("nav.7"), 1)
        self.assertEqual(restored.pending, [])
        self.assertEqual(self.controller.observes, 1)
        self.assertEqual(self.session.trace.read_bytes(), before)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event"], "session_restored")
        self.assertEqual(events[0]["session_id"], self.session.serial)
        self.assertEqual(events[0]["observation"]["observation_id"], "fresh-read-1")
        self.assertEqual(self.controller.ledger.path.read_bytes(), self.history_raw)
        self.assertNotIn("pending", snap["state"])
        self.assertNotIn("plan", snap["state"])

    def test_snapshot_is_independent_of_later_in_memory_changes(self):
        snap = self.capture()
        self.session.stage["max_moves"] = 1
        self.session.reserved.add("later")
        self.session.planner.state["visited"].append([3, 4])
        self.assertEqual(snap["state"]["stage"]["max_moves"], 8)
        self.assertNotIn("later", snap["state"]["reserved"])
        self.assertEqual(snap["planner"]["visited"], [[1, 2]])

    def test_cross_boot_marks_expired_without_changing_batch_or_stage(self):
        snap = self.capture()
        self.time = 2.
        restored = self.restore(snap, boot_id="boot-B")
        self.assertTrue(restored.batch_expired)
        self.assertEqual(restored.batch, snap["state"]["batch"])
        self.assertEqual(restored.stage, snap["state"]["stage"])
        self.assertEqual(restored.stage_number, 7)
        self.assertEqual(restored.reserved, self.session.reserved)
        self.assertEqual(restored.last_clock, 2.)

    def test_unknown_boot_never_claims_same_clock_domain(self):
        with patch.object(ss, "current_boot_id", return_value=None):
            snap = self.capture(boot_id=None)
            self.time = 1.
            restored = self.restore(snap, boot_id=None)
        self.assertTrue(restored.batch_expired)

    def test_elapsed_same_boot_is_expired_not_extended(self):
        snap = self.capture()
        self.time = 401.
        restored = self.restore(snap)
        self.assertTrue(restored.batch_expired)
        self.assertEqual(restored.batch["deadline"], 400.)

    def test_same_boot_regression_rejected_before_observe_or_evidence(self):
        snap = self.capture()
        self.time = 1.
        with self.assertRaisesRegex(ss.StateError, "regressing"):
            self.restore(snap)
        self.assertEqual(self.controller.observes, 0)
        self.assertFalse((self.root / "restored-evidence").exists())

    def test_nonidle_history_refuses_snapshot(self):
        for change in (lambda d: d.update(unknown_lock=True),
                       lambda d: d["actions"]["used-id"].update(state="PENDING"),
                       lambda d: d["actions"]["used-id"].update(state="UNKNOWN")):
            with self.subTest(change=change):
                original = copy.deepcopy(self.controller.ledger.data)
                change(self.controller.ledger.data)
                with self.assertRaises(ss.StateError):
                    self.capture()
                self.controller.ledger.data = original

    def test_pending_runtime_trace_not_serialized(self):
        self.session.pending = [("pre_start", {"request": {"id": "next-id"}})]
        with self.assertRaisesRegex(ss.StateError, "no_pending_serialization"):
            self.capture()

    def test_restore_requires_exact_current_history_bytes_not_equivalence(self):
        snap = self.capture()
        changed = json.dumps(self.controller.ledger.data, indent=2).encode()
        self.controller.ledger.path.write_bytes(changed)
        with self.assertRaisesRegex(ss.StateError, "same_current_history_bytes"):
            self.restore(snap, history_raw=changed)

    def test_supplied_history_must_match_persisted_disk_bytes(self):
        self.controller.ledger.path.write_bytes(self.history_raw + b"\n")
        with self.assertRaisesRegex(ss.StateError, "persisted_history"):
            self.capture()

    def test_restore_rejects_history_growth_and_unknown_even_with_fresh_raw(self):
        snap = self.capture()
        self.controller.ledger.data["actions"]["external-id"] = {"state": "CLOSED"}
        changed = ss.encode(self.controller.ledger.data)
        self.controller.ledger.path.write_bytes(changed)
        with self.assertRaises(ss.StateError):
            self.restore(snap, history_raw=changed)
        self.controller.ledger.data["unknown_lock"] = True
        with self.assertRaises(ss.StateError):
            self.restore(snap, history_raw=changed)

    def test_baseline_records_must_remain_exact(self):
        self.controller.ledger.data["actions"]["old-id"]["new-field"] = "changed"
        self.history_raw = ss.encode(self.controller.ledger.data)
        self.controller.ledger.path.write_bytes(self.history_raw)
        with self.assertRaisesRegex(ss.StateError, "baseline_records"):
            self.capture()

    def test_current_context_confirmation_cannot_adopt_rollback_world(self):
        snap = self.capture()
        changed = dict(self.session.ctx, world_generation=10)
        with self.assertRaisesRegex(ss.StateError, "no_world_rollback"):
            self.restore(snap, expected_context=changed)
        self.assertEqual(self.controller.observes, 0)

    def test_fresh_observation_not_stale_supplied_observation_is_authority(self):
        snap = self.capture()
        stale = copy.deepcopy(self.controller.observation)
        self.controller.observation["world_generation"] = 10
        with self.assertRaises(ss.StateError):
            self.restore(snap, initial_observation=stale)
        self.assertEqual(self.controller.observes, 1)
        self.assertFalse((self.root / "restored-evidence").exists())

    def test_fresh_paused_observation_refuses_no_automatic_resume(self):
        snap = self.capture()
        self.controller.observation["paused"] = True
        with self.assertRaisesRegex(ss.StateError, "paused"):
            self.restore(snap)

    def test_evidence_must_be_unchanged_and_new_outdir_required(self):
        snap = self.capture()
        with self.assertRaisesRegex(ss.StateError, "new_restore_evidence"):
            self.restore(snap, outdir=self.session.out)
        self.session.trace.write_bytes(self.session.trace.read_bytes() + b"{}\n")
        with self.assertRaisesRegex(ss.StateError, "evidence_bytes_changed"):
            self.restore(snap)

    def test_explicit_exact_trace_relocation_supported(self):
        snap = self.capture()
        relocated = self.root / "copied-trace.jsonl"
        relocated.write_bytes(self.session.trace.read_bytes())
        self.session.trace.unlink()
        restored = self.restore(snap, evidence_trace_path=relocated)
        self.assertEqual(restored.serial, self.session.serial)

    def test_actual_source_manifest_is_verified(self):
        snap = self.capture()
        self.extra_source.write_bytes(b"# changed dependency\n")
        with self.assertRaisesRegex(ss.StateError, "source_or_evidence_bytes_changed"):
            self.restore(snap)

    def test_source_set_cannot_be_reduced(self):
        snap = self.capture()
        with self.assertRaisesRegex(ss.StateError, "source_set"):
            self.restore(snap, source_paths={})

    def test_closed_schema_and_hash_tampering_rejected(self):
        snap = self.capture()
        for mutate in (lambda d: d.update(extra=True),
                       lambda d: d["state"].update(pending=[]),
                       lambda d: d["state"]["batch"].update(extra=1)):
            bad = copy.deepcopy(snap)
            mutate(bad)
            self.rehash(bad)
            with self.assertRaises(ss.StateError):
                self.restore(bad)
        bad = copy.deepcopy(snap)
        bad["state"]["stage_number"] = 999
        with self.assertRaisesRegex(ss.StateError, "content_hash"):
            self.restore(bad)

    def test_batch_rewinding_would_reissue_attempted_id_and_is_rejected(self):
        snap = self.capture()
        snap["state"]["batch"]["cursor"] = 0
        self.rehash(snap)
        with self.assertRaises(ss.StateError):
            self.restore(snap)

    def test_all_reserved_ids_including_retired_unused_survive(self):
        restored = self.restore(self.capture())
        self.assertIn("retired-unused-id", restored.reserved)
        self.assertEqual(restored.attempted, ["used-id"])
        self.assertEqual(restored.batch["cursor"], 1)
        self.assertEqual(restored.batch["new_stages"], 5)

    def test_trace_first_acceptance_cannot_leave_replayable_token(self):
        event = {"event": "decision_accepted", "command": {
            "decision_id": "decision-now", "token": "unused-token"}}
        self.session.trace.write_bytes(ss.encode(event) + b"\n")
        with self.assertRaisesRegex(ss.StateError, "accepted_decision"):
            self.capture()

    def test_mid_apply_decision_transition_refuses_even_token_cleared(self):
        self.session.accepted_decisions.add("decision-now")
        self.session.decision_token = None
        event = {"event": "decision_accepted", "command": {
            "decision_id": "decision-now", "token": "used-token"}}
        self.session.trace.write_bytes(ss.encode(event) + b"\n")
        with self.assertRaisesRegex(ss.StateError, "not_fully_applied"):
            self.capture()
        with self.session.trace.open("ab") as stream:
            stream.write(ss.encode({"event": "decision_applied", "decision_id": "decision-now"}) + b"\n")
        restored = self.restore(self.capture())
        self.assertIn("decision-now", restored.accepted_decisions)
        self.assertIsNone(restored.decision_token)

    def test_atomic_save_fsync_load_pin_and_no_temp_leftovers(self):
        snap = self.capture()
        path = self.root / "state.json"
        calls = []
        original = os.fsync
        with patch.object(ss.os, "fsync", side_effect=lambda fd: (calls.append(fd), original(fd))[1]):
            pin = ss.save_snapshot(path, snap)
        self.assertGreaterEqual(len(calls), 2)
        self.assertEqual(pin["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(ss.load_snapshot(path, expected_sha256=pin["sha256"]), snap)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(list(self.root.glob(".session-state-*")), [])
        with self.assertRaisesRegex(ss.StateError, "pinned_state_file"):
            ss.load_snapshot(path, expected_sha256="0" * 64)

    def test_failed_atomic_replace_preserves_existing_state_and_cleans_temp(self):
        snap = self.capture()
        path = self.root / "state.json"
        path.write_bytes(b"old-state")
        with patch.object(ss.os, "replace", side_effect=OSError("simulated replace failure")):
            with self.assertRaises(OSError):
                ss.save_snapshot(path, snap)
        self.assertEqual(path.read_bytes(), b"old-state")
        self.assertEqual(list(self.root.glob(".session-state-*")), [])

    def test_symlink_evidence_state_and_sources_refused(self):
        snap = self.capture()
        target = self.root / "target"
        target.write_bytes(b"do not overwrite")
        symlink = self.root / "state-link.json"
        symlink.symlink_to(target)
        with self.assertRaisesRegex(ss.StateError, "symlink"):
            ss.save_snapshot(symlink, snap)
        self.assertEqual(target.read_bytes(), b"do not overwrite")

    def test_duplicate_json_keys_and_nonfinite_rejected(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}'):
            with self.assertRaises(ss.StateError):
                ss._parse(raw)

    def test_no_snapshot_runtime_callable_or_set_leaks(self):
        snap = self.capture()
        ss._json_value(snap)
        with self.assertRaises(ss.StateError):
            ss.encode({"bad": lambda: None})


if __name__ == "__main__":
    unittest.main()

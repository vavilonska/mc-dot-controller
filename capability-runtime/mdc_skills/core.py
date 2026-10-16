"""Single-writer, durable, fail-closed capability execution over the real gateway.

There is deliberately no queue discovery, game startup, connection management,
credential handling or action retry in this module. The existing IntentClient may
maintain a bounded local ownership heartbeat; it never sends game actions.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import fcntl
import hashlib
import gzip
import json
import math
import os
import re
from pathlib import Path
import threading
import time
import uuid
import zlib

_DEFAULT_ACQUISITION = object()


class SkillError(RuntimeError):
    def __init__(self, reason, *, status="blocked", request_id=None):
        super().__init__(reason)
        self.reason, self.status, self.request_id = reason, status, request_id


class ObservationUnavailable(SkillError):
    """Rejected read evidence, never an Observation or mutation authority.

    Only an explicitly enrolled observe can attach the private retry token.
    Raising this exception alone cannot authorize another read or suppress a
    movement-budget failure.
    """
    def __init__(self, reason, *, evidence, request_id=None):
        super().__init__(reason, status="blocked", request_id=request_id)
        self.evidence = deepcopy(evidence)
        self._reacquisition_token = None


def require(condition, reason):
    if not condition:
        raise SkillError(reason)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _digest(value):
    return hashlib.sha256(_json(value)).hexdigest()


def atomic_write(path, value):
    """Write a bounded JSON checkpoint, flush bytes and directory before return."""
    _atomic_bytes(path, _json(value))


def _atomic_bytes(path, data, limit=8 * 1024 * 1024):
    path = Path(path)
    require(len(data) <= limit, "checkpoint_capacity_exhausted")
    require(not path.is_symlink(), "checkpoint_symlink_rejected")
    tmp = path.with_name("." + path.name + "." + uuid.uuid4().hex)
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        tmp.unlink(missing_ok=True)


@dataclass(frozen=True)
class Observation:
    state: dict
    terrain: dict | None
    raw: dict
    tick: int
    context: tuple
    captured_at: float
    request_id: str
    _owner: str = field(default="", repr=False)
    _fingerprint: str = field(default="", repr=False)
    _gateway_epoch: int | None = field(default=None, repr=False)
    _options: dict = field(default_factory=dict, repr=False)
    observation_clock: dict | None = None

    @property
    def player(self):
        return self.state["player"]


@dataclass(frozen=True)
class Survey:
    """Historical region proposal input. It confers no mutation/success authority.

    Every original page timestamp remains in terrain.source_pages. A region
    sweep is sequential evidence, never a simultaneous state or fresh preflight.
    """
    state: dict
    terrain: dict
    raw: dict
    tick: int
    context: tuple
    captured_at: float
    request_id: str
    acquisition_seconds: float
    _owner: str = field(default="", repr=False)
    _fingerprint: str = field(default="", repr=False)

    @property
    def player(self):
        return self.state["player"]


@dataclass(frozen=True)
class Outcome:
    status: str
    reason: str
    request_ids: tuple = ()
    evidence: dict = field(default_factory=dict)
    last_observation: Observation | None = None

    @property
    def ok(self):
        return self.status == "succeeded"


class Runtime:
    """Explicit one-owner lifetime. Only guarded native actions are dispatched.

    Construct using the already-authorized caller's IntentClient (or the sole
    QueueClient when no watchdog owns it). Existing controller ownership remains
    authoritative; this adds an exclusive capability journal, not a second writer.
    """
    ACTIONS = frozenset({"follow_path", "break_block", "place_block", "click_slot",
        "combat_entity", "recover_environment", "boat_drive", "boat_mount", "boat_dismount",
        "interact_block", "use_item", "select_hotbar", "close_menu", "attack_entity", "shoot_entity", "gateway_pearl",
        "movement_budget_start", "movement_budget_finish"})
    TERMINAL = frozenset({"succeeded", "failed", "cancelled"})
    TRANSITIONS = frozenset({"world_changed", "world_or_player_changed", "world_transition",
                             "capability_world_changed", "capability_dimension_changed"})

    def __init__(self, client, journal_directory, *, clock=time.monotonic,
                 sleeper=time.sleep, max_age=0.8, wait_timeout=30, capability_duration_seconds=7200,
                 required_execution_policy=None, observation_clock=None):
        require(observation_clock is None or type(observation_clock) is str and observation_clock == 'client-pre-tick-v1',
                'invalid_observation_clock_selection')
        require(observation_clock is None or type(self) is Runtime or
                type(self).__dict__.get('READONLY_OBSERVATION_ONLY') is True, 'read_only_clock_subclass_forbidden')
        self.observation_clock_contract=observation_clock
        self._last_observation_clock=None
        self._observation_clock_failed=False
        require(type(max_age) in (int, float) and math.isfinite(max_age)
                and 0 < max_age <= .8, "invalid_freshness_budget")
        require(type(wait_timeout) in (int, float) and math.isfinite(wait_timeout)
                and 0 < wait_timeout <= 660, "invalid_wait_budget")
        require(type(capability_duration_seconds) in (int, float) and math.isfinite(capability_duration_seconds)
                and 1 <= capability_duration_seconds <= 86400, "invalid_capability_ownership_duration")
        require(required_execution_policy in (None, "standard", "noncombat", "request_only"), "invalid_required_execution_policy")
        self.required_execution_policy = required_execution_policy
        self._lease_duration_ms = int(capability_duration_seconds * 1000)
        self._lease_enabled = callable(getattr(client, "acquire_capability", None))
        self._lease_attempted, self._lease_active = False, False
        self._lease_info = None
        self.close_outcome = None
        self._job_control = None
        self._job_generation = 0
        self._job_request_ids = []
        self._job_effect_certainty = "none_proven"
        self._job_scoped_profiles = {}
        self.client, self.clock, self.sleeper = client, clock, sleeper
        self.max_age, self.wait_timeout = max_age, wait_timeout
        self.journal_directory = Path(journal_directory)
        self.journal_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        require(not self.journal_directory.is_symlink(), "journal_symlink_rejected")
        self._mutex = threading.RLock()
        self._lock_fd = os.open(self.journal_directory / ".capability-owner.lock",
                                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(self._lock_fd)
            self._lock_fd = None
            raise SkillError("capability_owner_already_running") from None
        self._path = self.journal_directory / "execution.json"
        self._owner = uuid.uuid4().hex
        self._session_id = None
        self._context = None
        self._last_tick = None
        self._last = None
        self._preflight_request_id = None
        self._completed = set()
        self._observation_reacquisition = None
        try:
            if self._path.exists():
                require(not self._path.is_symlink(), "checkpoint_symlink_rejected")
                with self._path.open("rb") as stream:
                    raw = stream.read(8 * 1024 * 1024 + 1)
                require(len(raw) <= 8 * 1024 * 1024, "checkpoint_capacity_exhausted")
                self._journal = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                require(self._journal.get("schema_version") == 1
                        and isinstance(self._journal.get("records"), dict), "invalid_execution_checkpoint")
                self.audit_evidence()
                # Never restore in-memory clock or authorization from a checkpoint.
                if self._journal.get("pending"):
                    record = self._journal["records"][self._journal["pending"]]
                    record["status"] = "unknown"
                    record["reason"] = "restart_requires_exact_id_reconciliation"
                    self._save()
            else:
                self._journal = {"schema_version": 1, "pending": None, "semantic_pending": None, "records": {}}
                self._save()
        except BaseException:
            self.close()
            raise

    def begin_job(self, control, *, scoped_profiles=None):
        """Bind the sole runtime to one admitted job; no replacement owner stack."""
        with self._mutex:
            self._open()
            require(self._job_control is None and not self.has_unresolved_execution,
                    "runtime_job_or_unknown_owner_present")
            require(not self._lease_active, "previous_job_lease_not_released")
            self._job_control = control
            self._job_generation += 1
            self._job_request_ids = []
            self._job_effect_certainty = "none_proven"
            self._job_scoped_profiles = dict(scoped_profiles or {})
            self._owner = uuid.uuid4().hex
            self._lease_attempted = False
            self._preflight_request_id = None
            control.owner_check = self.check_job_owner
            try:
                control.emit("owner_context", self.owner_context())
            except Exception:
                self._job_control = None
                self._job_scoped_profiles = {}
                raise

    def owner_context(self):
        return {"owner_id": self._owner, "owner_generation": self._job_generation,
                "gateway_session": self._session_id,
                "world_context": list(self._context) if self._context else None,
                "original_request_ids": list(self._job_request_ids)}

    def check_job_owner(self):
        if self._lease_active:
            self._session(idle=False)
        for key in ("pending", "semantic_pending"):
            rid = self._journal.get(key)
            require(rid is None or self._journal["records"][rid].get("status") in
                    ("reserved", "submitted", "terminal_unverified", "verifying"), "job_owner_unknown")

    def finish_job(self):
        """Neutral read and exact per-job lease release; failed release stays blocked."""
        with self._mutex:
            control = self._job_control
            require(control is not None, "no_active_runtime_job")
            if self.has_unresolved_execution:
                self._stop_job_heartbeat()
                return Outcome("unknown", "job_execution_requires_reconciliation")
            try:
                with control.cleanup():
                    had_lease = self._lease_active
                    if self._lease_active:
                        self.observe(allow_menu=True)
                        session = self._session()
                        record = self._reserve("capability_release", {"op": "capability_release",
                            "owner_id": self._owner, "expected_defense_epoch": session["defense_epoch"]})
                        self._ownership_exchange(record)
                        self._lease_active = False
                    result = Outcome("succeeded", "job_owner_release_confirmed", tuple(self._job_request_ids),
                                     {"owner_context": self.owner_context(), "input_release_confirmed": True if had_lease else None,
                                      "cleanup_certainty": "confirmed" if had_lease else "not_needed"})
                    self._job_control = None
                    self._job_scoped_profiles = {}
                    return result
            except Exception as exc:
                self._stop_job_heartbeat()
                return Outcome("unknown", "job_owner_release_unconfirmed:" +
                               (exc.reason if isinstance(exc, SkillError) else type(exc).__name__),
                               tuple(self._job_request_ids), {"owner_context": self.owner_context()})

    def _stop_job_heartbeat(self):
        """Freeze uncertain ownership; stopping renewal never asserts input release."""
        stop = getattr(self.client, "stop_capability_heartbeat", None)
        if callable(stop):
            try:
                stop(self._owner)
            except Exception:
                pass  # Unknown remains latched; no alternative owner operation or retry.

    def _control_checkpoint(self):
        if self._job_control is not None:
            self._job_control.checkpoint()

    def _cancel_running_once(self, record):
        """In-band exact original owner cancellation, persisted before the write."""
        control = self._job_control
        if control is None or record["kind"] != "mutation" or record.get("cancel_control"):
            return
        require(self._lease_active and self._lease_info is not None, "exact_cancel_owner_unavailable")
        session = self._session(idle=False)
        require(session.get("capability_cancel_schema_version") == 1, "exact_cancel_not_supported")
        cancel_id = control.cancel_request_id or uuid.uuid4().hex
        command = {"op": "capability_cancel", "owner_id": self._owner,
                   "expected_defense_epoch": self._lease_info["defense_epoch"],
                   "expected_intent_id": record["request_id"],
                   "expected_action_session": record["before_context"][3]}
        with control.cleanup():
            control.consume("actions")
        record["cancel_control"] = {"request_id": cancel_id, "command": command, "state": "reserved"}
        self._save()
        control.emit("cancel_dispatched", {"request_id": cancel_id, "original_request_id": record["request_id"],
                                          "owner_context": self.owner_context()})
        try:
            if self.client.submit(command, request_id=cancel_id) != cancel_id:
                raise ValueError("cancel_identity_changed")
            record["cancel_control"]["state"] = "submitted"
            self._save()
        except Exception as exc:
            record["cancel_control"]["state"] = "unknown"
            self._unknown(record, "exact_cancel_submission_unknown:" + type(exc).__name__)

    def close(self):
        with self._mutex:
            if self._lock_fd is not None:
                try:
                    if self._lease_active and hasattr(self, "_journal"):
                        if self.has_unresolved_execution:
                            self.close_outcome = Outcome("unknown", "ownership_retained_for_unresolved_execution")
                        else:
                            # A fresh neutral observation is mandatory even when
                            # the last successful skill completed long ago.
                            self.observe(allow_menu=True)
                            session = self._session()
                            record = self._reserve("capability_release", {"op": "capability_release",
                                "owner_id": self._owner, "expected_defense_epoch": session["defense_epoch"]})
                            self._ownership_exchange(record)
                            self._lease_active = False
                            self.close_outcome = Outcome("succeeded", "capability_ownership_released", (record["request_id"],))
                except Exception as exc:
                    self.close_outcome = Outcome("unknown" if self.pending_request_id else "blocked",
                        "ownership_close_unconfirmed:" + (exc.reason if isinstance(exc, SkillError) else type(exc).__name__))
                finally:
                    try:
                        if self._lease_enabled:
                            self.client.close_capability()  # heartbeat only; never release unknown ownership
                    finally:
                        fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
                        os.close(self._lock_fd)
                        self._lock_fd = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _save(self):
        atomic_write(self._path, self._journal)

    def _open(self):
        require(self._lock_fd is not None, "runtime_closed")

    @property
    def pending_request_id(self):
        return self._journal.get("pending")

    @property
    def has_unresolved_execution(self):
        return self.pending_request_id is not None or self._journal.get("semantic_pending") is not None

    def _session(self, *, idle=True):
        self._open()
        try:
            data = self.client.session()
        except Exception as exc:
            self._preflight_request_id = None
            raise SkillError("gateway_session_unavailable:" + type(exc).__name__) from None
        require(isinstance(data, dict) and isinstance(data.get("session_id"), str)
                and data["session_id"], "gateway_session_missing")
        if self.required_execution_policy is not None:
            require(type(data.get("execution_policy_schema_version")) is int
                    and data["execution_policy_schema_version"] == 1
                    and data.get("execution_policy") == self.required_execution_policy,
                    "required_execution_policy_not_active")
        require(type(data.get("pending")) is int and data["pending"] >= 0,
                "published_pending_count_required")
        if self._session_id is None:
            self._session_id = data["session_id"]
        require(data["session_id"] == self._session_id, "gateway_session_changed")
        policy = data.get("resident_policy")
        if policy is not None:
            require(isinstance(policy, dict) and policy.get("requires_handoff") is False
                    and policy.get("input_release_unconfirmed") is False, "resident_handoff_required")
        require(data.get("state") in ("ready", "busy"), "gateway_not_ready")
        if idle:
            own_finished = data.get("state") == "busy" and data.get("active_request_id") in self._completed
            require((data.get("state") == "ready" or own_finished) and data["pending"] == 0,
                    "gateway_not_idle")
        if self._lease_enabled:
            if not self._lease_active:
                require(not self._lease_attempted, "capability_ownership_not_reacquired")
                require(not self.has_unresolved_execution, "unresolved_execution_blocks_ownership_acquisition")
                context = data.get("capability_context")
                require(data.get("capability_lease_schema_version") == 1 and isinstance(context, dict)
                        and all(isinstance(context.get(k), str) and context[k] for k in
                                ("world_generation", "dimension", "player_uuid", "action_session"))
                        and type(data.get("defense_epoch")) is int,
                        "capability_ownership_context_not_ready")
                record = self._reserve("capability_acquire", {"op": "capability_acquire", "owner_id": self._owner,
                    "expected_context": deepcopy(context), "expected_defense_epoch": data["defense_epoch"],
                    "duration_ms": self._lease_duration_ms})
                self._lease_attempted = True
                receipt = self._ownership_exchange(record)
                self._lease_info = deepcopy(receipt["capability_lease"])
                self._lease_active = True
                data = {**data, "capability_lease": self._lease_info}
            lease = data.get("capability_lease")
            require(isinstance(lease, dict) and lease.get("owner_id") == self._owner
                    and lease.get("state") == "active" and lease.get("defense_epoch") == data.get("defense_epoch")
                    and lease.get("defense_epoch") == self._lease_info.get("defense_epoch")
                    and lease.get("resident_session") == self._lease_info.get("resident_session")
                    and all(type(lease.get(k)) in (int, float) and lease[k] > 0 for k in
                            ("remaining_ms", "heartbeat_remaining_ms")), "capability_ownership_lost")
        return data

    def _ownership_exchange(self, record):
        """One durable control identity, never replayed or inferred from absence."""
        command, rid = record["command"], record["request_id"]
        try:
            if record["kind"] == "capability_acquire":
                receipt = self.client.acquire_capability(self._owner, command["duration_ms"],
                    min(3, self.wait_timeout), request_id=rid, expected_context=deepcopy(command["expected_context"]),
                    expected_defense_epoch=command["expected_defense_epoch"])
            else:
                receipt = self.client.release_capability(self._owner, min(3, self.wait_timeout), request_id=rid)
        except Exception as exc:
            self._unknown(record, "ownership_control_unknown:" + type(exc).__name__)
        if (not isinstance(receipt, dict) or receipt.get("request_id") != rid
                or receipt.get("session_id") != record["gateway_session"]
                or receipt.get("queue_request_id") is not None or receipt.get("status") != "succeeded"
                or self._unsafe_flags(receipt) or self._unsafe_flags(receipt.get("result"))):
            self._unknown(record, "ownership_control_receipt_unconfirmed")
        lease = receipt.get("capability_lease")
        if record["kind"] == "capability_acquire":
            if (not isinstance(lease, dict) or lease.get("owner_id") != self._owner
                    or lease.get("state") != "active" or lease.get("context") != command["expected_context"]
                    or lease.get("defense_epoch") != command["expected_defense_epoch"]):
                self._unknown(record, "ownership_control_identity_unconfirmed")
        elif lease is not None:
            self._unknown(record, "ownership_release_unconfirmed")
        self._receipt(record, receipt)
        self._finish(record, "succeeded", "local_ownership_control_confirmed")
        self._completed.add(rid)
        return receipt

    def _owned_command(self, command, session):
        if self._lease_active:
            require("_capability_owner_id" not in command or command["_capability_owner_id"] == self._owner,
                    "conflicting_capability_owner")
            command["_capability_owner_id"] = self._owner
            command["_navigation_defense_epoch"] = session["defense_epoch"]
        return command

    def _read_evidence(self, ref, kind):
        require(isinstance(ref, dict), "invalid_evidence_reference")
        filename = ref.get("file")
        pattern = (r"receipt-[0-9a-f]{32}-[0-9a-f]{64}\.json\.gz" if kind == "receipt"
                   else r"execution-segment-[0-9a-f]{64}\.json\.gz")
        require(isinstance(filename, str) and re.fullmatch(pattern, filename), "evidence_path_rejected")
        require(isinstance(ref.get("sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", ref["sha256"])
                and filename.endswith("-" + ref["sha256"] + ".json.gz"), "evidence_filename_digest_mismatch")
        path = self.journal_directory / filename
        limit = (32 if kind == "receipt" else 8) * 1024 * 1024
        require(type(ref.get("bytes")) is int and 0 <= ref["bytes"] <= limit,
                "evidence_capacity_invalid")
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, "rb") as stream:
                packed = stream.read(limit + 1)
            require(len(packed) <= limit and hashlib.sha256(packed).hexdigest() == ref.get("compressed_sha256"),
                    "compressed_evidence_hash_mismatch")
            decoder = zlib.decompressobj(31)
            raw = decoder.decompress(packed, limit + 1)
            require(decoder.eof and not decoder.unconsumed_tail and not decoder.unused_data
                    and len(raw) == ref["bytes"] and hashlib.sha256(raw).hexdigest() == ref.get("sha256"),
                    "evidence_hash_or_size_mismatch")
            return json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except SkillError:
            raise
        except (OSError, ValueError, zlib.error):
            raise SkillError("evidence_missing_or_invalid") from None

    def audit_evidence(self):
        """Read and verify all durable execution evidence, without dispatch."""
        with self._mutex:
            self._open()
            segments = self._journal.get("segments", [])
            require(isinstance(segments, list) and len(segments) <= 4096, "invalid_execution_segments")
            seen, receipts, previous = set(), 0, None
            groups = []
            for ref in segments:
                require(ref.get("previous_sha256") == previous, "execution_archive_chain_mismatch")
                body = self._read_evidence(ref, "segment")
                require(isinstance(body, dict) and body.get("schema_version") == 1
                        and isinstance(body.get("records"), dict) and len(body["records"]) == ref.get("records"),
                        "invalid_execution_segment_schema")
                groups.append(body["records"])
                previous = ref["sha256"]
            groups.append(self._journal["records"])
            for group_index, group in enumerate(groups):
                for rid, record in group.items():
                    require(isinstance(rid, str) and re.fullmatch(r"[0-9a-f]{32}", rid)
                            and rid not in seen and isinstance(record, dict) and record.get("request_id") == rid
                            and isinstance(record.get("command"), dict)
                            and _digest(record["command"]) == record.get("command_sha256"),
                            "invalid_execution_record_identity")
                    seen.add(rid)
                    if group_index < len(groups)-1:
                        require(record.get("status") in ("succeeded", "failed", "blocked", "reconciled"),
                                "nonterminal_execution_archived")
                    if "receipt_ref" in record:
                        require(record["receipt_ref"].get("file", "").startswith("receipt-" + rid + "-"),
                                "receipt_reference_identity_mismatch")
                        body = self._read_evidence(record["receipt_ref"], "receipt")
                        require(isinstance(body, dict) and body.get("request_id") == rid
                                and body.get("session_id") == record.get("gateway_session")
                                and (body.get("status") in self.TERMINAL or
                                     body.get("status") == "uncertain" and record.get("status") == "unknown"
                                     and self._journal.get("pending") == rid and record.get("kind") == "observation"
                                     and record["command"].get("terrain_acquisition") in {"native-full729-v1","native-full729-client-clock-v1"}),
                                "invalid_evidence_receipt_identity")
                        receipts += 1
            for key in ("pending", "semantic_pending"):
                rid = self._journal.get(key)
                require(rid is None or rid in self._journal["records"], "active_execution_archived_or_missing")
            return {"segments": len(segments), "records": len(seen), "receipts": receipts,
                    "level": "durable_exact_evidence_verified", "gameplay_dispatched": False}

    def _receipt(self, record, result):
        """Durably retain full exact evidence without growing the hot journal."""
        raw = _json(result)
        require(len(raw) <= 32 * 1024 * 1024, "receipt_evidence_capacity_exhausted")
        digest = hashlib.sha256(raw).hexdigest()
        name = "receipt-" + record["request_id"] + "-" + digest + ".json.gz"
        path = self.journal_directory / name
        packed = gzip.compress(raw, mtime=0)
        _atomic_bytes(path, packed, 32 * 1024 * 1024)
        record["receipt_ref"] = {"file": name, "sha256": digest, "bytes": len(raw),
                                 "compressed_sha256": hashlib.sha256(packed).hexdigest()}
        # Small correlation summary is informational; only the returned exact
        # result and native semantic checks can complete a mutation.
        record["receipt"] = {k: deepcopy(result[k]) for k in
            ("request_id", "session_id", "queue_request_id", "queue_session_id", "status", "reason") if k in result}

    def _compact(self):
        records = self._journal["records"]
        if len(records) < 128:
            return
        protected = {self._journal.get("pending"), self._journal.get("semantic_pending")}
        terminal = {"succeeded", "failed", "blocked", "reconciled"}
        selected = {k: v for k, v in list(records.items())[:-32]
                    if k not in protected and v.get("status") in terminal}
        if not selected:
            return
        chunks = self._journal.setdefault("segments", [])
        require(len(chunks) < 4096, "execution_archive_capacity_exhausted")
        body = {"schema_version": 1, "records": selected}
        raw = _json(body)
        digest = hashlib.sha256(raw).hexdigest()
        name = "execution-segment-" + digest + ".json.gz"
        packed = gzip.compress(raw, mtime=0)
        _atomic_bytes(self.journal_directory / name, packed)
        # The immutable segment reaches disk before the manifest replaces hot
        # records. A crash between writes leaves harmless duplicated evidence.
        chunks.append({"file": name, "sha256": digest, "compressed_sha256": hashlib.sha256(packed).hexdigest(),
                       "previous_sha256": chunks[-1]["sha256"] if chunks else None,
                       "records": len(selected), "bytes": len(raw)})
        self._journal["records"] = {k: v for k, v in records.items() if k not in selected}
        self._save()
        self._completed.difference_update(selected)

    def _reserve(self, kind, command, *, skill=None, before=None):
        require(self._journal["pending"] is None, "unknown_or_pending_request_blocks_new_work")
        enrollment = self._observation_reacquisition
        if enrollment is not None:
            require(kind == "observation" and enrollment.active_request_id is None,
                    "observation_reacquisition_read_only")
        if self._job_control is not None and kind in ("mutation", "observation", "survey"):
            self._job_control.consume("actions" if kind == "mutation" else "observations")
        self._compact()
        require(len(self._journal["records"]) < 4096, "execution_identity_capacity_exhausted")
        rid = uuid.uuid4().hex
        record = {"request_id": rid, "kind": kind, "skill": skill,
                  "command": deepcopy(command), "command_sha256": _digest(command),
                  "gateway_session": self._session_id, "status": "reserved",
                  "before_context": list(before.context) if before else None,
                  "before_tick": before.tick if before else None}
        if self._job_control is not None and kind == "mutation":
            record["prior_job_effect_certainty"] = self._job_effect_certainty
        self._journal["records"][rid] = record
        if enrollment is not None:
            enrollment.active_request_id = rid
            record["observation_reacquisition"] = {
                "schema_version": 1, "group_id": enrollment.group_id,
                "attempt": enrollment.attempt, "max_reads": enrollment.max_reads}
        self._journal["pending"] = rid
        self._save()  # Durable intent precedes any queue submission.
        if self._job_control is not None:
            self._job_request_ids.append(rid)
            record["job_id"] = self._job_control.job_id
            record["owner_context"] = self.owner_context()
            self._save()
            try:
                self._job_control.emit("owner_context", self.owner_context())
            except Exception:
                self._finish(record, "blocked", "job_identity_persistence_failed_before_dispatch")
                raise
        return record

    def _unknown(self, record, reason):
        record.update(status="unknown", reason=reason)
        self._save()
        raise SkillError(reason, status="unknown", request_id=record["request_id"])

    def _observation_timing(self, record, stage, now=None):
        """Diagnostic offsets only; never mint or move an observation's age origin."""
        timing = record.get("observation_acquisition")
        if timing is None:
            return
        now = self.clock() if now is None else now
        elapsed = now - timing["started_monotonic"]
        if not math.isfinite(elapsed):
            timing["clock_invalid"] = True
            return
        timing["checkpoints_ms"][stage] = round(elapsed * 1000, 3)

    def _exchange(self, record, *, before=None):
        rid = record["request_id"]
        try:
            self._observation_timing(record, "before_submit")
            command = deepcopy(record["command"])
            # Bound validation/session and command preparation consume the
            # original age too. This check is strictly before transport starts.
            if before is not None and not 0 <= self.clock() - before.captured_at <= self.max_age:
                self._finish(record, "blocked", "preflight_observation_stale")
                raise SkillError("preflight_observation_stale")
            if self._job_control is not None and record["kind"] == "mutation":
                # Reservation persistence/session work may have observed a stop.
                # This is the final admission boundary before transport starts;
                # a known unsubmitted mutation must not leave an unknown latch.
                try:
                    self._job_control.checkpoint()
                    # Owner validation can perform session I/O. Recheck stop
                    # without another owner/network call at the submit boundary.
                    stop = self._job_control.stop_reason()
                    if stop:
                        raise SkillError(stop, status="cancelled" if stop == "cancel_requested" else "interrupted")
                except SkillError as exc:
                    self._finish(record, "cancelled" if exc.status == "cancelled" else "blocked", exc.reason,
                                 {"submission_outcome": "stopped_before_dispatch", "gameplay_effect_confirmed": False})
                    raise
                self._job_effect_certainty = "unknown"
            returned = self.client.submit(command, request_id=rid)
            self._observation_timing(record, "submit_returned")
            if returned != rid:
                self._unknown(record, "submitted_request_identity_mismatch")
            record["status"] = "submitted"
            self._save()
            self._observation_timing(record, "submitted_journal_persisted")
            if self._job_control is None:
                result = self.client.wait(rid, timeout=self.wait_timeout)
            else:
                until = self.clock() + self.wait_timeout
                while True:
                    result = self.client.result(rid)
                    if result is not None:
                        cancel = record.get("cancel_control")
                        if cancel:
                            ack = self.client.result(cancel["request_id"])
                            if ack is not None:
                                cancel["receipt"] = deepcopy(ack)
                                self._save()
                                if (ack.get("request_id") != cancel["request_id"]
                                        or ack.get("session_id") != record["gateway_session"]
                                        or ack.get("status") != "succeeded" or self._unsafe_flags(ack)):
                                    self._unknown(record, "exact_cancel_receipt_unconfirmed")
                                break
                        else:
                            break
                    if self.clock() >= until:
                        self._unknown(record, "original_request_wait_unconfirmed")
                    if self._job_control.stop_reason() and result is None:
                        self._cancel_running_once(record)
                    self.sleeper(.025)
            self._observation_timing(record, "terminal_received")
        except SkillError:
            raise
        except Exception as exc:
            self._unknown(record, "queue_exchange_unknown:" + type(exc).__name__)
        if not isinstance(result, dict) or result.get("request_id") != rid:
            self._unknown(record, "result_request_identity_mismatch")
        if result.get("session_id") != record["gateway_session"]:
            self._unknown(record, "result_gateway_session_mismatch")
        if result.get("status") not in self.TERMINAL:
            if (record["kind"] == "observation"
                    and record["command"].get("terrain_acquisition") in {"native-full729-v1","native-full729-client-clock-v1"}
                    and result.get("status") == "uncertain"):
                # Preserve the original acquisition/closure evidence while the
                # same pending ID remains unknown. This is never acceptance.
                self._receipt(record, result)
            self._unknown(record, "request_" + str(result.get("status", "unknown")))
        self._receipt(record, result)
        self._observation_timing(record, "receipt_archived")
        record["status"] = "terminal_unverified"
        self._save()
        self._observation_timing(record, "terminal_journal_persisted")
        self._completed.add(rid)
        return result

    def _finish(self, record, status, reason, evidence=None):
        record.update(status=status, reason=reason)
        if evidence is not None:
            record["evidence"] = deepcopy(evidence)
        require(self._journal["pending"] == record["request_id"], "pending_identity_changed")
        self._journal["pending"] = None
        self._save()

    def _validate_state(self, payload, *, allow_menu=False, context=None, allowed_dimension=None):
        require(isinstance(payload, dict) and isinstance(payload.get("state"), dict), "state_missing")
        state = payload["state"]
        p, w, a = state.get("player"), state.get("world"), state.get("client_action")
        require(all(isinstance(v, dict) for v in (p, w, a)), "observation_context_missing")
        require(state.get("focused") is True, "game_window_unfocused_or_unknown")
        require(state.get("private_singleplayer") is True, "private_singleplayer_required")
        require(type(state.get("screen_open")) is bool and (allow_menu or not state["screen_open"]), "unexpected_menu")
        require(state.get("paused") is False, "game_paused_or_unknown")
        require(p.get("alive") is True and type(p.get("health")) in (int, float)
                and math.isfinite(p["health"]) and p["health"] > 0, "player_not_alive")
        held = state.get("held_inputs")
        require(isinstance(held, dict) and held.get("neutral") is True, "input_release_not_observed")
        require(a.get("status") in self.TERMINAL | {"idle"}, "native_action_still_running")
        require(all(type(p.get(k)) in (int, float) and math.isfinite(p[k]) for k in ("x", "y", "z")), "invalid_player_position")
        current = (w.get("world_generation"), w.get("dimension"), p.get("uuid"), a.get("action_session"))
        require(all(isinstance(v, str) and v for v in current), "context_identity_missing")
        require(p.get("dimension") == current[1], "dimension_observations_disagree")
        if context is not None and current != context:
            require(allowed_dimension is not None and current[1] == allowed_dimension
                    and current[2:] == context[2:], "world_dimension_player_or_action_session_changed")
        tick = w.get("game_time")
        require(type(tick) is int and tick >= 0, "game_tick_missing")
        guard = state.get("capability_guard")
        require(isinstance(guard, dict) and type(guard.get("schema_version")) is int
                and guard["schema_version"] == 1 and type(guard.get("source_tick")) is int
                and guard["source_tick"] == tick,
                "native_capability_sample_missing")
        require(isinstance(guard.get("source_nano"), str) and re.fullmatch(r"-?[0-9]{1,20}", guard["source_nano"])
                and -(2**63) <= int(guard["source_nano"]) < 2**63, "native_capability_nano_invalid")
        return state, current, tick

    def _make_observation(self, result, captured, *, allow_menu=False, context=None, allowed_dimension=None, epoch=None, options=None):
        checked_at = self.clock()
        record = self._journal["records"].get(result.get("request_id"))
        if record is not None:
            self._observation_timing(record, "freshness_checked", checked_at)
        require(0 <= checked_at - captured <= self.max_age, "observation_acquisition_stale")
        payload = result.get("result")
        require(not self._unsafe_flags(result) and not self._unsafe_flags(payload),
                "observation_requires_handoff_or_is_uncertain")
        # New wire provenance remains original bytes; semantic siblings are independently rechecked.
        # This never changes diagnostic observation-clock eligibility for action dispatch.
        try:
            from resident_controller.movement_wire import validate_delivery
            validate_delivery(payload, (options or {}).get("entity_radius", 8),
                              observation_clock=self.observation_clock_contract)
        except (ValueError, KeyError, TypeError) as exc:
            raise SkillError("invalid_native_capability_wire_provenance") from exc
        state, identity, tick = self._validate_state(payload, allow_menu=allow_menu,
                                                    context=context, allowed_dimension=allowed_dimension)
        stamp=None
        if self.observation_clock_contract is not None:
            try:
                from resident_controller.capability_snapshot import validate_snapshot
                from navigation_controller.observation_clock import ClockStamp, terrain_clocks
                validate_snapshot(payload,(options or {}).get("entity_radius",8),observation_clock=self.observation_clock_contract)
                stamp=ClockStamp.parse(payload["observation_clock"])
                if self._last_observation_clock is not None: stamp.after(self._last_observation_clock)
                if payload.get("terrain") is not None: terrain_clocks(payload["terrain"],state)
            except (ValueError,KeyError,TypeError) as exc:
                raise SkillError("invalid_read_only_observation_clock") from exc
        else:
            require(payload.get("capability_snapshot_schema_version",1) == 1 and
                    "observation_clock" not in payload and "observation_clock" not in state, "read_only_clock_not_selected")
            if self._context == identity and self._last_tick is not None:
                require(tick >= self._last_tick, "game_tick_regressed")
        data = deepcopy(payload)
        observation = Observation(data["state"], data.get("terrain"), data, tick, identity,
                                  captured, result["request_id"], self._owner, _digest(data), epoch, options or {},
                                  None if stamp is None else stamp.as_dict())
        self._context, self._last = identity, observation
        if stamp is None: self._last_tick=tick
        else: self._last_observation_clock=stamp
        return observation

    def observe(self, terrain=False, radius=4, vertical=4, allow_menu=False, *, entity_radius=8, _context=None, _allowed_dimension=None,
                acquisition=_DEFAULT_ACQUISITION):
        with self._mutex:
            self._control_checkpoint()
            require(self._journal["pending"] is None, "unknown_or_pending_request_blocks_new_work")
            require(not self._observation_clock_failed, "read_only_clock_attempt_failed")
            require(acquisition is _DEFAULT_ACQUISITION or type(acquisition) is str and acquisition == ("native-full729-client-clock-v1" if self.observation_clock_contract is not None else "native-full729-v1"),
                    "invalid_terrain_acquisition")
            if acquisition is not _DEFAULT_ACQUISITION:
                require(terrain is True and type(radius) is int and radius == 4
                        and type(vertical) is int and vertical == 4 and type(entity_radius) is int and entity_radius == 48
                        and allow_menu is False and _allowed_dimension is None,
                        "invalid_native_full729_options")
                require(self._observation_reacquisition is None, "native_full729_reacquisition_forbidden")
            session = self._session()
            if self._observation_reacquisition is not None:
                from .observation_reacquisition import _validate_session
                _validate_session(self, session)
                require(_allowed_dimension is None and (_context is None or
                        _context == self._observation_reacquisition.context),
                        "observation_reacquisition_context_override_rejected")
            require(type(entity_radius) is int and 1 <= entity_radius <= 128, "invalid_entity_radius")
            require(type(radius) is int and 1 <= radius <= 16 and type(vertical) is int and 2 <= vertical <= 8,
                    "invalid_observation_bounds")
            if self.observation_clock_contract is not None:
                require(self._observation_reacquisition is None and _allowed_dimension is None, "read_only_reacquisition_or_transition_forbidden")
            command = {"op": "observe", "entity_radius": entity_radius, "capability_observation": True}
            if self.observation_clock_contract is not None: command["observation_clock"]=self.observation_clock_contract
            if terrain:
                command.update(terrain=True, radius=radius, vertical=vertical)
            if acquisition is not _DEFAULT_ACQUISITION:
                command["terrain_acquisition"] = acquisition
            record = self._reserve("observation", self._owned_command(command, session))
            # A newer read is authoritative. Its failure/unsafe policy must not
            # leave a younger-than-TTL historical safe snapshot usable.
            self._preflight_request_id = None
            captured = self.clock()
            record["observation_acquisition"] = {"schema_version": 1, "clock": "runtime_monotonic",
                "started_monotonic": captured, "max_age_seconds": self.max_age,
                "checkpoints_ms": {}, "diagnostic_only": True}
            result = self._exchange(record)
            if result["status"] != "succeeded":
                if self.observation_clock_contract is not None: self._observation_clock_failed=True
                self._finish(record, "failed", "observation_failed")
                raise SkillError("observation_failed", status="failed", request_id=record["request_id"])
            try:
                if acquisition is not _DEFAULT_ACQUISITION:
                    self._validate_native_acquisition(result, record)
                obs = self._make_observation(result, captured, allow_menu=allow_menu,
                    context=self._context if _context is None else _context, allowed_dimension=_allowed_dimension,
                    epoch=session.get("defense_epoch"), options={"radius": radius, "vertical": vertical, "entity_radius": entity_radius,
                        **({"acquisition": acquisition} if acquisition is not _DEFAULT_ACQUISITION else {})})
                require(self._session().get("defense_epoch") == session.get("defense_epoch"), "defense_epoch_changed_during_observation")
            except SkillError as exc:
                if self.observation_clock_contract is not None: self._observation_clock_failed=True
                evidence = exc.evidence if isinstance(exc, ObservationUnavailable) else None
                if isinstance(exc, ObservationUnavailable) and acquisition is _DEFAULT_ACQUISITION:
                    try:
                        from .observation_reacquisition import _admit_unavailable
                        _admit_unavailable(self, exc, record, result, captured, session,
                                           allow_menu=allow_menu)
                    except SkillError as guard:
                        evidence = {"unavailable": deepcopy(evidence), "reacquisition_rejected": guard.reason}
                        exc = guard
                self._finish(record, "blocked", exc.reason, evidence)
                if isinstance(exc, ObservationUnavailable) and acquisition is _DEFAULT_ACQUISITION:
                    exc.request_id = record["request_id"]
                    raise exc from None
                raise SkillError(exc.reason, status=exc.status, request_id=record["request_id"]) from None
            self._finish(record, "succeeded", "fresh_observation")
            self._preflight_request_id = obs.request_id if self.observation_clock_contract is None else None
            return obs

    def _validate_native_acquisition(self, result, record):
        """No downgrade at the Runtime boundary; Resident owns wire validation."""
        version=2 if self.observation_clock_contract is not None else 1
        acquisition="native-full729-client-clock-v1" if version==2 else "native-full729-v1"
        payload = result.get("result")
        require(type(payload) is dict, "native_full729_result_missing")
        evidence, terrain, capture = (payload.get(k) for k in ("terrain_acquisition", "terrain", "capability_capture"))
        require(type(evidence) is dict and type(evidence.get("schema_version")) is int
                and evidence["schema_version"] == version and evidence.get("acquisition") == acquisition
                and evidence.get("capture_bracket") == "conservative_before_A_to_C_delivery",
                "native_full729_provenance_missing")
        manifest = evidence.get("manifest")
        require(type(manifest) is dict and manifest.get("acquisition") == acquisition
                and type(manifest.get("acquisition_schema_version")) is int
                and manifest["acquisition_schema_version"] == version
                and manifest.get("status") == "succeeded"
                and all(manifest.get(k) is False for k in ("stop_requested", "admission_held", "client_work_pending", "encoding_pending"))
                and type(manifest.get("request_admissions")) is int and manifest["request_admissions"] == 2,
                "native_full729_not_released")
        job = result.get("queue_request_id", result["request_id"])
        owner = result.get("queue_session_id", result["session_id"])
        require(evidence.get("job_id") == manifest.get("job_id") == job
                and evidence.get("owner_id") == manifest.get("owner_id") == owner,
                "native_full729_identity_mismatch")
        context = manifest.get("context")
        expected_epoch = record["command"].get("_navigation_defense_epoch")
        require(type(context) is dict and type(context.get("defense_epoch")) is type(expected_epoch)
                and context.get("defense_epoch") == expected_epoch, "native_full729_defense_epoch_mismatch")
        require(type(terrain) is dict and terrain.get("complete") is True and terrain.get("radius") == 4
                and terrain.get("vertical") == 4 and type(capture) is dict
                and evidence.get("started_monotonic") == terrain.get("capture_started_mono") == capture.get("started_mono"),
                "native_full729_capture_mismatch")

    def survey(self, radius=16, vertical=8, *, entity_radius=48, allow_menu=False):
        """Read a bounded sequential region for planning; never mint preflight.

        Historical survey safety/context still fail closed. A successful survey
        invalidates any prior preflight and must be followed by a fresh observe
        before every action or goal-success claim.
        """
        require(self.observation_clock_contract is None, "read_only_survey_forbidden")
        with self._mutex:
            require(self._journal["pending"] is None, "unknown_or_pending_request_blocks_new_work")
            require(self._journal.get("semantic_pending") is None, "previous_semantic_result_requires_reconciliation")
            session = self._session()
            require(type(radius) is int and 1 <= radius <= 16 and type(vertical) is int and 2 <= vertical <= 8,
                    "invalid_survey_bounds")
            require(type(entity_radius) is int and 1 <= entity_radius <= 128, "invalid_entity_radius")
            command = {"op": "observe", "terrain": True, "radius": radius, "vertical": vertical,
                       "entity_radius": entity_radius, "capability_observation": True, "capability_survey": True}
            record = self._reserve("survey", self._owned_command(command, session))
            self._preflight_request_id = None
            captured = self.clock()
            result = self._exchange(record)
            try:
                require(result["status"] == "succeeded", "survey_failed")
                payload = result.get("result")
                require(not self._unsafe_flags(result) and not self._unsafe_flags(payload),
                        "survey_requires_handoff_or_is_uncertain")
                state, identity, tick = self._validate_state(payload, allow_menu=allow_menu, context=self._context)
                elapsed = self.clock() - captured
                require(0 <= elapsed <= 20, "historical_survey_acquisition_budget_exhausted")
                terrain = payload.get("terrain")
                require(isinstance(terrain, dict) and terrain.get("complete") is True
                        and terrain.get("historical_survey") is True, "explicit_historical_survey_required")
                require(terrain.get("dimension") == identity[1] and terrain.get("world_generation") == identity[0],
                        "survey_terrain_context_mismatch")
                require(terrain.get("radius") == radius and terrain.get("vertical") == vertical,
                        "survey_bounds_mismatch")
                pages = terrain.get("source_pages")
                require(isinstance(pages, list) and 1 <= len(pages) <= 256, "survey_page_provenance_required")
                start, finish = terrain.get("capture_started_mono"), terrain.get("capture_finished_mono")
                require(all(type(v) in (int, float) and math.isfinite(v) for v in (start, finish))
                        and 0 <= finish - start <= 15, "survey_capture_interval_invalid")
                first, last = terrain.get("source_tick"), terrain.get("last_tick")
                require(type(first) is int and type(last) is int and 0 <= first <= last <= tick
                        and last - first <= 320, "survey_tick_provenance_invalid")
                previous_time, previous_tick, offset = start, first, 0
                for page in pages:
                    require(isinstance(page, dict) and type(page.get("source_tick")) is int
                            and type(page.get("response_tick")) is int and type(page.get("offset")) is int
                            and type(page.get("returned")) is int and page["returned"] > 0,
                            "survey_page_provenance_invalid")
                    t = page.get("captured_mono")
                    require(type(t) in (int, float) and math.isfinite(t) and previous_time <= t <= finish
                            and first <= page["source_tick"] <= page["response_tick"] <= last
                            and previous_tick <= page["response_tick"] and page["offset"] == offset,
                            "survey_page_provenance_invalid")
                    previous_time, previous_tick = t, page["response_tick"]
                    offset += page["returned"]
                require(self._session().get("defense_epoch") == session.get("defense_epoch"),
                        "defense_epoch_changed_during_survey")
                if self._context == identity and self._last_tick is not None:
                    require(tick >= self._last_tick, "game_tick_regressed")
                data = deepcopy(payload)
                survey = Survey(data["state"], data["terrain"], data, tick, identity, captured,
                                result["request_id"], elapsed, self._owner, _digest(data))
            except SkillError as exc:
                self._finish(record, "blocked", exc.reason)
                raise
            self._context, self._last_tick = identity, tick
            self._finish(record, "succeeded", "historical_region_survey")
            return survey

    def validate_survey(self, survey):
        """Check provenance for proposal use, without granting freshness."""
        require(self.observation_clock_contract is None, "read_only_survey_forbidden")
        with self._mutex:
            self._open()
            require(isinstance(survey, Survey) and survey._owner == self._owner, "foreign_survey")
            require(_digest(survey.raw) == survey._fingerprint and survey.state == survey.raw.get("state")
                    and survey.terrain == survey.raw.get("terrain"), "survey_modified_after_capture")
            require(survey.context == self._context, "survey_context_changed")
            return survey

    def _fresh(self, before, allow_menu=False):
        require(self.observation_clock_contract is None and getattr(before,"observation_clock",None) is None, "read_only_preflight_forbidden")
        require(isinstance(before, Observation) and before._owner == self._owner,
                "observation_not_owned_by_current_runtime")
        require(before.request_id == self._preflight_request_id, "newer_observation_invalidated_preflight")
        require(_digest(before.raw) == before._fingerprint and before.state == before.raw.get("state"),
                "observation_modified_after_capture")
        require(0 <= self.clock() - before.captured_at <= self.max_age, "preflight_observation_stale")
        self._validate_state(before.raw, allow_menu=allow_menu, context=self._context)

    def scoped_profile(self, action):
        """Negotiated action-local admission, only inside the original admitted job."""
        return self._job_scoped_profiles.get(action) if self._job_control is not None else None

    def _compile(self, command, before, session):
        require(self.observation_clock_contract is None and getattr(before,"observation_clock",None) is None, "read_only_action_forbidden")
        require(isinstance(command, dict) and command.get("op") == "action"
                and command.get("action") in self.ACTIONS, "guarded_native_action_required")
        require("action_id" not in command, "native_id_is_resident_owned")
        self._control_checkpoint()
        timeout = command.get("timeout_ms", 15000)
        require(type(timeout) is int and 50 <= timeout <= 60000, "finite_action_timeout_required")
        body = deepcopy(command)
        if self._job_control is not None:
            remaining_ms = int(self._job_control.budget.remaining_seconds() * 1000)
            require(remaining_ms >= 50, "original_deadline_insufficient_for_action")
            body["timeout_ms"] = min(timeout, remaining_ms)
            profile = self._job_scoped_profiles.get(body["action"])
            if profile is not None:
                body["scoped_native_preflight"] = {"version": "scoped-native-preflight/1", "profile": profile,
                    "owner_id": self._owner, "owner_generation": self._job_generation,
                    "job_id": self._job_control.job_id, "defense_epoch": session["defense_epoch"]}
        bindings = {"capability_guard": before.state["capability_guard"],
                    "expected_world_generation": before.context[0], "expected_dimension": before.context[1],
                    "expected_player_uuid": before.context[2], "expected_action_session": before.context[3]}
        for key, value in bindings.items():
            require(key not in body or body[key] == value, "conflicting_native_capability_binding")
            body[key] = deepcopy(value)
        require(session.get("defense_epoch") == before._gateway_epoch, "defense_epoch_changed_requires_fresh_plan")
        if body["action"] in ("click_slot", "close_menu"):
            menu_class = before.state.get("menu", {}).get("menu_class")
            require(isinstance(menu_class, str) and menu_class, "expected_menu_class_missing")
            require("expected_menu_class" not in body or body["expected_menu_class"] == menu_class, "conflicting_menu_class_binding")
            body["expected_menu_class"] = menu_class
        if body["action"] not in ("click_slot", "close_menu"):
            selected = before.player.get("selected_slot")
            require(type(selected) is int and 0 <= selected <= 8, "selected_hotbar_slot_missing")
            target_slot = body.get("hotbar_slot", selected)
            require(type(target_slot) is int and 0 <= target_slot <= 8, "invalid_hotbar_slot")
            item = next((v for v in before.player.get("inventory", []) if v.get("slot") == target_slot), None)
            require(isinstance(item, dict) and isinstance(item.get("item_fingerprint"), str), "exact_held_item_binding_missing")
            for key, value in (("expected_hotbar_slot", selected), ("expected_held_item", item)):
                require(key not in body or body[key] == value, "conflicting_held_item_binding")
                body[key] = deepcopy(value)
        if "defense_epoch" in session:
            require(type(session["defense_epoch"]) is int, "invalid_defense_epoch")
            body["_navigation_defense_epoch"] = session["defense_epoch"]
        if body["action"] in ("follow_path", "break_block", "place_block", "combat_entity"):
            from resident_controller.navigation_binding import NativeBindingContext
            if not hasattr(self, "_navigation_binding"):
                self._navigation_binding = NativeBindingContext()
            try:
                body = self._navigation_binding.bind(body, before.state)
            except ValueError as exc:
                raise SkillError(str(exc)) from None
        return self._owned_command(body, session)

    @staticmethod
    def _unsafe_flags(result):
        if not isinstance(result, dict):
            return False
        if any(k in result and result[k] is not False for k in ("requires_handoff", "unknown_outcome", "post_uncertain", "uncertain", "input_release_unconfirmed")):
            return True
        policy = result.get("resident_policy")
        return isinstance(policy, dict) and (policy.get("requires_handoff") is not False
                                            or policy.get("input_release_unconfirmed") is not False)

    @classmethod
    def _no_effect(cls, result):
        if cls._unsafe_flags(result) or cls._unsafe_flags(result.get("result")):
            return False
        policy = result.get("policy_rejection")
        if (result.get("status") == "cancelled" and result.get("reason") in ("noncombat_execution_policy", "request_only_execution_policy")
                and result.get("gameplay_effect_confirmed") is False and "queue_request_id" in result
                and result["queue_request_id"] is None and isinstance(policy, dict) and not cls._unsafe_flags(policy)
                and type(policy.get("schema_version")) is int and policy["schema_version"] == 1
                and policy.get("execution_policy") in ("noncombat", "request_only")
                and result.get("reason") == policy["execution_policy"] + "_execution_policy"
                and policy.get("dispatched") is False
                and result.get("action") is None and result.get("action_id") is None
                and result.get("cancellation") is None
                and result.get("result") in (None, {})):
            return True
        if (result.get("status") == "cancelled" and result.get("reason") == "navigation_defense_epoch_changed"
                and result.get("gameplay_effect_confirmed") is False and result.get("queue_request_id") is None):
            return True
        cancel = result.get("exact_cancel")
        if (result.get("status") == "cancelled" and isinstance(cancel, dict)
                and cancel.get("schema_version") == 1 and cancel.get("admitted") is False
                and cancel.get("input_release_confirmed") is True
                and cancel.get("original_request_id") == result.get("queue_request_id", result.get("request_id"))
                and result.get("action") is None and result.get("action_id") is None):
            return True
        admission = result.get("action_admission")
        return (result.get("status") == "failed" and isinstance(admission, dict)
                and type(admission.get("schema_version")) is int and admission["schema_version"] == 1
                and type(admission.get("http_status")) is int and 400 <= admission["http_status"] < 500
                and admission.get("admitted") is False and admission.get("uncertain") is False
                and isinstance(admission.get("reason"), str) and admission["reason"] == result.get("reason")
                and result.get("action") is None and result.get("action_id") is None
                and result.get("cancellation") is None)

    def _native_receipt(self, record, result, before):
        if self._unsafe_flags(result) or self._unsafe_flags(result.get("result")):
            self._unknown(record, "receipt_requires_handoff_or_is_uncertain")
        payload = result.get("result")
        native = payload.get("action") if isinstance(payload, dict) else None
        if not isinstance(native, dict):
            native = result.get("action")
        # Absence is never proof that a mutating request did not run.
        if not isinstance(native, dict):
            self._unknown(record, "native_receipt_missing")
        if self._unsafe_flags(native) or self._unsafe_flags(native.get("result")):
            self._unknown(record, "native_receipt_requires_handoff_or_is_uncertain")
        if (native.get("action_session") != before.context[3]
                or native.get("action") != record["command"]["action"]
                or native.get("status") not in self.TERMINAL):
            self._unknown(record, "native_receipt_identity_or_status_mismatch")
        queue_session = result.get("queue_session_id", record["gateway_session"])
        queue_id = result.get("queue_request_id", record["request_id"])
        try:
            expected = uuid.uuid5(uuid.UUID(queue_session), queue_id + ":1").hex
        except (ValueError, TypeError, AttributeError):
            self._unknown(record, "native_request_correlation_unavailable")
        if native.get("action_id") != expected:
            self._unknown(record, "native_action_id_mismatch")
        if native.get("result", {}).get("input_release_confirmed") is not True:
            self._unknown(record, "native_input_release_unconfirmed")
        if "scoped_native_preflight" in record["command"]:
            from resident_controller.capability_snapshot import validate_scoped_witness
            intent = {k: deepcopy(v) for k, v in record["command"].items() if k not in
                ("op", "scoped_native_preflight", "_navigation_defense_epoch", "_capability_owner_id", "_capability_expected_dimension")}
            intent["action_id"] = native["action_id"]
            try:
                validate_scoped_witness(native, record["command"]["scoped_native_preflight"], native["action_id"], intent)
            except (ValueError, KeyError, TypeError):
                self._unknown(record, "native_scoped_witness_unconfirmed")
        if self._job_control is not None:
            self._job_effect_certainty = "known"
        return native

    def execute(self, skill, command, verify, *, before=None, allow_menu=False,
                max_samples=8, stable_samples=2, allowed_dimension=None):
        require(self.observation_clock_contract is None and getattr(before,"observation_clock",None) is None, "read_only_action_forbidden")
        with self._mutex:
            record = None
            native = None
            all_ids = []
            try:
                self._open()
                self._control_checkpoint()
                require(self._journal.get("semantic_pending") is None, "previous_semantic_result_requires_reconciliation")
                require(callable(verify), "semantic_postcondition_required")
                require(type(max_samples) is int and 1 <= max_samples <= 128
                        and type(stable_samples) is int and 1 <= stable_samples <= max_samples,
                        "invalid_verification_budget")
                require(isinstance(skill, str) and 0 < len(skill) <= 128, "invalid_skill_name")
                require(allowed_dimension is None or allowed_dimension in (
                    "minecraft:overworld", "minecraft:the_nether", "minecraft:the_end"), "unsupported_destination_dimension")
                if before is None:
                    before = self.observe(allow_menu=allow_menu)
                self._fresh(before, allow_menu)
                transition_server = None
                if allowed_dimension is not None:
                    require(command.get('action') == 'follow_path' and
                        (before.context[1], allowed_dimension) in {
                            ('minecraft:overworld','minecraft:the_nether'),
                            ('minecraft:the_nether','minecraft:overworld'),
                            ('minecraft:overworld','minecraft:the_end'),
                            ('minecraft:the_end','minecraft:overworld')},
                        'expected_transition_requires_supported_portal_entry')
                    transition_server = before.state['world'].get('integrated_server_instance')
                    require(isinstance(transition_server, str) and re.fullmatch(
                        r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', transition_server),
                        'native_integrated_server_instance_required_for_transition')
                session = self._session()
                require("_capability_expected_dimension" not in command, "private_transition_binding_is_runtime_owned")
                body = self._compile(command, before, session)
                if allowed_dimension is not None and self._lease_active:
                    body["_capability_expected_dimension"] = allowed_dimension
                record = self._reserve("mutation", body, skill=skill, before=before)
                all_ids.append(record["request_id"])
                # Disk latency must not silently extend the original source age.
                try:
                    self._fresh(before, allow_menu)
                    self._session()
                except SkillError as exc:
                    self._finish(record, "blocked", exc.reason)
                    raise
                receipt = self._exchange(record, before=before)
                if self._no_effect(receipt):
                    if self._job_control is not None:
                        self._job_effect_certainty = record.get("prior_job_effect_certainty", "none_proven")
                    evidence = {"gameplay_effect_confirmed": False, "server_confirmed": False,
                        "submission_outcome": "known_no_effect_rejection",
                        "command_sha256": record["command_sha256"],
                        "queue_request_id": receipt.get("queue_request_id")}
                    if isinstance(receipt.get("action_admission"), dict):
                        # Preserve the actual native admission diagnostics. A
                        # submitted, rejected request is not a precompile stop.
                        # These fields never decide outcome or authorize retry.
                        evidence["action_admission"] = deepcopy(receipt["action_admission"])
                    self._finish(record, "blocked", str(receipt.get("reason", "known_no_effect_rejection")), evidence)
                    return Outcome("cancelled" if receipt.get("exact_cancel", {}).get("admitted") is False else "blocked",
                                   record["reason"], tuple(all_ids), evidence, before)
                native = self._native_receipt(record, receipt, before)
                transition = (allowed_dimension is not None and native["status"] == "cancelled"
                              and native.get("reason") in self.TRANSITIONS)
                if native["status"] != "succeeded" and not transition:
                    self._finish(record, "failed", str(native.get("reason", "native_action_failed")))
                    return Outcome("cancelled" if native["status"] == "cancelled" else "failed", record["reason"], tuple(all_ids),
                                   {"native": native, "server_confirmed": False}, before)
                # Native action is known terminal/released; independent observes
                # can safely use the queue. Keep semantic verification pending in
                # the record even though a new observation needs the pending slot.
                record["status"] = "verifying"
                self._journal["semantic_pending"] = record["request_id"]
                self._journal["pending"] = None
                self._save()
                consecutive, ticks, last = 0, [], None
                native_state = receipt.get("result", {}).get("state", {})
                native_tick = native_state.get("world", {}).get("game_time", before.tick)
                minimum_tick = native_tick if type(native_tick) is int else before.tick
                for _ in range(max_samples):
                    sample = self.observe(terrain=before.terrain is not None, allow_menu=allow_menu, **before._options,
                        _context=last.context if last is not None and last.context != before.context else before.context,
                        _allowed_dimension=None if last is not None and last.context != before.context else allowed_dimension)
                    all_ids.append(sample.request_id)
                    if allowed_dimension is not None:
                        require(sample.state['world'].get('integrated_server_instance') == transition_server,
                            'portal_integrated_server_instance_changed')
                        require(sample.context[1] == before.context[1]
                            or sample.context[0] != before.context[0], 'portal_world_generation_not_replaced')
                    require(sample.state["client_action"].get("action_id") == native["action_id"]
                            and sample.state["client_action"].get("action_session") == native["action_session"],
                            "postcondition_native_action_replaced")
                    # A destination dimension has its own time; never compare its
                    # ticks to the source dimension's clock.
                    lower = minimum_tick if sample.context == before.context else -1
                    if last is not None and sample.context == last.context:
                        lower = max(lower, last.tick)
                    valid_tick = sample.tick > lower
                    semantic = bool(verify(before, sample)) if valid_tick else False
                    if allowed_dimension is not None:
                        semantic = semantic and sample.context[1] == allowed_dimension
                    if valid_tick and semantic:
                        consecutive += 1
                        ticks.append(sample.tick)
                    else:
                        consecutive, ticks = 0, []
                    last = sample
                    if consecutive >= stable_samples:
                        evidence = {"level": "client_observed_stable", "server_confirmed": False,
                            "native_action_id": native["action_id"], "native_status": native["status"],
                            "stable_game_times": ticks, "destination_context": list(sample.context),
                            "command_sha256": record["command_sha256"]}
                        if allowed_dimension is not None:
                            evidence['integrated_server_instance'] = transition_server
                        record.update(status="succeeded", reason="semantic_postcondition_confirmed", evidence=evidence)
                        self._journal["semantic_pending"] = None
                        self._save()
                        return Outcome("succeeded", "semantic_postcondition_confirmed", tuple(all_ids), evidence, sample)
                    self.sleeper(.05)
                # A consumed menu interaction without its later menu proof is not a
                # no-effect rejection and must never be automatically replayed.
                unconfirmed_menu = body.get("scoped_native_preflight", {}).get("profile") == "block-menu-v1"
                record.update(status="blocked" if unconfirmed_menu else "failed", reason="postcondition_not_observed")
                self._journal["semantic_pending"] = None
                self._save()
                return Outcome(record["status"], "postcondition_not_observed", tuple(all_ids),
                               {"server_confirmed": False, "native_action_id": native["action_id"],
                                "native_dispatched": native.get("result", {}).get("dispatched"),
                                "menu_transition_confirmed": False, "automatic_replay_allowed": False}, last)
            except SkillError as exc:
                if exc.request_id and exc.request_id not in all_ids:
                    all_ids.append(exc.request_id)
                if record is not None and record.get("status") == "verifying":
                    record.update(status="blocked", reason=exc.reason)
                    if self._job_control is not None and self._job_control.stop_reason():
                        self._journal["semantic_pending"] = None
                    self._save()
                evidence = {"server_confirmed": False}
                if record is not None and native is not None:
                    evidence.update(native_action_id=native["action_id"], native_status=native["status"],
                        command_sha256=record["command_sha256"], semantic_verification="incomplete")
                return Outcome(exc.status, exc.reason, tuple(all_ids), evidence, self._last)
            except Exception as exc:
                # Verifier failures never reexecute a known action. A new pending
                # observe/mutation (if any) stays blocked for exact reconciliation.
                if record is not None and record.get("status") == "verifying":
                    record.update(status="blocked", reason="verification_error:" + type(exc).__name__)
                    self._save()
                evidence = {"server_confirmed": False}
                if record is not None and native is not None:
                    evidence.update(native_action_id=native["action_id"], native_status=native["status"],
                        command_sha256=record["command_sha256"], semantic_verification="incomplete")
                return Outcome("unknown" if self.pending_request_id else "blocked",
                               "capability_error:" + type(exc).__name__, tuple(all_ids),
                               evidence, self._last)

    def require_success(self, outcome):
        require(self.observation_clock_contract is None, "read_only_goal_success_forbidden")
        if not outcome.ok:
            raise SkillError(outcome.reason, status=outcome.status,
                             request_id=outcome.request_ids[0] if outcome.request_ids else None)
        return outcome.last_observation

    def result(self, skill, observations=(), **evidence):
        with self._mutex:
            self._control_checkpoint()
            require(self.observation_clock_contract is None, "read_only_goal_success_forbidden")
            self._open()
            require(self.pending_request_id is None and self._journal.get("semantic_pending") is None, "unresolved_execution_blocks_success")
            require(isinstance(skill, str) and observations, "observed_goal_evidence_required")
            for observation in observations:
                require(isinstance(observation, Observation) and observation._owner == self._owner,
                        "foreign_observation")
                require(_digest(observation.raw) == observation._fingerprint and observation.state == observation.raw.get("state"),
                        "historical_observation_modified_after_capture")
            if self._lease_enabled or self.required_execution_policy is not None:
                self._session()
            self._fresh(observations[-1], allow_menu=True)
            return Outcome("succeeded", "goal_already_observed", tuple(o.request_id for o in observations),
                {**evidence, "level": "client_observed", "server_confirmed": False}, observations[-1])

    def reconcile(self):
        """Read exact uncertain request only. Never replay or claim semantic success."""
        with self._mutex:
            self._open()
            rid = self._journal.get("pending")
            if rid is None and self._journal.get("semantic_pending"):
                rid = self._journal["semantic_pending"]
                record = self._journal["records"][rid]
                record.update(status="reconciled", reason="known_terminal_requires_fresh_goal_revalidation")
                self._journal["semantic_pending"] = None
                self._save()
                return Outcome("blocked", record["reason"], (rid,), {"server_confirmed": False})
            if rid is None:
                return Outcome("blocked", "no_pending_request")
            record = self._journal["records"][rid]
            try:
                result = self.client.result(rid)
            except Exception:
                return Outcome("unknown", "reconciliation_read_failed", (rid,))
            if (not isinstance(result, dict) or result.get("request_id") != rid
                    or result.get("session_id") != record["gateway_session"]
                    or result.get("status") not in self.TERMINAL):
                return Outcome("unknown", "matching_terminal_receipt_not_available", (rid,))
            if record["kind"] in ("capability_acquire", "capability_release"):
                return Outcome("unknown", "ownership_control_requires_operator_reconciliation", (rid,))
            if record["kind"] == "mutation" and not self._no_effect(result):
                fake_before = Observation({}, None, {}, 0, tuple(record["before_context"]), 0, "")
                try:
                    self._native_receipt(record, result, fake_before)
                except SkillError as exc:
                    return Outcome("unknown", exc.reason, (rid,))
            self._receipt(record, result)
            self._finish(record, "reconciled", "known_terminal_requires_fresh_goal_revalidation")
            self._completed.add(rid)
            return Outcome("blocked", "known_terminal_requires_fresh_goal_revalidation", (rid,),
                           {"native_status": result["status"], "server_confirmed": False})

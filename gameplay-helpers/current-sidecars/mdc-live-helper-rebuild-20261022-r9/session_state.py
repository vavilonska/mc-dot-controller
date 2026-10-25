"""Fail-closed, idle-only handoff of the *same* live helper Session.

This is not world recovery, a controller transaction log, or permission to retry
an action.  The controller must already be open on byte-identical retained
history.  No constructor, action, finish, new ID, plan bind, or batch allocation
is called.  A fresh read verifies the explicit, unchanged world context.

Only helper evidence/state files are written.  ``save_snapshot`` atomically
replaces its designated state file and fsyncs both file and directory.  Keep the
returned SHA separately and pass it to ``load_snapshot``.  A snapshot is a
checkpoint, not a concurrent-writer protocol: callers must serialize helper
access, flush pending trace events while idle, and not continue the old helper
after handing its state to another process.
"""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import tempfile
import time


class StateError(ValueError):
    """Handoff could not be proved safe; no action may be inferred or retried."""


SCHEMA_VERSION = 1
KIND = "survival6_same_session_state"
MAX_STATE_BYTES = 256 * 1024 * 1024
CONTEXT_KEYS = {"session", "world_generation", "player_uuid", "owner_id"}
STATE_KEYS = {
    "serial", "ctx", "reserved", "batch", "stage", "stage_number",
    "last_id", "finish_called", "attempted", "completed", "batch_number",
    "consume_state", "checkpoint", "last_clock", "timeout", "jump_parent",
    "alignment_parent", "decision_token", "recovery_note", "batch_expired",
    "accepted_decisions", "decision_serial",
}
TOP_KEYS = {
    "schema_version", "kind", "boot_id", "snapshot_clock", "pins", "baseline",
    "spec", "history", "evidence", "sources", "state", "planner", "sha256",
}


def _fail(reason):
    raise StateError(reason)


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _digest(value):
    return (isinstance(value, str) and len(value) == 64
            and all(c in "0123456789abcdef" for c in value))


def _object(value, keys, label):
    if type(value) is not dict or set(value) != set(keys):
        _fail("closed_" + label + "_schema_required")
    return value


def _json_value(value):
    """Reject non-JSON Python values and non-finite numbers, recursively."""
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float and math.isfinite(value):
        return
    if type(value) is list:
        for item in value:
            _json_value(item)
        return
    if type(value) is dict and all(type(k) is str for k in value):
        for item in value.values():
            _json_value(item)
        return
    _fail("finite_pure_json_state_required")


def encode(value):
    _json_value(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _parse(raw):
    if type(raw) is not bytes or len(raw) > MAX_STATE_BYTES:
        _fail("bounded_exact_json_bytes_required")

    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                _fail("duplicate_json_key")
            out[key] = value
        return out

    try:
        out = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                         parse_constant=lambda value: _fail("nonfinite_json"))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise StateError("strict_utf8_json_required") from exc
    _json_value(out)
    return out


def _safe_path(path, *, existing=False, directory=False):
    path = Path(path).absolute()
    if any(item.is_symlink() for item in (path, *path.parents)):
        _fail("symlink_evidence_or_source_forbidden")
    if existing and not (path.is_dir() if directory else path.is_file()):
        _fail("existing_evidence_or_source_required")
    return path


def _read(path):
    path = _safe_path(path, existing=True)
    with path.open("rb") as stream:
        return stream.read(MAX_STATE_BYTES + 1)


def _file_pin(path):
    path = _safe_path(path, existing=True)
    raw = _read(path)
    if len(raw) > MAX_STATE_BYTES:
        _fail("bounded_evidence_required")
    return {"path": str(path), "sha256": _sha(raw), "bytes": len(raw)}


def current_boot_id():
    """Linux boot identity; unknown identity can never preserve a time budget."""
    try:
        value = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return None
    return value or None


def _boot(value):
    if value is not None and (type(value) is not str or not 1 <= len(value) <= 128):
        _fail("bounded_boot_identity_required")
    return value


def _idle(controller):
    data = controller.ledger.data
    if (type(data) is not dict or type(data.get("actions")) is not dict
            or data.get("unknown_lock") is not False
            or any(type(rec) is not dict or rec.get("state") != "CLOSED"
                   for rec in data["actions"].values())):
        _fail("global_unknown_or_unreleased_history")
    return data


def _history(controller, raw):
    parsed = _parse(raw)
    if parsed != _idle(controller):
        _fail("exact_current_history_required")
    path = getattr(controller.ledger, "path", None)
    if path is not None and _read(path) != raw:
        _fail("exact_persisted_history_bytes_required")
    return parsed


def _string_list(value, label, *, unique=True):
    if (type(value) is not list
            or any(type(item) is not str or not item for item in value)
            or (unique and len(set(value)) != len(value))):
        _fail("invalid_" + label)


def _sources(session, source_paths):
    automatic = {"session": inspect.getsourcefile(type(session)),
                 "planner": inspect.getsourcefile(type(session.planner)),
                 "session_state": __file__}
    if source_paths is None:
        source_paths = {}
    if (type(source_paths) is not dict
            or any(type(key) is not str or not key or path is None
                   for key, path in source_paths.items())):
        _fail("explicit_source_paths_required")
    source_paths = dict(source_paths)
    for name, path in automatic.items():
        if path is None:
            _fail("executing_source_path_unavailable")
        if name in source_paths and Path(source_paths[name]).absolute() != Path(path).absolute():
            _fail("implementation_pin_cannot_be_replaced")
        source_paths[name] = path
    return {key: _file_pin(path) for key, path in sorted(source_paths.items())}


def _check_record_prefix(baseline, history):
    if (type(baseline) is not dict or type(baseline.get("actions")) is not dict
            or baseline.get("unknown_lock") is not False
            or any(rec.get("state") != "CLOSED" for rec in baseline["actions"].values())
            or any(history["actions"].get(aid) != rec
                   for aid, rec in baseline["actions"].items())):
        _fail("exact_closed_baseline_records_required")


def _validate(snapshot):
    _json_value(snapshot)
    _object(snapshot, TOP_KEYS, "session_state")
    if (type(snapshot["schema_version"]) is not int
            or snapshot["schema_version"] != SCHEMA_VERSION or snapshot["kind"] != KIND):
        _fail("unsupported_session_state")
    digest = snapshot["sha256"]
    if not _digest(digest) or _sha(encode({k: v for k, v in snapshot.items() if k != "sha256"})) != digest:
        _fail("state_content_hash_mismatch")
    _boot(snapshot["boot_id"])
    if not _finite(snapshot["snapshot_clock"]) or snapshot["snapshot_clock"] < 0:
        _fail("finite_snapshot_clock_required")
    pins = _object(snapshot["pins"], {"baseline_sha256", "spec_sha256", "baseline_raw", "spec_raw"}, "pins")
    for name in ("baseline", "spec"):
        raw = pins[name + "_raw"]
        if (type(raw) is not str or not _digest(pins[name + "_sha256"])
                or _sha(raw.encode("utf-8")) != pins[name + "_sha256"]
                or _parse(raw.encode("utf-8")) != snapshot[name]):
            _fail(name + "_pin_mismatch")
    history = _object(snapshot["history"], {"sha256", "count", "stage_uses"}, "history")
    if (not _digest(history["sha256"]) or type(history["count"]) is not int
            or not 1 <= history["count"] <= 4096
            or type(history["stage_uses"]) is not int or history["stage_uses"] < 0):
        _fail("invalid_history_pin")
    evidence = _object(snapshot["evidence"], {"trace"}, "evidence")
    if type(snapshot["sources"]) is not dict or not {"session", "planner", "session_state"}.issubset(snapshot["sources"]):
        _fail("source_pins_required")
    for pin in [evidence["trace"], *snapshot["sources"].values()]:
        _object(pin, {"path", "sha256", "bytes"}, "file_pin")
        if (type(pin["path"]) is not str or not Path(pin["path"]).is_absolute()
                or not _digest(pin["sha256"]) or type(pin["bytes"]) is not int
                or not 0 <= pin["bytes"] <= MAX_STATE_BYTES):
            _fail("invalid_file_pin")
    s = _object(snapshot["state"], STATE_KEYS, "session_runtime")
    _object(s["ctx"], CONTEXT_KEYS, "context")
    if type(s["serial"]) is not str or not s["serial"]:
        _fail("original_session_serial_required")
    for key in ("stage_number", "batch_number", "decision_serial"):
        if type(s[key]) is not int or s[key] < 0:
            _fail("invalid_" + key)
    for key in ("reserved", "attempted", "completed", "accepted_decisions"):
        _string_list(s[key], key)
    if not set(s["attempted"]).issubset(s["reserved"]):
        _fail("attempted_id_not_reserved")
    if s["last_id"] is not None and s["last_id"] not in s["attempted"]:
        _fail("last_id_not_attempted")
    if type(s["finish_called"]) is not bool or type(s["batch_expired"]) is not bool:
        _fail("explicit_runtime_booleans_required")
    if not _finite(s["last_clock"]) or s["last_clock"] != snapshot["snapshot_clock"]:
        _fail("last_clock_must_be_snapshot_clock")
    if not _finite(s["timeout"]) or not .05 <= s["timeout"] <= .5:
        _fail("bounded_transport_required")
    if type(s["recovery_note"]) is not str:
        _fail("recovery_note_string_required")
    for key in ("stage", "checkpoint", "jump_parent", "alignment_parent", "decision_token"):
        if s[key] is not None and type(s[key]) is not dict:
            _fail("invalid_" + key)
    if s["consume_state"] is not None and type(s["consume_state"]) is not list:
        _fail("invalid_consume_state")
    if s["decision_token"] is not None:
        token = _object(s["decision_token"],
                        {"token", "session_id", "context", "history_count", "decision_serial"},
                        "decision_token")
        if (type(token["token"]) is not str or not token["token"]
                or token["session_id"] != s["serial"] or token["context"] != s["ctx"]
                or token["history_count"] != history["count"]
                or token["decision_serial"] != s["decision_serial"]
                or s["checkpoint"] is None):
            _fail("current_unused_checkpoint_token_required")
    if type(snapshot["planner"]) is not dict:
        _fail("planner_snapshot_required")
    b = _object(s["batch"], {"id", "start", "deadline", "ids", "cursor", "new_stages"}, "batch")
    _string_list(b["ids"], "batch_ids")
    if (s["batch_number"] < 1 or b["id"] != f'{s["serial"]}:b{s["batch_number"]}'
            or not _finite(b["start"]) or not _finite(b["deadline"])
            or b["start"] < 0 or b["deadline"] - b["start"] != 300
            or not 1 <= len(b["ids"]) <= 128
            or not set(b["ids"]).issubset(s["reserved"])
            or type(b["cursor"]) is not int or not 0 <= b["cursor"] <= len(b["ids"])
            or type(b["new_stages"]) is not int or not 0 <= b["new_stages"] <= 16
            or set(b["ids"][b["cursor"]:]) & set(s["attempted"])):
        _fail("original_finite_batch_budget_required")
    if len(s["completed"]) > s["stage_number"]:
        _fail("original_stage_number_required")
    baseline = snapshot["baseline"]
    if (type(baseline) is not dict or type(baseline.get("actions")) is not dict
            or len(baseline["actions"]) > history["count"]
            or not set(baseline["actions"]).issubset(s["reserved"])
            or set(b["ids"]) & set(baseline["actions"])):
        _fail("original_reserved_history_required")
    spec = snapshot["spec"]
    if (type(spec) is not dict or spec.get("baseline_sha256") != pins["baseline_sha256"]
            or spec.get("baseline_count") != len(baseline["actions"])
            or spec.get("owner_id") != s["ctx"]["owner_id"]
            or spec.get("player_uuid") != s["ctx"]["player_uuid"]):
        _fail("original_spec_context_required")
    return snapshot


def snapshot_session(session, *, history_raw, session_spec_raw, baseline_raw,
                     source_paths=None, boot_id=None):
    """Return a self-contained JSON dict, only at a fully flushed idle boundary."""
    history = _history(session.c, history_raw)
    if session.pending:
        _fail("flush_idle_trace_before_snapshot_no_pending_serialization")
    baseline, spec = _parse(baseline_raw), _parse(session_spec_raw)
    if baseline != session.baseline or spec != session.spec:
        _fail("original_baseline_and_spec_bytes_required")
    _check_record_prefix(baseline, history)
    if not callable(getattr(session.planner, "snapshot", None)):
        _fail("explicit_planner_snapshot_required")
    now = session.now()
    state = {key: copy.deepcopy(getattr(session, key)) for key in STATE_KEYS
             if key not in {"reserved", "accepted_decisions", "consume_state"}}
    state["reserved"] = sorted(session.reserved)
    state["accepted_decisions"] = sorted(session.accepted_decisions)
    state["consume_state"] = None if session.consume_state is None else list(session.consume_state)
    snap = {
        "schema_version": SCHEMA_VERSION, "kind": KIND,
        "boot_id": _boot(current_boot_id() if boot_id is None else boot_id),
        "snapshot_clock": now,
        "pins": {"baseline_sha256": _sha(baseline_raw), "spec_sha256": _sha(session_spec_raw),
                 "baseline_raw": baseline_raw.decode("utf-8"), "spec_raw": session_spec_raw.decode("utf-8")},
        "baseline": copy.deepcopy(baseline), "spec": copy.deepcopy(spec),
        "history": {"sha256": _sha(history_raw), "count": len(history["actions"]),
                    "stage_uses": session.stage_uses(session.stage["id"]) if session.stage else 0},
        "evidence": {"trace": _file_pin(session.trace)}, "sources": _sources(session, source_paths),
        "state": state, "planner": session.planner.snapshot(),
    }
    _decision_evidence(state, _read(session.trace))
    snap["sha256"] = _sha(encode(snap))
    _validate(snap)
    _validate_history_state(snap, history)
    # Observe no history/pending drift while reading source and evidence files.
    _history(session.c, history_raw)
    if session.pending:
        _fail("session_changed_during_snapshot")
    return snap


def _validate_history_state(snapshot, history):
    _check_record_prefix(snapshot["baseline"], history)
    s = snapshot["state"]
    recorded = set(history["actions"])
    baseline = set(snapshot["baseline"]["actions"])
    if (not recorded.issubset(s["reserved"])
            or not (recorded - baseline).issubset(s["attempted"])
            or recorded & set(s["batch"]["ids"][s["batch"]["cursor"]:])):
        _fail("recorded_or_attempted_id_cannot_be_reissued")


def _decision_evidence(state, trace_raw):
    """A trace-first acceptance must not be serialized halfway through apply."""
    pending = set()
    active_token = (state["decision_token"] or {}).get("token")
    for line in trace_raw.splitlines():
        if not line:
            _fail("complete_jsonl_trace_required")
        event = _parse(line)
        if type(event) is not dict:
            _fail("trace_event_object_required")
        if event.get("event") == "decision_accepted":
            command = event.get("command")
            if (type(command) is not dict or type(command.get("decision_id")) is not str
                    or command["decision_id"] not in state["accepted_decisions"]
                    or (active_token is not None and command.get("token") == active_token)):
                _fail("accepted_decision_cannot_restore_unused_token")
            pending.add(command["decision_id"])
        elif event.get("event") == "decision_applied":
            pending.discard(event.get("decision_id"))
    if pending:
        _fail("decision_acceptance_not_fully_applied_no_retry")


def _fsync_directory(path):
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def save_snapshot(path, snapshot):
    """Atomically persist validated state; return its exact file SHA and size."""
    _validate(snapshot)
    raw = encode(snapshot)
    if len(raw) > MAX_STATE_BYTES:
        _fail("state_file_too_large")
    path = _safe_path(path)
    parent = _safe_path(path.parent, existing=True, directory=True)
    if path.exists() and not path.is_file():
        _fail("state_destination_must_be_file")
    fd, temporary = tempfile.mkstemp(prefix=".session-state-", dir=parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            if stream.write(raw) != len(raw):
                raise OSError("incomplete state write")
            stream.flush()
            os.fsync(stream.fileno())
        _safe_path(path)
        os.replace(temporary, path)
        _fsync_directory(parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return {"path": str(path), "sha256": _sha(raw), "bytes": len(raw)}


def load_snapshot(path, *, expected_sha256):
    """A separately retained file pin is required, not a self-asserted hash."""
    raw = _read(path)
    if not _digest(expected_sha256) or _sha(raw) != expected_sha256:
        _fail("pinned_state_file_sha256_required")
    return _validate(_parse(raw))


def _verify_pin(pin, path=None):
    actual = _file_pin(pin["path"] if path is None else path)
    if actual["sha256"] != pin["sha256"] or actual["bytes"] != pin["bytes"]:
        _fail("source_or_evidence_bytes_changed")


def restore_session(session_class, snapshot, *, controller, history_raw,
                    expected_context, outdir, planner_restore, monotonic=time.monotonic,
                    sleep=time.sleep, stop_requested=lambda: False,
                    on_event=lambda event: None, decision_reader=lambda checkpoint: None,
                    source_paths=None, boot_id=None, initial_observation=None,
                    evidence_trace_path=None):
    """Construct via ``__new__``, prove unchanged context, and open new evidence.

    ``expected_context`` is mandatory, external confirmation of this exact native
    session/world/player/owner; changing worlds is not supported.  The controller
    performs one fresh observe, never a start/finish.  Old trace bytes are pinned;
    an explicitly relocated byte-identical trace may use ``evidence_trace_path``.
    Cross-boot/unknown-boot restore preserves the old batch untouched and marks
    ``batch_expired``.  The runner MUST explicitly roll it over before an intent.
    """
    snap = _validate(copy.deepcopy(snapshot))
    state = snap["state"]
    _object(expected_context, CONTEXT_KEYS, "explicit_current_context")
    if expected_context != state["ctx"]:
        _fail("same_session_context_confirmation_required_no_world_rollback")
    if (not isinstance(session_class, type) or not callable(planner_restore)
            or any(not callable(callback) for callback in (monotonic, sleep, stop_requested, on_event, decision_reader))):
        _fail("explicit_restore_dependencies_required")
    history = _history(controller, history_raw)
    if (_sha(history_raw) != snap["history"]["sha256"]
            or len(history["actions"]) != snap["history"]["count"]):
        _fail("same_current_history_bytes_and_count_required")
    _validate_history_state(snap, history)
    if source_paths is not None:
        source_paths = dict(source_paths)
        source_paths.setdefault("session", inspect.getsourcefile(session_class))
        source_paths.setdefault("planner", inspect.getsourcefile(planner_restore))
        source_paths.setdefault("session_state", __file__)
        if set(source_paths) != set(snap["sources"]):
            _fail("exact_pinned_source_set_required")
    for name, pin in snap["sources"].items():
        _verify_pin(pin, None if source_paths is None else source_paths[name])
    # Always pin the implementation currently executing, not merely an old copy.
    _verify_pin(snap["sources"]["session_state"], __file__)
    _verify_pin(snap["sources"]["session"], inspect.getsourcefile(session_class))
    _verify_pin(snap["sources"]["planner"], inspect.getsourcefile(planner_restore))
    _verify_pin(snap["evidence"]["trace"], evidence_trace_path)
    _decision_evidence(state, _read(evidence_trace_path or snap["evidence"]["trace"]["path"]))
    out = _safe_path(outdir)
    if out.exists():
        _fail("new_restore_evidence_directory_required")
    timeout = getattr(controller.transport, "timeout", None)
    if timeout != state["timeout"] or not _finite(timeout):
        _fail("same_bounded_transport_required")
    if getattr(controller, "owner_id", None) != state["ctx"]["owner_id"]:
        _fail("same_controller_owner_required")
    current_boot = _boot(current_boot_id() if boot_id is None else boot_id)
    same_boot = current_boot is not None and snap["boot_id"] is not None and current_boot == snap["boot_id"]
    now = monotonic()
    if not _finite(now) or now < 0 or (same_boot and now < snap["snapshot_clock"]):
        _fail("invalid_or_regressing_restore_clock")
    session = object.__new__(session_class)
    for name, value in state.items():
        setattr(session, name, copy.deepcopy(value))
    session.reserved = set(state["reserved"])
    session.accepted_decisions = set(state["accepted_decisions"])
    session.consume_state = None if state["consume_state"] is None else tuple(state["consume_state"])
    session.c, session.clock, session.sleep = controller, monotonic, sleep
    session.stop_requested, session.on_event = stop_requested, on_event
    session.decision_reader = decision_reader
    session.spec, session.baseline = copy.deepcopy(snap["spec"]), copy.deepcopy(snap["baseline"])
    session.planner = planner_restore(copy.deepcopy(snap["planner"]))
    session.pending = []  # No serialized runtime intent, finish work, or callback.
    session.batch_expired = state["batch_expired"] or not same_boot or now >= session.batch["deadline"]
    session.last_clock = now
    session.out, session.trace = out, out / "trace.jsonl"
    fresh = controller.observe()
    if initial_observation is not None:
        for key in CONTEXT_KEYS:
            native = "bound_owner_id" if key == "owner_id" else key
            if initial_observation.get(native) != fresh.get(native):
                _fail("supplied_observation_context_not_current")
    session.now()
    session.check_context(fresh)
    _history(controller, history_raw)
    actual_uses = session.stage_uses(session.stage["id"]) if session.stage else 0
    if actual_uses != snap["history"]["stage_uses"]:
        _fail("original_stage_budget_not_preserved")
    # Every refusal above leaves the destination and old evidence untouched.
    out.mkdir(parents=True, mode=0o700)
    fd = os.open(session.trace, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        event = {"event": "session_restored", "session_id": session.serial,
                 "snapshot_sha256": snap["sha256"], "source_trace": snap["evidence"]["trace"],
                 "history_sha256": snap["history"]["sha256"], "history_count": snap["history"]["count"],
                 "context": session.ctx, "same_boot": same_boot,
                 "original_batch_deadline": session.batch["deadline"],
                 "batch_expired": session.batch_expired, "observation": fresh}
        raw = encode(event) + b"\n"
        if stream.write(raw) != len(raw):
            raise OSError("incomplete restore evidence write")
        stream.flush()
        os.fsync(stream.fileno())
    _fsync_directory(out)
    _fsync_directory(out.parent)
    on_event(copy.deepcopy(event))
    return session


# Short names are convenient in a runner; explicit names remain public API.
snapshot = snapshot_session
restore = restore_session

"""Narrow, bounded re-sampling of rejected read-only entity observations.

This is not action retry or reconciliation. Every attempt takes the normal
Runtime path, keeps the original freshness origin, and archives the complete
receipt. Unknown work, pending semantics and every other blocker stay blocked.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import math
import uuid

from .core import Observation, ObservationUnavailable, Runtime, SkillError, require


@dataclass
class _Enrollment:
    group_id: str
    context: tuple
    gateway_session: str
    defense_epoch: int
    max_reads: int
    last_tick: int | None
    token: object = field(default_factory=object)
    attempt: int = 0
    active_request_id: str | None = None
    native_identity: tuple | None = None


def reacquisition_enrolled(runtime):
    """True only inside the one explicit observe currently being acquired."""
    scope = getattr(runtime, "_observation_reacquisition", None)
    if not isinstance(scope, _Enrollment) or scope.active_request_id is None:
        return False
    record = runtime._journal["records"].get(scope.active_request_id)
    return (runtime._journal.get("pending") == scope.active_request_id
            and runtime._journal.get("semantic_pending") is None
            and isinstance(record, dict) and record.get("kind") == "observation"
            and record.get("status") == "terminal_unverified")


def _eligible_exception(runtime, error):
    scope = getattr(runtime, "_observation_reacquisition", None)
    return (isinstance(scope, _Enrollment) and isinstance(error, ObservationUnavailable)
            and error._reacquisition_token is scope.token
            and error.request_id == scope.active_request_id
            and runtime._journal.get("pending") is None
            and runtime._journal.get("semantic_pending") is None)


def _validate_session(runtime, session):
    scope = runtime._observation_reacquisition
    require(session.get("session_id") == scope.gateway_session,
            "observation_reacquisition_gateway_changed")
    require(type(session.get("defense_epoch")) is int
            and session["defense_epoch"] == scope.defense_epoch,
            "observation_reacquisition_epoch_changed")
    published = session.get("capability_context")
    if published is not None:
        require(isinstance(published, dict) and tuple(published.get(k) for k in
            ("world_generation", "dimension", "player_uuid", "action_session")) == scope.context,
            "observation_reacquisition_context_changed")


def _frame_identity(runtime, state, context, tick, *, require_release=True):
    scope = runtime._observation_reacquisition
    require(context == scope.context, "observation_reacquisition_context_changed")
    require(scope.last_tick is None or tick >= scope.last_tick,
            "observation_reacquisition_tick_regressed")
    if scope.native_identity is not None:
        require(tick > scope.last_tick, "observation_reacquisition_tick_not_advanced")
    if not require_release:
        scope.last_tick = tick
        return
    action = state["client_action"]
    status = action.get("status")
    if status == "idle":
        require(action.get("action_id") is None,
                "observation_reacquisition_idle_action_identity_invalid")
    else:
        require(isinstance(action.get("action_id"), str) and action["action_id"]
                and action.get("result", {}).get("input_release_confirmed") is True,
                "observation_reacquisition_native_release_unconfirmed")
    native = (action.get("action_session"), action.get("action_id"), status)
    require(scope.native_identity is None or native == scope.native_identity,
            "observation_reacquisition_native_action_changed")
    scope.native_identity = native
    scope.last_tick = tick


def _admit_unavailable(runtime, error, record, result, captured, session, *, allow_menu):
    """Recheck all runtime fences before granting a one-call private token."""
    require(reacquisition_enrolled(runtime), "observation_reacquisition_not_enrolled")
    require(0 <= runtime.clock() - captured <= runtime.max_age,
            "observation_acquisition_stale")
    require(not runtime._unsafe_flags(result) and not runtime._unsafe_flags(result.get("result")),
            "observation_requires_handoff_or_is_uncertain")
    scope = runtime._observation_reacquisition
    state, context, tick = Runtime._validate_state(runtime, result.get("result"),
        allow_menu=allow_menu, context=scope.context)
    # The subclass classifier has already run its health, native capture and
    # full entity-coverage checks. Independently retain the normal meter fence.
    check_meter = getattr(runtime, "_check_meter", None)
    if callable(check_meter):
        check_meter(state)
    evidence = error.evidence
    require(isinstance(evidence, dict) and evidence.get("context") == list(context)
            and type(evidence.get("game_tick")) is int and evidence["game_tick"] == tick
            and isinstance(evidence.get("missing_entities"), list) and evidence["missing_entities"]
            and all(isinstance(row, dict) and row.get("reason") == "entity_not_observed"
                    for row in evidence["missing_entities"]),
            "observation_reacquisition_evidence_invalid")
    _validate_session(runtime, session)
    _validate_session(runtime, runtime._session())
    _frame_identity(runtime, state, context, tick)
    require(0 <= runtime.clock() - captured <= runtime.max_age,
            "observation_acquisition_stale")
    if callable(check_meter):
        # Native meter evidence remains monotone even in a rejected entity
        # observation. This does not grant preflight or semantic authority.
        check_meter(state, update=True)
    evidence.update(request_id=record["request_id"], gateway_session=scope.gateway_session,
        defense_epoch=scope.defense_epoch, native_action=deepcopy(state["client_action"]),
        neutral_inputs_observed=True, preflight_eligible=False,
        acquisition_seconds=runtime.clock() - captured)
    error._reacquisition_token = scope.token


def read_with_reacquisition(runtime, read_callable, *, deadline_check,
                            max_additional_reads=2, wait_seconds=.05):
    """Return one normal fresh Observation, or permanently fail this budget.

    deadline_check must enforce the caller's original goal deadline. It is run
    before/after each attempt and wait; neither goal time nor action budget is
    reset. Only two extra reads and at most 100 ms per wait may be configured.
    """
    require(getattr(runtime,"observation_clock_contract",None) is None, "read_only_reacquisition_forbidden")
    require(isinstance(runtime, Runtime) and callable(read_callable) and callable(deadline_check),
            "invalid_observation_reacquisition_call")
    require(type(max_additional_reads) is int and 0 <= max_additional_reads <= 2,
            "invalid_observation_reacquisition_budget")
    require(type(wait_seconds) in (int, float) and math.isfinite(wait_seconds)
            and 0 < wait_seconds <= .1, "invalid_observation_reacquisition_wait")
    with runtime._mutex:
        require(runtime._observation_reacquisition is None, "nested_observation_reacquisition_rejected")
        scope = None
        summary = {"schema_version": 1, "group_id": uuid.uuid4().hex,
            "max_reads": 1 + max_additional_reads, "wait_seconds": wait_seconds,
            "attempts": [], "additional_reads": 0, "status": "reading"}

        def clear_work():
            require(runtime._journal.get("pending") is None,
                    "unknown_or_pending_request_blocks_new_work")
            require(runtime._journal.get("semantic_pending") is None,
                    "previous_semantic_result_requires_reconciliation")

        def deadline():
            require(deadline_check() is not False, "observation_reacquisition_goal_deadline_exhausted")

        def checkpoint():
            runtime._journal["observation_reacquisition"] = deepcopy(summary)
            # The first attempt also retains the final summary through normal
            # record compaction; replacing the latest summary loses no history.
            if summary["attempts"]:
                first = runtime._journal["records"].get(summary["attempts"][0]["request_id"])
                if first is not None:
                    first["reacquisition_summary"] = deepcopy(summary)
            runtime._save()

        try:
            clear_work()
            deadline()
            session = runtime._session()
            context = runtime._context
            if context is None:
                published = session.get("capability_context", {})
                require(isinstance(published, dict), "observation_reacquisition_context_missing")
                context = tuple(published.get(k) for k in
                    ("world_generation", "dimension", "player_uuid", "action_session"))
            require(len(context) == 4 and all(isinstance(v, str) and v for v in context),
                    "observation_reacquisition_context_missing")
            require(type(session.get("defense_epoch")) is int,
                    "observation_reacquisition_epoch_missing")
            scope = _Enrollment(summary["group_id"], context, session["session_id"],
                session["defense_epoch"], summary["max_reads"], runtime._last_tick)
            runtime._observation_reacquisition = scope
            checkpoint()
            for attempt in range(1, scope.max_reads + 1):
                clear_work()
                deadline()
                _validate_session(runtime, runtime._session())
                scope.attempt, scope.active_request_id = attempt, None
                failure = None
                try:
                    observation = read_callable()
                except SkillError as error:
                    failure = error
                    rid = error.request_id or scope.active_request_id
                    summary["attempts"].append({"attempt": attempt, "request_id": rid,
                        "status": error.status, "reason": error.reason,
                        "eligible_unavailable": _eligible_exception(runtime, error)})
                else:
                    require(isinstance(observation, Observation)
                            and observation.request_id == scope.active_request_id,
                            "observation_reacquisition_requires_one_observe")
                    summary["attempts"].append({"attempt": attempt, "request_id": observation.request_id,
                        "status": "succeeded", "reason": "fresh_observation", "eligible_unavailable": False})
                summary["additional_reads"] = attempt - 1
                checkpoint()
                # Preserve exact unknown/read failure identities. Checking the
                # pending slot first would mask unknown as an ordinary block.
                if failure is not None and not _eligible_exception(runtime, failure):
                    raise failure
                deadline()
                clear_work()
                if failure is None:
                    _frame_identity(runtime, observation.state, observation.context, observation.tick,
                                    require_release=attempt > 1)
                    _validate_session(runtime, runtime._session())
                    runtime._fresh(observation, allow_menu=observation.state.get("screen_open") is True)
                    summary.update(status="succeeded", reason="fresh_observation")
                    checkpoint()
                    return observation
                if attempt == scope.max_reads:
                    raise failure
                deadline()
                runtime.sleeper(wait_seconds)
                deadline()
            raise AssertionError("bounded observation acquisition fell through")
        except BaseException as error:
            runtime._preflight_request_id = None
            reason = error.reason if isinstance(error, SkillError) else "observation_reacquisition_error:" + type(error).__name__
            status = error.status if isinstance(error, SkillError) else ("unknown" if runtime.pending_request_id else "blocked")
            summary.update(status=status, reason=reason)
            latch = getattr(runtime, "_latch", None)
            if callable(latch):
                latch(reason, status)
            checkpoint()
            raise
        finally:
            runtime._observation_reacquisition = None

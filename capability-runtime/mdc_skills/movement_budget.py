"""Opt-in, single-attempt native self-walk meter over the ordinary action route.

This module never starts a process or retries an action. Native measurements,
not coordinates sampled by Python, are the distance authority. A budget is
permanently bound to its original case and native session. Use an ordinary
Runtime when this narrow dry-flat noncombat acceptance contract is not wanted.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, replace
import math
import re

from .core import Runtime, Outcome, SkillError, require


@dataclass(frozen=True)
class MovementBudgetBinding:
    bundle_id: str
    action_session: str
    world_generation: str
    dimension: str
    player_uuid: str
    max_distance: float
    arm_origin: tuple[float, float, float] | None = None


class MovementBudgetRuntime(Runtime):
    """Runtime-compatible native meter, with explicit start() and finish().

    Call start once, execute the approved skills and neutral cleanup using this
    same instance, then finish once. Both lifecycle calls return ordinary
    Outcomes with exact request identities and two later semantic samples.
    A closed/restarted instance cannot resume or rearm the original case.
    """
    MODE = "dry_flat_self_walk_v1"
    METRIC = "client_self_move_polyline"
    LIFECYCLE = frozenset({"movement_budget_start", "movement_budget_finish"})

    def __init__(self, client, journal_directory, *, bundle_id, max_distance=32, **kwargs):
        require(isinstance(bundle_id, str) and 0 < len(bundle_id) <= 128
                and bundle_id.strip() == bundle_id, "invalid_movement_budget_bundle_id")
        require(type(max_distance) in (int, float) and math.isfinite(max_distance)
                and max_distance == 32, "movement_budget_requires_32_block_limit")
        require(kwargs.get("required_execution_policy", "noncombat") == "noncombat",
                "movement_budget_requires_noncombat_policy")
        kwargs["required_execution_policy"] = "noncombat"
        self._bundle_id = bundle_id
        self._max_distance = int(max_distance)
        self._binding = None
        self._budget_phase = "new"
        self._budget_failure = None
        self._budget_failure_status = "blocked"
        self._meter = None
        self._meter_tick = None
        self._dispatch_lifecycle = None
        self._native_lifecycle_seen = False
        super().__init__(client, journal_directory, **kwargs)
        if "movement_budget" in self._journal:
            super().close()
            raise SkillError("movement_budget_original_case_cannot_restart")

    @property
    def binding(self):
        return self._binding

    @property
    def movement_budget(self):
        return deepcopy(self._meter)

    @property
    def budget_failed(self):
        return self._budget_failure is not None

    @property
    def failure_reason(self):
        return self._budget_failure

    def _budget_checkpoint(self):
        self._journal["movement_budget"] = {
            "schema_version": 1, "bundle_id": self._bundle_id,
            "phase": self._budget_phase,
            "binding": asdict(self._binding) if self._binding else None,
            "failure_reason": self._budget_failure,
            "failure_status": self._budget_failure_status,
            "last_meter": deepcopy(self._meter),
        }
        self._save()

    def _latch(self, reason, status="blocked"):
        if self._budget_failure is None:
            self._budget_failure, self._budget_failure_status = reason, status
            if hasattr(self, "_journal") and self._budget_phase != "new":
                self._budget_checkpoint()

    def _healthy(self):
        if self._budget_failure is not None:
            raise SkillError(self._budget_failure, status=self._budget_failure_status)

    def _session(self, *, idle=True):
        try:
            return super()._session(idle=idle)
        except SkillError as exc:
            if self._budget_phase != "new":
                self._latch(exc.reason, exc.status)
            raise

    def _check_meter(self, state, *, update=False):
        meter = state.get("movement_budget")
        # An unarmed native process is the only valid starting point. Missing
        # meter support is refused, rather than silently making a Python meter.
        if self._binding is None or (self._budget_phase == "starting" and not self._native_lifecycle_seen):
            require(isinstance(meter, dict) and type(meter.get("schema_version")) is int
                    and meter["schema_version"] == 1, "native_movement_budget_missing")
            require(meter.get("status") == "unarmed", "movement_budget_already_started_or_unavailable")
            require(meter.get("position_hook_seen") is True and meter.get("move_hook_seen") is True,
                    "movement_budget_hooks_unverified")
            return meter
        require(isinstance(meter, dict), "native_movement_budget_missing")
        require(type(meter.get("schema_version")) is int and meter["schema_version"] == 1,
                "native_movement_budget_schema_invalid")
        binding = self._binding
        expected = {"bundle_id": binding.bundle_id, "action_session": binding.action_session,
                    "world_generation": binding.world_generation, "player_uuid": binding.player_uuid,
                    "max_distance": binding.max_distance}
        require(all(meter.get(k) == v for k, v in expected.items()), "movement_budget_binding_changed")
        require(meter.get("metric") == self.METRIC and meter.get("mode") == self.MODE,
                "movement_budget_metric_or_mode_changed")
        origin = meter.get("arm_origin")
        require(isinstance(origin, dict) and set(origin) == {"x", "y", "z"}
                and all(type(origin[k]) in (int, float) and math.isfinite(origin[k]) for k in ("x", "y", "z")),
                "movement_budget_arm_origin_invalid")
        origin = tuple(origin[k] for k in ("x", "y", "z"))
        require(binding.arm_origin is None or origin == binding.arm_origin,
                "movement_budget_arm_origin_changed")
        require(meter.get("coverage_complete") is True, "movement_budget_coverage_incomplete")
        require(meter.get("moving_accepted") is True, "movement_budget_motion_not_accepted")
        require(meter.get("covers_armed_interval_only") is True and meter.get("no_reset") is True
                and meter.get("all_cause_physical_cap") is False, "movement_budget_coverage_contract_changed")
        for key in ("position_mutations", "boundary_samples"):
            require(type(meter.get(key)) is int and meter[key] >= 0, "movement_budget_counter_invalid")
        require(type(meter.get("settled_ticks")) is int and 0 <= meter["settled_ticks"] <= 3,
                "movement_budget_settled_ticks_invalid")
        require(isinstance(meter.get("started_nano"), str)
                and re.fullmatch(r"-?[0-9]{1,20}", meter["started_nano"])
                and -(2**63) <= int(meter["started_nano"]) < 2**63, "movement_budget_start_time_invalid")
        for key in ("actual_distance", "remaining_distance", "max_distance", "stop_reserve"):
            require(type(meter.get(key)) in (int, float) and math.isfinite(meter[key]),
                    "movement_budget_distance_invalid")
        require(meter["max_distance"] == 32 and meter["stop_reserve"] == 2,
                "movement_budget_limit_or_reserve_changed")
        distance, remaining = meter["actual_distance"], meter["remaining_distance"]
        require(0 <= distance <= 32 and 0 <= remaining <= 32
                and abs(remaining - (32 - distance)) <= 1e-7,
                "movement_budget_distance_or_remaining_invalid")
        expected_status = "sealed" if self._budget_phase == "finished" or (
            self._budget_phase == "finishing" and self._native_lifecycle_seen) else "armed"
        require(meter.get("status") == expected_status, "movement_budget_not_" + expected_status)
        require(isinstance(meter.get("reason"), str), "movement_budget_reason_missing")
        if expected_status == "sealed":
            require(meter.get("reason") == "movement_budget_sealed", "movement_budget_seal_reason_invalid")
            require(meter["settled_ticks"] == 3 and isinstance(meter.get("ended_nano"), str)
                    and re.fullmatch(r"-?[0-9]{1,20}", meter["ended_nano"])
                    and int(meter["started_nano"]) <= int(meter["ended_nano"]) < 2**63,
                    "movement_budget_seal_not_settled")
        else:
            require(distance < 32 - meter["stop_reserve"], "movement_budget_reserve_not_enforced")
            require(meter.get("ended_nano") is None, "movement_budget_end_time_premature")
        tick = state.get("world", {}).get("game_time")
        require(type(tick) is int and tick >= 0, "movement_budget_sample_tick_invalid")
        if self._meter is not None:
            # All supported callers consume fresh preflights and chronological
            # receipt/live snapshots. Historical surveys have a separate API.
            # Never accept an older tick or rewind the authoritative baseline.
            require(self._meter_tick is not None and tick >= self._meter_tick,
                    "movement_budget_sample_tick_regressed")
            require(distance >= self._meter["actual_distance"], "movement_budget_distance_regressed")
            require(meter["started_nano"] == self._meter["started_nano"], "movement_budget_start_time_changed")
            require(all(meter[k] >= self._meter[k] for k in ("position_mutations", "boundary_samples")),
                    "movement_budget_counter_regressed")
            require((distance > self._meter["actual_distance"]) ==
                    (meter["position_mutations"] > self._meter["position_mutations"]),
                    "movement_budget_mutation_distance_disagrees")
            if self._meter.get("status") == "sealed":
                require(meter == self._meter, "movement_budget_sealed_snapshot_changed")
        if update:
            if self._binding.arm_origin is None:
                self._binding = replace(self._binding, arm_origin=origin)
            self._meter, self._meter_tick = deepcopy(meter), tick
        return meter

    def _validate_state(self, payload, **kwargs):
        try:
            self._healthy()
            state, context, tick = super()._validate_state(payload, **kwargs)
            self._check_meter(state)
            return state, context, tick
        except SkillError as exc:
            if self._budget_phase != "new":
                status = "unknown" if self._binding is not None and exc.reason.startswith(("movement_budget_", "native_movement_budget_")) else exc.status
                self._latch(exc.reason, status)
                raise SkillError(exc.reason, status=status, request_id=exc.request_id) from None
            raise

    def _make_observation(self, *args, **kwargs):
        observation = super()._make_observation(*args, **kwargs)
        self._check_meter(observation.state, update=self._binding is not None and not (self._budget_phase == "starting" and not self._native_lifecycle_seen))
        return observation

    def _compile(self, command, before, session):
        self._healthy()
        name = command.get("action") if isinstance(command, dict) else None
        if name in self.LIFECYCLE:
            require(name == self._dispatch_lifecycle, "movement_budget_lifecycle_requires_explicit_method")
        else:
            require(self._budget_phase == "active", "movement_budget_not_started_or_already_finished")
            require("movement_budget" not in command, "movement_budget_rearm_rejected")
        require(self._binding is not None, "movement_budget_binding_missing")
        require(before.context == (self._binding.world_generation, self._binding.dimension,
                                   self._binding.player_uuid, self._binding.action_session),
                "movement_budget_original_context_changed")
        body = deepcopy(command)
        require("movement_budget_bundle_id" not in body or body["movement_budget_bundle_id"] == self._bundle_id,
                "movement_budget_bundle_id_conflict")
        if name == "movement_budget_start":
            require("movement_budget_bundle_id" not in body, "movement_budget_start_binding_conflict")
        else:
            body["movement_budget_bundle_id"] = self._bundle_id
        return super()._compile(body, before, session)

    def _native_receipt(self, record, result, before):
        native = super()._native_receipt(record, result, before)
        if record["command"]["action"] in self.LIFECYCLE and native["status"] == "succeeded":
            self._native_lifecycle_seen = True
        try:
            lifecycle = record["command"]["action"]
            if lifecycle in self.LIFECYCLE and native["status"] == "succeeded":
                reason = "movement_budget_started" if lifecycle == "movement_budget_start" else "movement_budget_sealed"
                require(native.get("reason") == reason, "movement_budget_lifecycle_receipt_reason_invalid")
            state = result.get("result", {}).get("state")
            require(isinstance(state, dict), "movement_budget_receipt_state_missing")
            for value in (native.get("result", {}).get("movement_budget"), native.get("movement_budget")):
                self._check_meter({"movement_budget": value, "world": {"game_time": before.tick}}, update=True)
            context = (state.get("world", {}).get("world_generation"), state.get("world", {}).get("dimension"),
                       state.get("player", {}).get("uuid"), state.get("client_action", {}).get("action_session"))
            require(context == before.context, "movement_budget_receipt_context_changed")
            super()._validate_state({"state": state}, allow_menu=True, context=before.context)
            require(state["world"]["game_time"] >= before.tick, "movement_budget_receipt_tick_regressed")
            require(state["client_action"].get("action_id") == native["action_id"],
                    "movement_budget_receipt_action_replaced")
            self._check_meter(state, update=True)
        except SkillError as exc:
            self._latch(exc.reason, "unknown")
            self._unknown(record, exc.reason)
        return native

    def execute(self, skill, command, verify, **kwargs):
        with self._mutex:
            try:
                self._healthy()
                require(self._budget_phase == "active", "movement_budget_not_started_or_already_finished")
                require(isinstance(command, dict) and command.get("action") not in self.LIFECYCLE,
                        "movement_budget_lifecycle_requires_explicit_method")
            except SkillError as exc:
                if self._budget_phase == "active":
                    self._latch(exc.reason, exc.status)
                return Outcome(exc.status, exc.reason, evidence={"server_confirmed": False}, last_observation=self._last)
            outcome = super().execute(skill, command, verify, **kwargs)
            if not outcome.ok:
                self._latch(outcome.reason, outcome.status)
            return outcome

    def start_command(self):
        """Fresh copy of the semantic action, before ordinary native bindings."""
        return {"op": "action", "action": "movement_budget_start", "timeout_ms": 3000,
                "movement_budget": {"schema_version": 1, "bundle_id": self._bundle_id,
                                    "max_distance": self._max_distance, "mode": self.MODE}}

    def finish_command(self):
        """Fresh copy of the semantic action, before ordinary native bindings."""
        return {"op": "action", "action": "movement_budget_finish", "timeout_ms": 3000,
                "movement_budget_bundle_id": self._bundle_id}

    def start(self, *, before=None):
        with self._mutex:
            try:
                self._healthy()
                require(self._budget_phase == "new", "movement_budget_start_already_attempted")
                self._budget_phase = "starting"
                self._budget_checkpoint()  # Single attempt survives interruption before dispatch.
                before = self.observe() if before is None else before
                self._fresh(before)
                self._binding = MovementBudgetBinding(self._bundle_id, before.context[3], before.context[0],
                    before.context[1], before.context[2], self._max_distance)
                self._budget_checkpoint()
                self._dispatch_lifecycle = "movement_budget_start"
                self._native_lifecycle_seen = False
                outcome = super().execute("movement_budget_start", self.start_command(),
                    lambda old, new: new.state["movement_budget"]["status"] == "armed",
                    before=before)
                if outcome.ok:
                    self._budget_phase = "active"
                    self._budget_checkpoint()
                else:
                    self._latch(outcome.reason, outcome.status)
                return outcome
            except SkillError as exc:
                self._latch(exc.reason, exc.status)
                return Outcome(exc.status, exc.reason, evidence={"server_confirmed": False}, last_observation=self._last)
            finally:
                self._dispatch_lifecycle = None

    def finish(self, *, before=None):
        with self._mutex:
            try:
                self._healthy()
                require(self._budget_phase == "active", "movement_budget_not_active_or_finish_already_attempted")
                before = self.observe(allow_menu=True) if before is None else before
                self._fresh(before, allow_menu=True)
                self._budget_phase = "finishing"
                self._native_lifecycle_seen = False
                self._budget_checkpoint()
                for _ in range(16):
                    if before.state["movement_budget"]["settled_ticks"] == 3:
                        break
                    self.sleeper(.05)
                    before = self.observe(allow_menu=True)
                require(before.state["movement_budget"]["settled_ticks"] == 3,
                        "movement_budget_finish_not_settled")
                self._dispatch_lifecycle = "movement_budget_finish"
                outcome = super().execute("movement_budget_finish", self.finish_command(),
                    lambda old, new: new.state["movement_budget"]["status"] == "sealed",
                    before=before, allow_menu=True)
                if outcome.ok:
                    self._budget_phase = "finished"
                    self._budget_checkpoint()
                else:
                    self._latch(outcome.reason, outcome.status)
                return outcome
            except SkillError as exc:
                self._latch(exc.reason, exc.status)
                return Outcome(exc.status, exc.reason, evidence={"server_confirmed": False}, last_observation=self._last)
            finally:
                self._dispatch_lifecycle = None

    def observe(self, *args, **kwargs):
        try:
            self._healthy()
            return super().observe(*args, **kwargs)
        except SkillError as exc:
            from .observation_reacquisition import _eligible_exception
            if self._budget_phase != "new" and not _eligible_exception(self, exc):
                self._latch(exc.reason, exc.status)
            raise

    def survey(self, *args, **kwargs):
        self._healthy()
        try:
            result = super().survey(*args, **kwargs)
            self._check_meter(result.state, update=self._binding is not None and not (self._budget_phase == "starting" and not self._native_lifecycle_seen))
            return result
        except SkillError as exc:
            if self._budget_phase != "new":
                self._latch(exc.reason, exc.status)
            raise

    def result(self, *args, **kwargs):
        self._healthy()
        require(self._budget_phase in ("active", "finished"), "movement_budget_not_started")
        return super().result(*args, **kwargs)

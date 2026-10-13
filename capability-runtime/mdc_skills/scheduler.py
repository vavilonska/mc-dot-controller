"""Bounded dependency-based skill scheduling and provenance-preserving memory.

Goals are data, never Python/code/commands. The caller explicitly advances one
skill at a time. Restart freezes incomplete work for revalidation; deadlines,
action reservations and completed goal identities are never reset by resume.
"""
from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass
import json
import hashlib
import os
import math
from pathlib import Path
import re
import time

from .core import Observation, Outcome, SkillError, atomic_write, require

ID = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")


@dataclass(frozen=True)
class SkillSpec:
    name: str
    run: object
    validate: object
    satisfied: object = None
    description: str = ""


class Registry:
    def __init__(self):
        self._skills = {}

    def register(self, spec):
        require(isinstance(spec, SkillSpec) and ID.fullmatch(spec.name) is not None
                and callable(spec.run) and callable(spec.validate)
                and (spec.satisfied is None or callable(spec.satisfied)), "invalid_skill_spec")
        require(spec.name not in self._skills, "skill_already_registered")
        self._skills[spec.name] = spec

    def get(self, name):
        require(name in self._skills, "unknown_skill")
        return self._skills[name]

    def describe(self):
        return tuple({"name": s.name, "description": s.description,
                      "resume_revalidation": s.satisfied is not None} for s in self._skills.values())


class _BoundedRuntime:
    def __init__(self, runtime, goal, scheduler):
        self._runtime, self._goal, self._scheduler = runtime, goal, scheduler

    def __getattr__(self, name):
        return getattr(self._runtime, name)

    def _check(self):
        require(self._scheduler._time() < self._goal["deadline_unix"], "goal_deadline_exceeded")
        require(self._goal["state"] == "running", "goal_not_running")

    def observe(self, *args, **kwargs):
        self._check()
        value = self._runtime.observe(*args, **kwargs)
        self._check()
        return value

    def survey(self, *args, **kwargs):
        self._check()
        value = self._runtime.survey(*args, **kwargs)
        self._check()
        return value

    def result(self, *args, **kwargs):
        self._check()
        return self._runtime.result(*args, **kwargs)

    def sleeper(self, seconds):
        self._check()
        left = self._goal["deadline_unix"] - self._scheduler._time()
        self._runtime.sleeper(min(seconds, left))
        self._check()

    def effective_remaining_budget(self):
        self._check()
        return {"remaining_actions": self._goal["max_actions"] - self._goal["actions_reserved"],
                "deadline_unix": self._goal["deadline_unix"],
                "remaining_seconds": self._goal["deadline_unix"] - self._scheduler._time()}

    def execute(self, skill, command, verify, **kwargs):
        self._check()
        require(self._goal["actions_reserved"] < self._goal["max_actions"], "goal_action_budget_exhausted")
        remaining_ms = int((self._goal["deadline_unix"] - self._scheduler._time()) * 1000)
        require(remaining_ms >= command.get("timeout_ms", 15000), "action_exceeds_remaining_goal_deadline")
        # Reserve before entering the transport, including blocked/ambiguous calls.
        self._goal["actions_reserved"] += 1
        self._scheduler._save()
        outcome = self._runtime.execute(skill, command, verify, **kwargs)
        self._goal["request_ids"] = list(dict.fromkeys(self._goal["request_ids"] + list(outcome.request_ids)))
        self._scheduler._save()
        return outcome


class _RevalidationRuntime(_BoundedRuntime):
    def _check(self):
        self._runtime._open()
        require(self._scheduler._time()<self._goal['deadline_unix'],'original_goal_deadline_expired')
        require(self._goal['state'] in ('interrupted','blocked','failed','unknown'),'goal_not_resumable')

    def execute(self,*args,**kwargs):
        raise SkillError('resume_revalidation_is_read_only')


class Scheduler:
    def __init__(self, runtime, registry, *, wall_clock=time.time):
        require(isinstance(registry, Registry), "skill_registry_required")
        self.runtime, self.registry, self.wall_clock = runtime, registry, wall_clock
        self.path = runtime.journal_directory / "goals.json"
        self._data = {"schema_version": 1, "goals": {}}
        with runtime._mutex:
            runtime._open()
            if self.path.exists():
                require(not self.path.is_symlink(), "goal_checkpoint_symlink_rejected")
                require(self.path.stat().st_size <= 8 * 1024 * 1024, "goal_checkpoint_too_large")
                self._data = json.loads(self.path.read_text())
                require(self._data.get("schema_version") == 1 and isinstance(self._data.get("goals"), dict),
                        "invalid_goal_checkpoint")
                for goal in self._data["goals"].values():
                    self._arguments(goal)  # Verify imported content before any resume.
                    if goal["state"] in ("running", "ready", "waiting"):
                        goal.update(state="interrupted", reason="restart_requires_explicit_revalidation")
                self._save()

    def _arguments(self, goal):
        ref = goal.get("arguments_ref")
        if ref is None:
            require(isinstance(goal.get("arguments"), dict), "invalid_goal_arguments")
            return deepcopy(goal["arguments"])
        require(isinstance(ref, dict) and isinstance(ref.get("sha256"), str)
                and re.fullmatch(r"[0-9a-f]{64}", ref["sha256"])
                and ref.get("file") == "goal-input-" + ref["sha256"] + ".json"
                and type(ref.get("bytes")) is int and 0 < ref["bytes"] <= 4 * 1024 * 1024,
                "invalid_goal_input_reference")
        path = self.runtime.journal_directory / ref["file"]
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, "rb") as stream:
                raw = stream.read(4 * 1024 * 1024 + 1)
            require(len(raw) == ref["bytes"] and hashlib.sha256(raw).hexdigest() == ref["sha256"],
                    "goal_input_hash_mismatch")
            arguments = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            require(isinstance(arguments, dict), "invalid_goal_arguments")
            return arguments
        except SkillError:
            raise
        except (OSError, ValueError):
            raise SkillError("goal_input_missing_or_invalid") from None

    def _time(self):
        now = self.wall_clock()
        require(type(now) in (int, float) and math.isfinite(now), "invalid_goal_clock")
        previous = self._data.get("last_wall_clock")
        require(previous is None or now >= previous, "goal_clock_regressed")
        self._data["last_wall_clock"] = now
        return now

    def _save(self):
        atomic_write(self.path, self._data)

    def add(self, goal_id, skill, arguments, *, dependencies=(), priority=0, max_actions=32, deadline_seconds=300):
        with self.runtime._mutex:
            self.runtime._open()
            require(isinstance(goal_id, str) and ID.fullmatch(goal_id), "invalid_goal_id")
            require(goal_id not in self._data["goals"], "goal_id_already_consumed")
            require(len(self._data["goals"]) < 256, "goal_capacity_exhausted")
            spec = self.registry.get(skill)
            require(isinstance(arguments, dict), "goal_arguments_required")
            args = deepcopy(arguments)
            raw_args = json.dumps(args, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
            require(len(raw_args) <= 4 * 1024 * 1024, "goal_arguments_too_large")
            validated = spec.validate(args)
            require(validated is not False, "goal_arguments_invalid")
            require(isinstance(dependencies, (tuple, list)) and len(dependencies) <= 16
                    and len(set(dependencies)) == len(dependencies)
                    and all(d in self._data["goals"] for d in dependencies), "invalid_goal_dependencies")
            require(type(priority) is int and -100 <= priority <= 100
                    and type(max_actions) is int and 1 <= max_actions <= 32768,
                    "invalid_goal_budget_or_priority")
            require(type(deadline_seconds) in (int, float) and math.isfinite(deadline_seconds)
                    and 1 <= deadline_seconds <= 86400, "invalid_goal_deadline")
            args_ref = None
            if len(raw_args) > 32000:
                digest = hashlib.sha256(raw_args).hexdigest()
                filename = "goal-input-" + digest + ".json"
                atomic_write(self.runtime.journal_directory / filename, args)
                args_ref = {"file": filename, "sha256": digest, "bytes": len(raw_args)}
            now = self._time()
            self._data["goals"][goal_id] = {"goal_id": goal_id, "skill": skill, "arguments": args if args_ref is None else None,
                "arguments_ref": args_ref,
                "dependencies": list(dependencies), "priority": priority, "max_actions": max_actions,
                "actions_reserved": 0, "created_unix": now, "deadline_unix": now + deadline_seconds,
                "state": "waiting" if dependencies else "ready", "reason": "new_goal", "attempts": 0,
                "request_ids": [], "evidence": {}}
            self._save()
            return self.status(goal_id)

    def status(self, goal_id=None):
        with self.runtime._mutex:
            if goal_id is None:
                return deepcopy(list(self._data["goals"].values()))
            require(goal_id in self._data["goals"], "goal_unknown")
            return deepcopy(self._data["goals"][goal_id])

    def advance(self):
        """Choose one eligible goal, run one bounded capability, then return."""
        with self.runtime._mutex:
            self.runtime._open()
            require(not self.runtime.has_unresolved_execution, "unresolved_execution_blocks_scheduler")
            choices = []
            for goal in self._data["goals"].values():
                if goal["state"] not in ("ready", "waiting"):
                    continue
                if self._time() >= goal["deadline_unix"]:
                    goal.update(state="blocked", reason="goal_deadline_exceeded")
                    continue
                dep_states = [self._data["goals"][d]["state"] for d in goal["dependencies"]]
                if any(s in ("failed", "blocked", "cancelled", "interrupted", "unknown") for s in dep_states):
                    goal.update(state="blocked", reason="dependency_not_succeeded")
                    continue
                if all(s == "succeeded" for s in dep_states):
                    choices.append(goal)
            self._save()
            if not choices:
                return Outcome("blocked", "no_runnable_goal")
            goal = min(choices, key=lambda g: (-g["priority"], g["created_unix"], g["goal_id"]))
            spec = self.registry.get(goal["skill"])
            goal.update(state="running", reason="capability_running", attempts=goal["attempts"] + 1)
            self._save()
            try:
                result = spec.run(_BoundedRuntime(self.runtime, goal, self), **self._arguments(goal))
                require(isinstance(result, Outcome), "skill_must_return_evidence_outcome")
                if result.ok:
                    require(self._time() < goal["deadline_unix"], "goal_deadline_exceeded")
                    require(not self.runtime.has_unresolved_execution, "unresolved_execution_blocks_success")
                    self.runtime._fresh(result.last_observation, allow_menu=True)
                    require(result.evidence.get("server_confirmed") is False
                            and result.last_observation is not None, "skill_success_requires_real_observation")
            except SkillError as exc:
                result = Outcome(exc.status, exc.reason, (exc.request_id,) if exc.request_id else ())
            except Exception as exc:
                result = Outcome("unknown" if self.runtime.pending_request_id else "blocked",
                                 "skill_exception:" + type(exc).__name__)
            goal.update(state=result.status, reason=result.reason,
                        request_ids=list(dict.fromkeys(goal["request_ids"] + list(result.request_ids))), evidence=deepcopy(result.evidence))
            self._save()
            return result

    def cancel(self, goal_id):
        """Cancel queued work only. It cannot cancel a native/unknown action."""
        with self.runtime._mutex:
            goal = self._data["goals"].get(goal_id)
            require(goal is not None, "goal_unknown")
            require(goal["state"] not in ("running", "unknown"), "native_cancellation_requires_exact_owner_protocol")
            require(goal["state"] != "succeeded", "completed_goal_is_immutable")
            goal.update(state="cancelled", reason="caller_cancelled_queued_goal")
            self._save()

    def resume(self, goal_id):
        """Explicit caller resume. Fresh semantic check precedes any renewed work.

        This does not retry unknown actions, resurrect expired goals, refund action
        budgets or rerun a skill lacking an explicit safe revalidation predicate.
        """
        with self.runtime._mutex:
            self.runtime._open()
            require(not self.runtime.has_unresolved_execution, "reconcile_original_request_first")
            goal = self._data["goals"].get(goal_id)
            require(goal is not None and goal["state"] in ("interrupted", "blocked", "failed", "unknown"),
                    "goal_not_resumable")
            require(self._time() < goal["deadline_unix"], "original_goal_deadline_expired")
            spec = self.registry.get(goal["skill"])
            require(spec.satisfied is not None, "skill_requires_manual_replanning")
            result = spec.satisfied(_RevalidationRuntime(self.runtime,goal,self), **self._arguments(goal))
            require(isinstance(result, Outcome), "revalidation_requires_evidence_outcome")
            require(self._time()<goal['deadline_unix'],'original_goal_deadline_expired')
            require(not self.runtime.has_unresolved_execution,'unresolved_execution_blocks_revalidation')
            if result.ok:
                require(result.last_observation is not None and result.evidence.get("server_confirmed") is False,
                        "revalidation_success_requires_observation")
                self.runtime._fresh(result.last_observation,allow_menu=True)
                goal.update(state="succeeded", reason="goal_confirmed_after_interruption",
                            request_ids=list(dict.fromkeys(goal["request_ids"] + list(result.request_ids))), evidence=deepcopy(result.evidence))
            else:
                # A predicate must explicitly prove the goal remains unmet and
                # that re-entry is safe; ordinary blocked/unknown is insufficient.
                require(result.evidence.get("safe_to_replan") is True
                        and result.evidence.get("goal_unmet") is True
                        and result.last_observation is not None, "revalidation_did_not_authorize_safe_replanning")
                self.runtime._fresh(result.last_observation,allow_menu=True)
                require(goal["actions_reserved"] < goal["max_actions"], "original_action_budget_exhausted")
                goal.update(state="waiting" if goal["dependencies"] else "ready", reason="fresh_replanning_required")
            self._save()
            return self.status(goal_id)


class KnowledgeStore:
    """Historical semantic hints. Records never become fresh action evidence."""
    def __init__(self, runtime):
        self.runtime = runtime
        self.path = runtime.journal_directory / "knowledge.json"
        self._records = {}
        if self.path.exists():
            require(not self.path.is_symlink() and self.path.stat().st_size <= 8 * 1024 * 1024,
                    "invalid_knowledge_checkpoint")
            data = json.loads(self.path.read_text())
            require(data.get("schema_version") == 1 and isinstance(data.get("records"), dict),
                    "invalid_knowledge_checkpoint")
            self._records = data["records"]

    def remember(self, key, observation, *, kind, value):
        with self.runtime._mutex:
            require(isinstance(key, str) and ID.fullmatch(key), "invalid_memory_key")
            require(kind in ("landmark", "resource", "workstation", "hazard", "portal", "build_progress"),
                    "unsupported_knowledge_kind")
            require(isinstance(observation, Observation) and observation._owner == self.runtime._owner,
                    "original_observation_required")
            self.runtime._fresh(observation, allow_menu=True)
            require(isinstance(value, dict) and len(json.dumps(value, allow_nan=False)) <= 8192,
                    "bounded_semantic_value_required")
            require(key in self._records or len(self._records) < 128, "knowledge_capacity_exhausted")
            self._records[key] = {"kind": kind, "value": deepcopy(value), "context": list(observation.context),
                "source_tick": observation.tick, "source_request_id": observation.request_id,
                "source_capture_monotonic": observation.captured_at, "capture_epoch": self.runtime._owner,
                "historical_only": True, "action_evidence": False}
            atomic_write(self.path, {"schema_version": 1, "records": self._records})

    def recall(self, key, *, context=None):
        with self.runtime._mutex:
            record = deepcopy(self._records.get(key))
            if record is None:
                return None
            record["same_context"] = context is not None and tuple(record["context"]) == tuple(context)
            record["requires_fresh_observation"] = True
            return record

"""Compose an explicit versioned blueprint with observed material procurement.

No design is embedded or inferred. Procurement is confined outside the declared
construction volume, and historical survey routes are proposals only. One outer
budget binds every nested material, navigation, placement and verification call.
There is no inventory staging, game startup, automatic recovery or action retry.
"""
from __future__ import annotations

from collections import Counter
import json
import math

from building_controller.model import Pos, PlanError
from .core import Outcome, SkillError, atomic_write, require
from . import building, building_v3, inventory, mobility, production, reach, supply


def _capacity(observation, requirements):
    """Conservative fit of the full bill while preserving all current stacks.

    Every supported vanilla building item stacks to 64. Existing component-bound
    stacks are counted at their actual observed size; an unobserved produced
    stack is never presumed compatible with an existing partial stack. This is
    a necessary preflight, not a guarantee of space for every recipe transient.
    """
    rows = inventory.items(observation)
    require(len(rows) == 36 and {r.get("slot") for r in rows} == set(range(36)),
            "construction_requires_all_36_inventory_slots")
    stock, occupied = Counter(), 0
    for row in rows:
        count, limit = row.get("count"), row.get("max_stack_size")
        require(type(count) is int and type(limit) is int,
                "construction_inventory_stack_capacity_missing")
        if row.get("empty") is True:
            require(count == 0 and limit == 0, "construction_invalid_empty_inventory_slot")
        else:
            require(row.get("empty") is False and isinstance(row.get("id"), str)
                    and row["id"].startswith("minecraft:") and 1 <= count <= limit <= 99,
                    "construction_invalid_observed_inventory_stack")
            occupied += 1
            stock[row["id"]] += count
    missing = {item: count - stock[item] for item, count in requirements.items() if stock[item] < count}
    new_slots = sum(math.ceil(count / 64) for count in missing.values())
    require(occupied + new_slots <= 36,
            "construction_materials_exceed_inventory_capacity_no_staging")
    return {"inventory_slots": 36, "occupied_slots": occupied, "empty_slots": 36 - occupied,
            "additional_slots_required": new_slots, "missing_items": missing,
            "observed_totals": {item: stock[item] for item in requirements},
            "partial_stack_merge_credit": False, "staging_supported": False,
            "transient_recipe_capacity_guaranteed": False}


def _protected_positions(blueprint):
    # Protect undeclared interior emptiness too. A one-cell shell protects
    # supports, cavity boundaries and immediate blockstate/light neighbors.
    low, high = blueprint.region.minimum, blueprint.region.maximum
    require((high.x - low.x + 3) * (high.y - low.y + 3) * (high.z - low.z + 3) <= 32768,
            "construction_protected_volume_budget_exceeded")
    try:
        protected = {Pos(x, y, z)
            for x in range(low.x - 1, high.x + 2)
            for y in range(low.y - 1, high.y + 2)
            for z in range(low.z - 1, high.z + 2)}
        for point in blueprint.value["access_points"]:
            position = Pos.parse(point)
            protected.update(position.offset(dx, dy, dz)
                for dx in (-1, 0, 1) for dy in (-1, 0, 1, 2) for dz in (-1, 0, 1))
        require(len(protected) <= 32768, "construction_protected_volume_budget_exceeded")
        return frozenset(protected)
    except PlanError as exc:
        raise SkillError("construction_protected_coordinates_invalid:" + str(exc)) from None


def _worksite(survey, protected, *, max_steps):
    """Choose a historical outside stand; movement will replan from fresh scans."""
    terrain, _ = building_v3._terrain(survey, historical=True)
    start, _, _ = building._geometry(survey)
    routes = building_v3._routes(terrain.cells, start, set(), max_steps)
    candidates = []
    for stand, route in routes.items():
        if stand in protected or stand.offset(y=1) in protected:
            continue
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            target = stand.offset(dx, 0, dz)
            # This proposes an ordinary clear station cell only. The actual
            # station helper independently checks fresh support/entities/state.
            area = (target, target.offset(y=1), target.offset(y=-1))
            if any(pos in protected for pos in area):
                continue
            if (terrain.get(target).kind == terrain.get(target.offset(y=1)).kind == "clear"
                    and terrain.get(target.offset(y=-1)).kind == "solid"):
                candidates.append((len(route), stand))
                break
    require(candidates, "construction_no_observed_outside_procurement_worksite")
    return min(candidates)[1]


class _ConstructionRuntime:
    def __init__(self, runtime, *, timeout_seconds, max_actions, protected, path):
        self._runtime, self.deadline = runtime, runtime.clock() + timeout_seconds
        self.remaining, self.initial_actions = max_actions, max_actions
        self.last_clock, self.context = runtime.clock(), None
        self.protected, self.path, self.procurement = protected, path, True
        self.ids, self.stages, self.last_observation = [], [], None
        self.action_ids, self.checkpoint = [], None
        self.composition_path = path.with_name("construction-" + path.name[len("building-"):])
        require(not self.composition_path.is_symlink(), "construction_progress_symlink_rejected")

    def existing(self, blueprint):
        if not self.composition_path.exists():
            return
        require(self.composition_path.stat().st_size <= 8 * 1024 * 1024,
                "construction_checkpoint_too_large")
        try:
            data = json.loads(self.composition_path.read_text(),
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except (OSError, ValueError) as exc:
            raise SkillError("construction_checkpoint_unreadable:" + type(exc).__name__) from None
        require(isinstance(data, dict) and data.get("schema_version") == 1
                and data.get("blueprint_sha256") == building._digest(blueprint.spec())
                and data.get("context") == list(self.context), "construction_checkpoint_identity_changed")
        previous = data.get("request_ids")
        require(isinstance(previous, list) and all(isinstance(x, str) for x in previous),
                "construction_checkpoint_request_ids_invalid")
        self.ids.extend(previous)
        raise SkillError("construction_started_job_requires_explicit_recovery_no_procurement_replay",
                         status="unknown" if data.get("status") == "unknown" else "blocked")

    def start(self, blueprint, job_id):
        require(not self.composition_path.exists() and not self.composition_path.is_symlink(),
                "construction_existing_composition_blocks_procurement")
        self.checkpoint = {"schema_version": 1, "job_id": job_id,
            "blueprint_sha256": building._digest(blueprint.spec()), "context": list(self.context),
            "status": "in_progress", "original_deadline_monotonic": self.deadline,
            "original_max_actions": self.initial_actions, "pending_admission": None,
            "automatic_resume_supported": False}
        self.save()

    def save(self, **changes):
        if self.checkpoint is not None:
            self.checkpoint.update(changes, request_ids=list(dict.fromkeys(self.action_ids)),
                                   actions_reserved=self.initial_actions - self.remaining)
            atomic_write(self.composition_path, self.checkpoint)

    def __getattr__(self, name):
        return getattr(self._runtime, name)

    def check(self):
        now = self._runtime.clock()
        require(math.isfinite(now) and now >= self.last_clock, "construction_clock_regressed")
        self.last_clock = now
        require(now < self.deadline, "construction_original_deadline_exceeded")
        return self.deadline - now

    def _remember(self, observation):
        if observation is None:
            return
        if self.context is None:
            self.context = observation.context
        require(observation.context == self.context, "construction_context_changed")
        self.last_observation = observation
        self.ids.append(observation.request_id)

    def observe(self, *args, **kwargs):
        self.check()
        value = self._runtime.observe(*args, **kwargs)
        self._remember(value)
        self.check()
        return value

    def survey(self, *args, **kwargs):
        self.check()
        value = self._runtime.survey(*args, **kwargs)
        # A survey identity may be recorded, but is never a final observation.
        require(value.context == self.context, "construction_context_changed")
        self.ids.append(value.request_id)
        self.check()
        return value

    def effective_remaining_budget(self):
        budget = {"remaining_actions": self.remaining, "remaining_seconds": self.check()}
        outer = getattr(self._runtime, "effective_remaining_budget", None)
        if outer is not None:
            original = outer()
            for key in budget:
                budget[key] = min(budget[key], original[key])
        return budget

    def _guard_procurement(self, command):
        require(not self.path.exists() and not self.path.is_symlink(),
                "construction_existing_build_job_blocks_procurement")
        action = command.get("action")
        if action in ("follow_path", "click_slot", "select_hotbar", "close_menu"):
            return
        try:
            if action in ("break_block", "interact_block"):
                affected = {Pos.parse(command["target"])}
            elif action == "place_block":
                support = Pos.parse(command["support"])
                affected = {support, support.offset(*building.FACES[command["face"]])}
                affected.update(Pos.parse(row["position"]) for row in command.get("placement_footprint", []))
            else:
                raise SkillError("construction_unsupported_procurement_mutation")
        except (KeyError, TypeError, PlanError):
            raise SkillError("construction_unbound_procurement_mutation") from None
        require(not affected.intersection(self.protected),
                "construction_procurement_mutation_inside_protected_worksite")

    def execute(self, skill, command, verify, **kwargs):
        left = self.effective_remaining_budget()
        require(left["remaining_actions"] > 0, "construction_original_action_budget_exhausted")
        require(left["remaining_seconds"] >= .05, "construction_original_deadline_exceeded")
        if self.procurement:
            self._guard_procurement(command)
        self.remaining -= 1
        body = dict(command)
        body["timeout_ms"] = min(body.get("timeout_ms", 15000), int(left["remaining_seconds"] * 1000), 60000)
        self.save(pending_admission={"skill": skill, "action": body.get("action")})
        outcome = self._runtime.execute(skill, body, verify, **kwargs)
        self.ids.extend(outcome.request_ids)
        self.action_ids.extend(outcome.request_ids)
        self.save(status="in_progress" if outcome.ok else outcome.status,
                  pending_admission=None if outcome.ok else self.checkpoint.get("pending_admission"),
                  last_action_reason=outcome.reason)
        if outcome.ok:
            self._remember(outcome.last_observation)
        # Preserve a terminal/unknown response even if the action finishes late.
        # Every subsequent action/observation/result must pass the same deadline.
        return outcome

    def sleeper(self, seconds):
        self._runtime.sleeper(min(seconds, self.check()))
        self.check()

    def result(self, *args, **kwargs):
        self.check()
        outcome = self._runtime.result(*args, **kwargs)
        self.ids.extend(outcome.request_ids)
        self._remember(outcome.last_observation)
        return outcome

    def accept(self, stage, outcome):
        self.ids.extend(outcome.request_ids)
        self.stages.append({"stage": stage, "status": outcome.status, "reason": outcome.reason,
                            "request_ids": list(outcome.request_ids)})
        observation = self._runtime.require_success(outcome)
        self._remember(observation)
        self.check()
        return observation


def build_with_materials(runtime, blueprint, *, job_id, max_actions=32768,
                         timeout_seconds=3600, max_nodes=512, max_blocks=1024,
                         max_batches=1024, max_search_steps=128, max_walk_distance=2048,
                         max_placements=8192, max_moves=8192, max_steps=64, hotbar_slot=0):
    """Acquire the explicit full item bill, return to anchor, then execute build.

    An existing build checkpoint is deliberately blocked before procurement,
    including a completed checkpoint. Use the separate build/reconcile entry
    points to inspect or continue it without repeating material acquisition.
    """
    blueprint = building_v3.VersionedBlueprint.parse(blueprint)
    require(type(max_actions) is int and 1 <= max_actions <= 32768, "invalid_construction_action_budget")
    require(type(timeout_seconds) in (int, float) and math.isfinite(timeout_seconds)
            and 1 <= timeout_seconds <= 86400, "invalid_construction_deadline")
    require(all(type(x) is int and 1 <= x <= 1024 for x in (max_nodes, max_blocks, max_batches)),
            "invalid_construction_supply_budgets")
    require(type(max_search_steps) is int and 0 <= max_search_steps <= 512
            and type(max_walk_distance) is int and 0 <= max_walk_distance <= 8192,
            "invalid_construction_search_budgets")
    require(type(max_placements) is int and 1 <= max_placements <= 8192
            and type(max_moves) is int and 0 <= max_moves <= 8192
            and type(max_steps) is int and 1 <= max_steps <= 64
            and type(hotbar_slot) is int and 0 <= hotbar_slot <= 8,
            "invalid_construction_build_budgets")
    path = building._path(runtime, job_id)
    protected = _protected_positions(blueprint)
    bounded = _ConstructionRuntime(runtime, timeout_seconds=timeout_seconds,
        max_actions=max_actions, protected=protected, path=path)
    bill = building_v3.material_requirements(blueprint)
    evidence = {"job_id": job_id, "blueprint_identity": bill["blueprint_identity"],
                "material_bill": bill, "staging_supported": False,
                "protected_positions": len(protected), "server_confirmed": False}
    try:
        if getattr(runtime, "has_unresolved_execution", False):
            pending = getattr(runtime, "pending_request_id", None)
            if pending:
                bounded.ids.append(pending)
            raise SkillError("construction_unresolved_execution_requires_read_only_reconciliation", status="unknown")
        first = bounded.observe(allow_menu=True)
        if path.exists():
            progress = building_v3._load(path, blueprint, first)
            pending = progress.get("pending")
            if isinstance(pending, dict):
                bounded.ids.extend(x for x in pending.get("request_ids", []) if isinstance(x, str))
            evidence["existing_build_status"] = progress.get("status")
            raise SkillError("construction_existing_build_job_requires_build_or_read_only_reconciliation_no_procurement")
        bounded.existing(blueprint)
        # Any occupied external crafting grid or machine is retained for explicit
        # recovery, rather than being closed or consumed as a side effect here.
        menu = inventory._menu(first)
        require(first.state.get("screen_open") is False and menu.get("container_id") == 0,
                "construction_requires_closed_clean_inventory_menu")
        view = production._craft_view(first)
        require(view.width == 2 and all(view.items[i] == production.EMPTY for i in (view.output,) + view.grid),
                "construction_partial_crafting_contents_require_explicit_recovery")
        evidence["capacity_preflight"] = _capacity(first, bill["items"])
        require(len(bill["items"]) <= 32 and all(count <= 2304 for count in bill["items"].values()),
                "construction_material_bill_exceeds_supply_bounds")
        require(bill["placement_items"] <= max_placements and bill["placement_items"] <= bounded.effective_remaining_budget()["remaining_actions"],
                "construction_minimum_placement_budget_insufficient_before_procurement")
        survey = building_v3.planning_survey(bounded, blueprint)
        anchor, _, _ = building._geometry(survey)
        evidence["survey_anchor"] = anchor.json()
        evidence["survey_authorizes_mutations"] = False
        proposal = building_v3.execution_plan(blueprint, survey, max_steps=max_steps,
            historical=True, planning_materials=bill["items"])
        evidence["build_budget_preflight"] = building_v3._initial_budget(bounded, proposal, anchor,
            max_placements=max_placements, max_moves=max_moves, max_steps=max_steps)
        evidence["build_budget_preflight"]["proposal_only"] = True
        if evidence["capacity_preflight"]["missing_items"]:
            worksite = _worksite(survey, protected, max_steps=max_steps)
            evidence["procurement_worksite_proposal"] = worksite.json()
        bounded.start(blueprint, job_id)
        if evidence["capacity_preflight"]["missing_items"]:
            bounded.accept("approach_procurement_worksite", mobility.navigate_loaded(
                bounded, worksite.json(), max_segments=128, max_steps=max_steps))
            left = bounded.effective_remaining_budget()
            require(left["remaining_seconds"] >= 1 and left["remaining_actions"] > 0,
                    "construction_original_budget_exhausted_before_supply")
            bounded.accept("ensure_materials", supply.ensure_items(bounded, bill["items"],
                max_nodes=max_nodes, max_blocks=max_blocks, max_batches=max_batches,
                timeout_seconds=min(3600, left["remaining_seconds"]), max_actions=left["remaining_actions"],
                max_search_steps=max_search_steps, max_walk_distance=max_walk_distance,
                excluded_positions=[p.json() for p in sorted(protected)]))
            bounded.accept("close_procurement_menu", reach.close_menu(bounded))
        bounded.accept("return_to_survey_anchor", mobility.navigate_loaded(
            bounded, anchor.json(), max_segments=128, max_steps=max_steps))
        before_build = bounded.observe(allow_menu=True)
        evidence["capacity_before_build"] = _capacity(before_build, bill["items"])
        require(not evidence["capacity_before_build"]["missing_items"], "construction_full_material_bill_not_observed_before_build")
        require(not path.exists() and not path.is_symlink(), "construction_existing_build_job_blocks_procurement")
        bounded.procurement = False
        result = building.build(bounded, blueprint.spec(), job_id=job_id,
            max_placements=max_placements, max_moves=max_moves, max_steps=max_steps, hotbar_slot=hotbar_slot)
        bounded.accept("build", result)
        bounded.save(status="complete", pending_admission=None)
        return Outcome(result.status, result.reason, tuple(dict.fromkeys(bounded.ids)),
            {**result.evidence, **evidence, "stages": bounded.stages,
             "actions_reserved": bounded.initial_actions - bounded.remaining,
             "one_original_deadline": True}, result.last_observation)
    except SkillError as exc:
        if exc.request_id:
            bounded.ids.append(exc.request_id)
            bounded.action_ids.append(exc.request_id)
        bounded.save(status=exc.status, reason=exc.reason)
        return Outcome(exc.status, exc.reason, tuple(dict.fromkeys(bounded.ids)),
            {**evidence, "stages": bounded.stages, "actions_reserved": bounded.initial_actions - bounded.remaining,
             "no_automatic_retry": True}, bounded.last_observation)

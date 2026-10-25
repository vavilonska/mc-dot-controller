> Historical version-specific source contract; current source identity and publication validation are in [latest publication](docs/latest-2026-10-25/README.md).

# Explicit new-life acknowledgment

This separate control permits fresh requests after a verified death and an actual replacement LocalPlayer instance. It never respawns the player, resumes a task, cancels an action, settles a gameplay UNKNOWN, or changes inventory. Normal in-game respawn occurs first.

The native full-state response exports `player.generation_schema_version: 1` and `player.generation`, a process-local random identity attached to the actual player object. The same player UUID, restored health, a changed position or a world transition alone is insufficient. A returning original object retains its original token. Exact player and entity-data readers and a final player/level/server/data identity fence bind the exported health/alive facts.

The Watchdog retains the first exact successful dead observation (alive false, finite health at most zero, generation, original context, server/Resident/bridge identities and request ID). Repeated death observations may advance the current defense epoch but do not rewrite that origin. A prior unsafe-environment pause does not prevent retaining a later proven death. Retaining evidence does not release an owner or uncertainty barrier.

Use the current `mdc_catalog.runtime_binding_availability.session_ref` and `new_life_acknowledgment.death_ref` only when the latter is eligible. Submit one `mdc_job` with operation `acknowledge_new_life`, a new request ID, those exact references, and acknowledgment `allow_new_life_requests_only_no_task_resume`. The clean-menu operation `acknowledge_pause` and its literal remain separate.

The control has a fixed five-second wall/monotonic deadline. It requires all original work to have known terminal cleanup, no active owner or uncertainty latch, and two distinct post-request ordinary Resident observations with increasing native ticks, fresh receipt age, a different player generation, the same player UUID/action session/server/Resident/bridge, and one stable new context. Respawn into another dimension is permitted only within those exact lifecycle identities. The new context is pinned by the first accepted alive sample. Both samples must be unpaused, menu closed and neutral, with no native or Resident handoff/ownership ambiguity. All final I/O precedes immutable sample binding and current owner/context/epoch/deadline checks.

Success advances the epoch once and allows only separately requested new jobs. A duplicate public request returns its durable original result. A missing reply remains UNKNOWN and permits only an exact original read; it does not resubmit the acknowledgment. Gameplay UNKNOWN jobs remain unresolved. Shutdown performs a bounded read of a pending control receipt and does not synthesize a gameplay cancel.

The first installation cannot retroactively prove a death recorded before generation telemetry existed. Use the reviewed normal cold-continuation procedure for that deployment. Future same-process deaths can use this control after the required evidence is observed. Offline tests use synthetic endpoints for the public chain; live repeated-death acceptance is a separate gate.

## Runtime destination adoption

A successful exact gateway acknowledgment separately adopts its proven destination into the same idle Runtime. The pre-submit local owner, job generation, prior context, observation identity/payload, tick floor and preflight binding must still match. Adoption sets only the destination context and a nondecreasing same-context second-sample tick floor, invalidates the old observation/preflight cache, and requires a distinct fresh read before new action planning. It preserves journals, sticky navigation capability knowledge and all uncertainty/reacquisition barriers.

Exact late receipt lookup uses nonblocking local locks. An already applied receipt is a no-op even after later jobs. If the local binding has changed, the proven gateway receipt remains in the result while `runtime_context_adoption.adopted` is false and the public control is blocked; no newer owner or cache is overwritten. This does not reinterpret any historical gameplay UNKNOWN.

A terminal `blocked` new-life control whose gateway receipt proves rearmed=true but whose local Runtime adoption was refused can be reconciled by its original public ID. This rereads only that original gateway receipt and attempts the same nonblocking local adoption under its unchanged pre-submit binding. It never resubmits the acknowledgment. Changed-owner or conflicting-receipt refusals remain blocked. Other blocked jobs retain their existing behavior.

Once the gateway success is proven, later missing, invalid or conflicting exact-result lookups add only a diagnostic event. They retain the original known blocked control and its accepted proof; they cannot replace its destination or convert that proven result to UNKNOWN.

Concurrent original-worker and shutdown readers share one backend-lifetime first-validated-receipt pin, recorded before either attempts local adoption locks. A conflicting same-ID command or receipt cannot replace that evidence or adopt another destination. Late pending, failed or blocked lookups cannot downgrade a concurrently proven local adoption. This cache contains only exact control receipts and grants no gameplay authority.

# P6: bounded construction preview and historical memory read

This is a staged, offline-tested toolbox slice. It is not new native construction
acceptance and does not start, resume, reconcile or execute a building job.

## Public construction preview

`mdc_plan` supports the existing `build` and `build_with_materials` capability IDs.
The required `arguments.blueprint` is embedded schema3 JSON from the existing
`building-v3.schema.json`. The original `VersionedBlueprint.parse` checks its
content SHA-256, exact blockstates, duplicate positions and paired footprints.
No blueprint reference or file path is accepted: there is no approved registry
resolver in this source selection. `identity.source` remains opaque provenance;
it is never opened as a path or URL.

The public slice is deliberately bounded more tightly than the legacy executor:

- At most 512 blockstate cells and 512 entries in each acceptance list
- At most 256 KiB of blueprint JSON
- Inclusive region spans no greater than 31 by 15 by 31, volume at most 8192
- Access points within the declared region expanded by four horizontal blocks
  and two vertical blocks
- At most 32 distinct material types and 512 total placement items
- Existing supported block/property families only

The returned material bill comes directly from `material_requirements`. A paired
door counts as two state cells and one item. Wall torches retain the underlying
helper's item mapping. This is a total bill: it grants no existing-world or
inventory credit. The original blueprint identity and exact digest, source
fingerprints and explicit non-authority flags accompany the result.

Without trusted terrain, `status` is `partial` and `terrain_preview.status` is
`unavailable`; the useful bill remains present. Access, placement, inventory
and actual completion are not inferred. P1 currently supplies no terrain to this
pure planner. The internal typed-observation seam reuses `execution_plan`, the
same effect-free planning kernel used by existing `plan_build`, preserving the
original request, source tick, capture time and context. It cannot accept caller
JSON observations, refresh evidence, mutate terrain or reconcile checkpoints.

Both construction entries remain `legacy_limited` and unavailable in P2's
state/menu execution allowlist. Direct `invoke` also fail-closes with a blocked,
no-effects result. Existing `build`, `build_with_materials`, `plan_build` and
progress reconciliation implementations are unchanged. In particular the old
progress reconciler can update a local checkpoint after evidence reads; it is
not silently invoked as an effect-free toolbox preview.

## Public memory read

Use the existing read tool with:

```json
{
  "api_version": "mdc.toolbox/1",
  "session_ref": "the verified current session reference",
  "profile": "memory",
  "selectors": {"query": "home"},
  "bounds": {"max_results": 1}
}
```

The query is one exact `[A-Za-z0-9_-]{1,80}` key. Empty/wildcard/path queries,
extra selectors, writes and larger result counts are rejected. A missing key or
absent knowledge file returns `found: false` without creating a file.

P2 routes this profile to
`memory.read(runtime, selectors, bounds, trusted_context=...)`. It uses the
operator-bound existing Runtime journal and `KnowledgeStore.recall`; no caller
chooses a journal path. It does not acquire a gameplay lease, observe the native
world, issue an action, call `remember`, update a checkpoint or reset a timestamp.
The gateway session may be read for current context comparison. P1's ordinary
session/private-singleplayer checks remain in place.

The returned record retains its original world/dimension/player/action-session
context, source tick, source request ID, monotonic capture time and capture epoch.
The flags must already be `historical_only: true` and `action_evidence: false`;
invalid stored provenance is rejected, never rewritten. `same_context` is based
on the trusted gateway context when supplied. Without it, the result explicitly
says comparison is unavailable. A different context remains labelled historical.
An age is calculated only when the runtime and record share the original capture
epoch and the monotonic comparison is valid. Otherwise age is null, not zero.

`memory_recall` is catalogued as a query with its job adapter pending. Use
`mdc_observe(profile="memory")`; the initial mutation allowlist is not widened
to run local reads as gameplay jobs. There is no public memory-write binding.

## Verification scope

`tests/test_toolbox_building_memory_p6.py` exercises the actual P1 public plan
route and P1 → P2 → KnowledgeStore read route, using only deterministic offline
fixtures. It covers closed schemas, bad hash/duplicate cells, paired-door bills,
region/access/material/option bounds, path/callback/write rejection, typed
historical geometry, direct execution refusal and cancellation boundary,
unchanged file bytes, missing store, symlink rejection, corrupt provenance,
context mismatch and incomparable epochs.

These tests establish Python data and routing behavior, not Minecraft geometry
or engine semantics. Terrain admission, building execution, native cancellation
and live construction acceptance remain unavailable/unrun for this slice.

# Block-menu failure diagnostics: original source-only checkpoint

This historical diagnostic-only delta preserves the T24 documentation baseline and changes
three production files: `BlockMenuDiagnostics`, `ClientActions`, and
`ScopedNativePreflight`. It adds bounded context to synchronous admitted
block-menu exceptions before the existing cleanup, only while the same admitted
owner remains active. No guard, deadline, terminal classification, packet/effect
predicate, or replay permission is relaxed.

The optional `result.block_menu_diagnostics` object contains exactly six fields:
`schema_version`, `stage`, `phase`, `exception_type`, `rejection_code`, and
`capture_elapsed_nanos`. Stage, phase, exception category and rejection codes use
finite vocabularies. Unknown messages become unclassified categories; arbitrary
exception messages, class names, stacks, player identity and inventory values are
not serialized by this diagnostic object. This claim does not describe every
other pre-existing receipt field. Elapsed time is diagnostic only.

A phase records the last-started step, not a proven failure cause. Nonthrowing,
already-finished and replaced-owner paths are not retroactively annotated. The
original T26 rejection was not recovered, and its outcome remains unknown.
Diagnostics do not make an unknown local effect safe to retry.

## Validation and provenance

- All 138 integrated production Java sources were freshly compiled against pinned
  genuine dependencies, without launching a game, server or world.
- The published Java regression passed 3018 assertions using real production
  diagnostics, ActionRegistry, BridgeJson and engine geometry. It covers 250
  stage/phase/cleanup combinations, bounded and sanitized output, terminal reason,
  identity, effect markers, and detached serialized results.
- Private observed geometry was translated to a synthetic origin in the public
  fixture, and elapsed time replaced by a synthetic value. Original private tests
  and evidence were preserved. No production bytes changed during integration.
- Actual pinned Mixin offline transformation and its missing-target negative
  control passed on byte-identical production sources before integration. This
  result is inherited; it was not rerun for the documentation/test-only changes.
- Real Python state-menu and block-menu consumers were checked using synthetic
  witnesses. The additive diagnostic preserves acceptance, and a failed
  post-click/pre-use witness remains `block_menu_late_local_effect_unknown`.

The production-source review freeze SHA-256 is
`18d2f98384f4bb40da5437a3fba12a90618edaef0ab9cc159c0fb5f367ef6256`.
This identifies the original five-file review inventory; the public test and its
README were subsequently sanitized as described above. Current published hashes
are in `PUBLICATION-MANIFEST.json` and `SOURCE_SHA256SUMS.txt`.

## Limits

ClientActions.interactBlock, its actual finish cleanup, injected runtime failures,
full NeoForge/FML launch, JVM linking, callbacks and gameplay are NOT_RUN. The
bytecode-only Mixin service is not any of those tests. No furnace-opening or
smelting success, runtime bug fix, deployment, or recovery of T26 is claimed.
Original worlds and unknown actions were not replayed. T22 unknown, T23 bounded
placement and T24 qualified crafting results retain their previous limits.

See [executable regression scope](../client-mod/validation/block-menu-diagnostics/README.md).
Private runtime logs, trial identities, worlds, dependencies and built artifacts
are excluded from this publication candidate.

## Later consolidation

The NOT_RUN statements above describe this original diagnostic checkpoint. Later
reviewed intended-ray and consume-completion changes, separate bounded live trials,
and their limits are recorded in [current fixes](BOUNDED-RAY-AND-CONSUME-FIXES.md)
and [T29–T31 acceptance](T29-T31-ACCEPTANCE.md). The original T26 unknown remains
unchanged. Current file hashes identify the consolidated source, not the earlier
five-file review inventory.

# Portable mining / collect regressions

These tests exercise the current combined checkout's production Python path.
Their native endpoints and game facts are synthetic. A passing result does not
prove native engine behavior, physics, live mining, or pickup safety.

## Run

After the live-run exclusion has been released, from any working directory:

```sh
python3 -I -B /path/to/checkout/capability-runtime/tests/mining_collect/run_offline.py \
  --output /path/outside/checkout/new-run-directory --include-combat
```

The runner requires a new evidence directory outside the source checkout,
records unmodified stdout/stderr and original child exit codes, applies a
120-second per-group timeout (configurable between 10 and 300), and never retries.
Tests use temporary offline mailboxes under that evidence directory. Child audit
guards reject networking, spawned processes, and source-checkout mutations.
The bootstrap selects only this checkout's modules and shared owner-chain harness.
No game, existing mailbox, credentials, world, or live service is used.

Default groups preserve 32 mining cases (21 contract/witness + 5 diagnostics +
6 actual-owner-chain), 22 collect contract/witness cases, and 7 collect
actual-owner-chain cases. `--include-combat` adds the existing mainline scoped
combat chain, combat contract alignment, and combat contract wire modules.
The 10 legacy menu checks retained in `collect/menu_fixture.py` are supporting
source only and are not silently added to the 61-case acceptance count.

`--groups` selects specific groups for an affected-area rerun. The additional
`native_wire` group has 8 cross-language checks and requires the original output
of `client-mod/validation/mining-collect-combat/CombinedWireChecks.java`:

```sh
python3 -I -B /path/to/checkout/capability-runtime/tests/mining_collect/run_offline.py \
  --output /path/outside/checkout/new-codec-run --groups native_wire \
  --native-wire-dir /path/to/original/combined-wire
```

That group directly consumes the original Java-emitted
`{collect,combat}-{standalone,coherent,request,intent}.json` files. The Java captured
facts are synthetic; the production witness serialization, assembly, HTTP codec
bytes, and Python consumers are real. Original input hashes are logged and input
bytes are checked unchanged at completion. Positive acceptance never reserializes
or substitutes fabricated native bytes. Explicitly mutated in-memory copies are
used only for negative tests. Collect uses reference-only siblings plus retained
original-byte provenance; combat preserves its current inline witness contract.
Standard discovery skips this group if actual Java output was not supplied.

## Verification recorded on 2026-10-14

After the explicit test release, the initial bounded invocation passed all 32
mining, 22 collect, 7 collect-owner-chain, and 32 existing combat cases, with
original exit code 0 for every group. After the separate mainline combat fixture
bootstrap correction, a fresh invocation passed 8 original-Java-byte consumer
cases and reran all 32 combat cases successfully. Evidence and temporary runtime
data remain outside this source package. These are offline checks only.

## Provenance and deliberate expectation changes

The mining files derive from `scoped-mining-preview-r1/tests`; collect files derive
from `scoped-collect-route-r1/tests`, captured on 2026-10-14. Exact original SHA-256
identities are in `PROVENANCE.sha256`. Fixture namespaces and relative imports
are separated to prevent mining/menu and collect/menu collisions. Mainline test
files and production source are not modified by this port.

Only two existing test expectations change for the combined tree:

1. `test_t13_movement_source_preserved_and_mining_budgeted` compares the three
   movement Java files against pinned accepted collect-source hashes, because
   collect deliberately extends T13 with its explicit pickup target. It remains
   an exact byte identity check. All mining budget/ownership assertions remain.
2. `test_catalog_union_preserves_every_original_entry` expects exactly
   `{mine_local, collect_local}` added by the resource binding. Every original
   definition is still compared for equality. `engage` must exist unchanged in
   both current tactical catalogs. No broad subset assertion replaces equality.

`references/original_resources.py` is a source-only frozen catalog expectation
from the original complete slice, with its relative helper import changed to the
current checkout's explicit production helper import. It is never installed as
the production resource module. Source lookups now use checkout-relative paths;
no sibling checkout or private absolute path is required.

All other test bodies, profile mappings, negative checks, unknown-outcome no-replay
assertions, exact cancellation IDs, and cleanup-certainty checks are preserved.

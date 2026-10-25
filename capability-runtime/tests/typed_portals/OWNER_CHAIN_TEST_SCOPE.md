# Typed item and portal offline owner-chain tests

These tests run production Python through:

`ToolboxService -> OwnerRuntimeBackend -> Runtime -> IntentClient -> Watchdog -> QueueClient -> Resident`

The Watchdog runs in `request_only` policy. The only fabricated execution endpoint is the native Bridge endpoint. Its world, inventory, terrain pages, admission receipts, and terminal receipts are synthetic. The tests do not start Minecraft, invoke native Java or Mixins, exercise packets or physics, connect a server, operate a GUI, control game processes, deploy, or push code. Passing tests establish Python contract and owner-chain behavior only.

## Files

- `typed_portal_fixture.py`: Complete generic wire facts, inventory/menu/equipment agreement, immutable submitted/compiled command digests, entity exclusion coverage, exact item geometry, and typed portal transition receipt bindings. Every valid receipt goes through the unchanged production strict validator.
- `test_strict_witnesses.py`: Admission and terminal validation; item outcome independence; exact portal source/action/session/player/server/deadline/contact bindings; forged and legacy profile refusal; generic digest/inventory/cell/entity coverage refusal.
- `test_owner_chain.py`: Public job submission and asynchronous completion through the complete owner chain. Covers one-use ignition, one-eye insertion, last-eye block footprint, independent semantic checks, unknown/no-replay handling, exact prepared portal entry, delayed source observations, expected destination rebinding, original deadline preservation/expiry, unrelated cancellation, disconnect, server mismatch, forged terminal proof, and public profile admission refusal.
- `test_producers.py`: Existing producer-level fixture and binding tests, maintained separately from this owner-chain work.

## Run against an integration source tree

Set `SOURCE` to the production integration source directory and `TESTS` to the directory containing this `typed_portals` package. No source files in `SOURCE` are edited by the test runner.

```sh
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$TESTS:$SOURCE/capability-runtime/tests:$SOURCE/capability-runtime:$SOURCE/resident-controller:$SOURCE/navigation-controller:$SOURCE/navigation-cursor:$SOURCE/defense-watchdog:$SOURCE/gameplay-helpers:$SOURCE/building-controller:$SOURCE/external-controller:$SOURCE/multiagent-coordination"
python -B -m unittest typed_portals.test_strict_witnesses typed_portals.test_owner_chain -v
```

All ordinary test threads, queues, runtime journals, and job stores are created in temporary test directories and cleaned up by the existing ownership harness.

## Regression findings

The tests include regressions for type-confused post-observation proof values. Python structural equality considers `True == 1`; native-terminal validation alone does not justify accepting a later altered observation proof. The portal owner must retain type-strict equality of its terminal proof across delayed observations, and semantic item predicates must distinguish observed integer durability/count values from booleans.

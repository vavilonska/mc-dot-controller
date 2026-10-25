# Typed item/portal offline validation result

PASS: 38 tests, 0 failures, 0 errors, 0 skips, 89.735 seconds.

- 25 complete public owner-chain tests
- 7 strict witness test methods (multiple adversarial subcases)
- 6 existing producer/binding tests

## Scope

The complete production Python route was exercised: ToolboxService → OwnerRuntimeBackend → Runtime → IntentClient → Watchdog → QueueClient → Resident. The native endpoint, its terrain/inventory, and its receipts were synthetic. No game, JVM/native hook execution, GUI, server connection, game process control, deployment, or push occurred.

This is an exact source-only integration-overlay result. It is not a final shared-source integration pass or evidence of Minecraft/native behavior.

Base source: `/workspace/scratch/5f333e5a575b/mdc-survival-primitives-candidate/source`

Tested source: `/tmp/mdc-typed-owner-overlay-mawwpx8v/source`

Only the five modules listed below were overlaid from the item candidate. All other copied source files retained their snapshot hashes. All 15 production module imports were checked in the same process after loading the complete suite. Source files and test Python files remained unchanged throughout the run.

## Covered behavior

- One native request for flint ignition, single eye insertion, and last-eye activation
- Independent observed item consumption, durability, protected inventory, and exact block results
- Rejection of boolean-as-integer durability and post-observation count proofs
- Delayed source observations followed by expected destination, same owner, exact native action, and original deadline
- Unrelated cancellation, wrong server, disconnect, forged original action, missing contact, unknown outcome, and original deadline expiry
- Forged proofs both before destination rebinding and after the first destination sample
- No automatic replay, no legacy native action fallback, and no transition permit after uncertain submission
- Public refusal for absent, legacy-only, or mismatched typed profiles

## Exact overlay module hashes

- `capability-runtime/mdc_skills/scoped_item_interaction.py`: `820c71a298f58a27b3b7f5fc559716e0bfc97164f144b4b3d68c3143c46121d7`
- `capability-runtime/mdc_skills/scoped_portal_entry.py`: `460039c4ecd1c47652c9d04cd71e99c11ec3f28a66c4977254556ee372316055`
- `capability-runtime/mdc_toolbox/bindings/typed_portals.py`: `98beee876690c280b4275f3aeb84427c07cfd316b4adb16c682c7a86473798dd`
- `resident-controller/resident_controller/item_interaction_snapshot.py`: `6a242f730b02f77400643219422b2d1c7395f4c94b14f35a56d9d7888036b4d3`
- `resident-controller/resident_controller/portal_entry_snapshot.py`: `96fd973694d5b7b2d7f2b25820bcf567f55c4e9576200866166ebe7e85774764`

## Evidence files

- `OWNER_CHAIN_OVERLAY_RESULTS.log`: complete successful test output
- `OWNER_CHAIN_OVERLAY_RECEIPT.json`: result, scope, test hashes, and unchanged-source checks
- `OWNER_CHAIN_OVERLAY_IMPORTS.json`: same-process production import paths and hashes
- `OWNER_CHAIN_OVERLAY_MANIFEST.json`: all 1,285 base/final snapshot file hashes and five overlay module hashes

Manifest SHA256: `1cb5f4a80cb83c76cef8a0a7a687cebfbdad01100f4fc3c9dea685554ec75621`

An earlier combined run is preserved only as `OWNER_CHAIN_MIXED_IMPORT_DIAGNOSTIC.log`. It is superseded and is not a valid overlay receipt: importing a generic fixture through `mining_collect.__init__` selected an older checkout’s watchdog. The fixture now loads directly by file path, and every full-chain setup rejects mixed production source trees.

Final shared-source integration and native/game validation remain outside this receipt.

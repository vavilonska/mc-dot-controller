> Historical version-specific source contract; current source identity and publication validation are in [latest publication](docs/latest-2026-10-25/README.md).

# Offline evidence and limits

This is the independently developed `recovery_interaction_v1` candidate, not a gameplay pass. The frozen input1 package and original formal world/journal have not been changed by the engineering build. Actual game operations remain solely with the designated operator after separate admission.

## Native

The reproducible script is `client-mod/validation/recovery-interaction/run-offline.sh`. It compiles all 245 production Java sources against the recovered pinned Minecraft/NeoForge API, emitting 559 production classes separately from validation harnesses. Flags are `-proc:none -source 21 -target 21` (not `--release`, not a claimed Gradle/FML run). No additional access transformer is used; one read-only `RecoveryMiningAccessor` is added to the mandatory Mixin configuration.

The final native run contains 423 interaction assertions, 68 retained legacy core assertions, 11 retained production-codec assertions, 501 pinned selector/signature checks and one conflicting-profile startup rejection. Counts are assertions, not real game actions. The pinned audit does not demonstrate transformed loader execution or a physical block break.

The authorized journal-only fixture contains the 57 actual known historical records. Tests use private copies, compare every original request/digest/production terminal with the actual old public receipts, then compare them again after RSI2 write and reopen. Historical status/exact stop retain their old schema. New kinds share owner/generation/action-ID/in-flight/UNKNOWN authority; interaction startup cannot initialize an empty identity. Unknown old records remain locked, and no uncertain action is replayed.

New tests cover bounded payloads and kind collisions, pre-effect persistence, queued cancellation/deadline, an entered callback concurrent with stop (the journal monitor is not held across vanilla calls), incomplete/late unwind release, first-stop attribution, restart lock and original-owner isolation. These are controlled tests of dispatch/control integrity. They are not a claim that a synchronous mod hook can be forcibly interrupted, or that already-requested vanilla server work is undone.

## Public and actual serializer

The new standalone `interaction-controller` passes 33 tests, including actual Java-produced request/receipt JSON for all four kinds, queued/known terminal, known zero calls, entered-stop and UNKNOWN-with-release. Raw receipt bytes are retained without rewriting and their typed digests/closed schemas are checked. A separate synthetic full observation test uses the actual final production serializer: 150 cells, 9 hotbar entries and 0/32 nearby flags encode to 18,237/21,084 bytes and pass the final public observation and local movement readers within the unchanged 65,536-byte limit. This is serialization/budget evidence, not an actual game observation or a general maximum for arbitrary content. The frozen `short-input-controller` remains byte-identical (17 files) and passes all 38 legacy tests. The coordinator independently reran both suites. Old MCP portable regression passes 83 tests plus 9 framing tests; it is not the entry for the new interaction profile.

Public policy admits only the two fixed cobblestone coordinates and observed slot2 stone pickaxe for this task. A local jump requires live whole-bbox source fit, source body and fresh y62 headroom, plus the adjacent z32/z33 landing supports. The finite input does not guarantee reaching or landing on the platform. The cold geometry fixture is explicitly only planning/negative evidence; modified positive geometries are synthetic.

## Remaining TEST gates

The paired package still requires independent source/class/archive readback and parent TEST admission. Required live evidence is loader/readiness with the original 57 records, one-shot look and slot selection, each exact block attempt/removal/release, genuine ACTIVE cancellation with original-ID reconciliation, and complete locally observed staging/ascent/landing. Do not convert offline coverage into live coverage, natural completion into cancellation, `target_changed` into server confirmation, or protocol completion into physical settlement. Formal recovery use remains on HOLD until that complete narrow TEST is reviewed.

No placement, combat, generic excavation, arbitrary inventory operations, global entity whitelist, credentials, owner bootstrap or future-world no-risk proof is added.

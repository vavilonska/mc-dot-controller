> Historical version-specific source contract; current source identity and publication validation are in [latest publication](docs/latest-2026-10-25/README.md).

# Native recovery short input — offline implementation evidence

Candidate only: `mdc-recovery-short-input-test-r1/source`; baseline TEST2.13 untouched. No game, world, process or deployment action performed by this subagent.

## New catalogue and prerequisites

Startup-only class-initialized `-DmineclientBridge.recoveryShortInputV1=true`. Existing bridge bearer authentication and loopback-only bind remain required. This mode requires isolated input and a private unpublished integrated singleplayer world. Prototype requires supported controller observation to report **absent**, not merely idle; the operator must prepare a modset without Baritone/other automated input controllers. This is input exclusivity, not a world-safety claim. No attack, use, yaw, packet, velocity, position or held-key operations are added.

Endpoints under `/control/recovery-short-input/v1/`:
- GET `observe`: bounded pose/velocity/health, 125 loaded-only nearby block facts (dx,dy,dz -2..2; registry id, any-collision boolean, fluid registry id), at most 32 living entities in radius 8 with truncation; no global threat proof. No-world null fields are explicitly serialized.
- POST `start`: strict flat fields `schema_version=1, profile=recovery_short_input_v1, id, session, owner_id, owner_generation, world_generation, player_uuid, forward, strafe, samples, jump_first, ttl_ms, observation_id`. Axes finite [-1,1], sample count 1..8, ttl 100..2000ms. First accepted owner UUID binds this native session. Observed generation is the next claim generation.
- GET `status?id=...&session=...&owner_id=...&owner_generation=...`: exact original ticket. No world/hazard checks or main-thread wait.
- POST `stop`: exact `schema_version,profile,id,session,owner_id,owner_generation`. HTTP thread invalidates authority first; game thread only clears the captured Input. May report STOPPING until that release is proven. No world/hazard admission predicate.

Duplicate JSON members, nested values, surplus/missing fields and mismatched typed values are rejected. Status and observation use the dedicated production `serializeNulls` codec, not legacy BridgeJson omission logic. Observe wait is bounded to 1 second; start/status/stop have no completion join. Start replies 202 after a durable queue record; loss of response does not replay. Same ID/exact normalized payload returns the original entry without another callback; any change rejects.

## Binding and lifecycle

Observe creates a native challenge. Admission and the first raw input sample require that exact observation id, same world/player references, source age <=250ms and <=5 native ticks, position drift <=0.05 each axis, yaw/pitch drift <=0.1 degrees. These are local source-binding conditions, not atomic global safety proofs. Subsequent samples use vanilla physics and can encounter normal damage/death.

One ticket is in flight. A native tick admits at most one counted input sample; jump appears only on sample zero. Durable ACTIVE/dispatch-fenced record precedes every possible raw Input field write. Post tick clears only the captured Input; the next pre tick first clears residual fields if Post was missed. Absolute monotonic lifetime never refreshes; signed elapsed arithmetic handles rollover and rejects clock rollback. Stop/expiry invalidate ticket authority; delayed admission/sample/cleanup callbacks cannot acquire a replacement owner.

States QUEUED/ACTIVE/STOPPING/SETTLED/UNKNOWN describe the **protocol**, not physical rest. `protocol_terminal` and compatibility `settled` mean known sample count plus invalidation/release. `settlement_state=not_observed` always; `gameplay_outcome=not_assessed`. Velocity may remain nonzero and future damage is possible. On UNKNOWN, persisted `applied_samples` is historical journal evidence, not proof of a complete effect count. Exact captured-input cleanup remains available without clearing UNKNOWN. Unproven replacement-input cleanup retains the old capture, blocks automatic cleanup retries, and requires explicit stop to recheck; it never clears replacement input.

Queued cancellation/expiry is known zero-input; post-sample cancellation can be known partial+released. Death/logout/player replacement/pause are known interruptions if captured release is proven, not automatically UNKNOWN. Bridge stop invalidates first, requests exact cleanup, and shuts down its watchdog even if journaling fails.

## Persistence

`config/recovery-short-input-v1.ledger` is a small bounded binary journal (256 IDs maximum), forced temporary file + atomic rename + forced parent directory. A process-lifetime sidecar file lock prevents concurrent writers; symlink paths are rejected. Every unfinished record found on restart is persisted UNKNOWN and globally blocks new input across session/owner/profile changes. No reset or unlock endpoint exists.

Initial admission journal failure occurs before enqueue/effect and returns `503 admission_not_committed_no_input_possible`, `admission_committed=false`, `no_input_possible=true`; the process remains fail-closed. Arbitrarily broken storage cannot magically persist a failure marker that never reached disk. After durable admission, the existing unfinished journal guarantees restart UNKNOWN even if a later write fails. Public pre-POST pending/UNKNOWN persistence independently handles an unreadable/lost receipt.

Canonical payload SHA-256: ASCII strings encoded unsigned big-endian 16-bit length+bytes in order id,session,owner_id; signed big-endian 64-bit owner_generation; strings world_generation,player_uuid; big-endian IEEE754 double forward,strafe (signed zero normalized +0); int32 samples; byte jump_first 0/1; int32 ttl_ms; string observation_id.

## Exclusive owner glue

- BridgeServer rejects every legacy non-GET mutation in exclusive mode before dispatch; static mode cannot change after startup, so an old mutation cannot be accepted in one mode and execute in the other.
- ClientActions start/directTakeover explicitly reject; ownsInput reports exclusive ownership. ClientActions pre/input/post hooks route only to the new owner in this mode.
- NativeManagedNavigation.start, NativeExternalNavigation.stop and NativeFallRescue.arm reject explicitly. Admission also checks no old runtime/terminal-cleanup owner, fall armed OR blocked, managed/external owner, guarded lease, held raw/mouse/key state, or non-absent external controller.
- Bridge global cleanup is not used by the new profile. Legacy release requests only invalidate the new ticket; replacement input is never globally reset.
- Watchdog and repeated stop coalesce to at most one pending cleanup callback per exact ticket; UNKNOWN released/no-capture does not create an unbounded main-thread queue.

## Offline verification

`RecoveryShortInputChecks`: pure production ledger tests, 68 assertions (bounds, duplicate/mismatch, queued expiry/cancel, partial stop, stale owner cleanup, restart UNKNOWN, before/after-effect IO failure, shutdown, monotonic rollover/backward, file lock/symlink/corruption, coalesced cleanup, missed Post residual release).

`RecoveryShortInputWireChecks`: actual native private request parser, production native describe/no-world describe, and production HTTP serializer; 11 assertions including duplicate JSON, explicit nulls, strict numeric types, known partial and known zero terminal outcomes. Raw request/response byte fixtures under `wire-fixtures/` are for independent public strict-reader/digest checks.

All 242 production Java source files compile against the restored actual 95-jar Minecraft/NeoForge access-transformed classpath with Java 21 `-source 21 -target 21 -proc:none`. This is actual API typechecking, not an FML/game-loader or live movement test. No mixin was changed. Annotation processing was disabled after the environment's default processor failed on missing java.sql.Time; no generated refmap claim is made.

## Final review clarifications

- `observe.client_tick` is the native ClientTickEvent.Pre counter (null without a world). It distinguishes native frames, not server simulation progress or physical settlement; paused frames do not establish safe motion.
- No new GameType/flying/fluid/health threat predicate was added. Survival-mode context is an operator precheck for the independent TEST world, not a new protocol UNKNOWN rule.
- `cleanupBlocked` is checked centrally in cleanup, so Post/contextLost cannot retry an ownership-unproven cleanup every tick. Exact explicit stop may clear that retry block, but cannot clear UNKNOWN or touch a replacement Input.
- Initial queue persistence failure is explicitly known **uncommitted/no input possible** at HTTP admission (503 fields above), not a claim that an unpersistable marker survives arbitrary disk failure.
- Missing Post is covered by the next Pre's `residualInput` predicate and exact release before any new input sample. The original count/deadline do not refresh.
- Final compile outputs are separated: `classes-production/` is production-only; `classes-tests/` contains offline harnesses. Earlier `allclasses/` is a development artifact and MUST NOT be packaged wholesale.
- Public cross-language wire validation passed 38 tests in its r2 report. Preserve the reviewed wire fixtures; re-running the fixture generator produces a fresh random native session and is not necessary for internal-only source changes.

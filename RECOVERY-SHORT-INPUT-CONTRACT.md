> Historical version-specific source contract; current source identity and publication validation are in [latest publication](docs/latest-2026-10-25/README.md).

# Recovery short-input prototype — recovery TEST contract

This explicitly opted-in `recovery_short_input_v1` profile is based on verified TEST2.13. It is not the unavailable TEST2.20–31 work, does not migrate or settle historical UNKNOWN, and does not silently widen an old guard. Offline qualification and a packaged candidate are not live-game qualification.

## Two layers and limits

The native executor owns control integrity: one session-bound owner, one action in flight, 1–8 counted native input samples, immutable request identity, cancellation of pending input, original monotonic deadline (100–2000 ms), exact-input release, and durable terminal/UNKNOWN accounting. Ordinary forward/strafe input is finite in [-1,1]; native optional jump is only the first sample. Public first-step policy does not enable jump. There is no attack, use-item, inventory, yaw, velocity, position, teleport, packet, command or world-edit operation.

The upper controller uses fresh bounded local observations to choose a short move and inspect its result. It does not require every loaded entity class or every remote causal process to be proved harmless. Nearby threats, damage, death, inertia and water flow are ordinary gameplay outcomes, not automatically protocol failures. The local first-step checks are intentionally limited; they are not a trajectory or no-damage proof.

## Identity, execution and uncertainty

Every request binds the profile, native session, world generation, player UUID, owner UUID/generation, action UUID and native observation challenge. Payload mismatch rejects; duplicate ID plus exact payload returns retained state without re-enqueue or reapplication. Observation admission and first sample bind <=250 ms / <=5 native frames and the source pose; obtaining a fresh observation does not change an existing action's deadline.

A durable queue record precedes enqueue. A durable dispatch fence precedes each possible raw Input write. Stop first invalidates authority, including pending queued input; release only touches the original captured Input, never a replacement owner's Input. Post-tick release and next-pre-tick residual release cover a missed Post. Deadline watchdog cleanup is coalesced to one pending callback per ticket. HTTP timeout/future cancellation is not proof that an operation did not run.

`SETTLED`, `settled`, and `protocol_terminal` describe the **protocol**, not physical rest. A known terminal accounts for input samples and invalidates future samples with release proved. `settlement_state=not_observed` and `gameplay_outcome=not_assessed` remain honest. The observer's `client_tick` distinguishes native frames, not guaranteed physics progress. Displacement and observed rest require separate observations.

Lost/malformed receipts or unproved effect/release transitions remain UNKNOWN. Native unfinished durable records become UNKNOWN on restart; public PENDING becomes UNKNOWN. No endpoint resets it, and no new action ID, owner, session or process settles it. Exact-original stop can still attempt release without clearing the UNKNOWN. A known CLOSED terminal is immutable and is not downgraded by a later diagnostic GET failure. On UNKNOWN only original-ID read/one explicit stop and evidence preservation are allowed; never replay start.

Initial admission-journal failure occurs before enqueue/effect and is explicitly `admission_not_committed_no_input_possible`, with `admission_committed=false` and `no_input_possible=true`; the process refuses further work. Broken storage cannot persist a marker that never reached disk. After committed admission, the pre-existing unfinished journal gives restart UNKNOWN even if a subsequent write fails. Public durable-before-POST recording independently handles lost replies. A stalled native callback cannot be claimed to have physically released input from the HTTP/watchdog thread.

## Isolation and startup/exit

Startup-only `-DmineclientBridge.recoveryShortInputV1=true` plus `-DmineclientBridge.isolatedInput=true` enables the exclusive catalogue. Legacy non-GET mutations and old native owner admissions reject in this mode; old guard semantics remain unchanged outside it. Input controllers such as Baritone must be absent for this initial prototype. No owner is acquired by an observation.

This first package does not add menu/shutdown control endpoints. An explicitly named private TEST copy may be opened using the official `--quickPlaySingleplayer <TEST-folder>` launcher option, with no multiplayer/Realms quickplay options. Native input isolation remains enabled throughout. Normal OS window-close is a lifecycle operation, not an in-world movement fallback; it follows the native save/close path. Both paths have pinned static evidence, but successful startup and cold saving remain live acceptance items. Normal close follows known action terminal/release; an intentional disconnect test must actually overlap the action to count as such.

## Storage and wire

Dedicated authenticated loopback catalogue: `/control/recovery-short-input/v1/{observe,start,status,stop}`. Exact fields, types, duplicate-member rejection, bounds, explicit nulls, owner binding and binary payload digest are implemented by the new codec. See `RECOVERY-SHORT-INPUT-NATIVE-NOTES.md` and `short-input-controller/README.md` for exact schema and commands.

Native ledger is `recovery-short-input-v1.ledger` beside the bridge config, bounded to 256 action IDs, with process file lock, no-symlink policy, forced temp/atomic replacement/parent-directory force. Public persistent ledger uses a separately explicit directory and cooperating-process lock. Never replace/delete either to evade UNKNOWN. No credentials, active ledgers or runtime configs are distributed in source/artifacts. Only the existing operator-held bearer token is used.

## Acceptance and preserved history

1. Offline state-machine/ledger/wire and owner-interference tests; independent source and artifact readback.
2. Separately admitted independent TEST: one **nonempty** finite step, input release and terminal receipt, then actual displacement plus separate two-frame observational settlement check. Receipt success alone is not movement success.
3. Queued/in-flight cancellation, expiry/disconnect, duplicate/payload mismatch, stale owner/stop injection; UNKNOWN cases remain offline fixtures or preserved uncertain originals. Live duplicate start is only for an already known terminal original, never UNKNOWN.
4. Only after those pass: short observed segments in the **actual recovered Nether layout**, not the unavailable later base. No combat.

Original archives remain read-only. The approved 01:20 UTC checkpoint is Nether (-635.7,59,76.7), not the later base. Recovery/test copies are explicitly labeled and are not presented as latest progress. Game operations are solely the appointed operator's after independent review and parent admission.

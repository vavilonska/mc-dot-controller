# Exact-owner paused cleanup

## Confirmed defect

TEST1.2's `Runtime.finish_job()` calls ordinary `observe(allow_menu=True)` before reserving `capability_release`. A normal Escape pause is still rejected because ordinary Runtime state validation requires `paused is False`, and Watchdog `capability_capture()` applies the same gameplay `safe_idle` gate. Consequently a confirmed standalone native disarm can be followed by public `UNKNOWN / cleanup unknown`, even with zero episodes and neutral inputs.

## New bounded path

The gateway advertises `capability_cleanup_observation_schema_version: 1`. A Runtime already holding its exact active lease can issue one `observe` carrying `capability_cleanup: true`. This marker is consumed at the gateway; the Resident receives its existing read-only capability observation. No new native endpoint or Java behavior is introduced.

Before submission, Runtime clears preflight authority and persists an exact `cleanup_observation` record. Gateway enters a one-way cleanup-only state before dispatch. No further ordinary reads, actions, fall controls, fresh owner acquisition, or observation retry can follow that read under this lease. Heartbeats and the original exact release control remain possible while existing lease deadlines are valid. The read never refreshes Runtime's ordinary `_last`/preflight, Watchdog's `latest`, or targeting/navigation admission.

Both layers validate the original context, live session/epoch/lease, neutral inputs, terminal native action, inactive Resident combat, and empty held mappings. A paused exception requires an actual boolean, current external-controller idle proof bound to world/player/action session/tick, empty held keys, integer zero raw keys and integer zero world mouse buttons. Missing, numeric, string or otherwise malformed pause is rejected. Focus, private singleplayer, living player, and known screen state remain mandatory. Normal active-only legacy clients retain their preexisting compatibility rules; ordinary gameplay still requires `paused is False`.

When native fall state is present it must be disarmed, input-neutral, not automation-blocked and not quarantined. A closing owner's native status requires the previously confirmed original disarm status: exact arm/owner/context, same arm revision and episode count, and monotonic evidence. A later replacement arm, missing prior disarm proof, or foreign context cannot settle the original owner. Optional advertised/present external-navigation and managed-navigation status must explicitly report unowned and non-quarantined with the correct schema; a clear external API alone does not override these owner fences.

The same existing single `capability_release` operation requires the fresh cleanup proof and an idle, unchanged Resident session. An explicit paused proof clears only the old lease and latches `needs_operator` / `capability_owner_released_while_game_paused`. It never sends an unpause, cancel, release-all, movement, or automatic resume. Active-world cleanup keeps the normal release behavior. Any unknown read or release response retains its exact identity, blocks further work and is never retried. A previous generic observation/lease/handoff fault is not reopened through this path.

## Historical original job

Job `TEST1_2_ORIGINAL_PAUSE_JOB`, native arm `TEST1_2_ORIGINAL_NATIVE_ARM`, remains historically `UNKNOWN / cleanup unknown`. Its exact archived read `TEST1_2_ARCHIVED_CLEANUP_READ` satisfies the new *neutral-at-capture* proof. No release was reserved for that job. This historical sample does not prove present ownership release and cannot be used to rewrite its result or authorize replay/resume. The existing `reconcile_original` only reads exact original receipts; this patch does not expand it, mutate its journals, or use a restart as settlement.

The results directory includes a hash-verified offline diagnostic over that archived receipt. It constructs no Runtime and never touches game control. Original inputs are hashed before and after reading.

## Verification and integration

Production-chain tests use the real public service, Runtime, IntentClient, Watchdog, QueueClient, and Resident; only the native endpoint is simulated. Coverage includes explicit pause, normal active repeated jobs, unknown/malformed pause, foreign world/rescue owner/gateway session, missing prior disarm, changed revision, external unknown, held input, native automation blocking, managed-navigation ownership, stale proof, unknown cleanup/read and release acknowledgements, no repeated reads/releases, no ordinary preflight, no new owner acquisition, and rejection of a malformed marker or a smuggled action.

No GUI, real game, process control, native build, deployment, repository push or original-world changes are performed by this patch. Live acceptance must use a separately controlled TEST ONLY run and retain the original failed receipt unchanged.

The TEST1.2 base is declared in the results manifest. Broader attached-fall or recovery unions must preserve unresolved original actions and native quarantine. Their separate original-owner adjudication is not part of this cleanup lane. Integration must re-run tests after semantic union, particularly `core.py`, `capability_ownership.py`, and the new shared proof helper.

## R2 release commit fence

R1 was frozen and independently reviewed. Its ordinary checkpoint-before-clear sequence allowed a delayed checkpoint to age out the proof, or a checkpoint callback to stop/replace the owner, before the subsequent unconditional local lease clear. A separate R1 reproduction retains all three failures; R1 is not the final integration candidate.

R2 first durably records the exact original release intent with the active lease. It then reads the Resident session and performs a final no-I/O fence immediately before clearing the specific in-memory lease: object identity, owner/context/epoch/session, original read IDs and proof value, age, lease/heartbeat deadline, active state, no outstanding native arm/transition/owner/RPC, no stop, and no handoff/input-release latch must all still match. A failed fence preserves a replacement and never writes a released tombstone. A repeated unknown release is not attempted again.

After the local release, admission stays temporarily latched while the released tombstone is persisted. Failed persistence leaves UNKNOWN and never re-enables admission. A second state/session check after that blocking commit refuses to overwrite a stop, changed epoch/session, replacement owner or new handoff. The pause decision uses the immutable consumed proof, so a later mutation cannot turn paused cleanup into gameplay admission. Successful active cleanup returns to its existing watching behavior only after the durable commit; paused cleanup remains `needs_operator`.

## R3 routing refinement

Cleanup release is routed directly to the R2 helper before the legacy release's Resident session read. The helper's post-preparation read is the sole pre-release read; all R2 exact fences and durable-commit behavior remain unchanged. This removes the redundant earlier read boundary where a replacement/stop could install a newer durable checkpoint before the old-owner preparation overwrote it. A direct production-method regression installs that new checkpoint during the first read and verifies its bytes remain the current durable record, as well as verifying no replacement is cleared.

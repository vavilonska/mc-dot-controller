# One-shot supported-dock entry guard

This small helper addresses one failure mode: the first fresh entry assertion
after resume throws, but the Python process returns/reports before requesting
pause. It protects only the stable-dock phase **before any mount or drive was
submitted**. It neither resumes nor mounts/drives; no new runtime/API is needed.
It does not protect swimming waits, a frozen Python/client/transport, an existing
boat action, or already-mounted drive preparation. Do not apply `on_ground` to a
normally seated player. Existing known mount-success/release evidence and later
boat operation remain separate; no current rider state can manufacture that
missing success evidence.

The designated sole operator supplies its existing QueueClient and the currently
verified resident/action/world/player identities. Do not construct another
producer, switch queues, use a watchdog-owned queue directly or reinitialize a
failed case. Independent scene review must establish stable solid support, full
air and a safe standing area. `on_ground` plus an evidence reference does not
compute/prove the supporting block or authorize creating a dock.

1. While actual native PauseScreen is open, world paused, native action idle,
   queue empty and all known inputs neutral, construct `BoatEntryGuard`. It reads
   fresh state, checks on-ground/alive/HP20/air300/eye above the water, and writes
   one exclusive fsynced queue-scoped reservation. That record consumes the case
   even if its process later disappears. The missing action ID is deliberately
   never submitted as a boat/combat action. The pause request ID must not already
   exist in inbox, working or results.
   Resident itself must be `ready` with an explicit null reason; this differs
   from the native game being paused. Foreign paused/unknown/STOP reasons refuse
   preparation and success. Only readback after this guard's one pause attempt
   can accept `encounter_pause_requested` or `encounter_pause_unknown`.
   The shared pure `validate_store` check must find every older guard phase
   definitely closed before another distinct case may be prepared. Empty,
   partial, orphan or unknown records refuse construction before another read.
   Changing case ID or restarting to a ready descriptor cannot bypass an
   unresolved prior guard. A known closed guard permits a new separately
   authorized case; it does not authorize it or prove any later boat action.
2. Only then perform the separately authorized existing resume step. The helper
   has no resume option. In the **same Python process**, immediately call `check`
   before exporting state, writing reports, returning to the model or submitting
   mount/drive. Put every read-only entry assertion in its callback, raising an
   exception (or returning False) for any failed condition. The callback must not
   submit an action, perform a look/use/move, write reports, wait for input, or
   contact another tool/process.
3. If fresh read or entry assertions fail, the helper attempts exactly one
   existing `op: encounter_pause` before its result report. Known foreign/unknown
   owner, changed identity, corrupt reservation or reused queue ID blocks that
   write. The native endpoint still performs its own final identity/owner checks.
   It cannot be used to stop a running boat. No retry, cancellation, raw Escape,
   alternative ID, or automatic resume is allowed after any pause uncertainty.
4. After that attempt only reads follow. Require actual PauseScreen + native
   paused + complete neutral-input evidence; a screen-installation acknowledgement
   alone is insufficient. Missing action acknowledgement retains
   `expected_action_present:false`, `client_action:null` and
   `input_release_confirmed:null`. It does not pretend an action or release took
   place. Newly held inputs may yield an observed pause but failed neutral-input
   verification; do not claim cleanup or continue.

Invocation shape (illustrative; not live authorization):

```python
from boat_entry_guard import BoatEntryGuard

guard = BoatEntryGuard(existing_queue_client, approved_case_id, current_binding,
    surface_y=verified_water_surface,
    support_evidence_ref=reviewed_solid_dock_evidence,
    pause_authorization_ref=explicit_pause_permission)
# Existing separately authorized resume happens here, in this same process.
# No game action, slow export, report or model handoff between resume and check.
def entry_assertions(observation):
    # Check the exact observed existing boat, reach, empty main hand, scene, etc.
    # Raise on failure. This callback is read-only; do not send mount/drive here.
    assert reviewed_entry_conditions(observation)

result = guard.check(entry_assertions, main_action_submitted=False)
if not result['entry_ready']:
    # Report/handoff now. Do not replay check(), resume or any game action.
    return_to_operator(result)
# True is only a fresh pre-action check. It is not mount/drive admission or success.
# A later action, if separately authorized, still uses its own original ID/budget.
```

`main_action_submitted` must be the actual caller state, not a constant used to
bypass scope. The helper independently requires all observed native actions to
remain idle/null, with no retained terminal action, and resident work empty.
It is intentionally restricted to that clean native-idle first-entry state;
it will not itself restart a session to obtain it. It is not a persistent monitor after a safe
return. The exact reservation is not reloadable; use the same live object once.
Do not change the case ID to recover from uncertainty. Reports preserve raw
receipts in memory until pause/reconciliation, then use the existing exclusive
`_write` format. A result-write failure cannot reauthorize another attempt.

Durable store: `<existing queue root>/boat-entry-guard/<case_id>.reservation.json`
and `<case_id>.result.json`, each with the existing `.sha256` sidecar. Both use
`boat_entry_guard_schema_version:1`, and bind case ID, the four session/world/
player identities, `pause_request_id` and exact pause command. A reservation
without a verified matching result, a pause attempt without acknowledgement, or
unconfirmed actual pause/neutral state is unresolved. Normal restart must not
discard these records merely because mailbox result retention expired. This
module does not implement restart, archive, reset or an uncertainty-resolution
capability; the existing restart policy must inspect this specific store.

`validate_store(queue_root)` is the one shared read-only validator for guard
construction and rollover. It returns `present`, `files` (queue-relative path to
SHA256, including all four files per case), `entries`, `consumed_request_ids` and
`main_action_evaluated:false`. Each entry has case ID, four-identity binding,
pause/missing-action IDs, raw request IDs and outcome `entry_ready` or
`paused_on_entry_failure`. It recomputes receipt/body/timing/identity bindings,
full before/final observations, actual pause and neutral inputs. It rejects
missing/partial/unknown records instead of accepting a saved success flag.
Raw entries retain resident descriptors before/after each read and wall/monotonic
start/finish times. The validator checks nondecreasing request order as well as
each receipt, so an old paused read cannot supply post-pause effect evidence.
The real 32-character `Resident.session_id` is preserved exactly; native
world/player/action-session UUIDs still use the existing strict native contract.
File pins are rechecked before return. Rollover must reuse this function and
retain/verify the pins; do not implement a looser second interpretation.

The consumed-ID set prevents local ID alias/reuse; it is not an authorization
service. Evidence/authorization references are required nonempty provenance
strings, not validated permissions or one-use approval tokens. The caller must
obtain authorization for each later case. Reusing a reference string cannot
create that authority. `entry_ready` closes only this guard phase; existing
main-action uncertainty and restart rules still apply independently.

Read/wait checks use the existing three-second observation limit. The one-shot
pause request may itself block or fail; this is cooperative software, not a
hard-real-time guarantee. Only a separately approved stable dock should ever be
resumed. The failed floating-entry world and its evidence remain untouched.

Offline check: add this harness directory and the candidate `resident-controller`
directory to PYTHONPATH, then run `python -m unittest discover -s safety_tests
-p test_boat_entry_guard.py -v`. All test identities are synthetic. No game or
queue operations against a live environment are included in these tests.

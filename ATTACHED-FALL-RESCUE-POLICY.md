# Attached ordinary-job fall policy, stage two

Source-only additive version: `native-fall-rescue-attached-policy/1`.
Declared base: first integrated TEST1 source manifest SHA256
`073c5447c88863194ab5bc6edd1ab483dd815ac04e215d78eeb91ee006f45bf0`.
No native Java changes; uses the reviewed native rescue and single-input arbiter.
No live-game acceptance or guaranteed rescue claim.

## Public activation

An ordinary `mdc_job` submit may include:

```json
"policy": {
  "version": 1,
  "execution_mode": "request_only",
  "reactions": "stop",
  "fall_rescue": {"schema_version": 1, "water_bucket": true}
}
```

Use the gateway's existing matching execution mode (`guarded` for its standard
mode). Supported public capabilities are `navigate_local`, `navigate_step_down`,
`navigate_route_local`, and `engage`, subject to their existing native profile
availability. This policy cannot enable an otherwise unavailable capability.
The catalog's `fall_rescue_availability` declares the precise supported subset,
fixed reserve, absence of renewal, and unsettled-original limitation.

No caller can choose native action IDs, arm IDs, preemption lists, or owner
bindings. Runtime derives the envelope from the current job owner and scoped
profile. Gateway derives the sole permitted native action ID and arm ID from
its actual queue request ID and Resident session. Resident validates that exact
binding before any arm. The ordinary action and local rescue share this one
original owner job. No second Python controller or background writer exists.

## Timing and budgets

Each supported native movement/combat action is armed before its one dispatch.
Its grant is the action's full original timeout plus a fixed 10,000 ms rescue
reserve. The original job deadline must still cover that full grant plus
2,000 ms orchestration margin. The action timeout and rescue reserve are never
silently shortened. The authorization uses the same-host monotonic deadline
and must fit the existing gateway lease; no clock comparison with game ticks.

The job prepays two ordinary action budget units for arm and eventual disarm,
in addition to its existing ordinary action cost. No renewal or heartbeat
extension is sent. Rescue settlement uses at most 128 internal native status
reads and is bounded by the original fixed grant plus one second. These are
internal control-protocol reads, analogous to existing native action polling;
they do not consume additional public world-observation budget units.

Native ticks can react during Python waits within the already granted fixed
lease. The grant cannot be extended after a Python stall. Expiry and unknown
receipts do not authorize a new owner. The normal serialized public cancel
waits for any outstanding owner-thread HTTP call; native GUI pause/stop remains
the immediate game-thread stop path. No heartbeat is claimed to make a stalled
Python controller timely.

Selection/menu setup steps are explicitly unprotected. Managed Baritone,
boats, swimming, pearls, building/mining, automatic defense escalation, and
other profiles are not covered. Each route segment receives its own bounded
exact-action grant; no grant persists across settled segments or jobs.

## Settlement and cancellation

A normal action terminal is read, then its exact guard is disarmed and verified
before ordinary postconditions or lease release can continue. A lost arm or
disarm response is never retried; no generic cleanup replaces an uncertain
original request.

If rescue preempts the action, Resident retains the original task and delays
its terminal publication while native rescue owns input. It only polls that
same bound status. When native rescue ends, the original result and strict
monotonic episode proof are sealed together and archived under the original
request. Client prediction, server water/bucket evidence, and later alive
landing remain separate. Rescue success never proves the interrupted action's
semantic outcome. Explicit user cancel disarms only that known arm once, then
uses only the exact original action cancellation if still necessary. Legacy
Resident cancel/shutdown/release-all and Ctrl-C use that same bound stop path.
Unrelated direct/task/resume takeovers refuse while the attached owner or its
uncertainty remains. Unexpected generic termination paths retain the original
UNKNOWN instead of publishing a premature cancelled receipt.

The reviewed native preemption receipt currently declares the old action
`unknown_interrupted`. Stage two faithfully preserves that historical UNKNOWN,
keeps quarantine/ownership, and never automatically resumes/replays the old job.
Read-only original-ID reconciliation can collect evidence but cannot clear
that authority. A separate explicit original-owner adjudication operation is
still required for a reusable post-rescue loop. This stage alone must not be
advertised as operationally reusable after an interrupted action. It does not
provide a journal-edit, new-session, or blanket UNKNOWN override.

## Evidence and tests

Production Python owner/gateway/Resident paths and the actual Node MCP front
door are exercised with a modeled native endpoint. The strict episode rows
come from the already reviewed production pure `FallRescueEpisode`/Gson model
fixtures; these tests do not run Minecraft. Callback fault tests cover old
owner replacement during arm/status/disarm, pause during arm, finish callbacks,
expired grants, exact bindings, evidence regression, and forged proof fields.
Native effect, packet, bucket, external-controller, and pause fences are
unchanged from the first integrated TEST1 artifact.

## Integrated owner coverage

Protection applies only to the exact same-owner native `follow_path` and
`combat_entity` actions. Managed Baritone walking has a separate owner and
rejects attached fall policy. Symmetric final admission/effect fences prevent
a new fall arm from overlapping a STOPPING or UNKNOWN external/managed lease,
and prevent those leases from starting over an armed or quarantined fall owner.
They never clear another owner or add cross-owner preemption.

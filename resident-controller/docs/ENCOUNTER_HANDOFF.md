# Frozen-v18 encounter consumer boundary

This mainline slice adds the exact frozen-v18 encounter contract validator and
selective consumer wiring. It keeps main's existing `NativeCombat` service byte
for byte; the default watchdog does not switch to the new bounded native engine.
The only new opt-in is raw `op: action`, `action: combat_entity` with the strict
`two_zombie_retreat_v1` scope. The native JVM gate remains disabled by default.

## Ownership and terminal meaning

The resident creates one stable native step ID under its queue request ID.
It validates schema, native action ID/session, action kind, world, target and the
ordered original two-zombie scope. A bounded success is only the original
three-sample clearance claim. It never means the encounter is safe, that either
zombie died, or that a subsequent action is authorized.

All new encounter task terminals carry `risk_remaining: true`,
`requires_handoff: true`, and `safety_assured: false`. The original native status,
reason and receipt remain available. Known admission rejection does not cancel
or replay. Unknown acceptance is never retried; the existing one different-ID
cancellation attempt is session-bound and cannot turn the task into success.

The watchdog holds legacy defense/environment/ranged work while this explicit
encounter owner is pending. It latches on the final handoff even when release is
confirmed. Explicit non-true release evidence retains higher priority. The
cursor keeps its pending intent for inspection and stops; play helpers raise
instead of returning the bounded success to an automatic recipe.

A successful read containing a historical encounter receipt alone does not
create a new terminal handoff. The resident does expose a separate current
`requires_handoff: true` observation flag while an encounter is active or its
operator handoff remains paused. A restarted watchdog consumes this flag before
any tactical work. This closes the reproduced restart path that otherwise
issued automatic cancel/release-all and cleared the resident pause. An explicit
operator resume/takeover remains a separate request under the existing rules.
The watchdog's dedicated latch itself is not cleared by a phase refresh.

## Verification and remaining surface

The tests use a real Resident mailbox, QueueClient, watchdog and cursor with
fake native I/O. Five fixture states were emitted by the actual Java bounded
encounter/registry code offline. At the fake boundary only the native step ID
and the running fixture's session are adapted to the real resident request;
this is not an unmodified native-wire or Minecraft physics claim.

Native `POST /control/pause` and the `encounter_pause_on_terminal` hook are wired
and tested. Resident's generic transport/direct allowlist and the MCP tool
surface are not widened to add a standalone pause producer in this slice. A
pause screen installation remains distinct from confirmed world pause. No live
encounter, callback timing, Windows/PowerShell, or game safety acceptance follows
from these offline tests.

The complete frozen cross-slice IntegratedCandidateContract and
ExpeditionPrerequisitesContract tests remain deferred until the container group
is present; they were not trimmed or reported as passing. The optional
RetreatClassInitialization startup warmup remains deferred. This slice makes no
cold-start or JIT performance equivalence claim.

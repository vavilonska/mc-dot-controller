# P2: selective three-zombie contract integration

This source extends the frozen v37 c41 mainline with the already reviewed
`three_zombie_retreat_v1` candidate capability. The original two-target mode is
still exact and has its own default-off feature property. The new three-target
property also defaults to false. This package does not enable either property,
start an operator, register a live case, create a queue, or deploy a JAR.

The production delta is limited to six native files (ClientActions only selects
the original mode-specific gate), two Resident codecs and two MCP codec/schema
files. Root recovery timeout0, default NativeCombat, stable mining/placement and
crafting, environment/adaptive cursor, terrain tick-reversal hard rejection,
current release/handoff policy, menu recovery and controlled-step owner/native
sample guards remain intact. The existing eight MCP tools are retained.

Three-target mode requires exactly three distinct canonical zombie identities.
It retains the original 4-block/60-tick/3-second budget, 12-block origin fence,
8ms planning check and 150ms observation policy. Approach, shield and offense
remain disabled. Its additional bounded projectile observation must be known
and zero before planning; any projectile, unavailable/truncated/stale evidence
stops the case. This is not arrow defense or support for mixed enemies.

The explicit callable path is the existing PostTrialSafety.register_active_case
with the new mode, followed by EncounterBinding and
active_case.run_registered_three_zombie_case. The host supplies the operator and
queue explicitly. One request owns the original action identity and budget;
unknown outcomes are not replayed. Exact three-UUID closeout remains a separate
operator-authorized phase after known terminal/release and paused observation.
No existing consumed NoAI, active-AI, boat or controlled-step case may be replayed.

The fixed harness includes its required session-rollover/boat-entry dependency
closure. A pure gate_probe_contract module and a synthetic status fixture reuse
only the original require/probe_body/ownership functions and fixture constructor;
no gate-off observation/dispatch implementation or Resident route was added.
The retained gate_off_case reference is not an enabled root probe operation.
Historical gate-claim validation is required so rollover cannot revive consumed
or uncertain old requests, even though no new gate-off case runs here.

The integration evidence package records exact baselines, new test execution,
source/JAR hashes, original failed runner invocations, and independent review.
Native-generated synthetic receipts are checked by actual Python and JavaScript
codecs. Additional tests reuse the unchanged real Resident/Queue/Watchdog/Cursor
and pause-policy assertions with three-target data, including late receipts and
release failure. Synthetic I/O is never represented as live game evidence.

The official optional real-loader configuration is retained from v36. Its seven
container object/registry gates have an actual loader entry; default skips are
reported separately. Real Windows/PowerShell remains unverified.

The earlier c41 JAR passed one separately authorized adjacent-target game case.
Any JAR rebuilt with this P2 change has a different identity and no three-zombie
live acceptance. New combat, mixed enemies, dragon combat, boat-drive and
conditional construction remain subject to their concrete case plans and the
original taskbook's prerequisites. This source change does not authorize them.

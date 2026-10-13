# Current resident policy during failed or pending observations

A new watchdog must not issue automatic cancel/release-all merely because its
first observation failed or remained pending while an encounter owns inputs or
an operator handoff is paused. The raw read error and the original action
ID/body/outcome remain unchanged.

Resident publishes a typed resident_policy object in its existing session file,
before observation reads and before an encounter POST. It also returns that
policy on a protected failed observation without clearing the reason, pending
commands, active task or inputs. Policy derives from current active/pending
encounter work or the current pause/release state, not an old action receipt.
A genuinely ready resident after explicit resume therefore remains compatible. Successful observations use the same policy predicate, including an encounter already pending before its native POST.

Before automatic observation-failure cancellation, Watchdog requires current
policy from the same pinned resident/native session. Missing, malformed,
wrong-session, future or older-than-three-second publication stops the watchdog
without sending a mutation. This is resident liveness metadata, not Minecraft
terrain/position freshness, a release acknowledgement, or a retry authority.
The three-second bound accounts for the existing one-second publication and
two-second pending-observation threshold; no game guard is relaxed.

An allowed automatic fallback carries an explicit marker and resident session.
Resident rechecks current policy when that command is processed, before any
local interruption or native input mutation. A new encounter queued after an
earlier clear policy therefore cannot be cancelled by the delayed fallback.
Explicit operator cancel/stop retains its original unmarked path.

The production file mailbox always has QueueClient.session. The original
non-mailbox duck interface used by the old offline watchdog tests is preserved;
a real session read error never falls back to that compatibility path.

Verification uses synthetic native I/O with the actual Resident, QueueClient and
Watchdog. The four independent restart counterexamples, policy corruption and
staleness, the admission race, original non-encounter cleanup, historical-receipt
and explicit-stop positive cases are covered. No JVM, game action or deployment
is part of this repair. The separate seven real NeoForge lifecycle tests remain
unfulfilled and are not counted as passing here.

Successful snapshots carry the same typed resident_policy. With that field
present, the watchdog classifies handoff/release from current policy only; an
old raw cleanup_failed receipt cannot label a newly admitted encounter as
unreleased. False policy flags are not input-release confirmations. The legacy
no-policy snapshot shape keeps its prior compatibility path.

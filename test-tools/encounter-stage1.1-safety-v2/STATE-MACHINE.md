# Exact v2 safety state and authority boundaries

All states below describe local reviewed evidence, not promises about a remote
world. There is no automatic transition to active AI, a new attack or a new route.
Authority references are retained audit references; the sole operator must still
have actual current owner authorization for the concrete action and targets.

## States

1. UNREGISTERED: no NoAI batch. Read-only preflight is permitted; encounter
   admission is refused. Constructor alone writes no ledger and sends nothing.
2. REGISTERED-NOAI: exactly two canonical zombie identities/positions, explicit
   per-UUID NoAI evidence, fresh complete local observation and full 20 HP. A case
   and owner authorization are recorded. No ordinary setup/chat command is granted.
3. TRIAL-RESERVED: immutable original Binding, final command, name and report path
   are registered. One original native step ID is planned; this is not admission.
4. TRIAL-DISPATCH-CLAIMED: claim is durably written before the original submit.
   It cannot be claimed again. Moving output, reconstructing Operator or changing
   request name does not renew it.
5. RUNNING-EVIDENCE: the original request/native owner is strictly observed running.
   A separate one-use same-owner cancel permit may be issued only with explicit
   stop authority. The main receipt and owner are rechecked at claim time; a
   visible terminal consumes/rejects that permit without a cancel dispatch.
6. KNOWN-HANDOFF: the persisted original report is re-resolved as bound terminal or
   complete explicit null admission and release is observed. Ordinary mutations
   stay blocked. Only the narrow post-trial capabilities may now be considered.
7. CLEANUP-IN-FLIGHT: one exact registered UUID's own intent exists. One submit and
   one wait are allowed. A successful dispatch is not yet a cleanup effect.
8. CLEANUP-EFFECT-RECORDED: one fresh, identity-bound, complete same-area observation
   proves exact target death/health0 or qualified local absence. Original report
   and old locks remain immutable. The second UUID has its own independent intent.
9. PAUSE-RECORDED: native PauseScreen plus paused is observed. If already paused,
   no toggle is sent. A raw-key click, if needed, has its own intent/receipt/effect.
10. CLOSED-FOR-REVIEW: prior trial known/released, both precise cleanup effects,
    current pause/no residual fixture/no active or pending activity are verified.
    This is not an ordinary action permission. Only a distinct, explicit owner
    authorization can register a future independent NoAI case in a new output,
    retaining the same shared ledger and all historical locks.
11. UNKNOWN-OR-STOPPED: ambiguous main POST/terminal, invalid or missing release,
    changed identity, corrupt/missing authority history, failed/unknown safety
    dispatch/effect, missing coverage or other contradiction. No ordinary mutation
    or safety retry is permitted. Independent operator CUA Escape rescue can be
    recorded, but that record alone does not resolve the unknown or unlock anything.

## Orthogonal health latch

Before/running/after health is tracked by one non-resettable HealthStopGuard.
Any decrease and any missing/untrustworthy window latches STOPPED-SAFETY. Healing,
native success, known terminal, cleanup, pause and future registration do not
rewrite that old trial. If a current bound running owner is known, an authorized
one-use stop may be attempted; otherwise only the operator's independent rescue
path remains. At most native limited evidence is retained, with
controlled_trial_accepted=false throughout.

## Allowed transmissions

- Normal trial: exact previously reserved one-step command, once.
- Running stop: exactly {op: cancel}, distinct permitted request ID, original owner,
  fresh bound running proof, then final owner/result checks, once.
- Post-trial UUID closeout: exactly direct/command with `kill <canonical UUID>`
  built internally from verified registration and original Binding, once per UUID.
- Post-trial pause: exactly direct/raw-key, key.keyboard.escape, click, after proving
  it will not blindly unpause an already paused game, once.
- Independent rescue record: no transmission; append operator evidence only.

No arbitrary body, selector, chat command, teleport, new combat, retargeting,
planning, gate toggle, launch change, unpause or broad cleanup is exposed.

## Evidence and tampering

Registration, reservation, original report, resolution, intent, raw receipt and
effect are separately immutable records. Their hashes and cross-record identity/
scope/command relations are rechecked. A mutable summary flag cannot become
cleanup permission. Case history is anchored so a renamed/deleted case cannot be
mistaken for an unused ledger. Damaged history fails closed; the tool does not
repair, clear or reset it automatically. This is local tamper detection, not a
claim of security against an actor rewriting all executable code and filesystem
trust material.

Every bound terminal in the report's intermediate samples must agree with the
final bound terminal. Such a sample also contradicts a later null admission
rejection, even if no running sample was captured. Recording and reopening the
ledger use the same check: a contradiction blocks narrow closeout, and a sample
cannot upgrade an unknown response into a known outcome.

## What remains outside the guarantee

Read/submit sequences are not atomic across processes. A last instant owner,
window or world change may occur after a check. Local nearby is bounded and cannot
prove global absence. Pause may prevent a single-player server from processing a
command until a future explicitly authorized intervention. Physical movement and
release follow client scheduling, not a hard 8ms/150ms/3s deadline. All current
proofs are synthetic/offline; one future NoAI rehearsal must establish actual
operation before any separately approved active-AI proposal.

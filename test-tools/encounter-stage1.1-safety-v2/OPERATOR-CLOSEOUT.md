# Append-only active operator closeout

This registers already completed, separately authorized operator work. It never sends kill, pause, resume, cancel or a new encounter. No resident, JVM or game restart is needed: import the updated harness in a fresh short-lived Python process, keeping the current queue/session and fixed ledger.

## Required evidence and result

`record_operator_closeout(case_id, *, native_terminal, before, cleanups, final_observation, authorization_ref, evidence_ref)` accepts only an active case whose original immutable report recomputes to a known, released, bound native terminal and whose fixed STOP reason is exactly `active_case_requires_separate_operator_closeout`. Unknown original outcomes and other STOP reasons remain blocked.

- `native_terminal`: exact original native terminal, not a rewritten summary.
- `before`: `{intent, receipt}`; receipt is the operator wrapper `{started_monotonic, finished_monotonic, receipt:<resident envelope>}` for a complete paused/released observation.
- `cleanups`: exactly two ordered `{uuid, dispatch:{intent,receipt}, effect:{intent,receipt}}` entries, in registered scope order. Each dispatch must be the known successful receipt for `kill <that exact UUID>`. It remains a submitted ACK, never a death proof.
- Each separate effect observation must prove that exact previously living target now has `alive:false` AND numeric `health:0`, at the same position, with the same complete player-centred coverage. Absence, unfamiliar identities and contradictory alive/health values are rejected. A visible dead corpse is valid evidence. Earlier verified deaths must remain consistent.
- `final_observation`: the unwrapped final effect result, exactly matching the last effect. All observations retain the same original action/world/player/session, actual native PauseScreen, release and known living-player health. Monotonic evidence must follow the original trial, be ordered/completed, and use one clock domain.

The method performs one fresh read through the existing queue to confirm pause, release, identity, coverage and no living original targets, then exclusively creates `operator-closeout.json` and its checksum. It preserves the original report, resolution, STOP and anchors. All gameplay-success flags stay false; no ordinary mutation permission is granted. Later disappearance cannot replace the required earlier positive death observations.

A separately approved next independent registration in the SAME ledger revalidates the closeout proof and its source hashes plus another fresh paused observation. It requires a new `previous_case_authorization_ref`, distinct from old case/closeout authority. Do not change ledger/output paths, delete history, reuse a request, or treat registration failure as permission to restart.

## Existing A evidence adapter (execute only under the actual closeout approval)

Add the updated harness and candidate resident-controller directories to PYTHONPATH. The following uses actual existing A artifacts; it does not perform the cleanup again. Supply the real approval reference as `APPROVED_CLOSEOUT_REF`.

```python
import json
from pathlib import Path
from types import SimpleNamespace
from resident_controller.ipc import QueueClient
from post_trial_safety import PostTrialSafety

root = Path('/path/to/operator-source')
evidence = root / 'evidence'
load = lambda name: json.loads((evidence / name).read_text())
pair = lambda name: {
    'intent': load(name + '-intent.json'),
    'receipt': load(name + '.json'),
}
binding = load('binding-before-dispatch.json')
queue = '/path/to/owner-approved/queue'
operator = SimpleNamespace(
    c=QueueClient(queue), out=root / 'case-output',
    resident=binding['resident_session'], session=binding['action_session'],
    world=binding['world_generation'], player=binding['player_uuid'],
)
safety = PostTrialSafety(operator, Path(queue) / 'safety-ledger')
result = safety.record_operator_closeout(
    'active-ee2cc9fcbd9e455abf508221cc7c7504',
    native_terminal=load('actual-native-receipt.json'),
    before=pair('manual-closeout-before'),
    cleanups=[{
        'uuid': entity['uuid'],
        'dispatch': pair('manual-cleanup-' + str(i)),
        'effect': pair('manual-cleanup-proof-' + str(i)),
    } for i, entity in enumerate(binding['encounter_request']['encounter_scope'])],
    final_observation=load('manual-closeout-final.json'),
    authorization_ref=APPROVED_CLOSEOUT_REF,
    evidence_ref=str(root / 'operator-closeout-evidence-hashes.json'),
)
```

A's original `failed / retreat_planning_budget_risk_remaining` remains failed. This registration means only that its separate operator closeout has been evidenced; it does not turn the zero-movement attempt into successful retreat, pursuit acceptance or a retry permit. If any original evidence, current session, paused state or effect cannot be verified, retain the stop and report the specific blocker.

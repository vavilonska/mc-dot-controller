> Publication context (2026-10-18): Recovery 2.5 source and its version-qualified acceptance are now recorded in [the current publication note](docs/recovery-2026-10-18/README.md). The text below is the historical candidate/change record; its unpushed or live-pending statements describe that earlier checkpoint. Historical failures and UNKNOWN outcomes remain unchanged.

# Recovery TEST2: upgrade and public calls

This build targets the pinned private, unpublished single-player Minecraft 1.21.1 / NeoForge environment. Keep the original world and use a clearly labeled independent test copy. Code is **not pushed to GitHub**. The release's `RELEASE.json` and `artifact/RUNTIME-SOURCE-MANIFEST-FINAL.json` supply the exact version, JAR/source hashes and paired verification instructions. Install the source runtime and native JAR as one cold, verified pair; use only the pinned official Baritone API variant, never API and standalone together. Use the separately reviewed operator startup recipe, with bytecode writes disabled.

## Start with discovery

Call `mdc_catalog` with `{"api_version":"mdc.toolbox/1","detail":"contracts"}`. Use the returned `runtime_binding_availability.session_ref` and `context_ref`, and confirm that the requested capability is supported. All examples below use the matching `request_only` gateway policy. They do not switch an existing gateway's policy.

Replace `NEW_REQUEST_ID`, `SESSION_REF`, `CONTEXT_REF`, `JOB_ID`, `NEW_CANCEL_ID` and observed target/goal placeholders before use. IDs are caller-created unique identifiers for new intents, or exact values copied from an existing response. Never invent a native action, arm, episode, owner or receipt ID.

Every submit uses `mdc_job` and this envelope:

```json
{"api_version":"mdc.toolbox/1","operation":"submit","request_id":"NEW_REQUEST_ID","session_ref":"SESSION_REF","expected_context_ref":"CONTEXT_REF","capability":"CAPABILITY","capability_version":1,"arguments":{},"policy":{"version":1,"execution_mode":"request_only","reactions":"stop"},"budgets":{"max_actions":8,"max_observations":80,"deadline_seconds":40},"wait_ms":0}
```

Use one of these exact capability/argument replacements:

- Standalone fall guard: `fall_rescue_guard`, `{"duration_ms":10000}`; use budgets `max_actions:16`, `max_observations:64`, `deadline_seconds:20`. A water bucket must be in the hotbar. The guard occupies the sole job owner.
- Attached native movement: `navigate_local`, `{"goal":{"x":OBSERVED_X,"y":OBSERVED_Y,"z":OBSERVED_Z},"min_health":14}`; retain the default example budgets and add `"fall_rescue":{"schema_version":1,"water_bucket":true}` to policy. The destination must satisfy the capability's one-cardinal-block native movement contract. Discovery also lists the precise supported attached subset.
- Shield-only defense: `defend_local`, `{"target_uuid":"OBSERVED_TARGET_UUID","window_ms":1000}`; retain the default budgets. `evade_local` instead accepts the observed target plus `window_ms`, `max_distance` and `minimum_separation_gain`. Neither mode attacks or establishes that danger is gone.
- Managed walking: `navigate_managed_walk`, `{"goal":{"x":OBSERVED_X,"y":OBSERVED_Y,"z":OBSERVED_Z},"max_distance":20,"timeout_ms":10000,"min_health":12}`; use budgets `max_actions:3`, `max_observations:100`, `deadline_seconds:30`. The pinned actual input transform must be ready. **Managed walking does not support attached fall rescue** and rejects that policy. It can load normal chunks but does not certify future terrain; doors/use/attack, boats, swimming, flight and portals are outside this walking scope.

Attached protection applies only to the exact same-owner native `follow_path` or `combat_entity` action. Setup/selection steps and other owners are unprotected. Standalone guard and managed walking cannot overlap. A retained STOPPING or UNKNOWN lease blocks a new conflicting owner even if Baritone currently looks idle.

## Status, cancellation and UNKNOWN

Status is a read using the exact original job and session:

```json
{"api_version":"mdc.toolbox/1","operation":"status","session_ref":"SESSION_REF","job_id":"JOB_ID","wait_ms":0}
```

Explicit cancellation uses `operation:"cancel"`, the same job/session, a new `cancel_request_id` and `wait_ms:0`. A cancel acknowledgment alone does not prove input release. Wait for the original job's effect/cleanup certainty and retained native evidence. Native GUI pause stops input immediately; the public cleanup-only proof can close the original paused owner but does not unpause or authorize ordinary work.

For UNKNOWN, preserve the original IDs and receipts. Do not repeat the gameplay submit, create a replacement mutation, resume a paused task or edit journals. `mdc_job` operation `reconcile` reads the retained original evidence using the same job/session. A separate diagnostic read is:

```json
{"api_version":"mdc.toolbox/1","profile":"reconciliation","session_ref":"SESSION_REF","original_job_id":"JOB_ID","request_id":"NEW_READ_ID","bounds":{"radius":1},"wait_ms":0}
```

Send that object to `mdc_observe`. It is lease-free, display-only and cannot settle the original or refresh action admission. Regular `profile:"compact"` is also display-only and retains its normal read-owner lifecycle.

Only a confirmed, ended **attached** rescue with the exact retained original-action quarantine supports explicit authority adjudication. It is not a generic reset or paused-guard cleanup tool:

1. `mdc_job`: `operation:"adjudication_prepare"`, original `job_id` and `session_ref`. Read `adjudication.selector.original_receipt_sha256`.
2. Explicitly submit `operation:"adjudicate"` with those same values, a new `adjudication_request_id`, the exact receipt digest, and `acknowledgment:"release_authority_keep_original_effects_unknown_no_resume"`.
3. On a lost or pending response, use only `operation:"adjudication_status"` with the same adjudication ID, digest, acknowledgment and original job/session. Do not create another write ID. A separately retained `native_write_never_attempted:true` plus `next_operation:"adjudicate"` is the sole documented pre-write continuation exception.

Successful adjudication releases authority for a separately requested fresh job. The old job and effects remain UNKNOWN; nothing resumes automatically. Full scope is in `FALL-RESCUE-ORIGINAL-ADJUDICATION.md`.

## Evidence and limits

The prior TEST1.2 pair demonstrated clear-both inventory recovery with six verified clicks, exact stack conservation and separately verified cold-saved player inventory; standalone solid-ground bucket rescue with correlated integrated-server water/bucket/landed-alive evidence; and wrong-bucket refusal. Its successful rescue began with the bucket already selected. The same pair exposed the paused public-cleanup bug.

TEST2.1 additionally demonstrated automatic bucket selection from an initially empty selected slot, one bucket use with correlated integrated-server water/bucket/alive-landing proof, and a stationary shield-use window with zero attacks or movement and confirmed cleanup. The shield window did not test incoming-hit damage mitigation. Its pause-renewal, fresh cursor-menu read and managed-route start exposed the three Python defects corrected in TEST2.2. Its attached combat case physically rescued the player after 12 attacks, but original input-release proof failed and the public job remained UNKNOWN. TEST2.3 adds the separately reviewed release-only native handoff correction. Fresh pause, explicit recover_cursor, managed walking, and attached rescue/adjudication acceptance are still required; storage/archive and lease-free diagnostics remain offline-only unless the release matrix adds evidence. Historical UNKNOWN jobs remain unchanged. Native/client confirmation and later cold-saved/server evidence are reported separately; a top-level `server_confirmed:false` is never relabeled from another receipt.

Storage admission defaults warn below 1 GiB and refuse new ordinary mutation below 512 MiB, with configurable event/history budgets. Status, reconciliation, cancel and existing emergency completion remain available. The archive command defaults to retaining originals; optional verified replacement is only for closed diagnostics under its cooperative-writer contract, never worlds, backups or UNKNOWN identity receipts. No automatic save/quit is triggered.

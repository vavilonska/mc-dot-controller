# Standalone short-input recovery prototype

New `recovery_short_input_v1` contract, separate from Resident / Runtime / Watchdog and old guarded profiles. Python 3 standard library only; Linux `flock` required. This prototype has **not** been qualified in a live world. It does not restart processes, resume paused tasks, roll back worlds, plan routes, fight, teleport, send movement packets, or install held-key loops.

## Safety meaning

A finite native request writes 1–8 ordinary input samples, then expires/releases under native ownership. This is **normal gameplay risk**, not a no-damage / no-death guarantee. Protocol terminal, input release, physical settlement and gameplay outcome are separate. `protocol_terminal` is permission/input closure, while `settlement_state:not_observed` and `gameplay_outcome:not_assessed` explicitly retain physical/gameplay uncertainty. The legacy-shaped `settled` boolean in this new snapshot means protocol terminal only, not zero velocity. Nearby mobs do not need to belong to a globally proved class closure. The local first-step policy checks finite pose, grounded state, local loaded support/drop/fluid cells and immediate body/short-projection entity overlap. Other nearby living entities are risk flags, not a blanket veto. Off-route unloaded cells do not block admission. Collision can simply block movement in the game.

The current public policy deliberately refuses `jump_first`: its strategy is not yet qualified. Native availability of that field does not establish a successful exit plan. The local checks do not certify the whole future trajectory or remove ordinary gameplay risk.

## Durable identity and UNKNOWN

Use one **persistent private ledger directory** for this controller; never swap paths, profiles or endpoints to bypass an unresolved action. The directory contains an immutable non-secret `owner_id`, a cooperating-process lock and the fsync/atomic-replace ledger. Native ownership and durable UNKNOWN enforcement are also required; local files alone cannot defend against a caller manually deleting evidence.

A native-generated short-lived `observation_id` binds the exact cached local observation to the request and payload digest; native admission rechecks its age, player/world and pose. No locally manufactured observation timestamp is treated as native authority.

Before the first possibly effectful POST, the entire original request is durably committed as PENDING. There is only one in-flight original. A repeated ID returns its original local record without a POST; changed payload under that ID is refused. Interrupted dispatch, missing/malformed/mismatched receipt or a process restart with PENDING produces persistent UNKNOWN. No API clears UNKNOWN, adopts a replacement owner, retries gameplay or starts a new ID around the lock. Raw response body bytes are retained as base64 **before** validation; subsequent original-ID reads append evidence and never rewrite UNKNOWN. Completed originals retain an immutable `terminal_native` and remain completed if a later read fails; later diagnostic observations are separate evidence.

`stop` is exact-original-owner cancellation, permitted even during UNKNOWN. Its attempt is durably recorded before sending, and the CLI never retries it automatically. A stop acknowledgment alone does not settle the original action or establish physical/gameplay safety. Cleanup cannot select a newer owner. A bounded `step` operation waits read-only for the finite native action to terminate naturally. Only when terminal evidence remains unavailable does it record UNKNOWN and issue the one exact stop; it never immediately cancels every queued step before the first tick.

## Authentication / transport

The operator supplies an **existing** token through a hidden prompt or an explicitly selected environment variable name. No token generation, file discovery, secret in argv, token persistence or token logging. Requests use only an explicit HTTP loopback IP and port, with no proxies, redirects or retries. Receipt body is bounded at 64 KiB; an absolute request deadline also interrupts slow headers/body. Duplicate JSON keys, nonfinite numbers (including numeric overflow), mismatched identities and open-ended protocol fields are rejected. Auth headers are never part of receipts. If a broken endpoint echoes the token into its body, that body is withheld rather than persisted, and the receipt is uncertain.

## Explicit commands (not authorization to run)

From this directory, use `python -m short_input_controller --help`. `--ledger` and `--endpoint` are always explicit. `report` is local-only and needs no token. `observe`, `status --id ORIGINAL_UUID` and `stop --id ORIGINAL_UUID` use only the existing selected endpoint and token. `step --id NEW_UUID --forward 0.5 --samples 1 --accept-normal-gameplay-risk` is the first-step entry point; it must be run only in an authorized independent private test world. Default forward is 0.5 (not a sprint-certification claim). Exit 0 for `step` requires full nonzero applied sample count, normal `samples_complete` reason, release and protocol terminal evidence; it still does not claim displacement or gameplay success. Exit 3 is known no input, exit 4 known interrupted/partial input, and exit 2 is refused/unknown. Do not point tests at a game server.

No actual endpoint invocation is included here: operator approval, correct deployed native version, original-world preservation, independent test copy and live acceptance remain separate requirements. A stored endpoint/profile/session is not fabricated evidence of the installed mod version.

## Offline validation

From the source root:

```
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=short-input-controller python -m unittest discover -s short-input-controller/tests -v
```

Tests use in-memory transports and controlled ephemeral loopback HTTP fixtures only. They cover durable-before-POST ordering, ledger failures, restart PENDING→UNKNOWN, lost responses/disconnect, sameID/mismatchedID, replacement-owner receipt, queued cancel/expiry states, natural async terminal polling, sticky UNKNOWN after later evidence, CLOSED after read failure, malformed/duplicate JSON, digest binding, bounded raw response, slow-header absolute timeout, redirect refusal, credential echo suppression and local-vs-global policy. They are not live-game evidence or proof of native tick integration.

Native-produced wire fixtures are vendored under `tests/fixtures/` with provenance. Tests consume their original bytes, verify the shared binary payload digest and null-bearing observation schema, and retain the exact native raw receipt without reserialization. They do not claim a live Minecraft run.

Observation `client_tick` is the native client-pre-tick frame counter (null without a world). Different values let an operator distinguish two native observation frames; this field is not proof that physics advanced or that motion settled. No automatic physical-settlement command or predicate is introduced.

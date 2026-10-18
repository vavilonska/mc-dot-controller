# Native outcome and telemetry reliability

## Implemented behavior

- Ordinary placement records the native useItemOn return value without treating FAIL as proof of no effect. It issues at most one interaction, then reads the target and selected material for up to 40 client ticks. Five distinct stable observations of the expected changed block and exact selected-item decrement (or the existing creative-mode exception), plus placement settlement, establish client-observed success. A bounded inconclusive result remains unknown; no second placement is attempted. This is not server confirmation.
- Scoped admission errors carry request-payload SHA-256, action ID/session, the exact owner/generation/job/defense-epoch scope, and a monotonic native stage. Only the validation stage before callback-backed readers can prove effects-none. Hooks, input transfer, and registration stages cannot. The wire stage `registered` means the registration boundary was entered; it does not prove that `ACTIONS.begin` or registration completed. The transport and runtime independently bind the proof to the submitted intent. Missing, malformed, mismatched, or post-hook proof cannot downgrade UNKNOWN.
- Unsupported rendered entities carry their exact bounded Java class and state that enumeration covered all rendered entities before spatial filtering. The diagnostic makes no position, corridor-membership, or getter-derived claim. Existing guards remain unchanged.
- A resident request's first published receipt is immutable. STOP/input release is a separate result and cannot rewrite an old uncertain outcome. Native and mailbox IDs remain available for exact reads; no blind retry is added.
- Session reads have a separate 1 MiB bound. Commands retain their 64 KiB bound. Large terrain diagnostics are retained in immutable SHA-256-addressed files (2 MiB each, 256 files), with bounded session summaries and explicit references. Capacity exhaustion keeps full evidence inline where the session bound permits and otherwise fails explicitly. No diagnostic failure evidence is silently discarded.

## Clock/coherent-observation assessment: pending

The frozen base already has an opt-in client-pre-tick-v1 clock, same-callback capability state/action/screen siblings, and native terrain acquisition whose final page and final capability capture happen in one client callback. Legacy terrain/state paths still use independently sampled world game_time, so a terrain page ahead of the final state must remain a rejection. This patch does not loosen that guard or reinterpret wall/Python/native clocks.

A safe next implementation is an explicit compact observation endpoint backed by the existing native callback and client clock: bind process/session/world/player/server identity once, sample a client epoch before reading, capture requested bounded state/inventory/menu/entity sections, sample the same epoch afterward, and reject an epoch/context change. Terrain must either fit the same callback budget with complete coverage or use the existing owner-bound acquisition manifest with monotonic same-domain page/final stamps. Do not combine cached pages with freshly relabeled timestamps. Read hooks can have effects; this endpoint is observation-only in intent, not an admission no-effect proof.

Required acceptance before making this default: real serialized Java-to-Python fixtures for same-epoch success, page-ahead-final failure, clock generation/session changes, duplicate or reversed samples, interrupted acquisition, hook-induced context changes, and explicit size/CPU budgets. Live ordinary-world evidence is still required for real tick scheduling and latency. Atomic compact observations and legacy-default migration remain unimplemented in this workstream.

## Verification limits

Offline production compile, pure verifier assertions, actual admission/HTTP serialization, Python transport fault injection, and immutable file/receipt tests are evidence of their stated boundaries only. They do not establish successful ordinary-world placement, server acknowledgement, or live render-thread behavior.

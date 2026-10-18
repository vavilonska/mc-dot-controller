# Public fall rescue, stage 1

This stage is a standalone `fall_rescue_guard` capability in the existing four-tool MCP facade. It uses the same ToolboxService → OwnerRuntimeBackend → Runtime → IntentClient → Watchdog → Resident → native route. It creates no direct-MCP native transport, second action thread, or second owner. Native stage r3 is required.

- Discover: `mdc_catalog` with `capability_ids:["fall_rescue_guard"]`, detail `contracts`.
- Arm: `mdc_job` submit, capability version 1, arguments `{"duration_ms":60000}`, policy `{"version":1,"execution_mode":"request_only","reactions":"stop"}`.
- Budget: action budget at least `ceil(duration_ms/1000)+3`; observation budget at least `ceil(duration_ms/250)+3`; deadline at least `duration_ms/1000+2` seconds. Default 60 seconds needs 63 actions, 243 observations, and 62 seconds, with the mandatory cleanup reserve included. Extra margin is sensible for acquisition latency.
- Status: query the original job ID/session. `fall_rescue_status` events carry native arm ID, owner proof, lease revision, client prediction, exact episode ID, and authoritative evidence separately.
- Disarm: cancel that original job. The same owner thread sends one exact disarm and later releases the original capability lease. An unknown original control is never replayed or followed by a replacement command.
- Renewal: the same owner thread renews a 5-second native lease every second, only within the original bounded duration/deadline. This does not depend on an LLM responding quickly. Owner crash, cancellation, or an unknown response stops renewal; the native lease expires within five seconds.

The public arm is bound to the runtime-generated owner ID, job ID/generation, gateway epoch, resident session, and native world/player/action session. The gateway installs its arm binding before submission; the Resident installs its corresponding binding before native POST. Exact full-response identity is checked at both layers. Public callers cannot supply native endpoints, owner IDs, preemption lists, native TTL overrides, or arbitrary native payloads.

This stage permits no parallel movement/combat job. Its native preemption list is empty. It is useful for authorized native protection while otherwise idle or reacting to physical knock-up, but does not yet protect an existing public movement/combat task. It must not be advertised as concurrent ordinary-job protection.

The native feature remains explicitly limited to private integrated survival, Overworld/End, a one-count water bucket in the hotbar, loaded supported inert full-block top, ordinary physics, and no unknown external input controller. Native `use_item` remains consumable-only; the dedicated rescue uses ordinary vanilla water-bucket input. The first integrated test artifact includes the pinned API-only read adapter: the supported official API distribution must prove idle on each admission/effect query. Standalone Baritone remains unsupported/unknown. The adapter does not stop an external controller or start managed routes.

Known/unknown, physical outcome, and ownership cleanup remain separate. A successful guard window without dispatch means only that the authorization window ended; it does not claim a fall occurred or death was prevented. Correlated server water + bucket transition followed by alive landing is stronger than client prediction, but is not an exact packet acknowledgement or a guarantee of future safety.

# Next slice: protection inside one ordinary owner job

The recommended next slice is an explicit bounded `policy.fall_rescue` attached to the existing job, not a second guard job and not a Python thread racing `Runtime`.

1. The existing owner thread carries a closed protection policy through the guarded action envelope. The gateway binds owner ID/generation and job identity and derives the one permitted native action ID from the exact resident request ID. Callers cannot nominate arbitrary predecessor IDs.
2. The Resident arms the native guard in the same serialized dispatch path before admitting that one native action. Native authorization is bounded by the original action/job deadline. It does not weaken existing action guards.
3. When the native guard preempts, Resident must retain the original action and wait read-only for the exact rescue episode's terminal state, rather than immediately invoking generic terminal cleanup that could cancel the rescue. Native input owner remains exclusive during this wait.
4. The original action's outcome remains unknown until reconciled. Rescue evidence is a separate sealed result linked to arm/episode/action/owner IDs. Confirmed rescue must never turn the interrupted job into succeeded, resume it, or permit a duplicate owner.
5. Every completion, stop, pause, timeout, and callback failure disarms/finalizes through the same owner path. A local mailbox is needed only for explicit arm/disarm changes while a job is waiting; process that mailbox on the owner thread, never from a second mutating thread.
6. Add real-chain tests for movement/combat preemption, original-result quarantine, delayed native rescue, stop during callback/packet, owner restart, and exact episode result propagation. Only then enable the concurrent-policy catalog feature and live acceptance.

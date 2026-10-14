# Explicit request-only execution policy

Start a NEW watchdog control directory with `--execution-policy request_only`.
The durable policy pin is written before observations or queue dispatch. A directory
pinned noncombat/request_only cannot switch to another policy. No old paused owner
is resumed. Standard and noncombat retain their existing semantics.

Use toolbox policy `{"version":1,"execution_mode":"request_only","reactions":"stop"}`,
or Runtime(required_execution_policy="request_only"). The skills CLI accepts
`--require-request-only`, mutually exclusive with `--require-noncombat`.

Before acquisition, during idle gaps, and after release, automatic hostile acquisition,
retargeting, health-loss retreat, environmental recovery and ranged producers are
suppressed. Explicit STOP retains existing release semantics. Lost/expired ownership
pauses with existing reconciliation requirements, never automatic takeover or replay.

Mutation requires an active exact capability lease, fresh guard/context, and a required
scoped native preflight whose profile advertises that exact action. Missing, wrong,
stale or unadvertised scope is refused before queue dispatch. Ordinary legacy direct
commands and unscoped actions are unavailable in this policy. Explicit capability
observations and exact owner cancellation retain the existing identity/terminal checks.

For engage, the existing combat-local-observed-v1 native route remains unchanged:
explicit target, bounded native deadline, caller health reserve, safetyRetreat enabled,
no automatic resumption. This policy does not disable native safety movement; a
stationary test must fail its acceptance predicate on any movement/safety interrupt.
Native attack/shield/mixin functional behavior still requires separate live evidence.

This policy is Python-only. Native source/resources and artifact 8048dde9 remain
unchanged; publish and pin the reviewed Python source separately before any trial.

## Active-action progress

Resident session publication adds `active_action_progress` for scoped combat only.
It projects the already accepted native status poll, with exact resident/request/action/
owner/job/target identity, native action-relative ticks and local monotonic/unix receive
clock. At most 0.8 seconds of age is exposed; no extra native request is made.
Consumers must recheck age and original identities when reading the persisted file.
Missing, stale, replaced, terminal, cancel-attempted or unknown tasks expose null.
It is diagnostic evidence, never dispatch authority or proof of effect attribution.
Existing native safety remains active; progress does not suppress it.

## MCP schema parity

The Node MCP façade embeds the pure Python `mdc_toolbox/contracts.py` schemas.
After any contract change, run `python3 client-mod/mcp/sync-toolbox-schema.py`,
then `python3 client-mod/mcp/sync-toolbox-schema.py --check` and
`node --test client-mod/mcp/toolbox-test.mjs` from the repository root.
The check loads only the contract module, without starting a runtime or game.
All policy declarations, including plan and job submission, must stay identical.
The regression covers production MCP parsing and forwarding; synthetic tests do
not establish live combat success or authorize replay of an earlier request.

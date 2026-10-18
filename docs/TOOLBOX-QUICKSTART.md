# Toolbox operator setup and playing-AI calls

This guide describes the current source interface, not a newly deployed or fully
live-accepted release. See [capability evidence](CAPABILITY-STATUS.md) for exact
bounded live cases. Use only the authorized private singleplayer test world;
retain the original world. Do not resume paused work, retry unknown mutations, or
join multiplayer using this guide.

## 1. What the MCP server actually exposes

`client-mod/mcp/mineclient-bridge-mcp.mjs` advertises 12 tools:

- Playing-AI façade: `mdc_catalog`, `mdc_observe`, `mdc_plan`, `mdc_job`.
- Legacy/native tools: `minecraft_client_action`, `minecraft_client_launch`,
  `minecraft_client_register`, `minecraft_client_status`, `minecraft_client_frame`,
  `minecraft_client_query`, `minecraft_client_input`, `minecraft_client_close`.

With `MINECLIENT_TOOLBOX_CONFIG` set, legacy launch, register, action, input and
close calls are refused with `toolbox_exclusive_operator_binding`. This remains
true if the configuration is invalid; failure does not enable a second writer.
Status/frame/query retain their separate legacy session requirements. Use the
four façade tools for a toolbox session; do not bypass its ownership by calling
raw input or directly writing to the Resident queue.

Without configuration, the source catalog remains readable but a catalog item is
not executable. The configured service negotiates native profiles/actions and
reports `runtime_available` and `availability_reason` per capability. Inspect
`runtime_binding_availability` for `available`, `private_singleplayer`,
`session_ref`, `context_ref`, `execution_policy` and `supported_policies`.

## 2. Platform and source requirements

- Matching Minecraft 1.21.1 / NeoForge client mod and complete sibling source tree.
  Rebuilding from current source does not inherit old JAR live acceptance.
- Node.js 20+; Linux synthetic platform self-tests require 20.6+.
- Python 3.10+ with POSIX `fcntl` for Toolbox, Runtime and Watchdog journal locks.
  Native Windows Python alone cannot run that owner stack. Legacy prepared launch
  remains Windows-specific. Do not interpret portable synthetic tests as proof of
  a turnkey Windows toolbox deployment or invent a cross-namespace transport.
- One already authorized Resident → Watchdog control chain. The Resident must
  actually reach Java's verified loopback listener. Toolbox and Watchdog must
  really share the chosen control directory; shared source files alone are not
  proof of shared filesystem/process/network visibility.

The supported delivery topology is Linux/POSIX on one host: Java client, Node
MCP, its spawned Python façade, Watchdog and Resident share the actual filesystem
and process namespace; Resident alone talks to the verified Java loopback API.
The existing authorized Linux launcher is used outside the Windows-specific
legacy `minecraft_client_launch` tool. No generic launcher or WSL bridge is
supplied here. Native-Windows toolbox deployment remains unsupported pending
Python locking portability and review of the real complete launch chain.

No pip/npm dependencies or new credential generation are required by this guide.
The operator must use the already approved environment and access, not switch
platforms or create persistent grants merely to satisfy these prerequisites.

## 3. Operator startup order

1. Verify that any previous owner is stopped with input release confirmed and no
   unresolved original IDs. A paused or unknown previous run is a blocker, not
   permission to erase a journal or use a replacement directory to evade it.
2. In the existing authorized launch flow, load the separate intended ordinary
   singleplayer test copy with the matching mod. Do not use a toolbox call to
   launch/login/join. Record the source/artifact identities outside public source.
3. Start the Resident once in Java's actual network/process environment using
   [owner-start](../resident-controller/README.md#owner-start-once-per-playing-session):
   `./owner-start.sh http://127.0.0.1:VERIFIED_PORT /verified/shared/mailbox`.
   Supply the existing bearer through the documented hidden prompt or explicitly
   approved existing token file. Never put it in AI tool arguments or this config.
   This guide's singleplayer restriction overrides that older guide's server example.
4. Start the sole Watchdog queue writer with the intended explicit policy. From
   `defense-watchdog/`, an example for the current request-only lane is:
   `python3 watchdog.py run --queue /verified/shared/mailbox --control /verified/private/control --execution-policy request_only`.
   Confirm its ready state and exact policy. Existing durable policy pins and
   paused ownership must be respected. Do not interleave direct QueueClient calls.
5. Prepare the private JSON configuration below on the actual Node/Python host.
   Resolve Python's real executable and calculate its SHA-256 locally. All paths
   are absolute on that host. The three directories must be pairwise disjoint
   (neither equal nor nested); source checkout is the full repository tree.
6. Configure the MCP client to execute Node with the absolute server path and set
   `MINECLIENT_TOOLBOX_CONFIG` to the absolute private JSON path. Restart/reload
   that MCP server through the client's supported flow. Server startup launches
   only the fixed Python façade, not Java, Resident or Watchdog. Do not separately
   start a second façade on those journal directories.
7. Initialize MCP, inspect `tools/list`, then query `mdc_catalog` and one small
   `mdc_observe`. Stop if runtime binding, session, policy or coverage is absent.

Example configuration structure (replace every placeholder; do not commit the
populated file):

```json
{
  "schema_version": 1,
  "python_executable": "/absolute/path/to/python3",
  "python_sha256": "REPLACE_WITH_64_LOWERCASE_HEX_DIGITS",
  "control_directory": "/verified/private/control",
  "journal_directory": "/verified/private/toolbox-journal",
  "runtime_journal_directory": "/verified/private/runtime-journal"
}
```

These are exactly the accepted keys. The config must be an ordinary nonsymlink
file at most 64 KiB. A changed executable hash requires deliberate operator
verification and configuration, not a fallback executable. The Node bridge sets
its own PYTHONPATH to the sibling packages and a minimal child environment;
custom inherited Python environment variables are not a supported setup method.

For a Codex-style MCP client, set the server's `command` to the verified Node
executable, `args` to the absolute `client-mod/mcp/mineclient-bridge-mcp.mjs`, and
`env.MINECLIENT_TOOLBOX_CONFIG` to that JSON path. Legacy Windows launcher
variables are documented separately in the [MCP README](../client-mod/mcp/README.md).
The config loader and executable hash check are the same for any MCP client.

## 4. Playing-AI call sequence

[toolbox-call-examples.json](toolbox-call-examples.json) contains nine structurally
validated examples: catalog, observe, optional plan, submit, status, cancel and
reconcile, plus two route submits showing stop and explicit defense. They are templates, not a script to execute in order.
Replace session/context/job references from actual returned results. Do not send
the placeholder strings to a live service. Select an actually observed occupied
hotbar slot and a new immutable request ID for a genuinely new approved intent.

MCP uses ordinary `tools/call` wrappers; for example:

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"mdc_catalog","arguments":{"api_version":"mdc.toolbox/1","detail":"contracts","capability_ids":["select_hotbar"]}}}
```

The MCP result is text content containing the toolbox JSON. Read the selected
capability's `input_schema`, prerequisites and `runtime_available`. Obtain the
session reference from `runtime_binding_availability.session_ref` and current
context reference from that description or the fresh observation. Public
observations do not grant action authority; mutation admission takes fresh facts.

The first example submit selects slot 0 in `request_only` mode with `reactions:stop`.
Only use it if that slot is occupied and this is the actual negotiated policy.
`noncombat` maps to Watchdog `noncombat`; `guarded` maps to Watchdog `standard`;
`request_only` maps to Watchdog `request_only`. A request cannot change the running
Watchdog policy. The example budget permits one ordinary mutation plus one
reserved cleanup action; complex recipes require a sufficient explicit budget.
Planning is optional, capability-dependent, and never grants execution authority.

Follow the returned job ID/state. Status accepts exactly one of `job_id` or
`request_id`, which lets a lost submit reply be queried by its original immutable
request ID. `accepted`, `running` and `stopping` are pending states. Inspect both
`effect_certainty` and `cleanup_certainty`, not only `state`: a known semantic
result can coexist with unknown release. Fresh `mdc_observe` is refused while a
mutation owns the backend or remains uncertain; poll its job instead.

Cancel only the intended current job, retaining one `cancel_request_id`.
Cancellation does not roll back effects. For an unknown/interrupted dispatched
job, `reconcile` reads original evidence; it does not resume/release/replay.
No response, malformed transport or wait timeout is not proof of no effect.
Do not allocate a replacement mutation ID or restart to try again. A known
refusal requires inspecting its reason and taking only a separately justified
next action, not blind replay.

For ordinary non-memory observations, leave selectors empty and omit bounds or
use the currently supported `radius`. Some generic schema fields such as
`max_cells`, `max_entities` and acquisition profiles are not supported by this
backend. Unsupported filters fail closed; they are not silently implemented.
Use small catalog pages and observations: the wire limit is 1 MiB even though
some internal JSON limits are larger.

## 5. Current operational limits

The backend allowlist currently contains 20 candidates: select_hotbar,
ensure_hotbar, equip, consume, close_menu, container_move, container_split,
container_merge, container_withdraw, container_deposit, craft, smelt, interact,
navigate_local, navigate_step_down, navigate_route_local, mine_local, collect_local, place_local, engage.
Each still requires its negotiated native profile, safety preconditions and
appropriate policy. Allowlisted does not mean live-accepted for every variant.

- `navigate_local` is exactly one flat cardinal block. `navigate_step_down` is one
  cardinal descent. Their older narrow admission contracts remain unchanged.
  `navigate_route_local` adds bounded loaded local routes through separately guarded
  cardinal flat/up-one/down-one segments, physical centering and bounded detours.
  It requires `request_only`, fresh negotiated local-segment support and a valid
  loaded route. It does not enable unloaded/global routes or arbitrary geometry.
  `navigate_loaded` remains outside this public backend.
- Reactions default to `stop`. Explicit `defend_once` is supported only when the
  combat profile is negotiated, on the allowlisted movement/mining/collection
  jobs, with a caller-selected supported hostile UUID and original action,
  cleanup, observation and health reserves. Route remains `request_only`.
  Only known damage interruption plus confirmed native input release and fresh
  exact-target evidence may start one bounded combat action under the same owner.
  Unknown outcomes, cancellation, deadline expiry and environmental hazards do
  not trigger it. The ordinary job stays interrupted and is never resumed.
  `avoid` and older `defend` are not implemented. This is offline-validated source;
  combined route/reactive-defense ordinary-world acceptance is still pending.
  See [terminal defense](DEFEND-ONCE.md) and [local routes](../capability-runtime/docs/NAVIGATE-ROUTE-LOCAL.md).
- `engage` runs native bounded combat against one supported observed hostile.
  The retained attack/cancel trial does not establish general encounter victory,
  multi-target survival or effective shielding.
- `place_local` is one stationary ordinary cobblestone. Blueprint execution,
  dimensions, boats, resource-goal planning and other source catalog entries
  remain outside the public runtime binding unless explicitly negotiated later.
- Every result remains client-observed (`server_confirmed:false`). Historical
  evidence belongs to its pinned runtime, not to arbitrary rebuilds.

## 6. Shutdown and offline verification

Finish or exact-cancel the active known job and inspect cleanup. EOF/SIGTERM on
this façade requests bounded exact-owner stop; an unconfirmed close remains
unknown. Only after confirmed release/exit should the operator stop Watchdog,
then Resident, and use the authorized ordinary save/close flow. Do not invoke
legacy `minecraft_client_close` through the toolbox-bound server, kill processes
as a success substitute, clear journals, or automatically restart on uncertainty.

File-only checks, with no Minecraft or live mailbox:

```sh
python3 -B test-tools/check_toolbox_call_examples.py
cd client-mod/mcp
npm run test:toolbox
```

The example check validates source schemas/domain arguments and placeholder call
shapes only. `test:toolbox` needs Node and POSIX Python (set `PYTHON` to the chosen
executable if necessary); its owner-chain native endpoint is synthetic. `npm test`
includes it. `npm run test:windows` remains the legacy Windows platform gate and
does not validate the POSIX toolbox owner chain. The full Python/Node runner is
`python3 -B capability-runtime/run_checks.py`, writing its report outside the tree
or to `MDC_TEST_OUTPUT`. It now includes schema and owner-chain Node suites.
Native Gradle/NeoForge loader gates and actual authorized gameplay are separate.
An absent fixture/platform is an unmet gate, not a passing test.

## 7. Preparing an installable delivery bundle

`test-tools/package_toolbox_delivery.py` is a file-only packaging utility. It
requires a final reviewed SHA256SUMS-format public source inventory, the full
source revision, and a separately built/verified JAR plus its exact SHA-256:

```sh
python3 -B test-tools/package_toolbox_delivery.py \
  --source /verified/final-source \
  --public-inventory /verified/final-public-source-inventory.txt \
  --source-revision FULL_40_HEX_REVISION \
  --jar /verified/final-mineclient-bridge.jar \
  --jar-sha256 EXACT_64_HEX_JAR_SHA256 \
  --output /verified/new-delivery.zip
```

Do not reuse a stale inventory after edits. The utility refuses mismatched bytes,
unreviewed implicit directory enumeration, source symlinks, forbidden/private
artifact path classes and an existing output. The only source-binary exceptions
are the existing Gradle wrapper JAR and mod icon PNG at their exact reviewed
paths and pinned SHA-256 values; modified bytes, symlinks and arbitrary binaries
still fail closed. Its manifest records source
revision, inventory hash, JAR hash and every packaged file. A fixed-timestamp
stored ZIP makes repeated identical inputs byte-for-byte reproducible. Node and
Python source are included; interpreter binaries, credentials, instance settings,
saves, live queues/journals and reports are not bundled. The operator's explicit
public inventory is still a content-review requirement; filename filtering cannot
detect every secret placed inside a public source file.

The output contains `source/`, `mod/mineclient-bridge.jar`,
`BUNDLE-MANIFEST.json`, and `SHA256SUMS.txt`. Packaging validates container shape
and integrity, not bytecode correctness, source-to-JAR provenance or gameplay.
No final JAR is supplied or installed by this documentation change. After the
authorized operator has installed the approved JAR and configured the existing
Linux instance, verify hashes, `tools/list`, negotiated catalog availability, and
a small observation as the health check. Then run the separately authorized
composed live acceptance; a source-only smoke check cannot replace it.

Packager regression checks are synthetic and safe offline:
`python3 -B test-tools/test_package_toolbox_delivery.py`.

## Synthetic route examples

The final two entries in `toolbox-call-examples.json` illustrate the same bounded route with default stop and explicit `defend_once`. Coordinates and target UUID are synthetic shape examples, never a live target selection. Replace them only using current observations and caller intent. Reserve one reflex action and one cleanup action in the original budget; 15 observations must remain at the defense transition. One defense action may include several native attack ticks or safety retreat. It does not assert the selected hostile caused the damage, and it never resumes the route.

## Composing inventory and workstation jobs

Observe actual slots after crafting or quick-move; output placement depends on current inventory occupancy. Do not hardcode an output slot from an earlier trial. Before a guarded block-menu interaction, verify its empty-hand requirements. If crafting filled the selected slot, plan a public exact container_move into an observed empty storage slot, verify item/component conservation and both hands, then submit the interaction with fresh context. Never discard items or use raw inputs to bypass admission.

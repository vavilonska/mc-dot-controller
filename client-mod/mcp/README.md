# MineClient Bridge MCP

This directory contains a dependency-free stdio MCP server for MineClient Bridge.

The stdio transport is UTF-8 newline-delimited JSON (NDJSON), not Content-Length
framing. Each incoming line is limited to 1 MiB before its LF terminator, including
when the line is still incomplete. Stdout contains only JSON-RPC messages.

## Requirements

- Node.js 20 or newer.
- MineClient Bridge installed in the target Minecraft client.
- Windows for `minecraft_client_launch`, because the prepared launcher uses a native background Desktop.

The other tools operate only on an explicitly registered, authenticated loopback bridge session. The current path contract uses normalized local Windows paths.

## Codex Configuration

```toml
[mcp_servers.mineclient_bridge]
command = '<absolute-path-to-node.exe>'
args = ['<absolute-path-to-repository>\mcp\mineclient-bridge-mcp.mjs']
startup_timeout_sec = 120

[mcp_servers.mineclient_bridge.env]
MINECLIENT_BRIDGE_PREPARED_ROOT_PARENT = '<absolute-parent-for-prepared-runs>'
MINECLIENT_BRIDGE_STATE_DIR = '<private-absolute-session-state-directory>'
MINECLIENT_BRIDGE_POWERSHELL = '<absolute-path-to-pwsh.exe-or-powershell.exe>'
```

Restart Codex after changing MCP configuration.

PowerShell 7 (`pwsh.exe`) is recommended when a prepared launcher references non-ASCII paths. Windows PowerShell 5.1 remains usable for ASCII-only launch inputs.

## Tools

- `minecraft_client_action`
- `minecraft_client_launch`
- `minecraft_client_register`
- `minecraft_client_status`
- `minecraft_client_frame`
- `minecraft_client_query`
- `minecraft_client_input`
- `minecraft_client_close`

Every tool declares a plain object input schema with no top-level `oneOf`, `anyOf` or `allOf`, so MCP clients that validate `tools/list` strictly load all eight tools. The original seven tools and their identities remain available. `minecraft_client_query` and `minecraft_client_input` select their operation with `kind`, and the server rejects any field that does not belong to that kind.

`minecraft_client_action` accepts `submit`, `status`, or `cancel`. Submit requires
an explicit immutable action ID, finite timeout, and expected native world,
player and action-session identities. Its frozen v18 submit set is `follow_path`,
`break_block`, `place_block`, `click_slot`, `combat_entity`, `boat_drive`,
`boat_mount`, and `boat_dismount`. Navigation epoch/origin must be supplied as a
pair when used. Combat encounter scope remains the explicit frozen two-zombie
contract. This tool does not select targets, plan routes, or arbitrate other
owners.

The root native API also supports `recover_environment` with absent or zero
timeout. That existing native contract is unchanged. The finite MCP adapter
rejects recovery submit with `action_unsupported` before descriptor/native I/O,
including timeout zero; it never converts recovery into another action or adds
a deadline. `status` and `cancel` may use an already known recovery action ID
and its exact native action session.

Submit and cancel make at most one native POST. A timeout, malformed response,
or mismatched receipt is an unknown outcome; inspect the original ID in the
same session. Do not replay, allocate a new ID, or automatically release inputs.
Native release/handoff/pause evidence is returned without inventing confirmation.

`minecraft_client_input` accepts these input kinds: `key`, `raw_key`, `look`, `mouse`, `text`, `command`, and `release_all`. Use `raw_key` with a Minecraft key name or short alias such as `key.keyboard.enter`, `escape`, or `f1`. Repeated raw-key presses and releases are idempotent. A tap completes an existing press or sends a new press/release pair, always ends released, and repeated taps remain independent. Named `key` taps drive the mapping's own bound key through that device's handler, so mods that read their controls from `InputEvent.Key` or `InputEvent.MouseButton` respond and every mapping sharing that key reacts; pass `exact: true` to target only the requested mapping, which is also how an unbound mapping is driven. Key, raw-key and world-mouse replies carry `mod_input_event`, which records whether a mod cancelled the input. `mouse` supports world button actions and coordinate-free world scroll as well as GUI coordinates. Session cleanup releases every tracked raw key. Use `command` with up to 256 command characters with or without a leading slash. All paths use the authenticated in-client bridge and do not inject operating-system input.

Launch roots are one-shot and must contain `final-preflight.json`, `launch.ps1`, and `launch/java-arguments.txt`. The launcher must preserve the MCP-provided `MINECLIENT_BRIDGE_*` environment variables when it starts Java. Every session is revalidated against its run ID, process ID, desktop, runtime root, evidence root, and authenticated bridge status.

Production descriptors are stored outside the repository. They contain the session token and must remain in a private user-owned directory. The MCP never returns or logs the token.

## Test

```powershell
npm test
```

The self-test keeps the original seven tool contracts: launch and registration identity, PNG transport, bounded queries and inputs including commands and raw keys, release-before-close behavior, exact PID exit, and secret redaction. The listed surface now contains eight tools. The portable action tests exercise actual adapter parsing/execution with synthetic hook responses; the framing test also calls the new route through real stdio.

On Windows, `npm test` runs the original self-test directly. On Linux (Node.js
20.6 or newer), it runs the same unmodified server and assertions in a private
temporary directory with a test-only Windows-path mapping and fixed Node fixture
launcher. The mapping rejects paths outside that directory, symlinks, and unknown
commands; it never executes PowerShell, Java, Minecraft, or arbitrary scripts.
The framing tests always run against the ordinary server without this mapping.

Linux success means the synthetic platform contract passed. It does **not** mean
the production adapter supports Linux, and it does not validate Windows path
case-folding, reparse points, ACLs, PowerShell syntax/process topology, native
Desktop behavior, or real Java/Minecraft isolation. Run `npm run test:windows` on
Windows for the original platform gate; Linux success cannot replace that gate.
The fixture copies and verifies the server, self-test, and its two fixed action
module dependencies without changing their bytes. No synthetic-platform switch
is added to the production server.

The package has no npm dependencies or lifecycle hooks. All tests can run fully
offline by invoking the installed Node binary directly:

```sh
node --test client-action-test.mjs encounter-contract-test.mjs mainline-client-action-test.mjs
node ndjson-framing-test.mjs
node self-test-platform.mjs
```

The optional `../validation/mcp-native-contract` gate compiles the actual pure
root parser/registry and tests their emitted JSON with this adapter. It does
not run Minecraft or replace the real platform gate.

The transport gate also covers initialize/tools/list over real stdio, clean output,
fragmented UTF-8, coalesced requests, CRLF, malformed JSON and complete/incomplete
line-size limits. Before deployment, run `npm run test:windows` on Windows; a Linux
`npm test` pass is only the synthetic gate. After deployment, run the same Windows
tests from the installed directory and
verify that its server SHA-256 matches the tested source.

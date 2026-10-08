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

- `minecraft_client_action` (new bounded submit/status/cancel)
- `minecraft_client_launch`
- `minecraft_client_register`
- `minecraft_client_status`
- `minecraft_client_frame`
- `minecraft_client_query`
- `minecraft_client_input`
- `minecraft_client_close`

Every tool declares a plain object input schema with no top-level `oneOf`, `anyOf` or `allOf`, so MCP clients that validate `tools/list` strictly load all eight tools. `minecraft_client_query` and `minecraft_client_input` select their operation with `kind`, and the server rejects any field that does not belong to that kind.

`minecraft_client_input` accepts these input kinds: `key`, `raw_key`, `look`, `mouse`, `text`, `command`, and `release_all`. Use `raw_key` with a Minecraft key name or short alias such as `key.keyboard.enter`, `escape`, or `f1`. Repeated raw-key presses and releases are idempotent. A tap completes an existing press or sends a new press/release pair, always ends released, and repeated taps remain independent. Named `key` taps drive the mapping's own bound key through that device's handler, so mods that read their controls from `InputEvent.Key` or `InputEvent.MouseButton` respond and every mapping sharing that key reacts; pass `exact: true` to target only the requested mapping, which is also how an unbound mapping is driven. Key, raw-key and world-mouse replies carry `mod_input_event`, which records whether a mod cancelled the input. `mouse` supports world button actions and coordinate-free world scroll as well as GUI coordinates. Session cleanup releases every tracked raw key. Use `command` with up to 256 command characters with or without a leading slash. All paths use the authenticated in-client bridge and do not inject operating-system input.

Launch roots are one-shot and must contain `final-preflight.json`, `launch.ps1`, and `launch/java-arguments.txt`. The launcher must preserve the MCP-provided `MINECLIENT_BRIDGE_*` environment variables when it starts Java. Every session is revalidated against its run ID, process ID, desktop, runtime root, evidence root, and authenticated bridge status.

Production descriptors are stored outside the repository. They contain the session token and must remain in a private user-owned directory. The MCP never returns or logs the token.

## Test

```powershell
npm test
```

The legacy Windows self-test covers the original seven tools and the updated tools/list contract, launch and registration identity, PNG transport, bounded queries and inputs including commands and raw keys, release-before-close behavior, exact PID exit, and secret redaction.

The transport gate also covers initialize/tools/list over real stdio, clean output,
fragmented UTF-8, coalesced requests, CRLF, malformed JSON and complete/incomplete
line-size limits. Do not deploy the MCP adapter before this full test command
passes. After deployment, run the same tests from the installed directory and
verify that its server SHA-256 matches the tested source.

## Integrated bounded action route

`minecraft_client_action` is newly implemented in `1.1.7-integrated.1`; the prior MCP adapter did not expose `/control/action`. The resident `op: action` route already existed and remains unchanged except for added tests.

Use `operation: submit`, `run_id`, `expected_action_session`, and a `body` with `action_id`, `action`, finite `timeout_ms`, and explicit expected world, player, and action-session UUIDs. Supported actions are follow_path, break_block, place_block, click_slot, combat_entity, and boat_drive. The schema lists each permitted field, and runtime validation rejects fields belonging to other actions. A 64 KiB payload cap, type/range/route bounds, session/player/world checks, authenticated identity revalidation, and existing background input-isolation checks apply. Native client admission still performs the final guards and single-owner/idempotency checks.

`status` and `cancel` require the exact `action_id` and expected action session. Cancellation now carries its session to a client-thread atomic check. Old HTTP/resident callers without that optional cancel field retain their prior behavior. For land actions after a position discontinuity, submit the observed `expected_navigation_epoch` plus `expected_origin` pair with a newly planned route; the adapter never refreshes a stale plan automatically. Boat requests keep their independent motion contract and do not accept land-binding fields.

There is exactly one bridge request per operation. POST errors are conservatively reported as potentially unknown outcomes; no retry, new ID, takeover, or automatic cancellation occurs. Inspect the original named ID in the original session. Native action IDs remain idempotent within the client action session. Do not run this as a second execution owner beside an active watchdog/resident. This adapter does not implement the optional coordination prototype's live fencing.

Portable verification: `npm run test:portable` exercises adapter route/validation/error behavior through injected authenticated transport hooks and real stdio tools/list framing. These are offline tests; no registration, real bridge call, or game action runs. Windows launch/registration integration and all real-game action routing remain untested for this integrated candidate.

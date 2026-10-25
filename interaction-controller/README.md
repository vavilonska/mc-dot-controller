# Recovery interaction prototype (offline development)

New `recovery_interaction_v1` only. The frozen sibling `short-input-controller` remains byte-for-byte unchanged and is required to read historical requests, payload digests and terminal receipts under their original contract.

This controller requires the existing private ledger directory, owner file, endpoint and nonempty history. It does not bootstrap an empty ledger, generate an owner or token, restart services, clear UNKNOWN, resume paused work, or reissue an uncertain effect. Legacy PENDING becomes persistent UNKNOWN on restart under the original ledger rules. Legacy CLOSED histories retain their request/digest/terminal evidence. New action IDs share that same authority and deduplication namespace.

Current development scope is two explicitly designated cobblestone blocks and one locally qualified one-block ascent; no placement, inventory/backpack operations, entity attacks, batch mining, arbitrary excavation, planner, or old-guard relaxation. Cold maps are planning hints only. Breaking below or at y=59 is forbidden. Fresh native observation/ray, exact held stack and bounded calls remain required. Ordinary damage and an incompletely broken block are gameplay results, not automatically uncertain protocol effects.

No live game action is authorized by these examples/tests. CLI/schema details and native wire-fixture evidence will be appended when the closed contract is finalized.

## Closed wire contract

New root: `/control/recovery-interaction/v1/`; `GET observe`, `POST start`, exact-original `GET status` and `POST stop`. Common start fields are schema/profile/kind, original IDs and generations, immutable observation ID and 100–2000 ms deadline. One action only:

- `move`: forward/strafe in [-1,1], 1–8 samples, optional first-sample jump.
- `look`: one absolute yaw [-180,180) / pitch [-90,90] pair, finite and at most 90° delta from the live observation.
- `select_hotbar`: one slot 0–8 plus its exact observed stack fingerprint; this task policy permits only slot 2, the stone pickaxe (one item, initial damage 104 and up to the two planned block uses).
- `break_block`: one x/y/z, uppercase face, `minecraft:cobblestone`, exact held-stack fingerprint and 1–32 calls; task policy permits only `(-636,60,33)` and `(-636,61,34)`, never y≤59. The current actual native block ray must match the target and face. No entity target, batch, placement or backpack operation.

Native statuses distinguish `requested_calls`/`applied_calls`, execution authority closure, captured input/use cleanup, and gameplay outcome. A bounded break that leaves its block unchanged is a **known incomplete gameplay result**, not UNKNOWN. A lost/malformed/mismatched dispatch receipt is UNKNOWN and locks both profiles. A stop acknowledgment never erases UNKNOWN or by itself settles the original intent. Known CLOSED original terminals remain immutable if a subsequent read fails.

The new binary payload digest includes profile, kind, every original identity, deadline, observation identity and every kind-specific parameter. Legacy digests retain their exact old byte ordering. Same ID across profiles/kinds shares one namespace: exact repeats read the original; any changed binding refuses before POST.

## Local ascent qualification

New observations contain 150 cells (dx/dz -2..2, dy -2..3); old observations/readers remain 125 cells. The only jump intent allowed by this task policy starts with the entire live player bbox inside x[-636,-635], z[34,35], feet y=59. The source body cell (-636,59,34) must also be live air. The bounded local z32..34 sweep requires live air at y=60/61/62, and both adjacent landing rows z33 and z32 have live `minecraft:nether_bricks` support at y=59, and source support is loaded/solid/dry. The finite input faces the adjacent northern step with 0<forward≤1, no strafe and at most 8 samples. One jump intent is permitted per actual native session/world-generation binding; no replacement jump in that binding is allowed even after a zero-effect result. A known TEST-world jump remains in history and does not consume the first separately authorized formal-world intent. This local qualification does not clear or scope down the global UNKNOWN lock; an unknown original from any world still blocks every new effect. These are local admission checks, not a landing, physical settlement, damage prevention or trajectory-completion guarantee.

Non-jump movement calls the frozen old local policy on an explicitly reduced 125-cell view, without changing the old policy or global guarded modes. Different `client_tick` values only identify observation frames, not physical settlement. Cold saved-world maps never create live admission authority.

## CLI

Run `python -m interaction_controller --help` from this directory. Always pass the **existing** private `--ledger` and exact `--endpoint`. `report` is local-only and prompts for no credentials. Other commands use an existing token from hidden input or `--token-env EXISTING_VARIABLE_NAME`; no secret value in argv, no generated token, no token persistence or logging. Transport is bounded HTTP loopback only, no proxies/redirects/retries; raw response bodies are retained before strict parsing except a token-echoing broken endpoint is quarantined rather than persisting the secret.

Effect commands are explicit `move`, `look`, `select_hotbar`, or `break_block`, each with caller-created canonical `--id` and `--accept-normal-gameplay-risk`. They obtain one fresh observation, commit the entire intent durably, send at most one effect POST and wait read-only for native finite completion. Only an unresolved original gets its one exact stop attempt. The CLI never executes the whole route or repeats an effect. An existing ID never causes another POST. Status/stop routing is derived from the retained request, not caller-supplied profile.

Exit 2 means refused/unknown/unsettled. Exit 3 means known zero calls. Exit 4 means known partial/interrupted calls or a break whose target was not confirmed changed. Exit 0 reports known native call completion (or local `target_changed`), **not server confirmation, safe landing, stable pose or general gameplay success**.

## Offline tests

From the source root:

```
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=interaction-controller python -m unittest discover -s interaction-controller/tests -v
```

Synthetic 57-record history and the coordinator's authorized journal-only fixture are validated in temporary private copies. Every prior request, digest, immutable terminal, evidence prefix and owner is compared; original fixture files are not modified. Tests never read runtime token paths or send to the game endpoint. The real fixture test explicitly skips when the authorized journal-only fixture is not included; synthetic tests are not presented as a substitute for that evidence. Production native raw-wire fixtures are separately validated when provided by the native harness.

## Current evidence

The final R3 offline suite passes 33 tests, including the actual authorized 57-entry public ledger, production native R2 wire fixtures for all four kinds, known-zero, entered-stop and UNKNOWN-with-release. The frozen old controller still passes its 38 tests and all 17 files compare byte-identical to the original input prototype. Actual prior history plus modeled TEST/formal transitions is compatibility evidence, not live interaction evidence. No game GET/POST, token read, runtime configuration edit or world modification was performed by this implementation task.

R3 adds only the already-observed adjacent z32 landing row to jump admission: support y59 must be nether bricks and body/head y60..62 clear. This bounds the immediate possible travel of forward=1/8 samples; it is not an unbounded future-terrain proof or safe-landing assertion. R2 result files remain historical, superseded by `results/public/final-r3-index.json`.

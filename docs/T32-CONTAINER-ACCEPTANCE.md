# T32 bounded barrel withdrawal acceptance

T32 independently verified one ordinary private-singleplayer barrel withdrawal
and its saved result. Three public jobs opened the barrel, withdrew one
cobblestone and closed the menu. Functional acceptance is qualified by a separate
automation failure: the original final-window closure path remains
`HOLD_NO_REPLAY`, followed by known manual ordinary completion. This is not a
fully automatic lifecycle pass or general container-workflow acceptance.

## Original live result

The three original public jobs succeeded through four native mutations: opening
the barrel, two pickup-click actions for the withdrawal, and closing the menu.
Independent verification of the original receipt graph confirmed all job effects
were known, all job-owner releases were confirmed, and no journal action remained
pending. The verifier checked the original native witnesses, owner bindings and
stable-state evidence; it did not infer functional success from shutdown or from
the saved inventory.

Exactly one cobblestone moved from the barrel to the player inventory, with full
item components matching. The barrel's external slots were empty afterward.
Other inventory, armor and offhand were conserved. The final cursor was empty
and menu closed, with known input release and owner cleanup. Sampled player
health remained 20 and sampled position was conserved. This is client-observed
evidence, not independent server confirmation or continuous no-motion proof.

There was no retry or replay of an unknown mutation. The later closure query
problem does not reclassify these known item-transfer effects as unknown.

## Saved result and its limits

After ordinary closure and separate read-safety verification, one stopped-world
reader retained 31 files and exited 0. Independent re-decoding of the prepared
baseline and exact retained copy reproduced the entire saved comparator result
without rereading the installed save.

All four typed player representations showed the exact barrel -1/player +1
cobblestone transfer and conserved logical combined player-plus-barrel item
totals. These are four representations of one player's state, not four transfers
or four players. Unrelated inventory, health, selected slot and saved position
were unchanged. The barrel was closed and empty, and all 75 declared terrain
cells were unchanged. The original source worlds were preserved.

The saved result is deliberately narrower than whole-world equality:

- Full-player records differed beyond the transfer. Motion, rotation,
  attributes, recipe-book fields and the warden timer changed. Saved position
  equality does not imply full pose equality.
- Current and backup full-player records differed; backup synchronization is not
  inferred.
- The barrel gained `keepPacked` with NBT type Byte and value 0, so its metadata
  was not byte-for-byte unchanged. Two unrelated block-entity locations also
  changed, making three changed block-entity locations in total.
- Forty-three existing entity records changed, with no entity identities added
  or removed. Retained item entities were not all typed-equal. No causal
  attribution is made for these broader differences.
- Eighteen retained files changed and thirteen were unchanged. Those file counts
  are descriptive, not a whole-world preservation test.

Saved inspection does not independently establish native success, live cursor
emptiness, menu continuity or process closure. Those facts have their own
original evidence.

## Case-only functional-first timing

T32's reviewed case harness used a 120-second setup bound, a 180-second action
window from the original validated ready sample, an action ceiling 360 seconds
from the immutable Play origin, and a 600-second ordinary closure ceiling from
that origin. These are bounded hang/cleanup allowances for functional acceptance,
not performance targets or a speed claim.

This timing revision was case-only. It did not relax production admission guards,
replace the runtime artifact, reset the original clocks, extend sample freshness
or weaken owner/effect authority, input-release requirements and unknown-result
latches. Original strict failures and predecessor evidence remain retained.

## Manual closure qualification

The original orchestrator stopped with `HOLD_NO_REPLAY` during a read-only
unloaded-window focus query after the known game Quit. Its failure was a focus
check, not an uncertain item-transfer mutation. The original automation result
remains failed; no uncertain GUI call was repeated.

Known manual closure of the remaining launcher and console windows completed
ordinary lifecycle closure in 135.015 seconds, inside the original 600-second
lifecycle bound. All nine original process identities were absent, and no game,
launcher or bridge listener remained. The four tracked owner exit codes were 0.
Java's numeric exit was unobserved and remains null. Neither owner exits nor
process absence may be substituted for an observed Java exit code.

The final acceptance is therefore one functional and saved withdrawal with
manual final-window closure. Later source or closure changes cannot retroactively
turn this original automatic HOLD into a pass. Live work stopped pending review
of the next scope.

## Coverage that remains open

This case accepts one ordinary barrel and one single-item withdrawal. It does
not accept deposits, repeated transfers, partial stacks, multiple containers,
other container types, hopper behavior, full inventories, interruption/recovery,
portable or nested-container contents, or a broader storage workflow.

The separate [bounded container platform checklist](container-platform-acceptance.md)
still requires its seven genuine-loader tests and designated read-only endpoint
fixtures. One successful barrel interaction does not supply that test suite,
the four-box observation-budget checks, metadata/truncation cases or nested
container coverage. See [Capability status](CAPABILITY-STATUS.md) for the
remaining acceptance boundaries.

Earlier unknown and HOLD outcomes remain preserved. This summary does not
authorize replay, resuming a paused task, a new live case, multiplayer access or
changes to the original worlds.

## Runtime and publication provenance

T32 used the separately bound consume-completion runtime also identified for
T31, with 877 runtime-source files. Its runtime-source manifest is distinct from
the public-source publication inventory.

- Runtime artifact SHA-256: `604032f4dc734dd16431ac9c99d16e2df336a9ecb96f15250d3f8da30de414d5`
- Runtime-source manifest SHA-256: `da84a430ac2ae8b715540df1edc760692eb2844546c2b44ba52b338d212cae05`
- T32 final handoff SHA-256: `f38a2236783974ef15f75f922ec93d899f8f193eb7f4dd7479e5cdb6ee26ef2c`

The separate r2 source consolidation was published as commit
`f09382b4fd1a3e7324ad3af466b3a8b082de59a3`. Its
[CodeQL analysis run](https://github.com/vavilonska/mc-dot-controller/actions/runs/38704084001)
completed successfully for Python, JavaScript/TypeScript and Java/Kotlin. That
result establishes this analysis run only, not a full Gradle/NeoForge build or
gameplay acceptance. This T32 documentation is a later evidence summary, not
proof of deployment or live testing of a newly rebuilt r2 artifact.

Only bounded summaries and source hashes are included here. Raw receipts,
private paths, coordinates, account/player identities, runtime/action/job
identifiers, saved worlds and binaries are not distributed.

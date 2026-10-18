# Capability evidence and outstanding acceptance

Current combined source adds bounded local routes and explicit terminal defense.
Both require their own combined runtime/live acceptance; the historical cases
below are unchanged. See [quickstart](TOOLBOX-QUICKSTART.md).

This matrix records the bounded evidence available through T34 on 2026-10-15.
It preserves the published r2 checkpoint, including T17 qualified collection,
and the exact T29–T31 handoffs summarized in
[Bounded acceptance](T29-T31-ACCEPTANCE.md). It adds the separately verified
[T32 barrel withdrawal](T32-CONTAINER-ACCEPTANCE.md), whose final-window closure
was manual and whose original automatic HOLD remains preserved. It also adds
[T34 qualified single-block descent](T34-DESCENT-ACCEPTANCE.md), accepted by
separate review of the original live evidence and saved endpoint while retaining
the original geometry-comparator failure.
It is a capability-level overview, not a declaration that every toolbox case
passed. In particular, the complete 49-case toolbox has not been live-accepted.

“Bounded live and saved” applies only to the stated case and its pinned runtime.
“Qualified” retains a failed harness or automation step alongside independently
verified results. “Offline/source only” does not establish ordinary-world
gameplay. Historical evidence is not transferred to an untested integration,
rebuild or new runtime artifact. Unlisted variants remain unaccepted here.

## Acceptance matrix

| Capability | Evidence accepted or retained | Outstanding acceptance |
| --- | --- | --- |
| Hotbar and inventory transfer | Earlier public cases are recorded as accepted in the source checkpoint. | Broader item/menu combinations and acceptance on a newly consolidated artifact; no additional coverage is inferred from this summary. |
| Local flat movement | T13 bounded live and saved: one cardinal flat-block movement with conserved health/inventory and ordinary closure. | Obstacles, long routes, unknown/unloaded terrain, dynamic hazards and generalized pathfinding. The separate T34 result does not expand the flat-movement contract. |
| Single-block descent | Reviewed `navigate_step_down` source is integrated. T34 qualified live/saved acceptance: one ordinary-input cardinal descent, native `path_reached` after 21 ticks, 0.194367-block horizontal error inside the unchanged 0.23 radius, conserved health/food/gear and ordinary closure. Original case failure remains; narrow source-derived bbox/roof geometry review accepted the original evidence separately. | A newly rebuilt integrated artifact still needs its own live acceptance. Terraces, obstacles, step-up, jumping, continuous trajectories and multi-step/chained routes remain outside this case. An accepted landing need not meet the next segment's tighter source-centering requirement. |
| Mining | T15/T16 functional and saved results retained. T16 saved target was air and inventory gained one ordinary oak plank. T15 missed its closure bound; T16 automatic HOLD remains despite manual closure. | A fresh fully automatic accepted mining case, broader targets/tools and independently scoped collection. Mining does not prove which drop caused the gain. |
| `collect_local` | T17 qualified independent live/saved acceptance: one plain oak-plank pickup, known public effect and confirmed cleanup, plus automatic closure in 57.553 seconds. Native `cancelled:scoped_collect_target_absent` is retained; the original success-only harness failed. | Other items, quantities, moving targets, interruptions and generalized collection. No separate after-public observation or causal drop attribution was established; acceptance is tied to the original T17 runtime, not this new consolidation. |
| Combat | T21 independently accepted one single-target attack and exact cancellation with saved target/player checks. Original harness encoding-comparison failure remains retained. | General engagement, chase, multiple targets, kill/loot, effective damage blocking, ranged use and unattended survival. No causal attribution of all target damage. |
| Local placement | T23 bounded live and saved: one stationary ordinary cobblestone placement, material decrement and release/cleanup. | Other blocks/states, movement-assisted placement, multiple cells, blueprint execution and full construction. T22 remains unknown. |
| Crafting | T24 bounded functional/saved result: two oak planks to four sticks. Automatic `HOLD_NO_REPLAY` remains; manual ordinary closure completed. | Fresh automatic closure acceptance, other recipes/workstations, batching and resource-to-product workflows. The later adapter fix does not rewrite T24. |
| Furnace interaction and close | T29 three-job chain includes one successful furnace open and close with confirmed owner/input release. | Other block menus, faces, geometries, distances and interruption paths; general interaction coverage. T26/T28 unknowns remain. |
| Smelting | T29 bounded live and saved: one sand plus one oak plank produced one collected glass; automatic closure passed. | Other recipes/fuels, multiple outputs, blast furnace/smoker, partial-output recovery and automatic material acquisition. |
| Equipment | T30 bounded live and saved: one torch/offhand shield swap with exact inventory/component conservation; automatic closure passed. | Armor destinations, different components/items, other displacement rules and repeated loadout changes. |
| Consumption | T31 bounded live and saved: one water-breathing potion, one returned bottle and observed amplifier-0 effect; automatic closure passed. | Food, milk, other potions, stack/container cases, interrupted use and broader terminal-ordering behavior. Exact effect decay/expiry is not proven. |
| Barrel withdrawal | T32 qualified live/saved acceptance: three public jobs and four native mutations transferred one cobblestone from one ordinary barrel to inventory, with confirmed input/owner release. Ordinary completion took 135.015 seconds with manual final-window closure; automatic `HOLD_NO_REPLAY` remains. | Fresh fully automatic lifecycle acceptance, deposits, other quantities/containers, full-inventory handling, interruptions and composed storage workflows. Saved position was conserved but rotation and broader world records changed. |
| Bounded container observations | Source/offline snapshot work and a documented real-platform acceptance checklist. | The checklist's seven genuine-loader tests and designated read-only metadata/budget/container fixtures remain a separate unmet gate in the cited checkpoint. T32's single barrel withdrawal does not supply that coverage. |
| Bounded local route | Source and offline evidence for `navigate_route_local`: loaded cardinal flat/up-one/down-one segments, physical endpoint centering, bounded detours and original-owner budgets. | Combined artifact/FML lifecycle and sustained ordinary-world route acceptance remain pending. No unloaded/global navigation claim. |
| Explicit terminal defense | Source and offline production-entry evidence for caller-selected `defend_once` after known damage interruption and native input release, retaining the same owner. Default remains stop. | Combined ordinary-world reaction acceptance remains pending. No arbitrary target acquisition, unknown retry, ordinary-task resume or general survival guarantee. |
| Broader navigation and transport | Guarded source and offline/synthetic evidence described by the capability package. | Ordinary-world route diversity, steps/stairs, boats and their full movement/cleanup chains on the target runtime. |
| Resource production and long goals | Bounded recipe/resource/scheduler implementations with explicit prerequisites and offline tests. | Composed ordinary-world acquisition, reservations, production, interruption and safe resumption. Individual T29–T31 successes do not validate composition. |
| Blueprint building | Planning/source evidence; the public scoped-placement contract keeps `build` and `build_with_materials` unavailable for runtime execution. | Supported front-door execution, material staging, multi-cell placement, access/support handling and final physical audit. One placed block is insufficient. |
| Dimensions and End workflows | Bounded implementation and synthetic/platform checks with documented prerequisites. | Ordinary-world transition, encounter, collection and expedition acceptance. No general End completion, guaranteed drops or city discovery is established. |
| Recovery, watchdog and parallel planning | Existing guarded implementations and historical/offline evidence remain separate from the new microtrials. | Current-runtime hazard recovery, combat recovery and integrated parallel-owner live acceptance. Automatic resumption and universal unattended operation are not established. |

The source documents remain authoritative for the detailed contracts:
[Movement](MOVEMENT-T13.md),
[T34 qualified descent](T34-DESCENT-ACCEPTANCE.md),
[Scoped descent source](SCOPED-STEP-DOWN.md),
[Mining collect and combat](MINING-COLLECT-COMBAT.md),
[Scoped placement](../capability-runtime/docs/SCOPED-PLACEMENT.md),
[Crafting](CRAFT-T24.md),
[T32 barrel withdrawal](T32-CONTAINER-ACCEPTANCE.md),
[Container platform acceptance](container-platform-acceptance.md),
[Reusable capabilities](../capability-runtime/README.md), and
[Source checkpoint](../SOURCE-CHECKPOINT.md).
Earlier development-only and pre-T21 statements in those documents are historical
checkpoints; later bounded results apply only to their explicitly named scope.

## T17 collection qualification and provenance

T17 is an independently qualified collection result, not an offline-only
capability. The original harness expected native `succeeded` and failed with
`original_receipt_not_succeeded`; the actual original terminal was the allowed
`cancelled:scoped_collect_target_absent`. Additive verification of the exact
original receipts passed six tests and independent review. It established one
observed item gain, known public effect and confirmed cleanup without rewriting
the original failed report or its strict saved requirements result.

The last original stable sample was grounded and settled. A distinct observation
after public completion was absent, so no such sample or continuous stationarity
is claimed. Independent retained decoding confirmed one plain oak plank added
in slot 9 across all four typed player representations; unrelated inventory and
health were conserved, saved position equaled the last original stable position,
and the 150 compared terrain cells were unchanged. The target item identity was
absent. This does not establish the causal origin of the drop, whole-world
identity, independent server confirmation or future dynamics.

Ordinary automatic closure completed in 57.553 seconds. All four tracked child
exits were zero and nine original process identities were absent; Java's numeric
exit remains unknown. The original strict saved result
`STOPPED_RETENTION_COMPLETE_REQUIREMENTS_NOT_MET` remains preserved alongside
the later additive, exact-original stable-state reconciliation.

- T17 final completion seal SHA-256: `be6c19e703085fd73e68867478e684a771b1610cf5a3130a8cf3fc35516c6324`.
- T17 installed runtime artifact SHA-256: `8048dde926387954edd47028703da0c2b3c8b97a1b441f85de77d670e741b3e7`.

This historical runtime identity is separate from T29–T32 artifacts and from this
public-source manifest. No raw receipt, world coordinate or runtime identifier
is distributed here. No action was retried or replayed for this correction.

## Outcomes that must not be promoted to success

| Record | Retained interpretation |
| --- | --- |
| T10 | Known pre-admission size refusal; no movement acceptance and closure over its bound. |
| T12 | Admitted movement cancelled at native tick 1 without successful continuation. The missing rejected world tick prevents a retrospective cause claim. |
| T14 | Original mining preview outcome remains unknown. Reconstructed wire measurements do not recover it. |
| T15 and T16 | Functional/saved mining evidence does not erase T15's closure failure or T16's automatic HOLD. |
| T17 | Qualified independent live/saved collection and automatic closure are accepted; the success-only original harness failure and missing separate after-public observation remain preserved. |
| T21 | Independent bounded attack/cancel evidence is accepted with the exact documented encoding reconciliation; the original failed harness report is preserved. |
| T22 | Original placement result remains unknown after the reported effect/packet. T23 is a distinct accepted case. |
| T24 | Qualified craft acceptance retains the report-size automatic HOLD and subsequent manual closure. |
| T25 | Pre-job driver-schema failure; no accepted live smelt. |
| T26 | Original interact remains unknown; smelt and close jobs were not submitted. Process exit does not by itself release a paused semantic lease. |
| T27 | Pre-play startup abort; no world load or public job. It is not a failed or passed smelting action. |
| T28 | Original interact remains unknown; smelt/close did not start. Later ray evidence makes the precision cause an inference, not an observed failing-instant fact. |
| T32 | Known withdrawal effects and saved persistence are independently accepted. A later read-only focus query left automatic `HOLD_NO_REPLAY`; known manual closure of the final windows did not erase it. Java's numeric exit remains unknown. |
| T33 | Known pre-Play harness abort: `t33Origin` was undefined before `pressKey` could be called. The input latch was set, but no origin, Play, public job or descent action occurred; original `HOLD_NO_REPLAY` remains. Known window closure completed within the original deadline, Java/launcher/Resident exited 0, six original process identities were absent and all 31 prepared-world files were unchanged. T34 corrected only case-harness App binding and pre-latch checks, leaving the product unchanged. This was not an unknown mutation or a descent action failure. |
| T34 | The original case report still fails `protected_player_inventory_health_food`. A separately reviewed additive verifier checks pose-derived bounding-box translation and shelter `roof_y`, then reruns every other frozen check. Known native success, saved endpoint and ordinary closure do not rewrite the original report or establish a composable route. |

Later passing cases do not authorize replay, restocking, resuming a paused owner
or relabeling earlier evidence. Unknown outcomes require the original read-only
reconciliation contract; they are never a retry instruction.

## Remaining integration gates

1. Preserve the exact published r2 source commit
   `f09382b4fd1a3e7324ad3af466b3a8b082de59a3` and its separate offline evidence.
   Any follow-on revision needs its own reviewed manifest and applicable checks.
   T29–T30's runtime artifact differs from the later artifact used by T31–T32;
   neither runtime manifest is a publication manifest. The published r2
   [CodeQL run](https://github.com/vavilonska/mc-dot-controller/actions/runs/38704084001)
   passed all three language jobs. The subsequent T32 documentation was published
   as `ade1df19b661701c96c6ffa088bc1df709fd3979`, also with successful
   [three-language CodeQL analysis](https://github.com/vavilonska/mc-dot-controller/actions/runs/38706299826).
   This T34 source integration and its distinct tested runtime require separate
   bindings; previous publication/analysis results do not establish a full
   Gradle/NeoForge build, deployment or live acceptance of its rebuilt artifact.
2. Keep source, synthetic-wire/policy, native/platform, live, closure and saved
   acceptance separate. A successful source merge or offline suite cannot stand
   in for live validation of the resulting artifact.
3. For a future authorized live case, choose one explicit unsupported scope,
   preserve the original world and prior evidence, use a distinct test copy,
   and define bounded success, input/owner release, closure and saved checks.
   A new case must not consume or replay an uncertain prior action.
4. Preserve the known limits in every summary: client-observed evidence is not
   independent server confirmation; sampled pose is not continuous no-motion;
   selected-field equality is not whole-world equality; Java's unknown numeric
   exit is not an observed zero.

These are outstanding gates, not authorization to run them. No further live
tests were started by the T34 handoff. The original worlds and paused tasks
remain protected, and multiplayer is outside this evidence.

# Bounded smelting equipment and consumption acceptance

The completed T29, T30 and T31 cases establish three separate, bounded ordinary
private-singleplayer results: one sand-to-glass furnace chain, one offhand swap,
and one water-breathing potion consumption. Each has original live evidence,
ordinary automatic closure and separately checked saved-state evidence. They do
not establish a combined end-to-end production workflow or general capability
coverage. The evidence belongs to the exact runtime artifacts listed below;
publishing source or rebuilding a JAR does not transfer that live acceptance.

## T29 furnace interaction and smelting

Three original public jobs, `interact`, `smelt` and `close`, succeeded through
seven native mutations. Independent review verified the original evidence and
the exact consumption of one sand and one oak plank, with one glass collected
into inventory. The final live menu was closed and the cursor empty. Native
input release and all three job-owner releases were confirmed. Player health
remained 20 and the sampled pose was conserved.

The separately stopped-world inspection and retained-only independent decoding
confirmed the -1 sand/-1 oak plank/+1 glass inventory delta in all four typed
player representations. These are mirrors of the same player, not four players
or four production results. Other inventory and the protected paper and shield
were conserved. The saved furnace was empty and unlit, with burn/cook timers
0/0 and total cook time 200. All 75 declared terrain cells were unchanged.

Live completion permitted residual heat. The later saved furnace state does not
establish its state at every intervening tick. Saved NBT does not prove menu,
crafting-grid or cursor emptiness; the live menu evidence is separate. Full
player data changed, including motion/rotation, attributes, recipes and warden
tracker fields, and current/backup full-player records differed. Furnace
serialization also changed. Thirty-nine existing entity records changed and
one original item entity disappeared; no causal explanation is established.

This accepts one ordinary furnace, recipe, fuel and collected-output chain.
Other menus, furnace variants, recipes, fuels, batches and material acquisition
remain outside this live result.

## T30 offhand equipment swap

One original public equip job succeeded through one native slot-swap action.
One torch moved from an ordinary inventory slot into the offhand and the
original shield moved into that source slot. The selected paper, other inventory,
armor and main hand were conserved. The cursor was empty, sampled player health
was 20, and input release and owner cleanup were confirmed.

Stopped-world inspection and independent retained-only decoding found exactly
that swap in all four typed inventory representations. All original item counts
and components were conserved; health, saved position and the 75 compared
terrain cells were unchanged. Full-player data was not equal: motion,
attribute-list ordering and the warden timer differed, and current/backup full
players differed. Forty existing entity records and two block entities changed;
no entities were added or removed. Those broader changes are descriptive.

This accepts one ordinary offhand swap. It does not validate all armor slots,
equipment rules, item components, displacement cases or repeated loadout changes.

## T31 potion consumption

One original public consume job and one native action succeeded with terminal
reason `item_use_finished_observed`. One water-breathing potion was consumed,
one plain glass bottle returned to its inventory slot, and a new
`minecraft:water_breathing` effect with amplifier 0 was observed. The original
live evidence contained duration samples of 3592, 3589 and 3580 ticks. The menu
was closed, cursor empty and player no longer using the item. Input release and
owner release were confirmed. Paper, shield, other inventory and gear were
conserved; health remained 20 and sampled position was unchanged.

The stopped-world result and independent retained-only decoding confirmed
-1 potion/+1 bottle and the amplifier-0 effect with saved duration 3443 in all
four player representations. Health and position, unrelated inventory and the
75 compared terrain cells were unchanged. The original source was preserved.
Full-player data and current/backup records were not equal: motion, attributes
and warden tracker fields differed. Forty-three existing entity records and two
block entities changed; no entity identities were added or removed.

The durations are observations, not an exact consumption time, decay-rate or
expiry proof. Saved elapsed world time does not supply the missing proof. The
native completion correction covers the reviewed terminal ordering; this one
case does not accept food, milk, other potions, stacked items or interrupted use.
There was no retry, restock or replay of an unknown action. Live work stopped
pending review of the next scope.

## Closure and evidence boundaries

| Case | Public jobs | Native mutations | Ordinary automatic closure |
| --- | ---: | ---: | ---: |
| T29 smelt chain | 3 | 7 | 71.209 seconds |
| T30 equip | 1 | 1 | 55.307 seconds |
| T31 consume | 1 | 1 | 68.737 seconds |

Each case records automatic ordinary closure inside its original 180-second
bound, confirmed input/owner release, and a retained 31-file saved copy with
independent re-decoding. The tracked launcher, Resident, Watchdog and MCP owner
receipts record exit 0. Java's numeric exit was unobserved and remains null in
all three cases. Process absence and a checker or owner exit must not be
substituted for a Java exit code. T30 and T31 additionally record absence of all
nine original process identities and the bridge listener.

Functional proof, process closure and saved persistence are separate evidence
layers. A live-only review does not prove persistence; a retained-save reader
does not retroactively prove native success or GUI closure. The final handoffs
combine the relevant records without expanding any individual review's scope.

All action results remain client-observed, with no independent server
confirmation or multiplayer acceptance. Sampled stationarity does not prove
continuous absence of motion. Equality of selected inventory/terrain fields
does not establish whole-world equality or unchanged full-player NBT. No causal
attribution is made for unrelated saved entity or block-entity differences.

Earlier outcomes remain intact. T26 and T28 original interact outcomes remain
unknown and cannot be replayed. T28's precision explanation remains an inference
because the failing-instant coordinates were unavailable. T25 remains a pre-job
driver-schema failure and T27 a pre-play startup abort, neither a passed smelt
case. Earlier T14/T22 unknown outcomes, T15 closure failure, T16 automatic HOLD
and T24 automatic `HOLD_NO_REPLAY` are not converted into passes by these later
cases. Historical acceptance and remaining work are summarized in
[Capability status](CAPABILITY-STATUS.md).

## Runtime provenance and publication

T29 and T30 used the same reviewed runtime-only quantized-ray candidate. T31 used
the subsequent consume-completion candidate. The runtime-source manifests below
are runtime bindings, not public-source publication manifests.

| Cases | Runtime artifact SHA-256 | Runtime-source manifest SHA-256 |
| --- | --- | --- |
| T29 and T30 | `730e08b58aabcfa4297a296c81055c72ade0b093f623b0d6e7db901cd8eca8f4` | `0bd260b65bd38e98a5a308b2620f73cc92e10f4dd7fb808dd1d83fed3a947b5e` |
| T31 | `604032f4dc734dd16431ac9c99d16e2df336a9ecb96f15250d3f8da30de414d5` | `da84a430ac2ae8b715540df1edc760692eb2844546c2b44ba52b338d212cae05` |

Exact final handoff SHA-256 values:

- T29: `af17a12410a46fb96933f60867c2f47ad7dd5fd9977b22fdd9b28e658e1b8c41`
- T30: `0ccfbc75d55eb8702496ad759afc7befb8a7abe56018bab9fa70b8b392d4f927`
- T31: `3e5b519c7555deee1398912d71e9b99d9110f847be19527ba25d117ef98173e3`

This summary distributes no raw receipts, session paths, coordinates, player or
account identities, action/job identifiers, world files or runtime binaries.
Any source consolidation needs its own reviewed manifest and offline checks.
Neither this document nor source publication authorizes deployment, a new game
run, resuming a paused task or replaying an unknown action. Original worlds must
remain preserved.

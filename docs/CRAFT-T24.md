# T24: bounded crafting functional and saved acceptance

One public crafting job succeeded through six unique original click chains.
Independent review reverified those original chains, public success, input release
and owner cleanup. Two oak planks were consumed and four sticks appeared in the
observed inventory slot 35. The crafting grid and cursor were empty in the live
observations. Player health was 20 and sampled position was conserved; continuous
absence of motion is not claimed.

Independent stopped-world inspection found the exact -2 oak planks/+4 sticks
change in all four typed inventory representations. Other inventory, equipment
and the selected paper were preserved, along with health, position and the 75
compared terrain cells. Saved grid/cursor emptiness was not established. Full
player data and entity metadata were not unchanged: motion, attributes, recipes
and warden-tracker fields differed; one entity was removed and 39 existing entities
changed. No causal attribution for those entity changes or whole-world equivalence
is claimed.

## Automation and closure limits

Functional and saved acceptance is qualified. Automatic closure remained
`HOLD_NO_REPLAY`: the adapter's 2,465,305-byte full report exceeded its inherited
2,097,152-byte (2 MiB) input limit before projection. This is not a complete
automation pass, and the original HOLD was not erased or retried.

Manual ordinary closure completed in 147.410904 seconds within the original
180-second bound. All nine original process identities were freshly confirmed
absent. The four tracked owner processes returned exit code 0, including MCP;
the Java process's numeric exit code was unavailable. Do not summarize this as
all process exit codes being zero.

A later adapter correction passed offline review but was not live-integrated for
T24. It requires a separately reviewed fresh case; it does not authorize replay
of the consumed T24 action.

## Scope and provenance

This validates one bounded two-plank-to-four-stick crafting job and its saved
inventory result. It does not establish arbitrary recipes, workstations, automated
material acquisition, a building workflow or general unattended automation. The
native product was unchanged for this craft trial; this documentation update also
changes no production code or tests. Earlier T22 unknown and T23 bounded placement
results retain their documented status.

- Tested production publication manifest SHA-256: `83131d302094a07c246b6cbbd3c2485d43b87f62e59cd1f58f2ba4e0595545d8` (874 files).
- Tested artifact SHA-256: `925f179a03dc6ede3b9e6a0aa014f9d9f73c201203e5ce5bbf0e8ebb7b3abc11`.
- Final T24 handoff SHA-256: `db98f89e24d3abf934f2725bd505ad3b8d4787e7ea1457fd8608759a6bc8fad9`.

Private receipts, world data, runtime identities, accounts and installed state are
not distributed with this summary.

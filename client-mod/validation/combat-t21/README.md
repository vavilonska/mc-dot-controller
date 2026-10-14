# T21 field-specific encoding regressions

Run from the repository root:

    python3 -B -m unittest discover -s client-mod/validation/combat-t21 -v

These synthetic tests preserve the two narrowly scoped representation rules used
by the independent original T21 evidence review. They never load live receipts,
read saved worlds, contact a native process or change production validation.
SOURCE-PROVENANCE.json pins the relevant serializer and health producers.
Neighboring float32 values, changed identities, non-null latch triggers, non-false
latch flags, missing fields and unrelated terminal differences must be rejected.
The full trial still requires original owner/action identity, exact cancellation,
input release, player/inventory/world invariants and independent saved readback.
See docs/MINING-COLLECT-COMBAT.md for the bounded result and original harness failure.

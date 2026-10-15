# Bounded intended-ray and consume-completion fixes

This source consolidation retains the finite block-menu exception diagnostics
and adds two independently reviewed fixes. Public source metadata remains
separate from the test runtime's versioned JAR and runtime-only source inventory.
The source tree is not a claim that a newly built release was deployed.

## Representable intended block-menu ray

Native and Resident validation now compare the actual ray to the hit produced by
the intended binary32 yaw/pitch and the engine's lookup-table view vector, rather
than to the ideal double-precision face center. The existing 0.0001 hit tolerance
is unchanged. Intended angles must match exactly, and identity, face, inward
entry, strict face interior, reach, captured cell prism, obstruction checks and
owner/effect fences remain required. Native angles are serialized as doubles
holding exact binary32 values. The wire schema remains unchanged.

The old predicate can reject a legitimate quantized hit in a reproduced geometry
case. That is evidence for the precision explanation, not proof of the exact
failing-instant ray in an earlier live action. Earlier unknown outcomes are not
reclassified or made safe to replay. Pathological cross-runtime atan2/hypot
rounding boundaries may still fail closed.

## Consume completion ordering

The original completion predicate is observed in guarded Pre, after tick
advancement and before vanilla held-key handling, as well as in Post. Completion
can therefore release a finished use before another mainhand/offhand use starts.
Pre does not dispatch use. The later-tick requirement, capability guards,
terminal reasons, request/result schemas and existing cleanup remain unchanged.
An additional identity/context recheck prevents observation callbacks from
finishing a replacement owner or stale player/world.

The regression executes type-aliased actual compiled method instructions, pinned
engine held-key/hand iteration and shield-use code, with explicit environment and
cleanup doubles. Modeled potion effects, bottle PASS and cleanup are not actual
world execution. This does not establish arbitrary mod callback safety.

## Evidence boundaries

The separately reviewed T29–T31 live and saved results are documented in
[T29–T31 acceptance](T29-T31-ACCEPTANCE.md). Offline component regressions, source
compilation and Mixin bytecode transformation are distinct from those trials.
Neither proves a complete Gradle/NeoForge distribution build, arbitrary recipes,
all items or unrestricted unattended operation. See the [capability status](CAPABILITY-STATUS.md)
for bounded acceptance and remaining work.

## Reproducing repository checks

Run the [portable regression package](../client-mod/validation/consolidation/README.md)
with explicit local dependencies and a new external output directory. For the
broader repository suite, use a disposable copy of this source tree, run
`python -B capability-runtime/tests/fixtures/generate_crystal_worlds.py` there,
then run `python -B capability-runtime/run_checks.py` with `MDC_TEST_OUTPUT`
pointing to a new external output directory. The supported runner supplies all
nine module roots and the watchdog candidate path required by CLI subprocess
tests. Bare unittest discovery without that environment is not an equivalent
invocation. The generated synthetic gzip is a test prerequisite, not part of the
published source inventory, and must not be confused with private world data.

Windows/PowerShell execution is not validated by the synthetic platform test.

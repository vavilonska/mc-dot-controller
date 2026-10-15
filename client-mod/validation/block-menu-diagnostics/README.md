# Block-menu diagnostic transport regression

This source adds diagnostic-only fields to an admitted block-menu exception receipt. It does not change terminal status/reason, local-effect markers, ownership, guard predicates, deadlines, packet sends, or outer unknown classification.

`block_menu_diagnostics` has exactly six fields: schema_version, stage, phase, exception_type, rejection_code, capture_elapsed_nanos. Stages/phases are enums. Exception categories are fixed. A finite rejection-code allowlist accepts only known literals from the production guard sources; other messages become an unclassified category. Arbitrary messages, exception class names, stacks and player/inventory values are not serialized. Elapsed nanoseconds are diagnostic, never authority.

Recording occurs only in the existing synchronous block-menu catch after `active == admitted`, before unchanged cleanup. It cannot attach a stale exception to a replacement owner. Already-finished/nonthrowing refusal paths retain their original behavior and are not retroactively annotated. A phase identifies the last-started step, not proof of which nested callback caused a failure.

## Executable scope

`BlockMenuDiagnosticsChecks.java` compiles against all fresh production classes and the pinned genuine engine. It tests 250 stage/phase/cleanup combinations, exact known rejection transport through the production BridgeJson serializer, sanitized unknown reasons, unchanged action identity and terminal semantics, detached wire JSON, finite output, and four checks using real engine geometry classes with synthetic translated furnace coordinates. Expected output: 3018 assertions.

These are production diagnostics/ActionRegistry transport and geometry tests, not execution of ClientActions.interactBlock, its actual cleanup, or injected runtime hook failures. No client, server, world, installed mod, or original action is launched or replayed. They cannot identify T26's lost rejection code or prove a furnace opens. The original unknown remains unknown.

A separate pinned Mixin bytecode-only harness validates actual transformations and injection ordering, including a missing-target negative control. It is not a gameplay test.

The published fixture translates private observed geometry to a synthetic origin and uses a synthetic elapsed value. The original private fixture and evidence remain unchanged. The original diagnostic checkpoint preserved the reviewed production bytes. This consolidated tree additionally includes the reviewed representable-ray and consume-completion changes; the diagnostics vocabulary remains unchanged. The 3018 assertions were rerun against fresh integrated production classes. No private trial artifacts are included.

## Reproduction

Use JDK 21 and the project-pinned genuine dependency classpath. With all production
sources freshly compiled into a separate output directory, compile this Java
file against that output plus the same dependency classpath, then run
`io.github.campione01.mineclientbridge.BlockMenuDiagnosticsChecks` on that combined
classpath. An optional single output-directory argument writes two synthetic
terminal receipts for consumer checks. The directory must already exist. No
network, world or runtime configuration is needed. Expected final output is
`PASS 3018 assertions; genuine production diagnostics/registry/geometry; no client/world bootstrap`.
Dependencies and generated outputs are intentionally not distributed.

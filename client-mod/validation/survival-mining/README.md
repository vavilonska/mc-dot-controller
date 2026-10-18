# Survival mining bootstrap offline checks

This source-only extension adds six explicit log IDs (oak, spruce, birch, jungle,
acacia, dark oak) with exact axis and two zero-XP iron ore IDs. It does not start,
control, deploy to, or validate a running game. Each target is still one stationary
ordinary break action with the original owner/callback/reach/tool/health/input
release and unknown-outcome fences.

The footprint accepts only explicit exact vanilla classes and complete state
properties: the six leaf species, dry short/tall grass and ferns, twelve ordinary
one-block flowers, and vines. Every cell remains loaded, fluid-free and without
block entities. Full solids/leaves require full-cube collision and outline;
plants require empty collision. Only harmless collision-empty plants may share
the stationary player body cells. Vines and leaves are excluded there; plants
and potentially decaying leaves cannot be standing support. Any mid-action
state change still stops the action. There is no foliage-equivalence relaxation.

Coal/deepslate coal are context only. Their XP-producing extraction is not
supported. Other XP-bearing ores, bamboo, modded/replaced classes, fluids,
falling blocks, harmful plants and other unknown geometry remain unsupported.
This is intentionally not a complete jungle-harvesting or Ender Dragon route.
Pickup, route planning, tools, crafting, smelting, and stations remain separate
capabilities. Broken blocks do not establish drop pickup or causal loot.

The original placement vocabulary is separately retained as LEGACY_BLOCKS,
LEGACY_STATIC and LEGACY_TARGETS. Extending mining must not expand placement.

## Reproducible current source and cross-language wire check

Supply the trusted Java 21 installation and existing compiler-only classpath:

    JAVA_HOME=/verified/jdk21 MDC_NATIVE_CLASSPATH=/verified/existing/jars \
      python3 -I -B client-mod/validation/survival-mining/run.py /new/output

The runner creates an exclusive output directory, compiles every current
production Java source, executes the production pure cell policy and actual
BridgeJson HTTP serializer, and sends those original emitted files to the real
Resident witness validator. It checks exact Java/Python vocabularies and classes.
34 synthetic admission/terminal fixtures cover each supported log axis, both
iron ores, natural leaves/plants/vines, coal context and deepslate context.
Negative native and Python cases cover wrong classes, missing/extra/typed state,
waterlogged foliage, unsafe support/body cells, hazards and unsupported targets.
Fresh public-tool integration tests execute the actual Runtime, watchdog and
Resident chain, replacing only the native endpoint. Cancellation, cleanup,
known/unknown outcomes and no-replay regressions are retained.

SurvivalMiningRegistryChecks is an optional registry/shape check for a genuine
NeoForge test-loader environment. A plain classpath bootstrap is insufficient:
NeoForge requires an initialized LoadingModList. Compilation is not evidence
that this optional check ran. No live native admission, callbacks, removal,
physics, pickup, or gameplay acceptance is claimed by this runner.

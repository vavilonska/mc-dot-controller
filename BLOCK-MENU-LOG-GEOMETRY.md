> Historical version-specific source contract; current source identity and publication validation are in [latest publication](docs/latest-2026-10-25/README.md).

# Bounded vanilla log geometry for block-menu dependencies

Base: the immutable 1.1.8-recovery-test.2.7 source. This change applies only to the existing block-menu preflight geometry policy. It does not add menu target families, mining actions, drop/XP assumptions, movement permission, or a retry path.

## Closed geometry addition

The native helper accepts only exact `RotatedPillarBlock` instances which are one of the 32 canonical overworld log/wood identities: oak, spruce, birch, jungle, acacia, dark oak, mangrove, and cherry, with log/wood and normal/stripped variants. Other pillars, stems, hyphae, bamboo, roots, unknown providers, fluids, and subclasses are not added.

All three canonical axis states inherit the audited static full-cube outline/collision and empty fluid implementation. Resident mirrors the 32 identities and additionally requires exactly one `axis` property in x/y/z, exactly one full-cube outline and collision AABB, and the existing empty-fluid rule. Existing support, body, ray, ownership, source clock, callback, local-use and packet fences remain in place.

## Refused dependency diagnostic

At the existing geometry rejection, the native code records one already-loaded dependency cell and its bounded class name. It does not read a registry, shape, fluid, neighboring cell, or new world fact for diagnostics. Coordinates are read only from an exact immutable BlockPos. Unknown/non-vanilla provider classes become `unclassified_provider`.

The closed metadata has schema_version=1, signed 32-bit x/y/z, and provider_class. It is attached only to HTTP409 `block_menu_unknown_geometry_provider`, copied defensively by the typed Rejected wrapper, and validated again by transport and Resident before appearing in the Runtime refusal summary. It never supplies effect-free, input-release, admission or completion authority.

Historical UNKNOWN records remain UNKNOWN. A duplicate public request does not replay its action. A new diagnostic is a refusal explanation, not permission to retry an uncertain action.

## Verification boundaries

Independent native tests use actual official registry identities and shape implementations without launching Minecraft, a server or a world. Public owner-chain tests use the production Toolbox, Runtime, IntentClient, Watchdog, QueueClient and Resident with only the native endpoint synthetic. HTTP parser tests substitute a bounded response object, not its validators. Native registry and public owner tests do not establish live ordinary-world acceptance.

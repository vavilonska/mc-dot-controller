# Bounded container platform acceptance

## Current gate status

This is an operator checklist, not evidence that Minecraft acceptance has passed.
The seven `BoundedContainerSnapshotTest` cases use actual Minecraft objects through
reflection. Their class is enabled only when the environment variable
`MDC_REAL_MOD_LOADER_TESTS` matches `true`. Without that opt-in, all seven cases are
skipped and the real-platform gate remains **UNMET**. A green ordinary offline
suite with these skips does not close this gate.

The previously observed plain-JVM bootstrap failure was a `NullPointerException`
because `LoadingModList.get()` was null. Adding Minecraft jars to a classpath, or
setting the environment variable, does not establish a NeoForge loader. These
tests call real `SharedConstants.tryDetectVersion()` and `Bootstrap.bootStrap()`;
an enabled bootstrap failure must be reported as a failure. Do not substitute a
fake `LoadingModList`, bootstrap, registry, item, component, or container class, and
do not convert loader failures into assumptions, skips, or successful results.

This addition was prepared by reading and writing source files only. No JVM,
javac, Gradle, npm, game process, endpoint, or platform test was run for it.

## Authorization and execution boundary

Only the designated operator may perform the subsequent acceptance pass in the
already approved cloud single-player Minecraft test environment. This document
does not grant permission to start or restart the game, create fixtures in a
world, open a menu, move items, click slots, move the player, attack, run commands,
connect a multiplayer server, or change credentials or access permissions.
The later pass is limited to read-only inventory/container observation using the
existing authorized connection. No other worker should operate the client while
the operator gathers the evidence. Unknown action state is never a reason to
retry an action.

Use only already available fixtures and approved lifecycle permissions. If the
required world, open menu, fixtures, loader-aware test harness, or authenticated
connection is missing, record the missing prerequisite and leave the gate open.
Fixture construction below is in-memory test construction, not a game command or
authorization to modify a world.

## Real-object checks: exactly seven

In an existing genuine NeoForge loader-aware JUnit execution context, select
`io.github.campione01.mineclientbridge.BoundedContainerSnapshotTest` with the
environment opt-in above. The repository's ordinary Gradle `test` task alone is
not proof of such a context; no new launcher or loader integration is supplied by
this change. Confirm the same Minecraft/NeoForge versions and compiled mainline
artifact as the proposed deployment. Run on one thread; the helper budget is
client-thread state. Retain the full test report and loader/bootstrap logs.

1. Null and real `ItemStack.EMPTY`: exactly the legacy five fields `empty`, `id`,
   `count`, `damage`, `max_damage`, with true, empty string, and zero values.
2. Real `Items.STONE`: preserve registry ID, count, damage and maximum damage;
   report zero unrepresented component changes and complete identity.
3. Actual `Component.literal` custom names of 128, 129 and 1024 characters:
   return exactly 128 characters, flag truncation only for the latter two, and
   never claim complete styled/component identity from the plain text.
4. Actual `Items.IRON_SWORD`: its damage prototype is present at zero, setting
   `DataComponents.DAMAGE` to seven is represented by the basic damage field,
   and removing that prototype component gives one unrepresented change and
   incomplete identity even though the numeric damage again reads zero.
5. Real `ItemContainerContents` with plain, named and nested-shulker cargo:
   return basic cargo identity only. Named and nested cargo are incomplete;
   no nested diamond contents, child custom name, arbitrary component payload,
   or recursive container object may appear. The enclosing item is incomplete.
6. Calls through private `BridgeServer.itemSnapshot` and the real helper share
   one four-box allowance. Boxes one through four expand; the fifth preserves
   its extent but has no returned cargo, is truncated and is incomplete.
   `beginSnapshot()` restores the allowance for the next observation.
7. A real in-memory 28-slot container preserves `slot_extent=28` and returns
   only slots 0 through 26, with `capacity=27`, truncation and incomplete identity.

Every returned container must have schema version 1 and
`nested_containers_supported=false`. Exact cargo rows contain only `slot`, `id`,
`count`, `damage`, and `identity_complete`. Passing means all seven tests executed
and passed with zero skips or aborts under the genuine loader. This establishes
real-object serialization, not the live endpoint gate below.

## Operator-only read-only endpoint checks

1. Record the artifact identifier/hash, Minecraft and NeoForge versions, loader
   startup evidence, single-player test-world identity, observation time, and
   whether the necessary fixture menu is already open. Keep credentials out of
   reports. Confirm no requested game action is still in an unknown state.
2. Through the existing authorized local connection, read `GET /control/state`
   and `GET /control/screen` only. Capture successful response bodies and their
   times. An absent world, unavailable fixture or closed required screen is a
   missing prerequisite, not a reason to send input or action requests.
3. Inspect item objects in `state.menu.carried`, `state.menu.slots[].item`,
   `state.player.inventory[]`, armor and offhand, and, where already present,
   `screen.menu` and `screen.slots[].item`. Confirm old field values are preserved
   and additive container/name/identity metadata is consistent with the fixtures.
   Outer inventory/menu rows may add slot-location fields; the five-field empty
   contract applies to the underlying `itemSnapshot`, before those row fields.
4. Check the finite observation budget using the actual serialization order.
   Menu carried/slots are observed before inventory in the state response, and
   before visible screen slots in the screen response. Repeated appearances of
   the same box consume the shared allowance too. Do not assume that every view
   of one box has identical expanded cargo or that every collection gets four
   boxes. After four observed boxes, later ones must explicitly truncate.
5. Read a second state/screen snapshot without changing the fixture. Confirm its
   allowance resets at the observation boundary rather than remaining exhausted
   from the preceding response. Preserve each response independently; never join
   partial views into an unsupported claim of verified complete cargo.
6. For every available named, component-bearing, nested or oversized fixture,
   compare the result against the seven real-object checks above. If a fixture
   is unavailable, label that endpoint check NOT OBSERVED. Do not manufacture it
   during this read-only acceptance pass.

## Acceptance decision

Close the platform gate only with both (a) seven genuinely executed loader tests,
zero failures/skips/aborts and (b) the operator's recorded read-only endpoint
evidence for the required inventory/container fixtures and reset boundaries.
Record incomplete coverage, missing fixtures, plain-JVM bootstrap failures and
default-disabled tests as open gates. A source review, compilation, mock result,
ordinary offline suite, or successful HTTP status alone is insufficient.

Any identity marked incomplete or container marked truncated remains unusable as
proof of exact cargo. This checklist authorizes no game actions and makes no
claim that live Minecraft acceptance has already passed.

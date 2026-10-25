> Historical version-specific source contract; current source identity and publication validation are in [latest publication](docs/latest-2026-10-25/README.md).

# Recovery death-screen GUI — explicit narrow capability

Status: independent candidate; offline review and a death-save TEST are required before formal use. This is not a generic menu/input endpoint and does not weaken the existing interaction v3 movement/mining checks.

## Scope and authority

The startup-only `mineclientBridge.recoveryDeathScreenUi=true` option is valid only with isolated input and the existing exclusive interaction v3 profile. Existing keyboard, mouse motion, scroll, drop, raw game-input and legacy action restrictions remain. The only newly handled hardware event is a real left-button PRESS in the exact game window, on the Minecraft client thread, over the enabled/visible native Respawn button of the exact vanilla DeathScreen for the currently dead local player. The native button's already-constructed callback performs the normal vanilla respawn. No command, invented network packet, direct health/position/inventory change, or synthetic movement callback is permitted.

MouseHandler's general press path is not reopened: it can alter button state and, after callbacks, reach gameplay KeyMapping logic. The DeathScreen's general mouseClicked path is not reopened either: it also handles death-message links. Only the identified original Respawn button may receive its `onPress()` callback; title-screen, spectate, links and other controls are outside this capability. Releases are swallowed, so no accepted GUI press can leave a gameplay button held.

## One-shot and concurrency

Before calling the GUI callback, the native ledger monitor atomically checks the original shared ledger is open, bound, not UNKNOWN-locked, and has no queued/active entry or retained input/mining capture. It claims the small UI lifecycle latch and consumes the one-shot permission for that dead LocalPlayer instance. A concurrent new action submission must lose to the same lock and cannot become an independent input owner. The GUI callback executes outside the ledger lock.

The first implementation is deliberately at most one accepted click per client process, bound to the captured dead LocalPlayer; completing one respawn does not grant a second UI click in that process. Consumption is distinct from in-flight blocking. Resizing/rebuilding the DeathScreen, callback exceptions, releases or repeated presses do not restore permission. After a normal callback return, the lifecycle remains blocked until the original connection/server supplies a different alive local-player object and the death screen is gone. An exception or ambiguous/context-lost transition remains blocked and is reported; no automatic second click or new gameplay is permitted.

This is a process-local UI gate, not a new persistent action protocol. The sole operator separately records the one CUA click and its outcome. An uncertain click may not be repeated or made retryable by restarting. Existing native/public UNKNOWN records remain locked across this UI feature and all old action records retain their original digests, routes and terminal facts.

## Observation and completion

Bounded safe lifecycle log markers distinguish the consumed click, normal callback return and a confirmed replacement alive player. They contain no credentials. Existing read-only v3 observations and supported UI screenshots establish the actual resulting screen, alive/health state, dimension/context and position. A session UUID or player UUID need not change during a normal respawn; player-object replacement and actual world generation are the relevant lifecycle facts. Respawn selects the vanilla bed/world spawn; it is not a teleport to a chosen location.

No additional HTTP action, owner, credential, control loop or general GUI remote is introduced. Normal death/respawn is a gameplay event, not a reason to rewrite the 101 existing known actions as UNKNOWN. Conversely, callback return alone is not proof of completed server respawn.

## Preservation and tests

The frozen formal death state is the only source for the isolated respawn TEST. Do not substitute or restore a pre-death world, heal the player, manufacture equipment, modify keepInventory or erase the failed/death evidence. The original archive and all 101 records remain intact. The original keepInventory setting was already true; preservation is not a rule change.

Offline tests cover flag-off isolation; wrong screen/window/thread/player/button/coordinates; disabled or hardcore/non-Respawn controls; existing queued/capture/UNKNOWN; concurrent start; duplicate press, resize and release; callback exception; pending replacement and context mismatch. Source/bytecode checks must bind the tiny native adapter to those tests and verify there is no general MouseHandler/keyboard/world-write path. Actual 101-entry binary and public terminal compatibility are checked separately. Offline tests do not substitute for a real death-save TEST with one supported CUA click.

## Runtime pacing

Prepare scripts, IDs, package and local route data before opening a maintenance-cold world. During non-paused play, perform timely short-interval health/position/local-threat observations before deciding the next action; do not leave a character waiting for minutes while engineering or planning is performed. A quiet current frame does not guarantee future immunity to attacks. If further engineering is required, use the authorized normal maintenance save/exit boundary rather than unattended live waiting.

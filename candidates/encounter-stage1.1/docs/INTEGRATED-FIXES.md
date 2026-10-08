# Integrated fixes candidate 1.1.7-integrated.2

This is a new, isolated offline union based on the verified `1.1.7-integrated.1` source. It includes exactly the final retreat-consistency, boat-passenger-admission, and offline parallel-validity updates. No ranged-primitives branch is included. Prior integration documentation and standalone branch version labels describe their original scopes; this document and the delivery manifest describe the union.

## Included fixes

- Retreat planning and each execution tick use the same bounded 0.65-block safety windows. Short final windows retain the full 0.1 clearance-improvement threshold and the full 0.65 collision lookahead. Actual player progress and minimum clearance across all threats are checked; changing threat identities, declining clearance, unknown geometry, expired evidence and exhausted budgets fail closed. See `../client-mod/docs/retreat-consistency.md`.
- Health result policy is unchanged, including the 150,000,000 ns wall-gap threshold. New diagnostics distinguish actual sample timing, trigger state and current state without explaining an unknown cause or clearing a latched failure.
- Boat admission uses current native rider attachment/pose geometry and actual AABBs, fixing the incorrect reuse of a buoyancy floor for passenger feet. Rider bodies must fit the checked two-water/three-air prism, with finite/complete geometry, exact native mount matching and bounded yaw clearance. Identity, ordered passengers, driver seat, boat type, water, hazards, speed, loaded cells and collisions remain guarded. See `../client-mod/docs/boat-passenger-admission.md` and `../acceptance/BOAT-DRIVE-LIVE-CHECKLIST.md`.
- Optional coordination distinguishes content revision from sample identity, preserves original capture expiry and lease authority, and requires bounded explicit synthetic threat proof for dry-run ordinary navigation. WAL, revocation, capacity and unknown-outcome gates remain fail-closed. `ResidentAdapter.dispatch`, `.poll` and `.cancel` still hard-reject live execution. See `../multiagent-coordination/INTEGRATION.md` and `../multiagent-coordination/VERIFICATION.md`.

## Merge and safety boundaries

The three production patches affect disjoint files. Every included production file is byte-identical to its independently reviewed branch delivery. Only global version, README context and source manifests require metadata resolution. No fallback live adapter or new native action is added. Existing world/player/session/vehicle/target binding, single active native owner, direct takeover, action termination and input release paths are retained.

Retreat completion still reports residual risk and does not certify safety, threat disappearance, a kill or a server result. Health gaps do not identify damage or network causes. Imported observations do not acquire fresh timestamps or prove threat clearance. Offline fake execution does not prove real multi-agent speedup. Boat input release does not freeze momentum or prove the boat settled.

## Verification and limits

The delivery contains a full source archive, one rebuilt union runtime JAR and its sources JAR, an exact patch from integrated.1, source and package hashes, complete Java/Python/Node logs, clean-build JUnit XML, independent union safety review and branch provenance. The patch is replayed in a new baseline copy and the complete offline regression suite is rerun there; candidate and replay JAR bytes are compared. Counts are parsed from those runs rather than summed from branch totals. One inherited watchdog historical-comparison test remains explicitly skipped because its old frozen source is unavailable.

This candidate has zero post-fix Minecraft executions and is not installed, restarted, deployed or live-accepted. No game, UI, live IPC, credentials, service, backup, Drive or upload operation is part of this work. Windows-specific registration/launch, real keyboard timing and server outcomes are not tested here. Source review and fake transports do not execute Minecraft physics.

The strict native rider mount epsilon of `1e-5` may conservatively reject during tick/interpolation/mount transitions. Its real client-tick behavior still requires a separately authorized observation-rich boat trial. Retreat must likewise be observed under actual tick timing and threats. Keep the original integrated.1 package unchanged for any separately authorized rollback decision; this package contains no installer or deployment authorization.

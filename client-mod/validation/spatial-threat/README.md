# Route-only spatial threat validation

This candidate adds `movement-local-segment-spatial-threat-v1` with `route-spatial-threat-v1`. The old route profile and mining/placement entity policies retain their original semantics.

The new opt-in route requires `route_threat_guard` with exactly numeric integer `schema_version: 1` and a canonical explicit non-player `target_uuid`. It enumerates all client-loaded rows (maximum 1024 including self), preserves removed identity-only rows, and rejects unknown live classes. The new allowlist is the old reviewed list minus rabbit, plus exact vanilla Zombie. Rabbit is deliberately excluded because the class alone does not distinguish killer-bunny goals. No general hostile-ignore switch exists.

The guard uses the full swept player-body corridor, independently projected from every entity's observed velocity and interpolation target over the remaining 160-tick action budget. This is current observed exclusion, not a claim about future AI or physics. Every zombie requires complete, known integrated-server target facts, at most 250 ms and 5 world ticks old. A targetless aggressive zombie is unknown. Other active attackers and non-selected zombies within 8 m refuse. Only the configured UUID actively targeting the current player within 3 m can produce a typed stop. Its current AABB must separate the entire swept corridor.

The optional top-level `route_stop_only` intent field accepts only literal boolean `true` on this new profile. It requires the configured fresh actual attacker at initial capture and each pre-registration recheck; a missing or changed attacker rejects before registration or effects. The original witness stays immutable while a separately captured current server batch is checked. After registration, attacker loss still cancels with no ordinary motion fallthrough. The flag is covered by the original/compiled command digests. Ordinary routes omit it.

## Stop-only admission and continuation

An initial selected attacker may have a future projected corridor overlap only when the registered action immediately cancels before any ordinary view/input/motion effect. Original terrain, player, owner, entity, immutable server-batch, context, freshness and deadline fences still run. The final pose must equal the original admission pose, and the selected entity retains the same object/UUID/id/type/class identity. One completed read-only validation is reported (`local_checks=entity_guard_checks=1`); zero effects are separately reported by `effect_attempted=false`, distance 0, jump count 0 and phase `ground`. No movement/landing accounting is run in this immediate branch.

A target acquired after ordinary effects can cause the same typed terminal only with strict projected exclusion. A targetless admission that gains a target before its first attempted effect cancels generically without typed defense handoff. Motion-gate failures remain unknown and never receive a typed known-threat proof. Every typed stop uses `capability_threat_observed`, carries a full current `route_threat_stop.entity_guard`, and proceeds through existing known input cleanup. Defense authorization remains a separate fresh Python/native combat admission after confirmed original release. There is no route resume.

The server observation source is the pre-existing owning-server-thread `NativeLivingObservation` contract. It binds UUID/id/type, target and clocks but does not serialize the server Java runtime class. The client class is exact-checked. This candidate does not extend that shared observation contract or claim modded server getter attestation.

## Wire budget

Admission frames remain bounded by 192 KiB. Both the stop frame and the **complete stop proof, including its outer envelope**, must fit 32768 Gson UTF-8 bytes, without truncation. Bounding the full proof prevents repeated identity strings from escaping the response reserve. The existing 256 KiB response ceiling is unchanged: reserving a 192 KiB proof three times would make this profile impossible to admit.

The response preview reserves 40960 bytes standalone and 122880 bytes for the coherent three-sibling response (schema 6). One proof uses at most 32768 bytes; the existing 8192-byte per-action terminal reserve covers its member key/comma and ordinary bounded action metadata. Thus admissible preview maxima are 221184 and 139264 bytes respectively, and adding the bounded growth stays within 262144. The existing reserve concerns controller-owned metadata, not arbitrary later growth in unrelated world snapshots. Legacy reserves stay 8192/24576.

An already observed admission attacker is checked for proof capacity before registration. Explicit stop-only current-batch admission fences repeat that check before their final freshness/identity fences. Runtime construction remains bounded before attaching any proof, so later population growth fails closed. A capacity refusal retains `route_spatial_stop_evidence_too_large`; unexpected runtime failures still map to `local_segment_check_failed`. Neither authorizes defense or automatic retry. Guard geometry, stale-data, object identity, zero-effect and release checks remain required.

## Reproduction and limits

`run_engine.py --output <new outside-source directory> --java <java21> --javac <javac21> --gson <gson.jar>` runs the unchanged production old/new controllers, new native row reader, immutable snapshot logic and geometry against explicit synthetic engine/server acquisition. It also reruns all legacy local-segment engine cases. It generates immediate and continuation capture files from the actual controller.

`run_native.py --output <new outside-source directory> --engine-output <engine directory> --java <java21> --javac <javac21> --classpath-file <pinned classpath>` freshly compiles every production Java file, then uses the actual witness/digest, ActionRegistry Entry, HTTP, CapabilitySnapshot and BridgeJson serializers over those captures. It writes original standalone/coherent/request/intent/schema-6-diagnostic JSON. Python consumers validate these bytes without rewriting, using `MDC_SPATIAL_THREAT_NATIVE_WIRE=<native output>/wire`.

These are source-linked synthetic-reader and real serializer checks, not FML/Mixin loading, game physics, actual complete ClientActions lifecycle, or live single-hostile acceptance. A real independent singleplayer live fixture and final artifact review remain required. No frozen T35 or original world is modified by these tests.

`RetainedAdmissionStopChecks` reconstructs the retained T43 admission through the actual Frame constructor and `json()`/`stop()` path with exact Gson measurement. It does not establish the unretained historical current frame or exception. `StopProofBoundaryChecks` checks below/equal/above complete-proof and general-frame byte limits, Unicode byte accounting, outer-envelope overflow, and complete BridgeJson response growth. Its padded transport envelopes are explicitly not semantic defense fixtures.

The engine harness additionally creates `spatial-large-stop`, `spatial-failure-size` (current population expands after a valid admission), `spatial-failure-frame-size` (current live population exceeds the existing 192 KiB general frame cap, preserving `route_spatial_evidence_too_large`), and `spatial-failure-generic` (injected unexpected reader failure). The standard `run_native.py` runs `SpatialThreatWireProducer` over all six captures for unchanged native standalone/coherent/request/intent consumer fixtures. Its budget check uses the detached admission preview, then separately verifies final sizes and growth; it does not reserve the proof a second time against a terminal reply that already contains it.

After `run_native.py` compiles the production and harness classes, the retained-admission and boundary checks are reproducible with:

```sh
CP="$NATIVE_OUT/classes:$(cat "$CLASSPATH_FILE")"
mkdir "$NEW_REPRODUCTION_OUT"
"$JAVA" -cp "$CP" io.github.campione01.mineclientbridge.RetainedAdmissionStopChecks \
  "$RETAINED_RECEIPT" "$NEW_REPRODUCTION_OUT"
"$JAVA" -cp "$CP" io.github.campione01.mineclientbridge.StopProofBoundaryChecks \
  "$RETAINED_RECEIPT" "$NEW_BOUNDARY_OUT" "$NATIVE_OUT/wire/spatial-immediate"
```

Use new output paths outside the source tree; the boundary program creates its own new output directory. `RETAINED_RECEIPT` is the read-only retained T43 `closure-screen-0-receipt-0.json`. `JAVA` is Java 21, and `CLASSPATH_FILE` is the same pinned local dependency list used for `run_native.py`. The native boundary uses actual Gson UTF-8 bytes; Python's independently conservative JSON encoding can reject an extreme boundary it encodes larger.

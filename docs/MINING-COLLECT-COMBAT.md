# Scoped mining, collect and combat integration

This source integration starts from published T13 commit
`9bfd430ee5b7667ae6a036e42df03b1c5d503bac`. It preserves the previous adapter,
test portability and movement checks. It adds the accepted mining-preview and
collect source and the independently reviewed offline combat candidate.
It does not deploy an artifact, start a client or authorize a live action.

## Shared-source merge

Collect was authored against the exact 757-file mining-preview baseline, so its
14-file delta is applied after that complete mining change. Combat was authored
against the same baseline. Shared Runtime capability/action mappings, native
admission/construction and Resident profile validation are merged additively.
The collector and combat profiles stay distinct. Mining's single-authority wire
projection and bounded diagnostics are preserved. Published-main portable test
hashes and discovery fixes are retained rather than overwritten with older copies.

## Mining

The mining route uses bounded native ownership, original intent/witness checks,
entity exclusions and same-effect callback fences. Mining response previews use
the same single-authority representation as actual replies. Size limits are not
increased; reconstructed synthetic wire measurements are not measurements of
the unavailable original T14 preview. T14's unknown outcome stays unknown.

Real mining functional and saved-world evidence must be reported separately
from shutdown timing. Earlier T15 functional/saved success does not turn its
failed bounded closure into a pass. T16 mining and the corrected result parser passed; Save/Quit and the title screen
were observed. An automatic marker helper still used an older suffix-rejecting
adapter, so the automatic HOLD remains a failure of that automation path. Manual
completion closed the known owned processes in 145.707 seconds, within its
180-second bound. Saved-state readback exited zero: the target was air, the other 59 compared
blocks were unchanged, and all four typed inventory views showed exactly one
additional ordinary oak plank. Independent retained-only decoding and final sealing confirmed those results,
with critical state conserved and monotonic live-to-saved gain. Final completion
seal SHA-256: `ddd8791941ec2ce4e9a46fb8669a6c2373d9260c0fdd23bd1e99c1c2ffa8f69b`.
The automatic HOLD remains. No causal drop attribution is claimed, and this ordinary mining pickup does not establish
collect_local acceptance. These results do not establish full automation acceptance.

## Collect: offline acceptance only

collect_local selects one explicit adjacent plain/default-component item from a
seven-type allowlist. It permits one cardinal movement under the established
ownership, entity and input fences, with strict resting-grounded target checks.
It does not chase, replan or replay. Stable typed inventory gain is required;
known native cancellation and UNKNOWN outcomes are preserved, and no causal
claim that a particular dropped item caused inventory gain is made.

The accepted candidate has genuine native compilation, 338 pure policy checks,
22 focused Python tests, 134 affected regressions and seven full owner-chain tests
with a synthetic native endpoint. These are prior candidate results. There is
no installed collector artifact, live pickup or real physics/cleanup acceptance.

## Combat: historical offline integration gate (before T21)

The engage route uses a separate scoped combat profile and exact owner binding.
Attack, shield and cancellation paths are guarded by the scoped callback/intent
contract. Cross-action reactions remain stop-only; automatic resume is not
supported. Native dispatch readiness and the corresponding mixin hooks remain
explicit prerequisites rather than assumptions made by Python orchestration.

The frozen candidate passed independent source review, final Java 21 compilation,
72 Python tests including six full owner-chain cases with a synthetic native
endpoint, 14 callback-fence assertions and 16 intent assertions. These results do
not establish transformed mixin application or real native attack/shield/cancel
behavior. Mixin application, native functional combat and live combat remain
NOT_RUN. This is not a game-ready combat release.

## T21: one bounded live combat microtrial

On 2026-10-14, source commit `eab30261271d5577cdfc4cd4d3a1a0f5fd471393`
and the separately verified native artifact
`8048dde926387954edd47028703da0c2b3c8b97a1b441f85de77d670e741b3e7`
were used for one explicit single-target engage under request_only policy.
Exactly one attack dispatch was observed, with the zombie's health changing from
20 to 16.06399917602539. One exact public cancellation reached the original native
action; input release and public cleanup were confirmed. Sampled player health
remained 20 and sampled pose was unchanged. This establishes this bounded
attack/cancel path, not general combat readiness.

Independent saved-state readback found the same target alive at the final health,
player health/position preserved, wooden sword wear increased by one, shield and
armor wear unchanged, and all 90 compared enclosure cells unchanged. Automated
ordinary closure completed in 69.698 seconds. Shield use (20 ticks) and observed
blocking stance (16 ticks) do not prove any damage was blocked. No chase,
multi-target combat, kill, loot, causal damage attribution, continuous absence of
motion, or server-confirmation claim is made.

The original harness report remains failed at `same_exact_terminal_action`.
Separate read-only verification of the original evidence passed after exactly
two source-backed encoding reconciliations:

- The optional `result.combat.threat_gate.health_diagnostics.latch_trigger` may
  be absent or null only when both `latched` and `latch_triggered_now` are exactly
  false. Every other terminal field and type remains exact.
- The same target's nearby health is serialized as Float (`16.064`), while the
  combat evidence widens that float to Double (`16.06399917602539`). Both encode
  binary32 bits `41808312`. This is exact float32 equivalence, not an epsilon
  allowance; target identity and all other state predicates remain required.

The original failed report was not overwritten and no action was replayed.
The independent verifier checked 183 frozen evidence pins and seven focused
cases. Final combined handoff SHA-256:
`239c3cc5588930557060a5ec301c9e456422db50ba03a790c986597b77f5c244`.
Only this bounded summary is public; original receipts, identities and saves are
excluded. Portable synthetic encoding regressions and source provenance are in
`client-mod/validation/combat-t21/`; these are offline tests, not a replacement
for the complete original-evidence verifier or production admission rules.

## Historical combined verification and publication boundary

Both source-owner reviews approved the actual combined tree and additive shared
merges. All combined checks below completed successfully. Fresh combined checks:

- All 128 production Java sources compiled against pinned external libraries;
  all 321 emitted class origins resolved from fresh output, with no prior mod JAR
- Existing T13 actual policy: 15 scenarios / 168 assertions
- Mining policy/codec: 10; collect policy: 338; combat callback fence: 14;
  combat intent: 16; combined codec: 15 checks
- Mining Python: 32; collect Python: 22; synthetic-native collect owner chain: 7
- Actual Java-emitted collect/combat standalone and coherent bytes passed eight
  real Python consumer tests, including provenance, nulls and profile isolation
- Broad suites: Resident 419, cursor 83, gameplay 64, toolbox 57 passed;
  capability reported 718 tests in 260.669 seconds with one fixture-dependent
  class skipped by ordinary discovery. That class's eight native-wire cases
  passed separately against actual Java-emitted bytes
- Existing Node: 122 portable and nine framing tests passed; synthetic platform
  gate passed. Windows/PowerShell remains unvalidated
- Existing T13 full reply chain on the combined source: eight codec tests,
  six Python full-reply tests / 22 cases, and 38 Node boundary cases passed

A real standalone collect serialization omission was found during integration:
its required nullable entity flag was dropped by the profile selector. The fix
adds collect only to the existing explicit-null witness selector. Frozen inputs
were preserved; response limits and legacy profile encoding were unchanged.
Fresh Java bytes, rather than hand-matched Python JSON, are the regression input.
Combat fixture imports were made repository-relative without changing facts or
assertions; the 32-case combat group passed again afterward. Combat witnesses have
no required nullable fields, and actual standalone/coherent witnesses agree, so
no combat expansion of the null-preserving selector was necessary. Candidate counts above remain separately identified historical evidence.
Current full Gradle/NeoForge build and Windows/PowerShell validation are not
claimed. The existing T13 movement live/saved acceptance remains limited to its
one cardinal flat-block case, not generalized to these added capabilities.

Only reviewed source, portable synthetic tests and bounded verification summaries
belong in this repository. Account/credential/profile data, raw live receipts,
world saves, screenshots, compiled artifacts, dependencies and operator packets
are excluded. The original world and paused tasks remain unchanged.

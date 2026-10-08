# MDC isolated source handoff

The current prepared increment is the v18 source candidate described in
[publication-v18-20261008.md](publication-v18-20261008.md). It extends the isolated
handoff at `68dd012841aa84a5d4caf1115aba1623093239cd`; it does not replace root/main.
All 234 existing main-line blobs and modes are preserved.

- `candidates/encounter-stage1.1/`: separately versioned mod/controller source,
  synthetic tests, engineering documentation and component license notices.
- `test-tools/encounter-stage1.1-safety-v2/`: public offline modules and synthetic
  tests only. No configured live Operator or environment-specific closeout guide.
- `run_offline_checks.py`: candidate Python, Node, terrain audit and public
  harness checks; no game launch or network transport.
- `test_native_wire_contract.py`: separate synthetic Java codec/resident/harness
  contract checks using an already available Java 21 JDK and compiled classpath.
- `main-v18-differences.json`: actual source path comparison to the queried main.

From repository root:

```
(cd candidates/encounter-stage1.1 && sha256sum -c PUBLISHED_SOURCE_SHA256SUMS.txt)
(cd test-tools/encounter-stage1.1-safety-v2 && sha256sum -c SOURCE_SHA256SUMS.txt)
python3 handoff/run_offline_checks.py
```

The frozen original `SOURCE_SHA256SUMS.txt` in the candidate remains historical
provenance; `PUBLISHED_SOURCE_SHA256SUMS.txt` checks the selected current payloads.
The candidate wrapper JAR remains omitted. Use installed Gradle 8.14.3 or the
existing repository-root wrapper with an explicit candidate project directory.
Java build instructions and newly repeated results are in the v18 publication
note. `verification-20261008.json` records the earlier handoff checks only.

The candidate and main have important divergent features. Do not overwrite main
or infer a successful integration from candidate tests. The publication note
explains environment recovery, stable-result, navigation and crafting conflicts.
Historical documents retain their original time scope. Source publication does
not install software, restore worlds, authorize gameplay or establish live
acceptance. Existing safety gates and licenses/notices are unchanged.

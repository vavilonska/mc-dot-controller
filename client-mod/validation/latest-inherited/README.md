# Inherited native regression checks against the current merged classes

First run `../current-native/verify.py` with Java 21 and the external pinned dependency packages. Then run:

```sh
python3 client-mod/validation/latest-inherited/run.py \
  --dependency-root /path/to/external-pinned-packages \
  --compiled-output /path/to/completed-native-verification \
  --output /path/to/new-test-output
```

This verifies the compiled manifest, class/source hashes and dependency pins before testing the ordinary monotonic boundary, admission, Blaze/Husk policies, portal/landing handoff, sheltered Enderman policy, backup compatibility/save diagnostics/threat gates and five scheduler intervals. Every test uses fake identities/data, actual policy/registry code or source hooks, not a game session.

The Blaze test is the newest Husk-aware version, rather than the older version that rejected the subsequently supported Husk type. The Enderman source-hook check ignores whitespace only; its original compacted-source mismatch and correction are recorded in publication validation. Deliberately induced backup save failures log warning/error messages as part of negative checks; a process exit of zero and corresponding check count are the result, not the absence of stderr text.

# Native-produced raw wire fixtures

Copied byte-for-byte from `results/native/wire-fixtures/` for self-contained offline regression tests. Native author generated them through production `NativeRecoveryShortInput.parseStart`, `RecoveryShortInputLedger`, `NativeRecoveryShortInput.describe` / actual no-world observation branch and `RecoveryShortInputCodec.encode`. They are **not** live-world evidence or hand-written JSON schemas. The fixture session/owner/action UUIDs are offline non-secret identities, not live credentials.

The terminal fixture has only 1 of 2 requested samples and reason `explicit_stop`: protocol terminal / input release are known; physical settlement is `not_observed`, gameplay outcome `not_assessed`. Public policy deliberately does not authorize the fixture's jump request; the wire/parser test tests interoperability, not a gameplay admission bypass.

# Production native wire fixtures

Copied byte-for-byte from `results/native/r2/wire-fixtures/`. Native harness uses actual `NativeRecoveryShortInput.parseInteractionStart` → native ledger → production `describe` / no-world observation branch → `RecoveryShortInputCodec.encode`. These are production-serializer offline fixtures, not hand-written status schemas and not live-world evidence. All UUIDs and stack fingerprints here are offline test data, not authentication credentials.

Four kinds retain independent kind-bound request digests. The break terminal intentionally reports `target_unchanged`; this is known incomplete gameplay, not UNKNOWN. The entered-call stop remains STOPPING until release; a subsequent UNKNOWN-with-release remains UNKNOWN. Zero-call terminal does not imply successful gameplay. Look -180 is accepted while +180 is rejected before public dispatch, matching the native boundary.

# Encounter safety-v2: public offline subset

This subset contains pure ledger/receipt/health modules, generic registered-case
entrypoints, synthetic observations and temporary-queue tests. It has no live
Operator, credential configuration, real-world evidence or runnable game setup.

The v18 source snapshot adds terminal-sample consistency, explicit active-case
pause-first contracts, unknown-effect no-retry handling and append-only operator
closeout reconciliation. Single-case and active-case entrypoints are dependency
injected: importing them does not start a game, connect to a server or submit a
request. Any real action still requires separately approved bindings and scope.

SOURCE_SHA256SUMS.txt checks 23 selected payloads. The private environment's
Operator closeout how-to is deliberately excluded; no private case paths or
evidence are reconstructed from these tests. Existing historical PLAN.md and
STATE-MACHINE.md refer to the fuller harness and are not permission to run it.

From repository root, run python3 handoff/run_offline_checks.py. It sets local
import paths and runs synthetic tests only. All mailbox/ledger writes in those
tests go to temporary directories. POSIX fcntl is required. The separate
handoff/test_native_wire_contract.py needs a locally compiled candidate classpath
and Gson, as documented in that file, but does not open an HTTP connection.

These sources are an isolated candidate, not a main-line integration or live
acceptance result. See ../../handoff/publication-v18-20261008.md for scope, checks
and the unresolved differences against main. Existing licenses/notices remain.

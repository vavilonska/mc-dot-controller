# Encounter safety-v2: public offline subset

## Mainline integration scope (2026-10-09)

This mainline tree carries the fixed 37-file offline harness dependency package
from the reviewed grass719 source, including its session-rollover and boat-entry
checks, plus a pure gate-claim contract and its synthetic fixture extracted from
the same reviewed source. The extraction retains the original function and
fixture-constructor ASTs and omits all probe observation/dispatch methods. The
historical publication notes below describe earlier selections and
are retained as provenance, not current file or test counts. `SOURCE_SHA256SUMS.txt` is refreshed for this adapted package; the original
source identities and actual test results are retained in the integration report.

The active runner has no live operator, CLI, transport startup, feature-gate
setting or automatic next-case entry here. Tests use synthetic observations,
in-memory clients and temporary filesystem ledgers only. Importing these modules
does not create a live queue, ledger, registration or dispatch claim. The retained
gate_off_case reference is not an enabled root Resident operation; no probe
observation or dispatch route was migrated.

The mainline resident modules are the only resident source used by the adapted
tests. This package does not fall back to a candidate tree in another checkout.
Run from this directory with `PYTHONDONTWRITEBYTECODE=1` and `PYTHONPATH` containing
this directory, its `adaptation_tests`, and `../../resident-controller`, then run
the three unittest discovery commands below. The native wire handoff test defaults
to the labelled frozen synthetic fixture unless a freshly generated mainline
fixture exists. Passing frozen wire tests does not establish a new JVM run or
any live acceptance.

This directory was published with 16 unchanged files selected from the private safety-v2
harness: five pure/core Python modules, synthetic/native-offline fixtures and
support, five test files, and two historical plan/state-machine documents.
It does not contain the live Operator or a complete runnable v2 game harness.
No runtime guard was weakened or rewritten for publication. Subsequent local
hardening now checks intermediate terminal samples during closeout; see below.

The original selection passed 287 offline tests on 2026-10-08. All clients used in these
tests are in-memory fakes; ledger writes use temporary directories. The emitted
native fixture explicitly describes synthetic offline observations and its
world/player identities are synthetic. Never use fixture IDs for live requests.

From this directory on Linux/macOS, with Python 3:

```sh
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$PWD"
python3 -m unittest discover -s tests -p test_receipt_binding.py -v
python3 -m unittest discover -s safety_tests -p 'test_*.py' -v
python3 -m unittest discover -s independent-review -p 'test_*.py' -v
```

The core ledger uses POSIX `fcntl`; Windows is not supported by these commands.
See `../../handoff/README.md` for omissions and owner-controlled access to the
full private archive. Source hashes here cover 19 current source/test/plan files;
the original hashes remain in Git at `68dd012841aa84a5d4caf1115aba1623093239cd`.
The two preserved plan documents refer to the full harness and prior context;
they do not claim that omitted APIs are available here, authorize future actions,
or establish active-AI readiness or actual input release.

## Closeout terminal evidence hardening

The ledger now retains terminal samples when deciding whether closeout is
eligible. A bound terminal sample contradicts an explicit null admission
rejection, and every bound terminal sample must match the final terminal receipt.
Both first-time recording and reopening a ledger apply the same validation.
Conflicts block cleanup and pause; unknown responses remain unknown even when a
terminal sample exists. Matching samples and unrelated retained old terminals
keep their previous meaning. Seven additional synthetic regressions cover these
paths. This patch does not update the omitted private live Operator harness;
that integration must be reviewed before a real trial.

Four additional `test_public_queue_integration.py` regressions now compose the
actual candidate file-mailbox client and this ledger, using a synchronous fake
resident and temporary directories only. They cover terminal closeout ordering,
explicit null rejection, unknown/reopened-ledger refusal, and mailbox retention
versus persistent case claims. They need the repository's candidate source tree.
No live Operator or controller is created by those tests. See
`../../handoff/public-single-case-readiness-20261008.md` for the remaining gaps.

## Minimal registered-case entry

`single_case.run_registered_case(safety, binding, trial_name,
closeout_authorization=None, clock=time.monotonic)` connects the existing ledger,
queue and health guard. It requires an already registered, separately approved
local NoAI case. It has no CLI or transport/game startup on import. It preserves
the binding's exact command and one claimed submission, captures every
before/during/after sample and receipt, and writes exclusive original and closeout
reports to the operator output directory. Default closeout is off. An explicit
authorization reference enables two exact UUID cleanups followed by pause only
after a known released outcome and an unstopped health window. No automatic
cancel, retry, unpause or next case is provided. Twelve focused tests cover this
entry using the synthetic resident and actual temporary file mailbox. Passing
them is not live acceptance.

## Explicit active case, pause first

`PostTrialSafety.register_active_case` is a separate opt-in for exactly two adult
enabled-AI zombies, registered in native paused state with exact evidence and a
separate pause authorization. `active_case.run_registered_active_case` uses the
same immutable encounter binding, health guard and consumed dispatch claim. It
requires `encounter_pause_on_terminal:true` and explicit `resume_authorization_ref`.
Baseline and claims finish while paused; one known resume dispatch goes directly
to the original submit, without another large observation. Native termination
attempts pause in the same callback after cleanup and terminal recording. An
already attempted hook, even unknown, makes the outer entry read-only; it never
repeats that pause. Only paths without a hook use the one reserved fallback.
It verifies actual
paused state and release separately. NoAI registration and closeout remain intact;
active cases cannot use that cleanup sequence. No setup, post-terminal unpause,
cleanup or next case is automatic. See `../../handoff/active-pursuit-readiness-20261008.md` for the
offline-only contract and remaining real-case prerequisites.

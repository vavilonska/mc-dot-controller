# Encounter safety-v2: public offline subset

This directory contains 16 unchanged files selected from the private safety-v2
harness: five pure/core Python modules, synthetic/native-offline fixtures and
support, five test files, and two historical plan/state-machine documents.
It does not contain the live Operator or a complete runnable v2 game harness.
No runtime guard has been weakened or rewritten for publication.

The selection passed 287 offline tests on 2026-10-08. All clients used in these
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
full private archive. Source hashes here cover the 16 unchanged selected files.
The two preserved plan documents refer to the full harness and prior context;
they do not claim that omitted APIs are available here, authorize future actions,
or establish active-AI readiness or actual input release.

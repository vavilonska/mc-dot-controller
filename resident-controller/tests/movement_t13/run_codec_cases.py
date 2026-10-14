"""Focused codec contracts plus the retained read-only navigation invariant."""
import json
import os
from pathlib import Path
import sys
import unittest
from offline_guards import offline_python


def main():
    with offline_python():
        suite = unittest.defaultTestLoader.loadTestsFromNames([
            'test_movement_wire_contract',
            'test_navigation_binding_contract.BindingContractTests.test_all_adapters_reject_read_only_observation_clock',
        ])
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = {'schema': 'mdc.movement-wire-codec-report/1',
              'scope': 'synthetic native facts; actual production Python consumers',
              'tests_run': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
              'success': result.wasSuccessful(), 'game_or_service_started': False}
    output = Path(os.environ['MDC_MOVEMENT_WIRE_E2E_OUTPUT']) / 'codec-report.json'
    with output.open('x') as stream:
        json.dump(report, stream, sort_keys=True, separators=(',', ':'))
    print(json.dumps(report, sort_keys=True))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main())

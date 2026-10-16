"""File-only shape checks for documentation examples; never binds a runtime."""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
# These imports define contracts and source bindings only, not Runtime instances.
for name in ('capability-runtime', 'resident-controller', 'navigation-controller',
             'navigation-cursor', 'defense-watchdog', 'gameplay-helpers',
             'building-controller', 'external-controller', 'multiagent-coordination'):
    sys.path.insert(0, str(ROOT / name))
from mdc_toolbox.contracts import validate_call
from mdc_toolbox.catalog import CapabilityCatalog


def main():
    calls = json.loads((ROOT / 'docs/toolbox-call-examples.json').read_text())
    catalog = CapabilityCatalog()
    assert not catalog.load_errors, catalog.load_errors
    expected = [('mdc_catalog', None), ('mdc_observe', None), ('mdc_plan', None),
                ('mdc_job', 'submit'), ('mdc_job', 'status'), ('mdc_job', 'cancel'),
                ('mdc_job', 'reconcile'), ('mdc_job', 'submit'), ('mdc_job', 'submit')]
    assert [(call['tool'], call['arguments'].get('operation')) for call in calls] == expected
    for call in calls:
        assert set(call) == {'tool', 'arguments'}
        args = validate_call(call['tool'], call['arguments'])
        if 'capability' in args:
            catalog.validate(args['capability'], args['capability_version'], args['arguments'])
    print(f'PASS: {len(calls)} documentation call shapes and domain arguments; no runtime or gameplay.')


if __name__ == '__main__':
    main()

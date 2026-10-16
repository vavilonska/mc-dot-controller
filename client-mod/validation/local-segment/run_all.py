"""Portable source-only local segment suite: fresh controllers, serializers and frontdoor consumers."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
from runner_common import new_output, run, sha256

here = Path(__file__).resolve().parent
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--repo', type=Path, default=here.parents[2])
p.add_argument('--output', type=Path, required=True)
p.add_argument('--java', required=True)
p.add_argument('--javac', required=True)
p.add_argument('--gson', type=Path, required=True)
p.add_argument('--classpath-file', type=Path, required=True)
a = p.parse_args()
repo = a.repo.resolve()
if not shutil.which('node'):
    p.error('Node.js must be available on PATH for the production MCP stdio tests')
out = new_output(a.output, repo)
common = ['--repo', str(repo), '--java', a.java, '--javac', a.javac]
run(out, 'controller', [sys.executable, '-B', str(here / 'run_engine.py'), *common,
                        '--gson', str(a.gson.resolve()), '--output', str(out / 'engine')])
run(out, 'native', [sys.executable, '-B', str(here / 'run_native.py'), *common,
                    '--classpath-file', str(a.classpath_file.resolve()), '--engine-output', str(out / 'engine'),
                    '--output', str(out / 'native')])
run(out, 'source-relation', [sys.executable, '-B', str(here / 'check_source_relation.py'), '--repo', str(repo)])
parts = ['capability-runtime/tests', 'capability-runtime', 'resident-controller', 'navigation-controller',
         'navigation-cursor', 'defense-watchdog', 'gameplay-helpers', 'building-controller',
         'external-controller', 'multiagent-coordination']
env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', WATCHDOG_CANDIDATE=str(repo / 'defense-watchdog'),
           PYTHONPATH=os.pathsep.join(str(repo / part) for part in parts),
           MDC_LOCAL_SEGMENT_NATIVE_WIRE=str(out / 'native/wire'), MDC_ROUTE_LOCAL_TEST_RESULTS=str(out / 'frontdoor'))
# Only fake Bridge readers are used. Actual Node/Python entry points communicate
# over stdio and isolated temporary filesystem queues, never a game endpoint.
run(out, 'python-frontdoor-wire', [sys.executable, '-B', '-m', 'unittest', '-v',
                                  'test_route_local_contract', 'test_route_local_planner', 'test_route_local_frontdoor',
                                  'test_local_segment_native_wire'], env=env, cwd=repo / 'capability-runtime')
result = {'status': 'passed', 'scope': 'Source-only, synthetic readers and isolated production entry chain',
          'production_compile': json.loads((out / 'native/result.json').read_text()),
          'controller': json.loads((out / 'engine/engine-result.json').read_text()),
          'harness_sha256': {path.name: sha256(path) for path in sorted(here.iterdir()) if path.is_file()},
          'python_test_sha256': {path.name: sha256(path) for path in sorted((repo / 'capability-runtime/tests').glob('*route_local*')) if path.is_file()},
          'not_run': ['game startup', 'external network', 'FML/Mixin bootstrap', 'ordinary-world acceptance', 'deployment']}
(out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
print('PASS portable local segment controller, source relation and native/frontdoor consumer gates', flush=True)

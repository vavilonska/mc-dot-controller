#!/usr/bin/env python3
"""Offline inherited native policy checks; no game, network or packaging."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess

p = argparse.ArgumentParser()
p.add_argument('--dependency-root', required=True)
p.add_argument('--compiled-output', required=True, help='Output from current-native/verify.py')
p.add_argument('--output', required=True, help='New test output directory')
p.add_argument('--java', default=os.environ.get('JAVA', 'java'))
a = p.parse_args()
here = Path(__file__).resolve().parent
repo = here.parents[2]
compiled = Path(a.compiled_output).resolve()
output = Path(a.output).resolve()
meta = here.parent / 'reactive-r1_4'
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
receipt = json.loads((compiled / 'COMPILE-RECEIPT.json').read_text())
assert receipt['compile_exit_code'] == 0
manifest_path = compiled / 'SOURCE-AND-CLASS-MANIFEST.json'
assert sha(manifest_path) == receipt['source_and_class_manifest_sha256']
manifest = json.loads(manifest_path.read_text())
# Class bytes and dependency pins must still match the completed compile.
for name, value in manifest['classes'].items():
    assert sha(compiled / 'classes' / name) == value
config = json.loads((meta / 'BUILD-CONFIG.json').read_text())
roots = {key: Path(a.dependency_root).resolve() / name for key, name in config['roots'].items()}
for row in json.loads((meta / 'CLASSPATH-PINS.json').read_text()):
    assert sha(roots[row['root']] / row['path']) == row['sha256']
cp = os.pathsep.join([str(compiled / 'classes')] +
                    [str(roots[x['root']] / x['path']) for x in config['runtime_classpath']])
output.mkdir(exist_ok=False)
source_root = repo / 'client-mod/src/main/java'
for name, value in manifest['sources'].items():
    assert sha(source_root / name) == value
source = source_root / 'io/github/campione01/mineclientbridge'
results = []
for group in sorted(x for x in here.iterdir() if x.is_dir()):
    sources = sorted(group.glob('*.java'))
    if not sources:
        continue
    target = output / group.name
    target.mkdir()
    rows = []
    with (target / 'tests.log').open('w') as log:
        command = [a.java, '-m', 'jdk.compiler/com.sun.tools.javac.Main', '-source', '21', '-target', '21',
                   '-proc:none', '-cp', cp, '-d', str(target)] + list(map(str, sources))
        build = subprocess.run(command, cwd=target, stdout=log, stderr=subprocess.STDOUT)
        rows.append({'compile_exit_code': build.returncode})
        if build.returncode == 0:
            for test in sources:
                if test.stem == 'BackupSchedulerChecks':
                    calls = [(['-Dmineclient.backup.intervalSeconds=' + str(n)], [str(n)])
                             for n in (0, 60, 1800, 59, 86401)]
                elif test.stem == 'BackupCompatibilityChecks':
                    calls = [([], [str(source / name) for name in ('ClientActions.java', 'NativeWorldBackup.java')])]
                elif test.stem == 'EndermanShelterChecks':
                    calls = [([], [str(source / 'ClientActions.java')])]
                else:
                    calls = [([], [])]
                for options, args in calls:
                    check = subprocess.run([a.java] + options + ['-cp', str(target) + os.pathsep + cp,
                        'io.github.campione01.mineclientbridge.' + test.stem] + args,
                        cwd=target, stdout=log, stderr=subprocess.STDOUT)
                    rows.append({'test': test.stem, 'jvm_options': options, 'exit_code': check.returncode})
    results.append({'group': group.name, 'results': rows})
    print(group.name, rows, flush=True)
(output / 'RESULTS.json').write_text(json.dumps(results, indent=2) + '\n')
raise SystemExit(any(row.get('compile_exit_code', row.get('exit_code', 0))
                     for group in results for row in group['results']))

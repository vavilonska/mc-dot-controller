#!/usr/bin/env python3
"""Offline mapped Java21 build; no game, network, token or original-world operations."""
from pathlib import Path
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED
import argparse
import hashlib
import json
import os
import subprocess

p = argparse.ArgumentParser()
p.add_argument('--root', required=True, help='Directory containing the three exact pinned package directories')
p.add_argument('--output', required=True, help='New nonexistent build output directory')
p.add_argument('--expected-jar-sha256', help='Optional exact final hash; final BUILD-RECEIPT is checked automatically when present')
a = p.parse_args()
W = Path(__file__).resolve().parent
R = Path(a.root).resolve()
D = Path(a.output).resolve()
D.mkdir(exist_ok=False)
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
m = json.loads((W / 'BUILD-CONFIG.json').read_text())
roots = {key: R / name for key, name in m['roots'].items()}
base = roots[m['base_jar']['root']] / m['base_jar']['path']
assert sha(base) == m['base_jar']['sha256'], 'base JAR hash mismatch'
for row in json.loads((W / 'CLASSPATH-PINS.json').read_text()):
    assert sha(roots[row['root']] / row['path']) == row['sha256'], row['path']
sources = json.loads((W / 'SOURCE-PINS.json').read_text())
allowed = set(m['allowed_families'])
assert len(sources) == len(allowed) == 4
assert {Path(row['path']).stem for row in sources} == allowed
for row in sources:
    assert sha(W / row['path']) == row['sha256'], row['path']
for row in json.loads((W / 'SOURCE-EVIDENCE-PINS.json').read_text()):
    assert sha(W / row['path']) == row['sha256'], 'unchanged evidence source: ' + row['path']
expected = a.expected_jar_sha256
if (W / 'BUILD-RECEIPT.json').exists():
    final = json.loads((W / 'BUILD-RECEIPT.json').read_text())['jar_sha256']
    assert expected is None or expected == final, 'explicit expected hash contradicts frozen receipt'
    expected = final
C, T, E = D / 'classes', D / 'test-classes', D / 'empty-sourcepath'
for directory in (C, T, E):
    directory.mkdir()
java = os.environ.get('JAVA', '/usr/lib/jvm/java-21-openjdk-amd64/bin/java')
cp = os.pathsep.join(str(roots[x['root']] / x['path']) for x in m['compile_classpath'])
rcp = os.pathsep.join([str(C)] + [str(roots[x['root']] / x['path']) for x in m['runtime_classpath']])
with (D / 'FOCUSED-TESTS.txt').open('w') as log:
    def run(command):
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                cwd=D, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        log.write(result.stdout)
        log.flush()
        print(result.stdout, end='', flush=True)
        result.check_returncode()
    run([java, '-m', 'jdk.compiler/com.sun.tools.javac.Main', '-source', '21', '-target', '21',
         '-encoding', 'UTF-8', '-proc:none', '-implicit:none', '-sourcepath', str(E), '-cp', cp,
         '-d', str(C)] + [str(W / row['path']) for row in sources])
    run([java, '-m', 'jdk.compiler/com.sun.tools.javac.Main', '-source', '21', '-target', '21',
         '-proc:none', '-cp', rcp, '-d', str(T)] + [str(W / (t['class'] + '.java')) for t in m['java_tests']])
    for test in m['java_tests']:
        run([java, '-cp', str(T) + os.pathsep + rcp,
             'io.github.campione01.mineclientbridge.' + test['class']]
            + [str(W / path) for path in test.get('source_args', [])])
    for script in m['python_tests']:
        run([os.environ.get('PYTHON', 'python3'), str(W / script)])
classes = {p.relative_to(C).as_posix(): p.read_bytes() for p in C.rglob('*.class')}
def allowed_entry(name):
    return name.startswith('io/github/campione01/mineclientbridge/') and name.rsplit('/', 1)[-1].split('$')[0].split('.')[0] in allowed
assert classes and all(allowed_entry(name) for name in classes)
out = D / m['jar']
with ZipFile(base) as old, ZipFile(out, 'w', ZIP_DEFLATED, compresslevel=9) as archive:
    names = set(old.namelist())
    for name in sorted({name for name in names if not allowed_entry(name)} | set(classes)):
        info = ZipInfo(name, (2026, 10, 23, 0, 0, 0))
        info.compress_type = ZIP_DEFLATED
        info.external_attr = old.getinfo(name).external_attr if name in names else 0o644 << 16
        archive.writestr(info, classes[name] if name in classes else old.read(name))
with ZipFile(base) as old, ZipFile(out) as new:
    previous, current = set(old.namelist()), set(new.namelist())
    removed = sorted(previous - current)
    assert all(allowed_entry(name) for name in removed), 'unexpected removed JAR entry'
    added = sorted(current - previous)
    changed = sorted(name for name in previous & current if old.read(name) != new.read(name))
    assert all(name in classes and allowed_entry(name) for name in changed + added)
    unchanged = sorted(previous & current - set(changed))
    protected = [name for name in previous if name.rsplit('/', 1)[-1].split('$')[0].split('.')[0]
                 in {'NativeWorldBackup', 'BackupStageFiles', 'BackupSaveValidation', 'ActionRegistry',
                     'NativeShelteredEnderman', 'EndermanShelterPolicy', 'NativeBlazeEscort', 'BlazeEscortPolicy'}]
    assert all(old.read(name) == new.read(name) for name in protected)
if expected:
    assert sha(out) == expected, 'Exact final JAR mismatch: ' + sha(out)
for row in sources:
    assert sha(W / row['path']) == row['sha256'], 'source changed during build: ' + row['path']
receipt = {'base_sha256': sha(base), 'jar': out.name, 'jar_sha256': sha(out), 'jar_bytes': out.stat().st_size,
           'changed_entries': changed, 'new_entries': added, 'removed_entries': removed, 'unchanged_entries': len(unchanged),
           'allowed_families': sorted(allowed), 'protected_entries_byte_exact': len(protected),
           'exact_expected_jar_verification': 'PASS' if expected else 'NO_FINAL_EXPECTED_HASH_SUPPLIED',
           'live': 'NOT_RUN', 'world_token_game_touched': False}
(D / 'BUILD-RECEIPT.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt))

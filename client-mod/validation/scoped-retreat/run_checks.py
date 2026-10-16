"""Offline fresh production compile, pure checks, and compiled-method controller replay."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[3])
p.add_argument('--output', type=Path, required=True)
p.add_argument('--java', type=Path, required=True)
p.add_argument('--javac', type=Path, required=True)
p.add_argument('--classpath-file', type=Path, required=True)
a = p.parse_args()
repo, out = a.repo.resolve(), a.output.resolve()
if out == repo or repo in out.parents:
    raise ValueError('Output must be outside source; use a fresh retreat-* result directory')
out.mkdir(parents=True, exist_ok=False)
classes = out / 'classes'
classes.mkdir()
source_root = repo / 'client-mod/src/main/java'
here = repo / 'client-mod/validation/scoped-retreat'
production = sorted(source_root.rglob('*.java'))
tests = [here / name for name in ('ScopedRetreatPlanningChecks.java', 'ScopedRetreatControllerChecks.java')]
inputs = production + tests + [here / 'run_checks.py']
before = {str(path.relative_to(repo)): digest(path) for path in inputs}
(out / 'source-before.json').write_text(json.dumps(before, indent=2) + '\n')
entries = [Path(value).resolve() for value in a.classpath_file.read_text().strip().split(os.pathsep) if value]
if not entries or not all(path.is_file() for path in entries):
    raise ValueError('Only existing local dependency JARs are accepted')
cp = os.pathsep.join(map(str, entries))
(out / 'dependencies.json').write_text(json.dumps([{'path': str(path), 'sha256': digest(path)} for path in entries], indent=2) + '\n')


def run(label, argv):
    result = subprocess.run(list(map(str, argv)), cwd=repo, capture_output=True, text=True)
    (out / (label + '.stdout')).write_text(result.stdout)
    (out / (label + '.stderr')).write_text(result.stderr)
    (out / (label + '.json')).write_text(json.dumps({'argv': list(map(str, argv)), 'exit_code': result.returncode}, indent=2) + '\n')
    if result.returncode:
        raise SystemExit(label + ' failed; original output retained')
    return result.stdout


compiler = [a.javac, '-J-Xmx384m', '-J-XX:ActiveProcessorCount=1', '-proc:none', '--release', '21']
run('compile-production', [*compiler, '-cp', cp, '-d', classes, *production])
run('compile-checks', [*compiler, '-cp', str(classes) + os.pathsep + cp, '-d', classes, *tests])
java = [a.java, '-Xmx256m', '-XX:ActiveProcessorCount=1', '-Djava.awt.headless=true', '-cp', str(classes) + os.pathsep + cp]
pure = json.loads(run('pure', [*java, 'io.github.campione01.mineclientbridge.ScopedRetreatPlanningChecks']))
controller = json.loads(run('controller', [*java, 'io.github.campione01.mineclientbridge.ScopedRetreatControllerChecks', classes, out / 'controller-result.json']))
after = {str(path.relative_to(repo)): digest(path) for path in inputs}
(out / 'source-after.json').write_text(json.dumps(after, indent=2) + '\n')
unchanged = before == after
summary = {'status': 'passed' if unchanged else 'source_changed_during_checks', 'production_sources': len(production),
           'source_unchanged': unchanged, 'pure': pure, 'controller': controller,
           'game_loader_world_network': 'NOT_RUN'}
(out / 'result.json').write_text(json.dumps(summary, indent=2) + '\n')
if not unchanged:
    raise SystemExit('Source changed during checks; evidence is not a frozen binding')
print(json.dumps(summary))

#!/usr/bin/env python3
"""Source-only, offline ray/consume regression. All generated files go to --output."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

HERE = Path(__file__).resolve().parent
PACKAGE = 'io/github/campione01/mineclientbridge/'
PINNED_ENGINE_SHA256 = 'aff67d0c3bbd015ecd881bb37416b740ada2e1e854433501ec5bb9381dbdd1c2'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def classpath_file(path):
    # A native-platform classpath; no dependency lookup or network downloading.
    entries = [Path(s).expanduser().resolve() for s in path.read_text().strip().split(os.pathsep) if s]
    if not entries or not all(p.is_file() for p in entries):
        raise ValueError('Classpath must contain existing local dependency JARs only')
    return entries


def first_resource(entries, name):
    for entry in entries:
        with zipfile.ZipFile(entry) as jar:
            try:
                return jar.read(name)
            except KeyError:
                pass
    raise ValueError('Missing engine resource: ' + name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=HERE.parents[2])
    parser.add_argument('--output', type=Path, required=True, help='New directory outside the source checkout')
    parser.add_argument('--classpath-file', type=Path, required=True, help='Compile dependencies, including ASM/SLF4J/logging/Netty')
    parser.add_argument('--runtime-classpath-file', type=Path, help='Defaults to compile dependencies')
    parser.add_argument('--engine-jar', type=Path, required=True, help='Unmodified NeoForge 21.1.255 client JAR')
    parser.add_argument('--javac', default='javac')
    parser.add_argument('--java', default='java')
    args = parser.parse_args()
    repo, out, engine = args.repo.resolve(), args.output.resolve(), args.engine_jar.resolve()
    if out == repo or repo in out.parents:
        parser.error('--output must be outside --repo')
    if out.exists():
        parser.error('--output must be new; existing results are never overwritten or retried')
    compile_entries = classpath_file(args.classpath_file)
    runtime_entries = classpath_file(args.runtime_classpath_file or args.classpath_file)
    if digest(engine) != PINNED_ENGINE_SHA256:
        parser.error('Engine hash differs from the reviewed NeoForge 21.1.255 pin')
    java_sources = sorted((repo / 'client-mod/src/main/java').rglob('*.java'))
    if not java_sources or not (repo / 'resident-controller').is_dir():
        parser.error('--repo is not an MDC source checkout')
    # NeoForge's client artifact is an overlay. Lock geometry dependency classes
    # separately, while extracting Entity/Minecraft/ShieldItem from the original pin.
    resources = json.loads((HERE / 'fixtures/geometry_resource_sha256.json').read_text())
    for name, expected in resources.items():
        if hashlib.sha256(first_resource(runtime_entries, name)).hexdigest() != expected:
            parser.error('Runtime geometry resource differs from reviewed pin: ' + name)
    with zipfile.ZipFile(engine) as jar:
        engine_bytes = {name: jar.read(name) for name in
                        ['net/minecraft/client/Minecraft.class', 'net/minecraft/world/item/ShieldItem.class',
                         'net/minecraft/world/entity/Entity.class']}
    out.mkdir(parents=True)
    classes, baseline_classes = out / 'classes', out / 'baseline-classes'
    classes.mkdir(); baseline_classes.mkdir(); (out / 'wire').mkdir()
    compile_cp = os.pathsep.join(map(str, compile_entries))
    runtime_cp = os.pathsep.join([str(classes), *map(str, runtime_entries)])
    logs = []
    def run(label, argv):
        # This starts only the explicit compiler/test child, never a game launcher.
        with (out / (label + '.stdout')).open('x') as stdout, (out / (label + '.stderr')).open('x') as stderr:
            try:
                result = subprocess.run(argv, stdout=stdout, stderr=stderr, timeout=120,
                                        env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
            except OSError as error:
                (out / (label + '-terminal.json')).write_text(json.dumps({'state': 'not_started', 'error': str(error)}))
                raise
            except subprocess.TimeoutExpired:
                (out / (label + '-terminal.json')).write_text(json.dumps({'state': 'owned_test_child_timeout_killed_and_reaped'}))
                raise
        terminal = {'state': 'known_terminal', 'exit_code': result.returncode}
        (out / (label + '-terminal.json')).write_text(json.dumps(terminal))
        logs.append({'stage': label, **terminal})
        print(label, terminal, flush=True)
        if result.returncode:
            raise RuntimeError('Failed stage: ' + label + '; see local output logs')
    compiler = [args.javac, '-J-Xmx384m', '-J-XX:ActiveProcessorCount=1', '-proc:none', '--release', '21']
    run('compile-production', [*compiler, '-cp', compile_cp, '-d', str(classes), *map(str, java_sources)])
    run('compile-harness', [*compiler, '-cp', str(classes) + os.pathsep + compile_cp,
                            '-d', str(classes), *map(str, sorted((HERE / 'java').glob('*.java')))])
    # Reconstruct the historical pre-fix method bodies using exact, fail-closed source deltas.
    fixed = repo / ('client-mod/src/main/java/' + PACKAGE + 'ClientActions.java')
    baseline = fixed.read_text()
    replacements = json.loads((HERE / 'fixtures/consume_baseline_replacements.json').read_text())
    for replacement in replacements:
        fragment = replacement['fixed']
        if not fragment or baseline.count(fragment) != 1:
            raise ValueError('Consume source changed; review the baseline replacements before updating this test')
        baseline = baseline.replace(fragment, replacement['baseline'], 1)
    baseline_source = out / 'baseline-source/ClientActions.java'
    baseline_source.parent.mkdir(); baseline_source.write_text(baseline)
    run('compile-baseline', [*compiler, '-cp', str(classes) + os.pathsep + compile_cp,
                             '-d', str(baseline_classes), str(baseline_source)])
    engine_paths = {}
    for name, payload in engine_bytes.items():
        path = out / ('Pinned-' + name.rsplit('/', 1)[1])
        path.write_bytes(payload); engine_paths[name] = path
    jvm = [args.java, '-Xmx256m', '-XX:ActiveProcessorCount=1', '-Djava.awt.headless=true',
           '-Dconsolidation.entity.class=' + str(engine_paths['net/minecraft/world/entity/Entity.class']),
           '-cp', runtime_cp]
    run('geometry', [*jvm, PACKAGE.replace('/', '.') + 'QuantizedRayChecks', str(out / 'geometry-rows.json')])
    run('wire', [*jvm, PACKAGE.replace('/', '.') + 'FurnaceBlockMenuWire', str(out / 'wire')])
    run('block-menu-python', [sys.executable, '-B', str(HERE / 'check_block_menu.py'), '--repo', str(repo), '--output', str(out)])
    run('consume-ordering', [*jvm, PACKAGE.replace('/', '.') + 'ConsumeCompletionChecks',
                            str(baseline_classes / (PACKAGE + 'ClientActions.class')),
                            str(classes / (PACKAGE + 'ClientActions.class')),
                            str(engine_paths['net/minecraft/client/Minecraft.class']),
                            str(out / 'consume-result.json'),
                            str(engine_paths['net/minecraft/world/item/ShieldItem.class'])])
    result = {'status': 'passed', 'stages': logs, 'production_java_sources': len(java_sources),
              'engine_sha256': digest(engine),
              'source_sha256': {str(p.relative_to(repo)): digest(p) for p in java_sources},
              'python_validator_sha256': digest(repo / 'resident-controller/resident_controller/block_menu_snapshot.py'),
              'harness_sha256': {str(p.relative_to(HERE)): digest(p) for p in sorted(HERE.rglob('*')) if p.is_file()},
              'dependency_sha256': [{'name': p.name, 'sha256': digest(p)} for p in dict.fromkeys(compile_entries + runtime_entries)],
              'baseline': 'Exact reverse-source fixture compiled fresh; not a bundled historical binary',
              'scope': 'Headless source/bytecode/geometry/serialization only; no game/world/network/Mixin bootstrap'}
    (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print('PASS all portable consolidation checks', flush=True)


if __name__ == '__main__':
    main()

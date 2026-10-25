"""Prepare focused native-owner tests; --run-jvm requires a separately coordinated JVM slot.

Compiles production NativeManagedNavigation and its production lease, input policy,
responses, fence, and marker types directly from source. Minecraft, Baritone,
settings, and ManagedDryWorld/ManagedDryRoute are controlled doubles. This does
not exercise actual world readers, movement geometry, Mixins, or a running game.
The separate ManagedDryStepPolicyProbe covers geometry (140 checks in the parent
validation run); those checks are not rerun or claimed by this harness.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import sys

from owner_test_doubles import SOURCES
from input_provenance import capture, inventory, write


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--delta', type=Path, help='Exact frozen source delta; required with --run-jvm')
    parser.add_argument('--run-jvm', action='store_true', help='Use only after acquiring the serialized JVM slot')
    parser.add_argument('--java', type=Path)
    parser.add_argument('--javac', type=Path)
    parser.add_argument('--gson', type=Path, help='Existing installed official Gson JAR')
    args = parser.parse_args()
    repo, out = args.repo.resolve(), args.output.resolve()
    if out == repo or repo in out.parents:
        raise ValueError('Use a fresh result directory outside the source tree')
    here = repo / 'client-mod/validation/managed-water'
    source = repo / 'client-mod/src/main/java/io/github/campione01/mineclientbridge'
    names = ('NativeManagedNavigation', 'ManagedNavigationLease', 'ManagedNavigationInputPolicy',
             'ManagedNavigationResponses', 'ExternalNavigationLease', 'ExternalNavigationFence',
             'ManagedNavigationInputFence', 'ManagedDryInputFence', 'ManagedDryTravelFence',
             'ManagedDryAccelerationFence')
    production = [source / (name + '.java') for name in names]
    probe = here / 'ManagedWaterOwnerProbe.java'
    inputs = production + [probe, here / 'run_owner_checks.py', here / 'owner_test_doubles.py']
    before = {str(path.relative_to(repo)): digest(path) for path in inputs}
    out.mkdir(parents=True, exist_ok=False)
    stubs = out / 'doubles'
    generated = []
    for name, contents in sorted(SOURCES.items()):
        path = stubs / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding='utf-8')
        generated.append(path)
    (out / 'source-before.json').write_text(json.dumps(before, indent=2) + '\n')
    manifest = {'state': 'prepared_only', 'production_sources': list(before)[:len(production)],
                'doubles': {str(p.relative_to(out)): digest(p) for p in generated},
                'scope': 'actual production native owner control with controlled callbacks',
                'world_route_settings_geometry': 'DOUBLED; not an integration/world/geometry test',
                'private_data_construction': 'real Data constructor; no Unsafe',
                'game_gui_loader_network': 'NOT_RUN', 'java_tests': 'NOT_RUN'}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    if not args.run_jvm:
        print(json.dumps(manifest))
        return
    for value, label in ((args.java, 'java'), (args.javac, 'javac'), (args.gson, 'gson'), (args.delta, 'delta')):
        if value is None or not value.is_file():
            raise ValueError('--run-jvm requires existing explicit --' + label)
    all_before = capture(repo, args.delta, args.java, args.javac, [args.gson])
    write(out / 'INPUTS-BEFORE.json', all_before)
    doubles_before = inventory(stubs)
    classes = out / 'classes'
    classes.mkdir()
    empty = out / 'empty-sourcepath'
    empty.mkdir()
    (out / 'dependency.json').write_text(json.dumps({'gson': str(args.gson.resolve()), 'sha256': digest(args.gson)}, indent=2) + '\n')

    def run(label, argv):
        write(out / (label + '-command.json'), {'argv': list(map(str, argv)), 'cwd': str(repo), 'timeout_seconds': 40, 'environment_overrides': {'PYTHONDONTWRITEBYTECODE': '1'}})
        result = subprocess.run(list(map(str, argv)), cwd=repo, capture_output=True, text=True, timeout=40, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        (out / (label + '.stdout')).write_text(result.stdout)
        (out / (label + '.stderr')).write_text(result.stderr)
        (out / (label + '.json')).write_text(json.dumps({'argv': list(map(str, argv)), 'exit_code': result.returncode}, indent=2) + '\n')
        if result.returncode:
            raise SystemExit(label + ' failed; output retained')
        return result.stdout

    try:
        run('compile', [args.javac.resolve(), '-J-Xmx256m', '-J-XX:ActiveProcessorCount=1', '-proc:none',
                        '--release', '21', '-implicit:none', '-cp', args.gson.resolve(), '-sourcepath', empty,
                        '-d', classes, *production, *generated, probe])
        stdout = run('owner-probe', [args.java.resolve(), '-Xmx128m', '-XX:ActiveProcessorCount=1',
                     '-Djava.awt.headless=true', '-cp', str(classes) + os.pathsep + str(args.gson.resolve()),
                     'io.github.campione01.mineclientbridge.ManagedWaterOwnerProbe'])
    finally:
        all_after = capture(repo, args.delta, args.java, args.javac, [args.gson])
        write(out / 'INPUTS-AFTER.json', all_after)
        write(out / 'OUTPUT-CLASS-HASHES.json', inventory(out, '*.class'))
        assert all_before == all_after, 'source/dependency/toolchain changed during owner checks'
        assert doubles_before == inventory(stubs), 'generated test doubles changed during checks'
    result = json.loads(stdout)
    sys.path.insert(0, str(repo / 'resident-controller'))
    from resident_controller.managed_navigation_control import validate_status
    row = result['native_status_row']
    assert validate_status(row['status'], row['command']) == row['status']
    try:
        validate_status({**row['status'], 'dry_step': {}}, row['command'])
    except ValueError:
        pass
    else:
        raise AssertionError('strict Resident validator accepted an added native status key')
    result['actual_native_status_resident_validation'] = 'passed; controlled external proof, actual NativeManagedNavigation.status JSON'
    after = {str(path.relative_to(repo)): digest(path) for path in inputs}
    (out / 'source-after.json').write_text(json.dumps(after, indent=2) + '\n')
    result['source_unchanged'] = before == after
    result['input_manifest_sha256'] = digest(out / 'INPUTS-BEFORE.json')
    result['output_class_manifest_sha256'] = digest(out / 'OUTPUT-CLASS-HASHES.json')
    result['production_native_control'] = 'compiled directly from listed production files'
    result['world_route_settings_geometry'] = manifest['world_route_settings_geometry']
    result['game_gui_loader_network'] = 'NOT_RUN'
    (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    if before != after:
        raise SystemExit('Source changed during checks; result does not bind a frozen source')
    print(json.dumps(result))


if __name__ == '__main__':
    main()

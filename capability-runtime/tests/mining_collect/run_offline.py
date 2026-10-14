#!/usr/bin/env python3
"""Bounded, isolated offline regression runner; never starts Minecraft."""
from datetime import datetime, timezone
import argparse
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
GROUPS = {
    'mining': (32, (
        'mining_collect.mining.test_scoped_mining',
        'mining_collect.mining.test_preview_diagnostics',
        'mining_collect.mining.test_mining_chain')),
    'collect': (22, ('mining_collect.collect.test_collect_route',)),
    'collect_ownerchain': (7, ('mining_collect.collect.test_collect_chain',)),
}
NATIVE_GROUP = (8, ('mining_collect.test_native_wire',))
COMBAT_MODULES = ('test_scoped_combat_chain', 'test_combat_contract_alignment',
                  'test_combat_contract_wire')


def now():
    return datetime.now(timezone.utc).isoformat()


def offline_guard(event, args):
    """Fail closed on accidental networking, external processes or source writes."""
    if event.startswith('socket.') or event in ('subprocess.Popen', 'os.system', 'os.fork', 'os.forkpty'):
        raise PermissionError('Offline regression forbids network/process access: ' + event)
    if event.startswith(('os.exec', 'os.spawn', 'os.posix_spawn')):
        raise PermissionError('Offline regression forbids process access: ' + event)
    write_paths = ()
    if event == 'open' and len(args) >= 3 and isinstance(args[2], int):
        if args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            write_paths = args[:1]
    elif event in ('os.remove', 'os.rmdir', 'os.mkdir', 'os.chmod', 'os.utime', 'os.truncate'):
        write_paths = args[:1]
    elif event in ('os.rename', 'os.link', 'os.symlink'):
        write_paths = args[:2]
    for value in write_paths:
        if isinstance(value, (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(value)).resolve()
            if path.is_relative_to(ROOT):
                raise PermissionError('Offline regression cannot mutate its source checkout')


def child(group, scratch):
    sys.dont_write_bytecode = True
    tempfile.tempdir = str(scratch)
    sys.addaudithook(offline_guard)
    sys.path.insert(0, str(HERE.parent))
    from mining_collect.bootstrap import configure_source_paths
    configure_source_paths()
    expected, names = ((None, COMBAT_MODULES) if group == 'combat' else
                       NATIVE_GROUP if group == 'native_wire' else GROUPS[group])
    suite = unittest.defaultTestLoader.loadTestsFromNames(names)
    if unittest.defaultTestLoader.errors:
        for error in unittest.defaultTestLoader.errors:
            print(error, file=sys.stderr)
        return 2
    count = suite.countTestCases()
    if expected is not None and count != expected:
        print(f'Unexpected case count for {group}: {count}, expected {expected}', file=sys.stderr)
        return 2
    origins = {}
    for name in ('mdc_skills', 'mdc_toolbox', 'resident_controller',
                 'base_watchdog', 'watchdog', 'intent_client'):
        module = importlib.import_module(name)
        path = Path(module.__file__).resolve()
        if not path.is_relative_to(ROOT):
            raise ImportError(f'{name} is not loaded from this checkout: {path}')
        origins[name] = str(path.relative_to(ROOT))
    print(json.dumps({'group': group, 'test_count': count, 'source_modules': origins,
                      'network': 'blocked', 'subprocesses': 'blocked', 'game': 'not used'}), flush=True)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='New evidence directory outside the source checkout')
    parser.add_argument('--timeout-seconds', type=int, default=120,
                        help='Per-group timeout, from 10 through 300 seconds (default: 120)')
    parser.add_argument('--include-combat', action='store_true',
                        help='Also run the three existing current-checkout combat regression modules')
    parser.add_argument('--groups', nargs='+', choices=(*GROUPS, 'combat', 'native_wire'),
                        help='Run only these named groups, in the specified order')
    parser.add_argument('--native-wire-dir', type=Path,
                        help='Original actual Java-emitted combined-wire directory; required for native_wire')
    parser.add_argument('--child', choices=(*GROUPS, 'combat', 'native_wire'), help=argparse.SUPPRESS)
    parser.add_argument('--scratch', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        if args.scratch is None or not args.scratch.is_dir() or args.scratch.resolve().is_relative_to(ROOT):
            parser.error('Child scratch directory must already exist outside source')
        if args.child == 'native_wire':
            if args.native_wire_dir is None or not args.native_wire_dir.is_dir():
                parser.error('native_wire requires an existing --native-wire-dir')
            os.environ['MDC_NATIVE_WIRE_DIR'] = str(args.native_wire_dir.resolve())
        return child(args.child, args.scratch.resolve())
    if args.output is None:
        parser.error('--output is required')
    if not 10 <= args.timeout_seconds <= 300:
        parser.error('--timeout-seconds must be between 10 and 300')
    output = args.output.resolve()
    if output.is_relative_to(ROOT):
        parser.error('Evidence output must be outside the source checkout')
    # Evidence is append-only by run directory: never overwrite or retry an
    # unknown previous invocation. Choose a new path after inspecting it.
    output.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ)
    for name in tuple(env):
        if name.startswith(('MDC_', 'PYTHON')) or name == 'WATCHDOG_CANDIDATE':
            env.pop(name)
    env.update(PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1',
               WATCHDOG_CANDIDATE=str(ROOT / 'defense-watchdog'))
    groups = list(dict.fromkeys(args.groups or [*GROUPS, *(['combat'] if args.include_combat else [])]))
    if 'native_wire' in groups and (args.native_wire_dir is None or not args.native_wire_dir.is_dir()):
        parser.error('native_wire requires an existing --native-wire-dir')
    report = {'started_utc': now(), 'source_root': str(ROOT), 'scope': 'offline synthetic-native only',
              'per_group_timeout_seconds': args.timeout_seconds, 'groups': []}
    result_path = output / 'RESULTS.json'
    result_path.write_text(json.dumps(report, indent=2) + '\n')
    for group in groups:
        scratch = output / (group + '-scratch')
        scratch.mkdir()
        command = [sys.executable, '-I', '-B', str(Path(__file__).resolve()),
                   '--child', group, '--scratch', str(scratch)]
        if group == 'native_wire':
            command.extend(['--native-wire-dir', str(args.native_wire_dir.resolve())])
        entry = {'group': group, 'started_utc': now(), 'command': command,
                 'status': 'running', 'original_exit_code': None}
        report['groups'].append(entry)
        result_path.write_text(json.dumps(report, indent=2) + '\n')
        with (output / (group + '.stdout.log')).open('wb') as stdout, \
             (output / (group + '.stderr.log')).open('wb') as stderr:
            try:
                completed = subprocess.run(command, cwd=output, env=env, stdin=subprocess.DEVNULL,
                                           stdout=stdout, stderr=stderr, timeout=args.timeout_seconds,
                                           check=False)
                entry.update(status='passed' if completed.returncode == 0 else 'failed',
                             original_exit_code=completed.returncode)
            except subprocess.TimeoutExpired:
                entry.update(status='timed_out', timeout_seconds=args.timeout_seconds,
                             original_exit_code=None)
        entry['ended_utc'] = now()
        result_path.write_text(json.dumps(report, indent=2) + '\n')
        print(f"{group}: {entry['status']}; original_exit_code={entry['original_exit_code']}", flush=True)
        # A bounded offline failure is reported exactly once, never auto-retried.
        if entry['status'] != 'passed':
            break
    report['ended_utc'] = now()
    report['status'] = 'passed' if len(report['groups']) == len(groups) and all(
        group['status'] == 'passed' for group in report['groups']) else 'failed'
    result_path.write_text(json.dumps(report, indent=2) + '\n')
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())

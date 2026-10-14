"""Run isolated codec and Python-to-Node boundary tests against this repository.

Requires synthetic fixtures freshly emitted by the production Java codecs.
Starts only the three bounded test interpreter children. Test bodies forbid
networking and nested processes. No service, game, credentials, or live settings.
Outputs are create-only; this runner never retries a phase or overwrites results.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[2]
PYTHON_ROOTS = ('capability-runtime', 'resident-controller', 'defense-watchdog',
                'building-controller', 'navigation-controller', 'navigation-cursor',
                'external-controller', 'multiagent-coordination', 'gameplay-helpers')
COUNTS = (0, 3, 32, 64, 128, 180)
LOG_LIMIT = 64 * 1024
TOTAL_OUTPUT_LIMIT = 192 * 1024 * 1024
PACKET_SECONDS = 300
PHASE_SECONDS = 120


def check(ok, why):
    if not ok:
        raise RuntimeError(why)


def hashed(path, expected=None, limit=8 * 1024 * 1024):
    check(not path.is_symlink() and path.is_file(), 'missing or symlinked pinned file: ' + str(path))
    check(path.stat().st_size <= limit, 'pinned file exceeds bound: ' + str(path))
    raw = path.read_bytes()
    if expected is not None:
        check(len(raw) == expected['bytes'] and hashlib.sha256(raw).hexdigest() == expected['sha256'],
              'pinned file changed: ' + str(path))
    return raw


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def fresh(path, raw):
    with path.open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def status(output, value):
    raw = encode(value)
    temporary = output / '.status.tmp'
    with temporary.open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, output / 'status.json')
    directory = os.open(output, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def output_size(output):
    return sum(p.stat().st_size for p in output.rglob('*') if p.is_file())


def phase(command, env, output, name, deadline):
    """Own exactly this child PID/process group; never discover, replay or kill others."""
    logs = {}
    counts = {'stdout': 0, 'stderr': 0}
    child = None
    started = time.monotonic()
    reason = None
    result = {'name': name, 'command': command, 'pid': None, 'exit_code': None,
              'owned_child_reaped': False, 'reason': None, 'receipt_errors': []}
    try:
        for key in ('stdout', 'stderr'):
            logs[key] = (output / (name + '.' + key + '.log')).open('xb')
        child = subprocess.Popen(command, cwd=HERE, env=env, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 shell=False, start_new_session=True)
        result['pid'] = child.pid
        fresh(output / (name + '-child-start.json'), encode({'pid': child.pid, 'command': command,
              'started_monotonic': started, 'owned_process_group': child.pid, 'retry': False}))
        with selectors.DefaultSelector() as selector:
            for key in ('stdout', 'stderr'):
                selector.register(getattr(child, key), selectors.EVENT_READ, key)
            until = min(deadline, started + PHASE_SECONDS)
            while selector.get_map():
                if time.monotonic() >= until:
                    reason = 'owned_child_timeout'; break
                if output_size(output) > TOTAL_OUTPUT_LIMIT:
                    reason = 'output_capacity_exceeded'; break
                for key, _ in selector.select(timeout=0.15):
                    chunk = os.read(key.fileobj.fileno(), 8192)
                    if not chunk:
                        selector.unregister(key.fileobj); continue
                    name_key = key.data
                    remaining = LOG_LIMIT - counts[name_key]
                    logs[name_key].write(chunk[:max(0, remaining)])
                    counts[name_key] += len(chunk)
                    if counts[name_key] > LOG_LIMIT:
                        reason = 'owned_child_log_limit_exceeded'; break
                if reason:
                    break
        if reason and child.poll() is None:
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=2)
        elif child.poll() is None:
            try:
                child.wait(timeout=max(0.01, min(2, deadline - time.monotonic())))
            except subprocess.TimeoutExpired:
                reason = 'owned_child_terminal_unconfirmed'
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=2)
        result.update(exit_code=child.returncode, reason=reason,
                      owned_child_reaped=child.poll() is not None)
    except BaseException as exc:
        result['reason'] = reason or 'owned_runner_exception'
        result['control_error'] = {'type': type(exc).__name__, 'reason': str(exc)[:1500]}
    finally:
        if child is not None and child.poll() is None:
            try:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=2)
            except BaseException as exc:
                result['cleanup_error'] = {'type': type(exc).__name__, 'reason': str(exc)[:1500]}
        if child is not None:
            # Capture the actual wait result before any receipt work can fail.
            result.update(exit_code=child.returncode, owned_child_reaped=child.poll() is not None)
            for stream in (child.stdout, child.stderr):
                try:
                    stream.close()
                except BaseException as exc:
                    result['receipt_errors'].append({'operation': 'close_child_stream', 'type': type(exc).__name__})
        for stream in logs.values():
            try:
                stream.flush(); os.fsync(stream.fileno())
            except BaseException as exc:
                result['receipt_errors'].append({'operation': 'flush_log', 'type': type(exc).__name__})
            finally:
                try:
                    stream.close()
                except BaseException as exc:
                    result['receipt_errors'].append({'operation': 'close_log', 'type': type(exc).__name__})
        result.update(seconds=round(time.monotonic() - started, 3), log_bytes_observed=counts,
                      terminal_monotonic=time.monotonic())
        # First durable terminal operation after wait/stream closure. Receipt
        # failures never replace the observed original child exit code.
        try:
            fresh(output / (name + '-child-terminal.json'), encode(result))
            result['terminal_receipt_durable'] = True
        except BaseException as exc:
            result['terminal_receipt_durable'] = False
            result['receipt_errors'].append({'operation': 'seal_child_terminal', 'type': type(exc).__name__})
    return result


def file_record(path, root):
    raw = hashed(path, limit=16 * 1024 * 1024)
    return {'path': str(path.relative_to(root)), 'bytes': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest()}


def source_records():
    paths = set(HERE.glob('*.py')) | set(HERE.glob('*.mjs'))
    for name in PYTHON_ROOTS:
        paths.update(p for p in (SOURCE / name).rglob('*.py')
                     if 'tests' not in p.relative_to(SOURCE / name).parts)
    paths.add(SOURCE / 'resident-controller/tests/test_navigation_binding_contract.py')
    paths.add(SOURCE / 'resident-controller/tests/test_navigation_binding_producers.py')
    paths.add(SOURCE / 'client-mod/mcp/toolbox-bridge.mjs')
    return [file_record(path, SOURCE) for path in sorted(paths)]


def fixture_records(directory):
    names = {f'{prefix}-{count}.json'
             for prefix in ('coherent', 'standalone', 'legacy-inline') for count in COUNTS}
    names |= {'coherent-at-reserved-limit.json', 'standalone-at-reserved-limit.json',
              'original-request.json', 'original-intent.json', 'size-refusal.json',
              'producer-case-sizes.json'}
    records = [file_record(directory / name, directory) for name in sorted(names)]
    for record in records:
        check(record['bytes'] <= 2 * 1024 * 1024, 'fixture exceeds test input bound')
    return records


def verify_records(root, records):
    for record in records:
        hashed(root / record['path'], record, limit=16 * 1024 * 1024)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixtures', default=os.environ.get('MDC_MOVEMENT_WIRE_FIXTURES'),
                        help='directory emitted by the native offline movement runner')
    parser.add_argument('--output', default=os.environ.get('MDC_MOVEMENT_WIRE_E2E_OUTPUT'),
                        help='fresh result directory; never reused or overwritten')
    args = parser.parse_args()
    if not args.fixtures or not args.output:
        parser.error('--fixtures and --output (or matching MDC_MOVEMENT_WIRE_* variables) are required')
    fixtures = Path(args.fixtures).absolute()
    output = Path(args.output).absolute()
    check(fixtures.is_dir() and not fixtures.is_symlink(), 'fixture directory must exist without symlinks')
    check(output.parent.is_dir() and not output.exists() and not output.is_symlink(),
          'output must be fresh under an existing directory; no automatic retry or overwrite')
    check(not output.is_relative_to(SOURCE), 'test outputs must stay outside the source repository')
    check(not output.is_relative_to(fixtures) and not fixtures.is_relative_to(output),
          'fixtures and output must be disjoint')
    node = shutil.which('node')
    check(node is not None, 'Node is required; no installation is attempted')
    source_files = source_records()
    fixture_files = fixture_records(fixtures)
    output.mkdir(mode=0o700)
    report = {'schema': 'mdc.movement-t13-offline-run/1', 'state': 'running', 'phases': [],
              'scope': 'synthetic native facts; actual production codecs and consumer chain',
              'source_root': str(SOURCE), 'fixture_directory': str(fixtures),
              'automatic_retry': False, 'game_or_service_started': False}
    status(output, report)
    def interrupted(signum, _frame):
        raise RuntimeError('runner_interrupted_signal_' + str(signum))
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    original = None
    original_sealed = False
    inputs = output / 'input-fixtures'
    try:
        fresh(output / 'source-files.json', encode({'files': source_files}))
        fresh(output / 'fixture-files.json', encode({'files': fixture_files}))
        inputs.mkdir(mode=0o700)
        for record in fixture_files:
            fresh(inputs / record['path'], hashed(fixtures / record['path'], record))
        env = {'PATH': os.defpath, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1',
               'LANG': 'C.UTF-8', 'MDC_MOVEMENT_WIRE_FIXTURES': str(inputs),
               'MDC_MOVEMENT_WIRE_E2E_OUTPUT': str(output),
               'PYTHONPATH': os.pathsep.join([str(HERE), str(SOURCE / 'resident-controller/tests')]
                                           + [str(SOURCE / name) for name in PYTHON_ROOTS])}
        commands = [('codec', [sys.executable, '-B', '-s', '-P', str(HERE / 'run_codec_cases.py')]),
                    ('python', [sys.executable, '-B', '-s', '-P', str(HERE / 'test_full_reply_boundary.py')]),
                    ('node', [node, str(HERE / 'test_node_reply_boundary.mjs')])]
        deadline = time.monotonic() + PACKET_SECONDS
        for name, command in commands:
            result = phase(command, env, output, name, deadline)
            report['phases'].append(result)
            if (result['exit_code'] != 0 or result['reason'] is not None
                    or not result['owned_child_reaped'] or not result.get('terminal_receipt_durable')
                    or result['receipt_errors']):
                report['state'] = 'failed'
                break
        else:
            report['state'] = 'succeeded'
    except BaseException as exc:
        report['state'] = 'failed'
        report['runner_error'] = {'type': type(exc).__name__, 'reason': str(exc)[:1500]}
    finally:
        original = {'schema': 'mdc.movement-t13-original-execution/1', 'state': report['state'],
                    'terminal': True, 'phases': report['phases'],
                    'runner_error': report.get('runner_error'), 'automatic_retry': False}
        try:
            fresh(output / 'ORIGINAL-SEQUENCE-TERMINAL.json', encode(original))
            original_sealed = True
        except BaseException as exc:
            report['original_terminal_receipt_error'] = {'type': type(exc).__name__, 'reason': str(exc)[:1500]}
    post = {'schema': 'mdc.movement-t13-postverification/1', 'success': False}
    try:
        check(original_sealed, 'original execution terminal could not be sealed')
        verify_records(SOURCE, source_files)
        verify_records(fixtures, fixture_files)
        verify_records(inputs, fixture_files)
        post['retained_bytes'] = output_size(output)
        check(post['retained_bytes'] <= TOTAL_OUTPUT_LIMIT, 'retained output exceeds packet bound')
        post['success'] = True
    except BaseException as exc:
        post['error'] = {'type': type(exc).__name__, 'reason': str(exc)[:1500]}
    try:
        fresh(output / 'POSTVERIFY.json', encode(post))
        report['postverify'] = post
        report['original_execution_state'] = original['state']
        if not post['success']:
            report['state'] = 'postverify_failed'
        report['terminal'] = True
        status(output, report)
        fresh(output / 'TERMINAL.json', encode(report))
    except BaseException as exc:
        print(json.dumps({'state': 'reporting_failed', 'original_execution_state': original['state'],
                          'original_terminal_sealed': original_sealed, 'error_type': type(exc).__name__}))
        return 1
    print(json.dumps({'state': report['state'], 'terminal_receipt': str(output / 'TERMINAL.json'),
                      'phases': len(report['phases'])}))
    return 0 if report['state'] == 'succeeded' else 1


if __name__ == '__main__':
    sys.exit(main())

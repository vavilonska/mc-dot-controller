"""Local-only test process helpers; outputs are always separate from source."""
import hashlib
import json
import os
from pathlib import Path
import subprocess


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def new_output(path, repo):
    path, repo = Path(path).resolve(), Path(repo).resolve()
    if path == repo or repo in path.parents:
        raise ValueError('Output must be outside the source checkout')
    path.mkdir(parents=True, exist_ok=False)
    return path


def run(out, label, argv, *, env=None, cwd=None, timeout=120):
    # Commands/logs stay in the user-selected evidence directory, never in sources.
    (out / (label + '-start.json')).write_text(json.dumps({'argv': argv, 'timeout_seconds': timeout}, indent=2))
    with (out / (label + '.stdout')).open('x') as stdout, (out / (label + '.stderr')).open('x') as stderr:
        try:
            result = subprocess.run(argv, stdout=stdout, stderr=stderr, timeout=timeout, cwd=cwd,
                                    env=env or dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
        except OSError as error:
            (out / (label + '-terminal.json')).write_text(json.dumps({'state': 'not_started', 'error': str(error)}))
            raise
        except subprocess.TimeoutExpired:
            (out / (label + '-terminal.json')).write_text(json.dumps({'state': 'owned_test_child_timeout_killed_reaped'}))
            raise
    terminal = {'state': 'known_terminal', 'exit_code': result.returncode}
    (out / (label + '-terminal.json')).write_text(json.dumps(terminal))
    print(label, terminal, flush=True)
    if result.returncode:
        raise RuntimeError('Failed stage ' + label + '; inspect its evidence logs. No automatic retry.')

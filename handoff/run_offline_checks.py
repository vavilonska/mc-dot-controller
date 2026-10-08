#!/usr/bin/env python3
"""Run selected synthetic/offline checks; never construct a game Operator."""
from pathlib import Path
import hashlib
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'candidates/encounter-stage1.1'
HARNESS = ROOT / 'test-tools/encounter-stage1.1-safety-v2'

def verify(root, manifest):
    lines = (root / manifest).read_text().splitlines()
    for line in lines:
        digest, name = line.split(None, 1)
        name = name.lstrip('*')
        file = root / name
        if hashlib.sha256(file.read_bytes()).hexdigest() != digest:
            raise SystemExit('Checksum mismatch: ' + name)
    print(f'Checksums verified: {len(lines)} payloads', flush=True)

verify(SOURCE, 'PUBLISHED_SOURCE_SHA256SUMS.txt')
verify(HARNESS, 'SOURCE_SHA256SUMS.txt')
env = os.environ.copy()
env['PYTHONDONTWRITEBYTECODE'] = '1'
env['WATCHDOG_CANDIDATE'] = str(SOURCE / 'defense-watchdog')
env['PYTHONPATH'] = os.pathsep.join(str(SOURCE / name) for name in (
    'resident-controller', 'gameplay-helpers', 'defense-watchdog',
    'navigation-controller', 'navigation-cursor', 'multiagent-coordination'))

def run(cwd, command, selected_env=env):
    print('\nRUN ' + str(cwd.relative_to(ROOT)) + ': ' + ' '.join(command), flush=True)
    subprocess.run(command, cwd=cwd, env=selected_env, check=True)

for component in ('resident-controller', 'navigation-controller',
                  'navigation-cursor', 'gameplay-helpers', 'building-controller',
                  'external-controller', 'defense-watchdog', 'acceptance',
                  'multiagent-coordination'):
    start = 'tests' if component in ('resident-controller', 'navigation-cursor',
        'gameplay-helpers', 'multiagent-coordination') else '.'
    run(SOURCE / component, [sys.executable, '-m', 'unittest', 'discover',
        '-s', start, '-p', 'test_*.py', '-v'])
run(SOURCE / 'client-mod/mcp', ['node', '--test', 'client-action-test.mjs',
    'encounter-contract-test.mjs'])
run(SOURCE / 'client-mod/mcp', ['node', 'ndjson-framing-test.mjs'])
run(SOURCE, [sys.executable, 'client-mod/scripts/audit-terrain-source.py'])
harness_env = dict(env, PYTHONPATH=str(HARNESS))
for start, pattern in (('tests', 'test_receipt_binding.py'),
                       ('safety_tests', 'test_*.py'),
                       ('independent-review', 'test_*.py')):
    run(HARNESS, [sys.executable, '-m', 'unittest', 'discover', '-s', start,
        '-p', pattern, '-v'], harness_env)
print('\nSelected offline checks passed. Java build and gameplay were not run.')

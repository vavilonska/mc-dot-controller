#!/usr/bin/env python3
"""Bounded combined source/native/policy/codec regression. Never starts a game."""
from pathlib import Path
import hashlib
import json
import os
import re
import signal
import subprocess
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
MOVEMENT = HERE.parent / 'movement-t13'
VM = ['-Xms32m', '-Xmx384m', '-XX:ActiveProcessorCount=1', '-XX:+UseSerialGC', '-XX:-UsePerfData']
if len(sys.argv) != 2:
    raise SystemExit('Usage: JAVA_HOME=... MDC_NATIVE_CLASSPATH=... MDC_GSON_JAR=... python3 -I -B run.py NEW_OUTPUT_DIRECTORY')
JDK = Path(os.environ['JAVA_HOME']).resolve()
CP = [Path(p).resolve() for p in os.environ['MDC_NATIVE_CLASSPATH'].split(os.pathsep)]
OUT = Path(sys.argv[1]).resolve()
if OUT.exists():
    raise SystemExit('Refusing existing output directory; review terminal state before a new attempt')
OUT.mkdir(parents=True, exist_ok=False)
for name in ['tmp', 'empty-sourcepath', 'test-classes', 'combined-wire']:
    (OUT / name).mkdir()
receipts = []
status = 'failed'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')

def inputs():
    roots = [REPO / 'client-mod/src/main/java', HERE, MOVEMENT]
    paths = {p for root in roots for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    paths.update([REPO / 'client-mod/src/test/java/io/github/campione01/mineclientbridge/ScopedCollectPolicyFiniteTest.java',
                  HERE.parent / 'scoped-combat/CombatCallbackFenceChecks.java',
                  HERE.parent / 'scoped-combat/ScopedCombatIntentChecks.java'])
    return [{'path': str(p.relative_to(REPO)), 'sha256': sha(p)} for p in sorted(paths)]

frozen = inputs()
write(OUT / 'INPUTS.json', frozen)

def run(label, args, timeout=60):
    name = f'{len(receipts)+1:02}-{label}'
    write(OUT / (name + '-started.json'), {'argv': list(map(str, args)), 'timeout_seconds': timeout})
    with (OUT / (name + '.stdout')).open('xb') as stdout, (OUT / (name + '.stderr')).open('xb') as stderr:
        child = subprocess.Popen(list(map(str, args)), cwd=REPO, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, start_new_session=True)
        write(OUT / (name + '-child.json'), {'pid': child.pid, 'owned_process_group': child.pid})
        try:
            code = child.wait(timeout=timeout)
            receipt = {'label': label, 'exit_code': code, 'state': 'known_terminal'}
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            try:
                code = child.wait(timeout=5)
                receipt = {'label': label, 'exit_code': code, 'state': 'known_timeout_owned_group_reaped'}
            except subprocess.TimeoutExpired:
                receipt = {'label': label, 'exit_code': None, 'state': 'unknown_no_retry'}
        receipts.append(receipt)
        write(OUT / (name + '-terminal.json'), receipt)
    if receipt['state'] != 'known_terminal' or receipt['exit_code']:
        raise RuntimeError(label + ' did not pass; retained receipts; no automatic retry')
    print('PASS ' + label, flush=True)

def java(label, classname, args=()):
    log = OUT / (label + '-class-init.log')
    run(label, [JDK / 'bin/java', *VM, '-Djava.io.tmpdir=' + str(OUT / 'tmp'),
                '-Xlog:class+init=info:file=' + str(log) + ':uptime,level,tags', '-cp', runtime,
                'io.github.campione01.mineclientbridge.' + classname, *args])

try:
    run('full-production-and-movement-regression', [sys.executable, '-I', '-B', MOVEMENT / 'run.py', OUT / 'movement-t13'], timeout=180)
    classes = OUT / 'movement-t13/native-classes'
    runtime = os.pathsep.join(map(str, [OUT / 'test-classes', OUT / 'movement-t13/wire-classes', classes, *CP]))
    sources = [HERE / 'CombinedWireChecks.java', HERE / 'MiningObservedPolicyTest.java',
               REPO / 'client-mod/src/test/java/io/github/campione01/mineclientbridge/ScopedCollectPolicyFiniteTest.java',
               HERE.parent / 'scoped-combat/CombatCallbackFenceChecks.java', HERE.parent / 'scoped-combat/ScopedCombatIntentChecks.java']
    run('combined-test-compile', [JDK / 'bin/javac', *['-J' + flag for flag in VM], '-J-Djava.io.tmpdir=' + str(OUT / 'tmp'),
                                '-proc:none', '--release', '21', '-encoding', 'UTF-8', '-implicit:none', '-sourcepath', OUT / 'empty-sourcepath',
                                '-cp', runtime, '-d', OUT / 'test-classes', *sources])
    java('combined-wire-codecs', 'CombinedWireChecks', [OUT / 'combined-wire'])
    java('mining-policy-codec', 'MiningObservedPolicyTest', [OUT / 'combined-wire/mining-policy-input.json', OUT / 'combined-wire/mining-policy-output.json'])
    java('collect-policy', 'ScopedCollectPolicyFiniteTest')
    java('combat-callback-fence', 'CombatCallbackFenceChecks')
    java('combat-intent', 'ScopedCombatIntentChecks')
    forbidden = re.compile(r"Initializing '(?:io/github/campione01/mineclientbridge/(?:BridgeServer|ClientActions)|net/minecraft/(?:client/Minecraft|world/entity/Entity))'")
    for path in OUT.glob('*-class-init.log'):
        if forbidden.search(path.read_text()):
            raise AssertionError('Unexpected real game/bridge initialization in ' + path.name)
    if inputs() != frozen:
        raise AssertionError('Inputs changed during attempt; results invalidated')
    status = 'passed'
finally:
    write(OUT / 'RESULT.json', {'schema': 'mdc.combined-native-offline-result/1', 'status': status, 'children': receipts,
                              'inputs_unchanged': inputs() == frozen, 'baseline_mod_artifact_used': False,
                              'scope': 'Complete source compilation, T13 synthetic-engine regression, native pure policies and actual Java serialization with synthetic captured facts.',
                              'mixin_transformed_application': 'NOT_RUN', 'real_combat_functional': 'NOT_RUN', 'live_world': 'NOT_RUN',
                              'game_started': False, 'deployment': False, 'network': False,
                              'cross_language_consumer': 'Separate consumer must validate actual files under combined-wire.'})
print('PASS combined native offline regression; no live-game acceptance', flush=True)

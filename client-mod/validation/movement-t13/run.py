#!/usr/bin/env python3
"""Finite offline Java/source/codec regression. Never starts a game or bridge."""
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PACKAGE = REPO / 'client-mod/src/main/java/io/github/campione01/mineclientbridge'
NATIVE = ['BridgeServer', 'CapabilitySnapshot', 'ClientActionRequest', 'ClientActions',
          'ScopedFlatMovement', 'ScopedMovementEntities', 'ScopedMovementWire',
          'ActionRegistry', 'BridgeJson', 'ScopedNativePreflight', 'ScopedEntityPolicy', 'ScopedFlatPolicy']
SYNTHETIC = ['ScopedFlatMovement', 'ScopedMovementEntities', 'ScopedFlatPolicy',
             'ScopedEntityPolicy', 'ActionRegistry', 'ClientActionRequest', 'BridgeJson']
VM = ['-Xms32m', '-Xmx384m', '-XX:ActiveProcessorCount=1', '-XX:+UseSerialGC', '-XX:-UsePerfData']

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')

def extract(text, signature):
    start = text.index(signature)
    brace = text.index('{', start)
    depth, end = 1, brace + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]

def verify_inputs():
    for row in json.loads((HERE / 'expected-production.json').read_text())['sources']:
        if sha(REPO / row['path']) != row['sha256']:
            raise ValueError('Production source pin changed: ' + row['path'])
    pins = json.loads((HERE / 'expected-prerequisites.json').read_text())
    for kind in ['javac', 'java']:
        if sha(JDK / 'bin' / kind) != pins[kind + '_sha256']:
            raise ValueError('Toolchain pin changed: ' + kind)
    if len(CP) != len(pins['classpath']):
        raise ValueError('Supply exactly the pinned compiler-only classpath entries, in manifest order')
    for path, row in zip(CP, pins['classpath']):
        if path.name != row['basename'] or sha(path) != row['sha256']:
            raise ValueError('Classpath pin changed: ' + row['basename'])
    gson = next(row for row in pins['classpath'] if row['basename'].startswith('gson-'))
    if sha(GSON) != gson['sha256']:
        raise ValueError('Gson pin changed')

def run(label, argv, timeout=60):
    index = len(receipts) + 1
    name = f'{index:02}-{label}'
    # Commands are retained only in the caller-selected output directory, never in source.
    write(OUT / (name + '-started.json'), {'argv': list(map(str, argv)), 'timeout_seconds': timeout})
    with (OUT / (name + '.stdout')).open('xb') as stdout, (OUT / (name + '.stderr')).open('xb') as stderr:
        try:
            done = subprocess.run(list(map(str, argv)), cwd=REPO, stdin=subprocess.DEVNULL,
                                  stdout=stdout, stderr=stderr, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            # subprocess.run kills and waits for only its own child. Do not rerun this attempt.
            receipts.append({'label': label, 'status': 'timed_out_owned_child_reaped'})
            write(OUT / (name + '-terminal.json'), receipts[-1])
            raise RuntimeError('Known timeout; retained output; no retry: ' + label)
    receipts.append({'label': label, 'exit_code': done.returncode})
    write(OUT / (name + '-terminal.json'), receipts[-1])
    if done.returncode:
        raise RuntimeError(f'{label} failed with exit {done.returncode}; see {name}.stderr')
    print('PASS ' + label, flush=True)

def compile_java(label, destination, classpath, sources):
    run(label, [JDK / 'bin/javac', *['-J' + flag for flag in VM],
                '-J-Djava.io.tmpdir=' + str(OUT / 'tmp'), '-proc:none', '--release', '21',
                '-encoding', 'UTF-8', '-implicit:none', '-sourcepath', OUT / 'empty-sourcepath',
                '-cp', classpath, '-d', destination, *sources])

def java(label, classname, classpath, arguments, log=False):
    args = [JDK / 'bin/java', *VM, '-Djava.io.tmpdir=' + str(OUT / 'tmp')]
    if log:
        args += ['-Xlog:class+init=info:file=' + str(OUT / (label + '-class-init.log')) + ':uptime,level,tags']
    run(label, [*args, '-cp', classpath, 'io.github.campione01.mineclientbridge.' + classname, *arguments])

if len(sys.argv) != 2:
    raise SystemExit('Usage: JAVA_HOME=... MDC_NATIVE_CLASSPATH=... MDC_GSON_JAR=... python3 run.py NEW_OUTPUT_DIRECTORY')
JDK = Path(os.environ['JAVA_HOME']).resolve()
CP = [Path(p).resolve() for p in os.environ['MDC_NATIVE_CLASSPATH'].split(os.pathsep)]
GSON = Path(os.environ['MDC_GSON_JAR']).resolve()
OUT = Path(sys.argv[1]).resolve()
if OUT.exists():
    raise SystemExit('Refusing existing output directory; no automatic retry or overwrite')
verify_inputs()
OUT.mkdir(parents=True, exist_ok=False)
for name in ['tmp', 'empty-sourcepath', 'synthetic-src', 'engine-classes', 'native-classes', 'wire-classes', 'wire-fixtures', 'action-fixtures']:
    (OUT / name).mkdir()
receipts = []
status = 'failed'
try:
    run('prepare-synthetic-readers', [sys.executable, '-I', '-B', HERE / 'prepare_engine_fixtures.py', OUT / 'synthetic-src'])
    text = (PACKAGE / 'ClientActions.java').read_text()
    excerpts = [extract(text, sig) for sig in ['static boolean ownsScopedMovement(', 'static String session()', 'static boolean ownsInput()', 'static long ownershipRevision()']]
    body = '''package io.github.campione01.mineclientbridge;
/** Synthetic lifecycle driver around four exact production owner-query excerpts.
 * Does not execute real ClientActions preTick, input, start, or finish lifecycle. */
final class ClientActions {
 static ActionRegistry ACTIONS=new ActionRegistry();static RuntimeAction active;static long ownershipRevision;
 static final class RuntimeAction {ActionRegistry.Entry entry;ScopedFlatMovement scopedMovement;RuntimeAction(ActionRegistry.Entry e,ScopedFlatMovement m){entry=e;scopedMovement=m;}}
 static void reset(){ACTIONS=new ActionRegistry();active=null;ownershipRevision=0;}
 static ActionRegistry.Entry install(ClientActionRequest r,ScopedFlatMovement m){var e=ACTIONS.begin(r);active=new RuntimeAction(e,m);ownershipRevision++;return e;}
 static void end(boolean released){active=null;ACTIONS.finishAfterCleanup("cancelled","fixture_end",released);}
''' + '\n'.join(excerpts) + '\n}\n'
    (OUT / 'synthetic-src/io/github/campione01/mineclientbridge/ClientActions.java').write_text(body)
    run('source-wiring', [sys.executable, '-I', '-B', HERE / 'check_source_relation.py', OUT / 'synthetic-src', OUT / 'source-relation-results.json'])
    compile_java('native-production-compile', OUT / 'native-classes', os.pathsep.join(map(str, CP)),
                 [PACKAGE / (n + '.java') for n in NATIVE])
    compile_java('wire-test-compile', OUT / 'wire-classes', os.pathsep.join(map(str, [OUT / 'native-classes', *CP])),
                 [HERE / n for n in ['WireV1Facts.java', 'WireV1Fixture.java', 'WireV1ProducerCases.java', 'LegacyBridgeJsonReference.java', 'ActionTickWitnessTest.java', 'NativeClassOrigins.java']])
    runtime_cp = os.pathsep.join(map(str, [OUT / 'wire-classes', OUT / 'native-classes', *CP]))
    java('production-class-origins', 'NativeClassOrigins', runtime_cp, [OUT / 'native-classes'])
    java('native-wire-producer', 'WireV1ProducerCases', runtime_cp, [OUT / 'wire-fixtures'], log=True)
    print('WIRE_FIXTURES_READY=' + str(OUT / 'wire-fixtures'), flush=True)
    compile_java('synthetic-policy-compile', OUT / 'engine-classes', str(GSON),
                 [*[PACKAGE / (n + '.java') for n in SYNTHETIC],
                  *sorted((OUT / 'synthetic-src').rglob('*.java')), HERE / 'ActionTickLifetimeTest.java'])
    java('synthetic-policy-tests', 'ActionTickLifetimeTest', os.pathsep.join(map(str, [OUT / 'engine-classes', GSON])), [OUT / 'action-fixtures'])
    java('native-action-witness', 'ActionTickWitnessTest', runtime_cp, [OUT / 'action-fixtures'], log=True)
    run('generated-python-consumer', [sys.executable, '-I', '-B', HERE / 'check_generated_consumer.py', OUT / 'action-fixtures'])
    forbidden = re.compile(r"Initializing '(?:io/github/campione01/mineclientbridge/(?:BridgeServer|ClientActions)|net/minecraft/(?:client/Minecraft|world/entity/Entity))'")
    for log in OUT.glob('*-class-init.log'):
        if forbidden.search(log.read_text()):
            raise AssertionError('Unexpected real engine initialization in ' + log.name)
    verify_inputs()
    classes = []
    for path in sorted((OUT / 'native-classes').rglob('*.class')):
        raw = path.read_bytes()
        if raw[:4] != b'\xca\xfe\xba\xbe' or int.from_bytes(raw[6:8], 'big') != 65:
            raise AssertionError('Not a Java 21 class: ' + path.name)
        classes.append({'path': str(path.relative_to(OUT)), 'bytes': len(raw), 'sha256': sha(path), 'major': 65})
    write(OUT / 'native-class-manifest.json', {'classes': classes})
    status = 'passed'
finally:
    write(OUT / 'RESULT.json', {
        'schema': 'mdc.movement-t13-offline-result/1', 'status': status, 'children': receipts,
        'production_sources_compiled': NATIVE, 'native_classes': len(list((OUT / 'native-classes').rglob('*.class'))),
        'scope': 'Focused source wiring, native compilation, real codec with synthetic captured facts, and actual policy logic with synthetic engine readers; no live Minecraft lifecycle or successful movement proof.',
        'wire_fixtures': 'wire-fixtures', 'action_fixtures': 'action-fixtures',
        'game_started': False, 'deployment': False, 'network': False})
print('PASS focused offline validation; no live-game acceptance', flush=True)

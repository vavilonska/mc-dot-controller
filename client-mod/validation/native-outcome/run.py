#!/usr/bin/env python3
"""Offline complete native compile + pure production policy/wire assertions. No game startup."""
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(sys.argv[1]).resolve()
if OUT.exists(): raise SystemExit('output_exists_no_blind_retry')
OUT.mkdir(parents=True)
JDK = Path(os.environ['JAVA_HOME'])
CLASSPATH = os.environ['MDC_NATIVE_CLASSPATH']
classes = OUT / 'classes'; classes.mkdir()
empty = OUT / 'empty'; empty.mkdir()
sources = sorted((ROOT / 'client-mod/src/main/java').rglob('*.java'))
fixture = Path(__file__).with_name('NativeOutcomeWire.java')
manifest = [{'path': str(p.relative_to(ROOT)), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in sources + [fixture, Path(__file__).resolve()]]
(OUT / 'SOURCE-MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n')
receipts = []
def run(label, command):
    (OUT / (label + '-command.json')).write_text(json.dumps([str(x) for x in command], indent=2))
    with (OUT / (label + '.stdout')).open('w') as output, (OUT / (label + '.stderr')).open('w') as error:
        try:
            value = subprocess.run([str(x) for x in command], stdin=subprocess.DEVNULL,
                stdout=output, stderr=error, timeout=180)
            receipt = {'step':label, 'state':'known_terminal', 'exit_code':value.returncode}
        except subprocess.TimeoutExpired:
            receipt = {'step':label, 'state':'owned_child_timeout_killed_reaped'}
    receipts.append(receipt)
    if receipt.get('exit_code') != 0: raise RuntimeError(label + '_failed')
status = 'failed'
try:
    run('compile', [JDK/'bin/javac', '-J-Xmx384m','-J-XX:ActiveProcessorCount=1','-proc:none',
        '--release','21','-encoding','UTF-8','-implicit:none','-sourcepath',empty,
        '-cp',CLASSPATH,'-d',classes,*sources,fixture])
    run('wire', [JDK/'bin/java','-Xmx128m','-XX:ActiveProcessorCount=1',
        '-Xlog:class+init=info:file=' + str(OUT/'class-init.log'),'-cp',str(classes)+os.pathsep+CLASSPATH,
        'io.github.campione01.mineclientbridge.NativeOutcomeWire',OUT/'wire'])
    if re.search(r"Initializing '(?:net/minecraft/client/Minecraft|net/minecraft/world/entity/Entity|io/github/campione01/mineclientbridge/(?:BridgeServer|ClientActions))'",
            (OUT/'class-init.log').read_text()):
        raise AssertionError('unexpected_game_class_initialization')
    for entry in manifest:
        if hashlib.sha256((ROOT/entry['path']).read_bytes()).hexdigest() != entry['sha256']:
            raise AssertionError('source_changed_during_gate')
    status = 'passed'
finally:
    (OUT/'RESULT.json').write_text(json.dumps({'status':status,'steps':receipts,
        'game_started':False,'world_effects_proven':False,'scope':'Complete pinned native compile; pure verifier and real admission/HTTP serialization only'},indent=2)+'\n')
print('PASS native outcome policy and production wire gate')

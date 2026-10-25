#!/usr/bin/env python3
"""Offline full-source Java 21 verification; never installs or runs Minecraft."""
from contextlib import ExitStack
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import zipfile

REFERENCE_SHA256 = '29141caad50641cdcfc9826a138ff30b2cfd7c555e24ce726fd03abbe366b68e'
AT_SHA256 = 'ffd3960447c486a61abda97b2e20f4d28ac1b5ddcc04729dae4ba8259ae4c803'
EXPECTED_SOURCES = 269
EXPECTED_CLASSES = 632


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def transform(raw, class_name, targets, public_classes):
    """Change only existing AT access flags, including InnerClasses metadata."""
    data = bytearray(raw)
    u2 = lambda offset: struct.unpack_from('>H', data, offset)[0]
    u4 = lambda offset: struct.unpack_from('>I', data, offset)[0]
    def make_public(offset):
        struct.pack_into('>H', data, offset, (u2(offset) & ~7) | 1)
    require(data[:4] == b'\xca\xfe\xba\xbe', 'Invalid class header')
    strings, references = {}, {}
    index, offset = 1, 10
    while index < u2(8):
        tag = data[offset]
        offset += 1
        if tag == 1:
            size = u2(offset)
            offset += 2
            # Member names/descriptors used below are ASCII; unrelated modified
            # UTF-8 constants remain untouched in the original byte array.
            strings[index] = bytes(data[offset:offset + size]).decode(errors='replace')
            offset += size
        elif tag in (3, 4):
            offset += 4
        elif tag in (5, 6):
            offset += 8
            index += 1
        elif tag in (7, 8, 16, 19, 20):
            references[index] = u2(offset)
            offset += 2
        elif tag in (9, 10, 11, 12, 17, 18):
            offset += 4
        elif tag == 15:
            offset += 3
        else:
            raise RuntimeError('Unsupported constant-pool tag: ' + str(tag))
        index += 1
    if None in targets:
        make_public(offset)
    offset += 6
    count = u2(offset)
    offset += 2 + 2 * count
    matched = []
    for methods in (False, True):
        count = u2(offset)
        offset += 2
        for _ in range(count):
            flags_offset = offset
            name, descriptor = strings[u2(offset + 2)], strings[u2(offset + 4)]
            offset += 6
            key = name + descriptor if methods else name
            if key in targets:
                make_public(flags_offset)
                matched.append(key)
            attributes = u2(offset)
            offset += 2
            for _ in range(attributes):
                size = u4(offset + 2)
                offset += 6 + size
    attributes = u2(offset)
    offset += 2
    for _ in range(attributes):
        name, size = strings[u2(offset)], u4(offset + 2)
        payload = offset + 6
        if name == 'InnerClasses':
            for number in range(u2(payload)):
                row = payload + 2 + 8 * number
                inner_index = u2(row)
                if inner_index and strings.get(references.get(inner_index)) in public_classes:
                    make_public(row + 6)
        offset = payload + size
    require(set(matched) == set(targets) - {None}, 'AT member mismatch: ' + class_name)
    return bytes(data), matched


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dependency-root', type=Path, required=True,
                        help='Existing external directory containing the pinned package roots')
    parser.add_argument('--reference-jar', type=Path,
                        help='Optional final r1.4 JAR; its SHA-256 is mandatory and fixed')
    parser.add_argument('--output', type=Path, required=True, help='New nonexistent output directory')
    parser.add_argument('--java', default=os.environ.get('JAVA', 'java'), help='Java 21 executable')
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    client_mod = here.parent.parent
    metadata = here.parent / 'reactive-r1_4'
    source_root = client_mod / 'src/main/java'
    at = client_mod / 'src/main/resources/META-INF/accesstransformer.cfg'
    output = args.output.resolve()
    require(not output.exists(), '--output must not already exist')
    require(sha(at) == AT_SHA256, 'Original AT rules have changed')
    sources = sorted(source_root.rglob('*.java'))
    require(len(sources) == EXPECTED_SOURCES, 'Unexpected production source count')
    source_pins = {p.relative_to(source_root).as_posix(): sha(p) for p in sources}
    config = json.loads((metadata / 'BUILD-CONFIG.json').read_text())
    dependency_root = args.dependency_root.resolve()
    roots = {key: dependency_root / value for key, value in config['roots'].items()}
    pins = json.loads((metadata / 'CLASSPATH-PINS.json').read_text())
    for pin in pins:
        path = roots[pin['root']] / pin['path']
        require(path.is_file() and sha(path) == pin['sha256'], 'Dependency pin mismatch: ' + pin['path'])
    pinned_pairs = {(pin['root'], pin['path']) for pin in pins}
    require(all((row['root'], row['path']) in pinned_pairs for row in config['compile_classpath']),
            'Compile classpath contains an unpinned entry')
    reference = args.reference_jar.resolve() if args.reference_jar else None
    if reference:
        require(sha(reference) == REFERENCE_SHA256, 'Reference JAR must match final r1.4 SHA-256')
    java = shutil.which(args.java)
    require(java is not None, 'Java executable not found')
    version = subprocess.run([java, '-version'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, check=True).stdout
    require('version "21.' in version or 'version "21"' in version, 'Java 21 is required')
    output.mkdir()
    classes, empty = output / 'classes', output / 'empty-sourcepath'
    classes.mkdir()
    empty.mkdir()
    rules = {}
    for line in at.read_text().splitlines():
        fields = line.split('#')[0].split()
        if not fields:
            continue
        require(fields[0] == 'public' and len(fields) in (2, 3), 'Unsupported AT rule')
        rules.setdefault(fields[1].replace('.', '/'), []).append(fields[2] if len(fields) == 3 else None)
    public_classes = {name for name, targets in rules.items() if None in targets}
    cp = [roots[row['root']] / row['path'] for row in config['compile_classpath']]
    overlay = output / 'compile-only-full-existing-at.jar'
    at_changes = []
    with ExitStack() as stack:
        archives = [stack.enter_context(zipfile.ZipFile(path)) for path in cp]
        destination = stack.enter_context(zipfile.ZipFile(overlay, 'w', zipfile.ZIP_DEFLATED))
        for name, targets in sorted(rules.items()):
            entry = name + '.class'
            archive = next((z for z in archives if entry in z.namelist()), None)
            require(archive is not None, 'AT target class missing: ' + name)
            raw = archive.read(entry)
            changed, matched = transform(raw, name, targets, public_classes)
            destination.writestr(entry, changed)
            at_changes.append({'class': name, 'members': matched, 'class_public': None in targets,
                               'before_sha256': hashlib.sha256(raw).hexdigest(),
                               'after_sha256': hashlib.sha256(changed).hexdigest()})
    write_json(output / 'AT-RECEIPT.json', {'rules_sha256': AT_SHA256, 'compile_only': True,
                                         'runtime_modified': False, 'changes': at_changes})
    command = [java, '-m', 'jdk.compiler/com.sun.tools.javac.Main', '-source', '21', '-target', '21',
               '-encoding', 'UTF-8', '-proc:none', '-implicit:none', '-sourcepath', str(empty),
               '-cp', os.pathsep.join(map(str, [overlay] + cp)), '-d', str(classes)] + list(map(str, sources))
    write_json(output / 'command.json', command)
    result = subprocess.run(command, cwd=output, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    (output / 'compile.log').write_text(result.stdout)
    print(result.stdout, end='')
    compiled = {p.relative_to(classes).as_posix(): p.read_bytes() for p in classes.rglob('*.class')}
    receipt = {'compile_exit_code': result.returncode, 'source_count': len(sources),
               'classpath_pins_verified': len(pins), 'compiled_class_count': len(compiled),
               'java_version': version.strip(), 'original_at_sha256': AT_SHA256,
               'reference_comparison': 'NOT_REQUESTED', 'runtime_jar_packaged': False,
               'game_network_install_touched': False}
    if reference:
        with zipfile.ZipFile(reference) as archive:
            expected = {n: archive.read(n) for n in archive.namelist() if n.endswith('.class')}
        missing = sorted(expected.keys() - compiled.keys())
        extra = sorted(compiled.keys() - expected.keys())
        different = sorted(n for n in compiled.keys() & expected.keys() if compiled[n] != expected[n])
        exact = len(compiled.keys() & expected.keys()) - len(different)
        receipt.update(reference_jar_sha256=REFERENCE_SHA256, reference_class_count=len(expected),
                       missing_classes=missing, extra_classes=extra, byte_different_classes=different,
                       byte_exact_class_count=exact,
                       reference_comparison='PASS' if not missing and not extra and not different else 'FAIL')
    receipt['sources_unchanged'] = all(sha(source_root / name) == digest for name, digest in source_pins.items())
    write_json(output / 'SOURCE-AND-CLASS-MANIFEST.json', {'sources': source_pins, 'classes': {
        name: hashlib.sha256(raw).hexdigest() for name, raw in sorted(compiled.items())}})
    receipt['source_and_class_manifest_sha256'] = sha(output / 'SOURCE-AND-CLASS-MANIFEST.json')
    write_json(output / 'COMPILE-RECEIPT.json', receipt)
    print(json.dumps(receipt, indent=2))
    require(result.returncode == 0, 'Full-source compilation failed; see compile.log')
    require(len(compiled) == EXPECTED_CLASSES, 'Unexpected compiled class count')
    require(receipt['sources_unchanged'], 'Source files changed during verification')
    require(receipt['reference_comparison'] != 'FAIL', 'Reference class-byte comparison failed')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError, zipfile.BadZipFile) as error:
        print('Verification failed: ' + str(error), file=sys.stderr)
        sys.exit(1)

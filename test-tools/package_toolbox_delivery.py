"""Deterministic file-only bundle from an explicitly reviewed public inventory.

Never discovers runtime directories, launches processes, installs a JAR, or edits
source manifests. An inventory is SHA256SUMS format: lowercase digest, two spaces,
relative public source path. The final reviewed inventory must match all bytes.
"""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import io
import json
import re
import zipfile

ROOT_FILES = {'README.md', 'NOTICE.md', 'SOURCE-CHECKPOINT.md', 'PUBLICATION-MANIFEST.json',
              'SOURCE_SHA256SUMS.txt', 'COORDINATION-INTEGRATION.md', 'P2-INTEGRATION.md', '.gitignore'}
ROOT_DIRS = {'client-mod', 'capability-runtime', 'resident-controller', 'defense-watchdog',
             'navigation-controller', 'navigation-cursor', 'gameplay-helpers',
             'building-controller', 'external-controller', 'multiagent-coordination', 'docs', 'test-tools', 'handoff'}
DENIED_PARTS = {'secrets', 'credentials', 'saves', 'worlds', 'logs', 'screenshots', 'journals',
                'runtime', 'node_modules', '__pycache__', '.git', '.aws', '.codex', '.env', 'build', '.gradle'}
DENIED_SUFFIXES = {'.jar', '.class', '.pyc', '.log', '.sqlite', '.db', '.nbt', '.dat', '.mca', '.png', '.jpg', '.key', '.pem'}


# Existing reviewed public build wrapper and mod icon only; never arbitrary binaries.
PUBLIC_BINARY_SHA256 = {
    'client-mod/gradle/wrapper/gradle-wrapper.jar': '7d3a4ac4de1c32b59bc6a4eb8ecb8e612ccd0cf1ae1e99f66902da64df296172',
    'client-mod/src/main/resources/mineclient_bridge.png': 'da10abd80803b272f6b6b60c488035e6e5b160871a61083bf0a7c64c55f4a798',
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def public_path(name):
    p = PurePosixPath(name)
    if (p.is_absolute() or str(p) != name or '\\' in name or ':' in name
            or any(part in ('', '.', '..') for part in p.parts)
            or any(part.lower() in DENIED_PARTS for part in p.parts)
            or any(part.startswith('.') and part != '.gitignore' for part in p.parts)
            or (p.suffix.lower() in DENIED_SUFFIXES and name not in PUBLIC_BINARY_SHA256)
            or (name not in ROOT_FILES and (len(p.parts) < 2 or p.parts[0] not in ROOT_DIRS))):
        raise ValueError('Not an allowed public source path: ' + name)
    return p


def checked_read(root, name):
    relative = public_path(name)
    candidate = root
    for part in relative.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise ValueError('Symlink refused: ' + name)
    if not candidate.is_file():
        raise ValueError('Missing public file: ' + name)
    data = candidate.read_bytes()
    if name in PUBLIC_BINARY_SHA256 and digest(data) != PUBLIC_BINARY_SHA256[name]:
        raise ValueError('Pinned public asset checksum mismatch: ' + name)
    return data


def bundle_bytes(source, inventory, jar, jar_sha256, revision):
    if not re.fullmatch('[a-f0-9]{40}', revision):
        raise ValueError('Full reviewed source revision required')
    if not re.fullmatch('[a-f0-9]{64}', jar_sha256) or digest(jar) != jar_sha256:
        raise ValueError('Final JAR checksum mismatch')
    # Container sanity only; no claim this links the JAR to source or validates gameplay.
    with zipfile.ZipFile(io.BytesIO(jar)) as z:
        if 'META-INF/neoforge.mods.toml' not in z.namelist() or not any(n.endswith('.class') for n in z.namelist()):
            raise ValueError('Expected NeoForge mod metadata/classes absent')
    entries = {}
    for line in inventory.splitlines():
        match = re.fullmatch(r'([a-f0-9]{64})  (.+)', line)
        if not match:
            raise ValueError('Malformed public inventory line')
        expected, name = match.groups()
        key = 'source/' + name
        if key in entries:
            raise ValueError('Duplicate inventory path')
        data = checked_read(source, name)
        if digest(data) != expected:
            raise ValueError('Reviewed public file checksum mismatch: ' + name)
        entries[key] = data
    required = {'source/README.md', 'source/NOTICE.md',
                'source/client-mod/mcp/mineclient-bridge-mcp.mjs',
                'source/capability-runtime/mdc_toolbox/__main__.py',
                'source/docs/TOOLBOX-QUICKSTART.md'}
    if not required.issubset(entries):
        raise ValueError('Required public bundle files absent')
    entries['mod/mineclient-bridge.jar'] = jar
    manifest = {'schema_version': 1, 'source_revision': revision, 'target': 'linux-posix-single-host',
                'jar_sha256': jar_sha256, 'source_inventory_sha256': digest(inventory.encode()),
                'scope': 'packaging integrity only; no installation or live acceptance implied',
                'files': [{'path': name, 'bytes': len(data), 'sha256': digest(data)}
                          for name, data in sorted(entries.items())]}
    entries['BUNDLE-MANIFEST.json'] = (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode()
    entries['SHA256SUMS.txt'] = ''.join(f'{digest(data)}  {name}\n' for name, data in sorted(entries.items())).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED) as z:
        for name, data in sorted(entries.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            mode = 0o100755 if name.endswith('/gradlew') or name.endswith('.sh') else 0o100644
            info.external_attr = mode << 16
            z.writestr(info, data)
    return output.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'public-inventory', 'jar', 'jar-sha256', 'source-revision', 'output'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    source = Path(args.source).resolve(strict=True)
    output = Path(args.output).absolute()
    if output.resolve().is_relative_to(source):
        parser.error('Output must be outside source')
    jar_path = Path(args.jar)
    inventory_path = Path(args.public_inventory)
    if jar_path.is_symlink() or inventory_path.is_symlink():
        parser.error('Input symlinks refused')
    inventory = inventory_path.read_text(encoding='utf-8')
    data = bundle_bytes(source, inventory, jar_path.read_bytes(), args.jar_sha256, args.source_revision)
    # Exclusive creation: no overwrite/replacement of existing artifacts.
    with output.open('xb') as stream:
        stream.write(data)
    print(json.dumps({'path': str(output), 'bytes': len(data), 'sha256': digest(data), 'installed': False}))


if __name__ == '__main__':
    main()

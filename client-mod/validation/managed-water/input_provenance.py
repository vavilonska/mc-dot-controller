"""Exact source-union, ordered dependency, and toolchain evidence for offline gates."""
from pathlib import Path
import hashlib
import json
import sys

BASE_SHA = 'aa782d4c9b904cbc1ce0929c8832ead1cb068db3e3779be83581c27ef57500d9'

def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def inventory(root, pattern='*'):
    root = Path(root)
    return {str(p.relative_to(root)): digest(p) for p in sorted(root.rglob(pattern)) if p.is_file()}

def capture(repo, delta_path, java, javac, dependencies, classpath_file=None):
    repo, delta_path = Path(repo).resolve(), Path(delta_path).resolve()
    base_path = repo.parent.parent / 'mdc-managed-water-results/BASE-SOURCE-MANIFEST.json'
    assert digest(base_path) == BASE_SHA, 'base manifest changed'
    base, delta = json.loads(base_path.read_text()), json.loads(delta_path.read_text())
    assert delta['base_manifest_sha256'] == BASE_SHA
    expected = {item['path']: item['sha256'] for item in base['files']}
    for item in delta['files']:
        assert expected.get(item['path']) == item['before_sha256'], ('delta base mismatch', item['path'])
        expected[item['path']] = item['sha256']
    actual = inventory(repo)
    assert actual == expected, 'source tree is not exactly the frozen base plus delta'
    java, javac = Path(java).resolve(), Path(javac).resolve()
    jdk = java.parent.parent
    toolchain = [java, javac, jdk/'release', jdk/'lib/modules', jdk/'lib/server/libjvm.so']
    result = {'source_root': str(repo), 'source_inventory': actual,
        'base_manifest': {'path': str(base_path), 'sha256': digest(base_path)},
        'delta_manifest': {'path': str(delta_path), 'sha256': digest(delta_path)},
        'ordered_dependencies': [{'path': str(Path(p).resolve()), 'bytes': Path(p).stat().st_size, 'sha256': digest(p)} for p in dependencies],
        'toolchain': [{'path': str(p), 'sha256': digest(p)} for p in toolchain],
        'python': {'path': str(Path(sys.executable).resolve()), 'sha256': digest(sys.executable), 'version': sys.version}}
    if classpath_file:
        result['classpath_file'] = {'path': str(Path(classpath_file).resolve()), 'sha256': digest(classpath_file)}
    return result

def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + '\n')

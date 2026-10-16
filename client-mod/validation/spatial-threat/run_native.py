"""Fresh full production compile and serializers over current synthetic-controller output."""
from pathlib import Path
import argparse
import json
import os
from runner_common import new_output, run, sha256

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[3])
p.add_argument('--output', type=Path, required=True)
p.add_argument('--engine-output', type=Path, required=True)
p.add_argument('--java', required=True)
p.add_argument('--javac', required=True)
p.add_argument('--classpath-file', type=Path, required=True)
a = p.parse_args()
here, repo = Path(__file__).resolve().parent, a.repo.resolve()
native = repo / 'client-mod/src/main/java'
engine_output = a.engine_output.resolve()
package = native / 'io/github/campione01/mineclientbridge'
# Reject stale source evidence; normal use generates this immediately beforehand.
for name, digest in json.loads((engine_output / 'source-sha256.json').read_text()).items():
    if sha256(package / (name + '.java')) != digest:
        raise ValueError('Engine evidence does not match current source: ' + name)
owner = json.loads((engine_output / 'owner-source-binding.json').read_text())
if sha256(package / 'ClientActions.java') != owner['ClientActions.java']:
    raise ValueError('Engine owner-query source changed')
for name, digest in owner['harness_sha256'].items():
    if sha256(here / name) != digest:
        raise ValueError('Engine harness changed: ' + name)
out = new_output(a.output, repo)
classes = out / 'classes'; classes.mkdir()
entries = [Path(part).expanduser().resolve() for part in a.classpath_file.read_text().strip().split(os.pathsep) if part]
if not entries or not all(path.is_file() for path in entries):
    raise ValueError('Classpath must list existing local dependency JAR files')
cp = os.pathsep.join(map(str, entries))
compiler = [a.javac, '-J-Xmx384m', '-J-XX:ActiveProcessorCount=1', '-proc:none', '--release', '21']
sources = sorted(native.rglob('*.java'))
run(out, 'compile-production', [*compiler, '-cp', cp, '-d', str(classes), *map(str, sources)])
fixtures = repo / 'client-mod/validation/movement-t13'
run(out, 'compile-wire', [*compiler, '-cp', str(classes) + os.pathsep + cp, '-d', str(classes),
                          str(fixtures / 'WireV1Fixture.java'), str(fixtures / 'WireV1Facts.java'),
                          str(here / 'SpatialThreatWireProducer.java'),
                          str(here / 'RetainedAdmissionStopChecks.java'),
                          str(here / 'StopProofBoundaryChecks.java')])
(out / 'wire').mkdir()
for kind in ('spatial-immediate', 'spatial-continuation', 'spatial-large-stop',
             'spatial-failure-size', 'spatial-failure-frame-size', 'spatial-failure-generic'):
    run(out, 'wire-'+kind, [a.java, '-Xmx256m', '-XX:ActiveProcessorCount=1', '-Djava.awt.headless=true',
        '-cp', str(classes) + os.pathsep + cp,
        'io.github.campione01.mineclientbridge.SpatialThreatWireProducer', str(engine_output/kind), str(out/'wire'/kind)])
(out / 'source-sha256.json').write_text(json.dumps({str(path.relative_to(repo)): sha256(path) for path in sources}, indent=2))
(out / 'result.json').write_text(json.dumps({'status': 'passed', 'production_source_count': len(sources),
    'dependencies': [{'name': path.name, 'sha256': sha256(path)} for path in entries],
    'scope': 'Native compilation and real production serializers; no game, FML/Mixin or world runtime'}, indent=2))

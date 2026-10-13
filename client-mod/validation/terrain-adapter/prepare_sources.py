#!/usr/bin/env python3
"""Verify/copy the selected project's actual reader, plus the immutable legacy fixture.
No source outside this kit's .build directory is written. No dependencies are fetched.
"""
from pathlib import Path
import hashlib,json,sys,shutil
kit=Path(__file__).resolve().parent
if len(sys.argv)!=3:raise SystemExit('Usage: prepare_sources.py PROJECT_ROOT EXISTING_GSON_JAR')
project=Path(sys.argv[1]).resolve();jar=Path(sys.argv[2]).resolve()
build=kit/'.build';src=build/'src';pkg='io/github/campione01/mineclientbridge'
# Never let deleted fixture/source classes survive a new compilation.
if build.is_symlink():raise SystemExit('Test output must not be a symlink')
for output in (src,build/'classes'):
 if output.is_symlink():raise SystemExit('Test output must not be a symlink')
 if output.exists():shutil.rmtree(output)

pins=json.loads((kit/'expected-source-pins.json').read_text())
manifest={}
def sha(data):return hashlib.sha256(data).hexdigest()
def write(rel,data,origin,transform='none'):
 out=src/rel;out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(data)
 manifest[str(rel)]={'origin':origin,'sha256':sha(data),'transformation':transform}
for f in sorted((kit/'src').rglob('*.java')):write(f.relative_to(kit/'src'),f.read_bytes(),'fixture:'+str(f.relative_to(kit)))
for name,expected in pins['project_sources'].items():
 f=project/'client-mod/src/main/java'/pkg/name;data=f.read_bytes()
 if sha(data)!=expected:raise SystemExit('SOURCE PIN MISMATCH: '+str(f))
 write(Path(pkg)/name,data,'project:'+str(f.relative_to(project)))
old=(kit/'baseline/TerrainReader.java').read_bytes()
if sha(old)!=pins['legacy_reader_sha256']:raise SystemExit('Legacy fixture pin mismatch')
renamed=old.replace(b'final class TerrainReader {',b'final class LegacyTerrainReader {').replace(b'private TerrainReader() {',b'private LegacyTerrainReader() {')
if old.count(b'TerrainReader')!=2 or renamed.replace(b'LegacyTerrainReader',b'TerrainReader')!=old:raise SystemExit('Invalid legacy class/constructor-only rename')
write(Path(pkg)/'LegacyTerrainReader.java',renamed,'fixture:baseline/TerrainReader.java','class + constructor token only; reversible')
for name in ('TerrainCoreChecks.java','TerrainDispatchChecks.java','FlatStepCorridorChecks.java'):
 f=project/'client-mod/src/test/java'/pkg/name;write(Path(pkg)/name,f.read_bytes(),'project:'+str(f.relative_to(project)))
if sha(jar.read_bytes())!=pins['gson_2_11_0_sha256']:raise SystemExit('Existing Gson 2.11.0 jar pin mismatch')
manifest['inputs']={'project_root':str(project),'gson_jar':str(jar),'gson_sha256':sha(jar.read_bytes()),'legacy_reader_sha256':sha(old)}
(build/'executed-source-pins.json').write_text(json.dumps(manifest,indent=2)+'\n')
print('Verified project source, immutable legacy baseline and real Gson; prepared test-only copies.')

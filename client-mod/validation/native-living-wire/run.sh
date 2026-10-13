#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ $# -ne 4 ]]; then
  echo 'Usage: bash run.sh CLIENT_MOD_ROOT EXISTING_GSON_JAR JDK21_HOME BUILT_CLIENT_JAR' >&2
  exit 2
fi
PROJECT=$(realpath "$1"); GSON=$(realpath "$2"); JDK=$(realpath "$3"); CLIENT_JAR=$(realpath "$4")
[[ -f "$CLIENT_JAR" && -f "$GSON" && -x "$JDK/bin/java" && -x "$JDK/bin/javac" ]]
mkdir -p .build/emitter-classes .build/empty-sourcepath
NATIVE_CP="$CLIENT_JAR:$GSON"
# Compile only the emitter; never compile production sources or a substitute codec.
timeout 20s "$JDK/bin/javac" -J-Xms16m -J-Xmx128m -J-XX:ActiveProcessorCount=1 -J-XX:+UseSerialGC \
  --release 21 -implicit:none -sourcepath .build/empty-sourcepath -cp "$NATIVE_CP" -d .build/emitter-classes NativeLivingWire.java
# Both compile/runtime classpaths put the exact final production JAR first.
# The emitter also verifies production class CodeSource locations at runtime.
timeout 10s "$JDK/bin/java" -Xms16m -Xmx128m -XX:ActiveProcessorCount=1 -XX:+UseSerialGC \
  -cp "$NATIVE_CP:.build/emitter-classes" io.github.campione01.mineclientbridge.NativeLivingWire "$CLIENT_JAR" > .build/native-wire.json
python3 - "$PROJECT" "$GSON" "$JDK" "$CLIENT_JAR" <<'PY'
from pathlib import Path
import hashlib,json,sys
project,gson,jdk,jar=map(Path,sys.argv[1:])
hash_file=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
production=[project/'src/main/java/io/github/campione01/mineclientbridge'/f'{name}.java'
            for name in ('BridgeJson','NativeLivingSnapshot','BridgeServer')]
files=[jar,gson,jdk/'bin/java',jdk/'bin/javac',*production,Path('NativeLivingWire.java').resolve(),Path('run.sh').resolve()]
classes=list(Path('.build/emitter-classes').rglob('*.class'))
assert len(classes)==1 and classes[0].name=='NativeLivingWire.class',classes
payload=Path('.build/native-wire.json')
cases=json.loads(payload.read_text())
manifest={'offline_only':True,'synthetic_input_not_live_evidence':True,
          'production_class_origin_verified':True,'compiled_production_source':False,
          'classpath':[str(jar),str(gson),str(Path('.build/emitter-classes').resolve())],
          'inputs':[{'path':str(p),'sha256':hash_file(p),'bytes':p.stat().st_size} for p in files],
          'emitter_classes':[{'path':str(p.resolve()),'sha256':hash_file(p)} for p in classes],
          'output':{'path':str(payload.resolve()),'sha256':hash_file(payload),'cases':[case['name'] for case in cases]}}
Path('.build/INPUTS.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(f'Production-JAR wire emitter: {len(cases)} cases; {payload}')
PY

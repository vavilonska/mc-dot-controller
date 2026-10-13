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
timeout 20s "$JDK/bin/javac" -J-Xms16m -J-Xmx128m -J-XX:ActiveProcessorCount=1 -J-XX:+UseSerialGC \
  --release 21 -implicit:none -sourcepath .build/empty-sourcepath -cp "$NATIVE_CP" -d .build/emitter-classes CapabilitySnapshotWire.java
timeout 10s "$JDK/bin/java" -Xms16m -Xmx128m -XX:ActiveProcessorCount=1 -XX:+UseSerialGC \
  -cp "$NATIVE_CP:.build/emitter-classes" io.github.campione01.mineclientbridge.CapabilitySnapshotWire "$CLIENT_JAR" > .build/capability-snapshot-wire.json
node - "$PROJECT" "$GSON" "$JDK" "$CLIENT_JAR" <<'JS'
const fs=require('fs'),path=require('path'),crypto=require('crypto');
const [project,gson,jdk,jar]=process.argv.slice(2);
const hash=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const out=path.resolve('.build/capability-snapshot-wire.json');const cases=JSON.parse(fs.readFileSync(out));
const production=['BridgeJson','CapabilitySnapshot','NativeLivingSnapshot','MovementBudgetLedger','ActionRegistry','ClientActionRequest','BridgeServer'].map(n=>path.join(project,'src/main/java/io/github/campione01/mineclientbridge',n+'.java'));
const files=[jar,gson,path.join(jdk,'bin/java'),path.join(jdk,'bin/javac'),...production,path.resolve('CapabilitySnapshotWire.java'),path.resolve('run.sh')];
const rows=cases.map(c=>({name:c.name,body:JSON.parse(c.response_json)}));
for(const row of rows){
 const b=row.body,a={...b.action};delete a.protocol;delete a.schema_version;
 const stable=o=>JSON.stringify(o,(_,v)=>v&&typeof v==='object'&&!Array.isArray(v)?Object.fromEntries(Object.entries(v).sort(([a],[b])=>a.localeCompare(b))):v);
 if(stable(a)!==stable(b.status.client_action)||stable(a)!==stable(b.state.client_action)||stable(a.movement_budget)!==stable(b.state.movement_budget))throw Error('cross-sibling mismatch '+row.name);
 if(b.schema_version!==2||b.capability_snapshot_schema_version!==1)throw Error('schema mismatch');
 fs.writeFileSync(path.join('.build','encoded-bundle-'+row.name+'.json'),JSON.stringify(b)+'\n');
}
const manifest={offline_only:true,synthetic_input_not_live_evidence:true,production_class_origin_verified:true,compiled_production_source:false,
 classpath:[jar,gson,path.resolve('.build/emitter-classes')],inputs:files.map(p=>({path:p,sha256:hash(p),bytes:fs.statSync(p).size})),
 output:{path:out,sha256:hash(out),cases:cases.map(c=>c.name)}};
fs.writeFileSync('.build/INPUTS.json',JSON.stringify(manifest,null,2)+'\n');
console.log('Production-JAR coherent bundle emitter: '+cases.length+' cases; '+out);
JS

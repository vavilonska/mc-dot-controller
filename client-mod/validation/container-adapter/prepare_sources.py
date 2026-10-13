from pathlib import Path
import hashlib,json,shutil,sys
kit=Path(__file__).resolve().parent
project=Path(sys.argv[1]).resolve()
production=project/'src/main/java/io/github/campione01/mineclientbridge'
bridge=(production/'BridgeServer.java').read_text()
start=bridge.index('    private static JsonObject itemSnapshot(ItemStack stack) {')
pos=bridge.index('{',start); depth=1;end=pos+1
while depth:
    depth += (bridge[end]=='{')-(bridge[end]=='}');end+=1
method=bridge[start:end]
helper=(production/'BoundedContainerSnapshot.java').read_bytes()
actual={'helper_sha256':hashlib.sha256(helper).hexdigest(),'itemSnapshot_sha256':hashlib.sha256(method.encode()).hexdigest()}
expected=json.loads((kit/'expected-source-pins.json').read_text())
assert actual==expected,(actual,expected)
# Only observed producer reset sites are accepted; no per-item or per-collection reset.
assert bridge.count('BoundedContainerSnapshot.beginSnapshot();')==2
assert bridge.count('BoundedContainerSnapshot.append(stack, item);')==1
for signature in ['private static JsonObject createScreenSnapshot() {','static JsonObject menuSnapshot(AbstractContainerMenu menu) {']:
    assert signature+'\n        BoundedContainerSnapshot.beginSnapshot();' in bridge
out=kit/'.build/src';out.mkdir(parents=True,exist_ok=True)
shutil.copytree(kit/'src',out,dirs_exist_ok=True)
pkg=out/'io/github/campione01/mineclientbridge';pkg.mkdir(parents=True,exist_ok=True)
(pkg/'BoundedContainerSnapshot.java').write_bytes(helper)
(pkg/'BridgeServer.java').write_text('package io.github.campione01.mineclientbridge;\nimport com.google.gson.JsonObject;\nimport net.minecraft.world.item.ItemStack;\nimport net.minecraft.core.registries.BuiltInRegistries;\nfinal class BridgeServer {\n'+method+'\n}\n')
(kit/'.build/actual-source-pins.json').write_text(json.dumps(actual,indent=2)+'\n')
print('source pins and two shared-budget reset hooks: PASS')

from pathlib import Path
import json,hashlib,sys
V=Path(__file__).resolve().parent;sys.path.insert(0,str(V.parent/'target-diagnostic'))
from classfile import ClassFile,instructions
root=Path(sys.argv[1]);out=Path(sys.argv[2]);P='io/github/campione01/mineclientbridge/';pins={}
def read(name):
 p=root/(P+name+'.class');b=p.read_bytes();pins[name]=hashlib.sha256(b).hexdigest();return ClassFile(b)
def code(cf,m):
 a=m['attributes']['Code'];n=int.from_bytes(a[4:8],'big');return instructions(cf,a[8:8+n])
def field(cf,name,desc):
 found=[f for f in cf.fields if f['name']==name and f['descriptor']==desc];assert len(found)==1 and found[0]['flags']&0x10,('not final',name)
guard=read('ScopedTargetAction');field(guard,'deadline','J')
fence=read('CombatCallbackFence');field(fence,'actionDeadline','J');field(fence,'actionBound','Z')
call=read('ScopedTargetDispatch$Call');init=call.method('<init>');ins=code(call,init);factory=[i for i,r in enumerate(ins) if r.get('reference','')==P+'CombatCallbackFence.forAction:(Ljava/util/function/BooleanSupplier;Ljava/util/function/LongSupplier;Ljava/util/function/LongSupplier;J)L'+P+'CombatCallbackFence;'];assert len(factory)==1
idx=factory[0];assert ins[idx-1].get('reference')==P+'ScopedTargetAction.deadline:J' and ins[idx-1]['opcode']=='0xb4','factory does not consume original field directly'
assert sum(r.get('reference','')==P+'CombatCallbackFence.<init>:(Ljava/util/function/BooleanSupplier;Ljava/util/function/LongSupplier;Ljava/util/function/LongSupplier;)V' for r in ins)==1,'cleanup constructor missing'
assert not any(r['opcode'] in ('0x61','0x65','0x69') for r in ins),'Call recomputes deadline'
methods=[m for m in fence.methods if m['name']=='forAction'];assert len(methods)==1;factory_code=code(fence,methods[0]);assert not any(r['opcode'] in ('0x61','0x65','0x69') for r in factory_code),'factory recomputes deadline'
result={'status':'passed','class_sha256':pins,'original_final_guard_deadline':True,'direct_field_to_factory':True,'captured_deadline_and_mode_final':True,'legacy_cleanup_constructor_present':True,'no_deadline_arithmetic_in_call_or_factory':True,'call_constructor':ins,'factory':factory_code,'limits':'Actual fresh compiled classes. Branch behavior separately exercised by production Call/hook tests with explicit engine doubles; no populated game engine.'};out.write_text(json.dumps(result,indent=2)+'\n');print('Compiled original deadline binding passed')

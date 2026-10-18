"""Generate exact synthetic before-click witnesses and validate Java-round-tripped bytes."""
from pathlib import Path
import sys,json,copy
ROOT=Path(__file__).resolve().parents[3]
for path in list(ROOT.iterdir())+[ROOT/'capability-runtime/tests']:
    if path.is_dir():sys.path.insert(0,str(path))
from test_inventory_recovery import Runtime,inventory_observation,stack
from test_inventory_recovery_chain import normalize,make_witness,_fixture_module
from mdc_skills import inventory_recovery as recovery
from resident_controller.capability_snapshot import validate_scoped_witness


def generate(destination):
    destination.mkdir(parents=True,exist_ok=False)
    model=Runtime(inventory_observation(offhand=stack('minecraft:torch',2)));normalize(model.current)
    original=model.execute;cases=[]
    def collect(skill,command,verify,*,before,**options):
        _,scope,_,base=_fixture_module.base_fixture()
        intent={k:v for k,v in command.items() if k!='op'}
        intent.update(action_id='native-recovery-'+str(len(cases)),expected_menu_class=before.state['menu']['menu_class'],
            capability_guard={'schema_version':1,'source_tick':100,'source_nano':'100'},
            **{k:v for k,v in base.items() if k.startswith('expected_')})
        native=make_witness(before,intent,scope)
        cases.append(dict(native=native,scope=scope,intent=intent))
        result=original(skill,command,lambda *_:True,before=before,**options)
        normalize(model.current)
        from mdc_skills.core import Outcome
        ok=verify(before,model.current)
        return Outcome('succeeded' if ok else 'failed','synthetic_click',(intent['action_id'],),{},copy.deepcopy(model.current))
    model.execute=collect
    result=recovery.clear_hand(model);assert result.ok,result
    for i,case in enumerate(cases):(destination/f'{i:02}.json').write_text(json.dumps(case,allow_nan=False))
    return len(cases)

def verify(source):
    count=0;negative=0
    for file in sorted(source.glob('*.json')):
        case=json.loads(file.read_text());native,scope,intent=case['native'],case['scope'],case['intent']
        validate_scoped_witness(native,scope,intent['action_id'],intent);count+=1
        # Re-seal intent digests so rejection proves semantic state binding, not only a changed hash.
        for mutation in (
            lambda j:j['inventory_recovery']['context'].update(menu_instance='99999999-9999-4999-8999-999999999999'),
            lambda j:j['inventory_recovery']['context'].update(screen_instance='99999999-9999-4999-8999-999999999999'),
            lambda j:j.update(expected_menu_state_id=j['expected_menu_state_id']+1),
            lambda j:j['expected_carried'].update(item_fingerprint='99999999-9999-4999-8999-999999999999'),
            lambda j:j['inventory_recovery']['inventory'][40].update(item_fingerprint='99999999-9999-4999-8999-999999999999'),
            lambda j:j['inventory_recovery']['slots'].pop(),
            lambda j:j['inventory_recovery'].pop('context'),
            lambda j:j['inventory_recovery'].update(selected_slot=True),
        ):
            bad=copy.deepcopy(case);mutation(bad['intent'])
            _fixture_module.reseal((bad['native'],bad['scope'],bad['intent']['action_id'],bad['intent']))
            try:validate_scoped_witness(bad['native'],bad['scope'],bad['intent']['action_id'],bad['intent'])
            except (ValueError,KeyError):negative+=1
            else:raise AssertionError('changed recovery binding accepted')
    return {'valid_wire_cases':count,'altered_bindings_rejected':negative,'live_gameplay':False}

if __name__=='__main__':
    result=generate(Path(sys.argv[2])) if sys.argv[1]=='generate' else verify(Path(sys.argv[2]))
    print(json.dumps(result))

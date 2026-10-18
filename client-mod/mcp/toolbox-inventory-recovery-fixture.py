"""Offline MCP process: real owner/mailbox chain, explicitly synthetic native click endpoint."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
for path in list(ROOT.iterdir())+[ROOT/'capability-runtime/tests']:
    if path.is_dir():sys.path.insert(0,str(path))
from test_inventory_recovery_chain import InventoryRecoveryChainTests,normalize
from test_inventory_recovery import stack,cursor_args

def emit(value):print(json.dumps(value,allow_nan=False),flush=True)
fixture=InventoryRecoveryChainTests('test_full_public_clear_hand_and_dedup');fixture.setUp()
try:
    fixture.bridge.model.current.state['menu']['carried']=stack('minecraft:stone',1)
    normalize(fixture.bridge.model.current)
    description=fixture.backend.describe()
    emit({'ready':True,'synthetic_native':True,'session_ref':description['session_ref'],
          'context_ref':description['context_ref'],'cursor_arguments':cursor_args(fixture.bridge.model.current)})
    for line in sys.stdin:
        request=json.loads(line)
        if request.get('command')=='proof':
            value={'posts':fixture.bridge.posts,'commands':fixture.bridge.model.commands,
                   'lease':fixture.client.session()['capability_lease'],
                   'inventory':fixture.bridge.model.current.player,'menu':fixture.bridge.model.current.state['menu']}
        else:
            value=fixture.service.call(request['name'],request['arguments'])
            if request['name']=='mdc_job' and request['arguments'].get('operation')=='submit' and 'job_id' in value:
                value=fixture.finish(value)
        emit({'id':request['id'],'result':value})
finally:fixture.tearDown()

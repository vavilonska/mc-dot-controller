"""Production facade fixture; synthetic native endpoint, no game."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/p) for p in ('capability-runtime','capability-runtime/tests','resident-controller','defense-watchdog','navigation-controller')]
from test_managed_navigation_owner import ManagedOwnerTests
fixture=ManagedOwnerTests();fixture.setUp()
def emit(value):print(json.dumps(value,allow_nan=False),flush=True)
try:
 d=fixture.backend.describe();emit({'ready':True,'session_ref':d['session_ref'],'context_ref':d['context_ref']})
 for line in sys.stdin:
  request=json.loads(line)
  if request.get('command')=='proof':result={'calls':fixture.bridge.route_calls,'lease':fixture.dog.capability_lease}
  elif request.get('command')=='lose':fixture.bridge.lose_start=True;result={'ok':True}
  else:
   result=fixture.service.call(request['name'],request['arguments'])
   if request['name']=='mdc_job' and request['arguments'].get('operation')=='submit' and 'job_id' in result:result=fixture.finish(result)
  emit({'id':request['id'],'result':result})
finally:fixture.tearDown()

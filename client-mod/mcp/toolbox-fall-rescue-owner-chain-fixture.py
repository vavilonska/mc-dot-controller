"""Offline stdio fixture: real owner/mailboxes, synthetic native only."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/p) for p in ('capability-runtime','capability-runtime/tests','resident-controller','defense-watchdog','navigation-controller')]
from test_fall_rescue_owner_chain import FallOwnerChainTests

def emit(value):print(json.dumps(value,allow_nan=False),flush=True)
def main():
    fixture=FallOwnerChainTests('test_cancel_disarms_exact_original_without_resume');fixture.setUp();calls=[]
    try:
        d=fixture.backend.describe()
        emit({'ready':True,'session_ref':d['session_ref'],'context_ref':d['context_ref'],'synthetic_native':True})
        for line in sys.stdin:
            request=json.loads(line)
            if request.get('command')=='proof':
                result={'calls':calls,'fall_calls':fixture.bridge.fall_calls,
                    'capability_lease':fixture.client.session()['capability_lease'],'synthetic_native':True}
            else:
                name,args=request['name'],request['arguments'];calls.append({'name':name,'arguments':args})
                result=fixture.service.call(name,args)
                if name=='mdc_job' and args.get('operation')=='submit' and 'job_id' in result:
                    fixture.until(lambda:any(op=='arm' for op,_ in fixture.bridge.fall_calls))
                    result=fixture.service.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'status',
                        'job_id':result['job_id'],'session_ref':result['session_ref']})
                elif name=='mdc_job' and args.get('operation')=='cancel' and 'job_id' in result:
                    result=fixture.finish(result)
            emit({'id':request['id'],'result':result})
    finally:fixture.tearDown()
if __name__=='__main__':main()

"""Offline subprocess test endpoint: real Python owner/mailbox chain, synthetic native.

Never points at a game or installed queue. RequestOnlyCombat allocates temporary
queues and an in-memory synthetic native endpoint. EOF performs test teardown.
"""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'capability-runtime'),str(ROOT/'capability-runtime/tests'),
              str(ROOT/'resident-controller'),str(ROOT/'defense-watchdog')]
from test_request_only_policy import RequestOnlyCombat


def emit(value):
    print(json.dumps(value,allow_nan=False),flush=True)


def main():
    fixture=RequestOnlyCombat('test_exact_cancel_no_resume')
    fixture.setUp()
    calls=[]
    try:
        fixture.bridge.hold=True
        original=fixture.bridge.snapshot
        def complete_snapshot():
            state=original()
            # Native production advertises this; the old synthetic fixture did not.
            state['combat_capabilities']={'schema_version':1,'caller_health_reserve_guard_schema_version':1}
            return state
        fixture.bridge.snapshot=complete_snapshot
        description=fixture.backend.describe()
        emit({'ready':True,'session_ref':description['session_ref'],
              'context_ref':description['context_ref'],'execution_policy':fixture.client.session()['execution_policy'],
              'target_uuid':fixture.bridge.entities[0]['uuid'],'synthetic_native':True})
        for line in sys.stdin:
            request=json.loads(line)
            if request.get('command')=='proof':
                emit({'id':request['id'],'result':{'calls':calls,
                    'scoped_posts':[body for path,body in fixture.bridge.posts if path=='/control/scoped-action'],
                    'cancel_posts':[body for path,body in fixture.bridge.posts if path=='/control/action/cancel'],
                    'legacy_posts':[body for path,body in fixture.bridge.posts if path=='/control/action'],
                    'capability_lease':fixture.client.session()['capability_lease'],
                    'execution_policy':fixture.client.session()['execution_policy'],'synthetic_native':True}})
                continue
            name,args=request['name'],request['arguments']
            calls.append({'name':name,'arguments':args})
            result=fixture.service.call(name,args)
            if name=='mdc_job' and args.get('operation')=='submit' and 'job_id' in result:
                fixture.until(lambda:any(path=='/control/scoped-action' for path,_ in fixture.bridge.posts))
                result=fixture.service.call('mdc_job',{'api_version':'mdc.toolbox/1','operation':'status',
                    'session_ref':args['session_ref'],'job_id':result['job_id'],'wait_ms':0})
            elif name=='mdc_job' and args.get('operation')=='cancel' and 'job_id' in result:
                result=fixture.finish(result)
            emit({'id':request['id'],'result':result})
    finally:
        fixture.tearDown()

if __name__=='__main__':main()

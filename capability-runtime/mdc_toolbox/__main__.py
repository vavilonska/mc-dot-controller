"""Operator-configured, long-lived bounded JSON-lines adapter. No network listener."""
import argparse
import json
import signal
import sys
import threading
from .contracts import API_VERSION, ToolboxError, json_data
from .service import ToolboxService, UnavailableBackend

MAX_LINE=1024*1024
MAX_INFLIGHT=32

def unique_object(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('Duplicate JSON key')
        result[key]=value
    return result

def serve(service,source=sys.stdin.buffer,sink=sys.stdout.buffer):
    output_lock=threading.Lock(); slots=threading.BoundedSemaphore(MAX_INFLIGHT); workers=[]
    def write(value):
        encoded=json_data(value)+b'\n'
        if len(encoded)>MAX_LINE:
            original=value.get('result',{})
            identity={key:original[key] for key in ('api_version','job_id','request_id','job_request_id','session_ref',
                      'state','job_state','effect_certainty','cleanup_certainty','continuation')
                      if isinstance(original,dict) and key in original and isinstance(original[key],(str,int,bool,type(None)))}
            ids=original.get('request_ids',[]) if isinstance(original,dict) else []
            # Bound even the fallback, but never invent or replace an identity.
            if isinstance(ids,list):
                identity['request_ids']=[rid for rid in ids if isinstance(rid,str) and len(rid)<=128][:512]
                identity['request_ids_truncated']=len(identity['request_ids'])!=len(ids)
            identity.update(api_version=API_VERSION,error={'code':'response_too_large','stage':'transport',
                            'reason':'Result exceeds transport bound; query the original identity',
                            'effect_certainty':original.get('effect_certainty','unknown') if isinstance(original,dict) else 'unknown',
                            'affected_ids':identity.get('request_ids',[]),'suggested_next_operation':'status'})
            encoded=json_data({'id':value.get('id'),'result':identity})+b'\n'
        with output_lock:sink.write(encoded);sink.flush()
    def respond(request):
        identity=request.get('id') if isinstance(request,dict) else None
        try:
            if not isinstance(request,dict) or set(request)!={'id','tool','arguments'}:
                raise ToolboxError('invalid_request','Envelope requires only id, tool and arguments')
            if type(identity) not in (str,int) or (isinstance(identity,str) and len(identity)>128):
                raise ToolboxError('invalid_request','Invalid correlation ID')
            write({'id':identity,'result':service.call(request['tool'],request['arguments'])})
        except ToolboxError as exc:write({'id':identity,'error':exc.as_dict()})
        except Exception:write({'id':identity,'error':{'code':'invalid_request','reason':'Invalid request envelope'}})
        finally:slots.release()
    try:
        while True:
            line=source.readline(MAX_LINE+1)
            if not line:break
            if len(line)>MAX_LINE:
                while line and not line.endswith(b'\n'):line=source.readline(MAX_LINE+1)
                write({'id':None,'error':{'code':'invalid_request','reason':'Request exceeds transport bound'}});continue
            try:
                request=json.loads(line,object_pairs_hook=unique_object,parse_constant=lambda value:(_ for _ in ()).throw(ValueError(value)))
            except (ValueError,UnicodeError,RecursionError):
                write({'id':None,'error':{'code':'invalid_request','reason':'Invalid JSON'}});continue
            if not slots.acquire(blocking=False):
                write({'id':request.get('id') if isinstance(request,dict) else None,'error':{'code':'owner_busy','reason':'Too many in-flight reads'}});continue
            worker=threading.Thread(target=respond,args=(request,),daemon=True,name='mdc-toolbox-rpc')
            workers=[w for w in workers if w.is_alive()];workers.append(worker);worker.start()
    finally:
        # EOF is an operator disconnect. Stop exact known work before shutdown.
        service.shutdown()
        for worker in workers:worker.join(timeout=0.1)
    return service.shutdown_result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--control',help='Operator-only existing authorized control directory')
    parser.add_argument('--journal',required=True,help='Operator-only toolbox identity journal')
    parser.add_argument('--runtime-journal',help='Operator-only existing Runtime journal')
    parser.add_argument('--storage-warn-free-bytes',type=int,default=1024*1024*1024)
    parser.add_argument('--storage-min-free-bytes',type=int,default=512*1024*1024)
    parser.add_argument('--event-history-admission-bytes',type=int,default=64*1024*1024)
    args=parser.parse_args()
    if bool(args.control)!=bool(args.runtime_journal):parser.error('--control and --runtime-journal must be provided together')
    if args.control:
        from .runtime_adapter import create_backend
        backend=create_backend(args.control,args.runtime_journal)
    else:backend=UnavailableBackend()
    from .storage_reserve import StorageReserve
    policy=StorageReserve(args.storage_warn_free_bytes,args.storage_min_free_bytes,args.event_history_admission_bytes)
    service=ToolboxService(backend,args.journal,storage_reserve=policy)
    def stop(signum,frame):
        result=service.shutdown();raise SystemExit(0 if result['cleanup_confirmed'] else 3)
    signal.signal(signal.SIGTERM,stop)
    signal.signal(signal.SIGINT,stop)
    result=serve(service)
    return 0 if result['cleanup_confirmed'] else 3

if __name__=='__main__':sys.exit(main())

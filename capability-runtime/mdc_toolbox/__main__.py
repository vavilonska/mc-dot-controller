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
            encoded=json.dumps({'id':value.get('id'),'error':{'code':'response_too_large','reason':'Result exceeds transport bound; query a narrower view'}}).encode()+b'\n'
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
    args=parser.parse_args()
    if bool(args.control)!=bool(args.runtime_journal):parser.error('--control and --runtime-journal must be provided together')
    if args.control:
        from .runtime_adapter import create_backend
        backend=create_backend(args.control,args.runtime_journal)
    else:backend=UnavailableBackend()
    service=ToolboxService(backend,args.journal)
    def stop(signum,frame):
        result=service.shutdown();raise SystemExit(0 if result['cleanup_confirmed'] else 3)
    signal.signal(signal.SIGTERM,stop)
    signal.signal(signal.SIGINT,stop)
    result=serve(service)
    return 0 if result['cleanup_confirmed'] else 3

if __name__=='__main__':sys.exit(main())

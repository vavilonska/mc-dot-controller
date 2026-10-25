"""Explicit local CLI for the newly restored F1220 world; no launcher/UI control.

Requires a previously approved existing private token. Never creates or logs one.
The operator launches only the matching isolated instance. No automatic restart,
retry, pause, game close or lost-session history adoption is implemented here.
"""
import argparse, hashlib, http.client, json, os, stat, sys, time
from pathlib import Path
from urllib.parse import urlsplit
sys.dont_write_bytecode=True


def safe_read(path,limit,private=False):
    path=Path(path).absolute()
    if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('symlink input forbidden')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as f:
        s=os.fstat(f.fileno())
        if not stat.S_ISREG(s.st_mode) or s.st_uid!=os.getuid() or s.st_size>limit:raise ValueError('owner bounded regular input required')
        if private and stat.S_IMODE(s.st_mode)&0o077:raise ValueError('private input mode required')
        return f.read(limit+1)


def write_new(path,data):
    path=Path(path);fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())


def atomic_status(path,data):
    path=Path(path);tmp=path.with_suffix('.tmp')
    fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)


def singleplayer_state(endpoint,token,path='/control/state?radius=0'):
    if path not in ('/control/state?radius=0','/control/status'):raise ValueError('closed read-only identity path required')
    u=urlsplit(endpoint)
    if u.scheme!='http' or u.hostname not in ('127.0.0.1','::1') or not u.port:raise ValueError('loopback endpoint only')
    c=http.client.HTTPConnection(u.hostname,u.port,timeout=2.)
    try:
        c.request('GET',path,headers={'Authorization':'Bearer '+token,'Connection':'close'})
        response=c.getresponse();raw=response.read(1024*1024+1)
        if response.status!=200 or len(raw)>1024*1024 or token.encode() in raw:raise ValueError('bounded private singleplayer evidence unavailable')
        return json.loads(raw)
    finally:c.close()


def initial_identity_read(endpoint,token,path,wait_error):
    try:return singleplayer_state(endpoint,token,path)
    except (TimeoutError,ConnectionError,http.client.IncompleteRead) as e:
        raise wait_error('read_only_identity_transport_unavailable') from e


def make_transport(HttpTransport, endpoint, token, PROFILE, ROOT):
    class Transport(HttpTransport):
        def __init__(self):super().__init__(endpoint,token,5.);self.observer=HttpTransport(endpoint,token,2.);self.scheduling_quantum=.5;self.pool=set();self.started=set();self.timings=[];self.last_observe_return=None
        def request(self,method,path,body=None):
            operation=path[len(ROOT):].split('?',1)[0] if path.startswith(ROOT) else None
            if method=='GET' and operation=='observe':
                start=time.monotonic();reply=self.observer.request(method,path,body);self.last_observe_return=time.monotonic();self.timings.append(dict(operation='observe',seconds=self.last_observe_return-start,complete=reply.complete if hasattr(reply,'complete') else None));return reply
            if method=='GET' and operation=='status':pass
            elif method=='POST' and operation=='start':
                if not isinstance(body,dict) or body.get('profile')!=PROFILE or body.get('id') not in self.pool or body['id'] in self.started:raise ValueError('one start from current explicit batch only')
                self.started.add(body['id'])
            elif method=='POST' and operation=='stop':
                if not isinstance(body,dict) or body.get('id') not in self.started:raise ValueError('original started ID stop only')
            else:raise ValueError('unsupported local transport operation')
            started=time.monotonic();gap=None if self.last_observe_return is None else started-self.last_observe_return
            reply=super().request(method,path,body)
            self.timings.append(dict(operation=operation,seconds=time.monotonic()-started,from_observe_return_seconds=gap,complete=reply.complete if hasattr(reply,'complete') else None))
            return reply
    return Transport()


def cli(argv=None):
    ap=argparse.ArgumentParser()
    ap.add_argument('--source-root',required=True)
    ap.add_argument('--recovery-root',required=True)
    ap.add_argument('--baseline',required=True)
    ap.add_argument('--baseline-sha256',required=True)
    ap.add_argument('--world-name',required=True)
    ap.add_argument('--run-dir',required=True)
    ap.add_argument('--maintenance-resume-run')
    ap.add_argument('--maintenance-trace-sha256')
    ap.add_argument('--known-closed-resume-run')
    ap.add_argument('--known-closed-trace-sha256')
    ap.add_argument('--manifest-resume-run')
    ap.add_argument('--manifest-path')
    ap.add_argument('--manifest-sha256')
    ap.add_argument('--manifest-trace-sha256')
    ap.add_argument('--source-history-path')
    ap.add_argument('--resolved-resume-run')
    ap.add_argument('--resolved-trace-sha256')
    ap.add_argument('--predecessor-resume-run')
    ap.add_argument('--predecessor-trace-sha256')
    ap.add_argument('--resolution-result')
    ap.add_argument('--resolution-result-sha256')
    ap.add_argument('--stop-x',type=float,default=-635.)
    ap.add_argument('--enable-bread',action='store_true')
    ap.add_argument('--enable-exact-ray-blaze',action='store_true')
    args=ap.parse_args(argv)
    if sum(bool(v) for v in (args.known_closed_resume_run,args.maintenance_resume_run,args.resolved_resume_run,args.manifest_resume_run))>1:raise ValueError('one explicit maintenance route only')
    if bool(args.known_closed_resume_run)!=bool(args.known_closed_trace_sha256):raise ValueError('known CLOSED source run and retained trace SHA required together')
    resolution_args=(args.resolved_resume_run,args.resolved_trace_sha256,args.predecessor_resume_run,args.predecessor_trace_sha256,args.resolution_result,args.resolution_result_sha256)
    if not args.manifest_resume_run and any(resolution_args) and not all(resolution_args):raise ValueError('resolved original requires complete explicit predecessor, trace and resolution pins')
    if not args.manifest_resume_run and any((args.manifest_path,args.manifest_sha256,args.manifest_trace_sha256,args.source_history_path)):raise ValueError('manifest source run required')
    manifest_args=(args.manifest_resume_run,args.manifest_path,args.manifest_sha256,args.manifest_trace_sha256)
    if args.manifest_resume_run and (not all(manifest_args) or bool(args.resolution_result)!=bool(args.resolution_result_sha256) or args.predecessor_resume_run or args.predecessor_trace_sha256 or args.resolved_trace_sha256):raise ValueError('manifest recovery requires exact manifest, trace and original resolution pins')
    source=Path(args.source_root).resolve();root=Path(args.recovery_root).resolve()
    sys.path.insert(0,str(source/'survival6-controller'))
    from survival6_controller import Controller
    from survival6_controller.legacy import encode,strict_json,PROFILE,ROOT,Refused
    from maintenance5_controller.transport import HttpTransport
    import rebuilt_session as r
    base=safe_read(args.baseline,128*1024*1024)
    if hashlib.sha256(base).hexdigest()!=args.baseline_sha256:raise ValueError('baseline bytes mismatch')
    baseline=strict_json(base)
    baseline_count=len(baseline['actions'])
    if not 1<=baseline_count<4096:raise ValueError('explicit retained complete history count required')
    endpoint=baseline['endpoint']
    baseline_reference=baseline if (args.resolved_resume_run or args.manifest_resume_run) else None
    del baseline
    game=root/'polymc-data/instances/MDC-RECOVERY-F1220-20261022/minecraft'
    if not (game/'saves'/args.world_name).is_dir():raise ValueError('selected restored world missing')
    token=safe_read(game/'config/mineclient-bridge.token',512,True).decode('ascii').strip()
    ledger=root/'controller-state'
    if not (args.known_closed_resume_run or args.resolved_resume_run or args.manifest_resume_run) and safe_read(ledger/'ledger.json',128*1024*1024,True)!=base:raise ValueError('run must begin from the exact explicitly pinned retained ledger')
    out=Path(args.run_dir).absolute()
    if out.exists() or any(p.is_symlink() for p in (out,*out.parents)):raise ValueError('new unique run directory required')
    out.mkdir(parents=True,mode=0o700);(out/'commands').mkdir(mode=0o700);(out/'consumed-commands').mkdir(mode=0o700)
    spec=dict(schema_version=1,kind='survival6_live_corridor_session',baseline_sha256=args.baseline_sha256,baseline_count=baseline_count,owner_id=r.OWNER,player_uuid=r.PLAYER,mission=dict(kind='west_corridor',stop_x=args.stop_x),batch_seconds=300,start_reserve_seconds=8,batch_max_intents=128,batch_max_new_stages=16,enable_bread=args.enable_bread,enable_exact_ray_blaze=args.enable_exact_ray_blaze)
    spec_raw=encode(spec);write_new(out/'SESSION-SPEC.json',spec_raw)
    write_new(out/'RUN-IDENTITY.json',encode(dict(kind=('MANIFEST_SAME_SESSION_TERMINAL_RECOVERY' if args.manifest_resume_run else 'EXPLICITLY_RESOLVED_ORIGINAL_SAME_SESSION' if args.resolved_resume_run else 'KNOWN_CLOSED_SAME_SESSION_POLICY_UPGRADE' if args.known_closed_resume_run else 'KNOWN_ZERO_ATTEMPT_SAME_SESSION_MAINTENANCE' if args.maintenance_resume_run else 'NEW_MAINTENANCE_RUN_COMPLETE_HISTORY'),world_name=args.world_name,baseline_count=baseline_count,baseline_sha256=args.baseline_sha256,lost_later_history_not_retried=True,source_root=str(source),recovery_root=str(root),started_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))))
    transport=make_transport(HttpTransport,endpoint,token,PROFILE,ROOT);status={};last_wait=[0.]
    def event(e):
        if e['event'] in ('batch_open','maintenance_batch_restored'):transport.pool=set(e['batch']['ids'])
        status.update(event=e['event'],utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),session_id=e.get('session_id'))
        if 'observation' in e:
            o=e['observation'];status.update(pose=o.get('pose'),health=o.get('health'),ready=o.get('ready'),history_count=(o['owner_generation']-1 if type(o.get('owner_generation')) is int else None))
        if e['event']=='decision_available':status.update(decision=e['decision'],reason=e['checkpoint']['reason'],decision_required=True)
        if e['event'] in ('decision_applied','gameplay_resume'):status.update(decision_required=False,decision=None)
        if e['event']=='session_result':status.update(result=e['result'])
        atomic_status(out/'STATUS.json',encode(status))
    def read_decision(checkpoint):
        files=sorted((out/'commands').glob('*.json'))
        if not files:return None
        p=files[0];raw=safe_read(p,8192,True);dest=out/'consumed-commands'/p.name
        if dest.exists():raise ValueError('duplicate command delivery must be reconciled, not retried')
        os.rename(p,dest)  # Single process owns this inbox; consumed before parse/apply.
        try:return strict_json(raw)
        except Refused as e:
            write_new(dest.with_suffix('.parse-rejected.json'),encode(dict(reason=str(e)[:180],sha256=hashlib.sha256(raw).hexdigest(),effect_submitted=False)))
            return {}  # Consumed once; original Session rejects without losing its token.
    def wait(o):
        if time.monotonic()-last_wait[0]>1:
            last_wait[0]=time.monotonic();atomic_status(out/'STATUS.json',encode(dict(event='initial_wait',ready=o.get('ready'),reason=o.get('reason'),gameplay_started=False)))
    def identity_read(path):
        return initial_identity_read(endpoint,token,path,r.InitializationWait)
    def confirm(o):
        process=identity_read('/control/status')
        pid=process.get('process_id')
        if type(pid) is not int or pid<=0:raise ValueError('actual game process identity required')
        cwd=Path(os.readlink(f'/proc/{pid}/cwd')).resolve()
        if cwd!=game.resolve():raise ValueError('loopback endpoint is not the selected instance process')
        saves=[p.name for p in (game/'saves').iterdir() if p.is_dir()]
        if saves!=[args.world_name]:raise ValueError('single explicitly restored world required in selected instance')
        patch=strict_json(safe_read(game.parent/'patches/net.neoforged.neoforge.json',2*1024*1024))
        fields=patch.get('minecraftArguments','').split()
        positions=[i for i,v in enumerate(fields) if v=='--quickPlaySingleplayer']
        if len(positions)!=1 or positions[0]+1>=len(fields) or fields[positions[0]+1]!=args.world_name:raise ValueError('pinned quickplay target differs from restored world')
        actual=identity_read('/control/state?radius=0')
        world=actual.get('world',{});player=actual.get('player',{})
        accepted=actual.get('private_singleplayer') is True and world.get('world_generation')==o['world_generation'] and player.get('uuid')==o['player_uuid'] and player.get('dimension')=='minecraft:the_nether'
        if accepted:
            write_new(out/'INITIAL-RUNTIME-IDENTITY.json',encode(dict(process_id=pid,actual_cwd=str(cwd),only_world=args.world_name,quickplay_target=args.world_name)))
            write_new(out/'INITIAL-SINGLEPLAYER-STATE.json',encode(actual))
        return accepted
    write_new(out/'DRIVER-STARTED.json',encode(dict(pid=os.getpid(),utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),game_launched_by_this_script=False)))
    try:
        with Controller(ledger,transport) as controller:
            from fast_pending import PreparedHistory
            from terminal_resolution import install as install_terminal_resolution
            install_terminal_resolution(controller,out/'original-terminal-resolutions')
            from edge_support import install as install_edge_support
            install_edge_support(controller)
            controller._prepared_history=PreparedHistory(controller.ledger)
            controller.ledger._save_pending=controller._prepared_history.save_pending
            kwargs=dict(maintenance_baseline_path=args.baseline,baseline_raw=base,expected_baseline_sha256=args.baseline_sha256,session_spec_raw=spec_raw,expected_session_spec_sha256=hashlib.sha256(spec_raw).hexdigest(),outdir=out/'session',confirm_world=confirm,stop_requested=lambda:(out/'EXPLICIT-STOP').exists(),on_event=event,decision_reader=read_decision,on_initial_wait=wait)
            if args.manifest_resume_run:
                from resume_manifest import restore
                old=Path(args.manifest_resume_run)
                manifest_raw=safe_read(args.manifest_path,2*1024*1024,True)
                trace_raw=safe_read(old/'session/trace.jsonl',32*1024*1024,True)
                result_raw=safe_read(old/'session/RESULT.json',128*1024,True)
                resolution_raw=safe_read(args.resolution_result,65536,True) if args.resolution_result else None
                if result_raw!=safe_read(old/'DRIVER-TERMINAL.json',128*1024,True):raise ValueError('manifest predecessor terminal differs')
                if spec_raw!=safe_read(old/'SESSION-SPEC.json',4096,True):raise ValueError('manifest original Session spec differs')
                def factory(c,**kw):
                    return restore(c,manifest_raw=manifest_raw,manifest_path=args.manifest_path,
                        expected_manifest_sha256=args.manifest_sha256,trace_raw=trace_raw,
                        trace_path=old/'session/trace.jsonl',expected_trace_sha256=args.manifest_trace_sha256,
                        result_raw=result_raw,result_path=old/'session/RESULT.json',
                        expected_result_sha256=hashlib.sha256(result_raw).hexdigest(),
                        resolution_raw=resolution_raw,resolution_path=args.resolution_result,
                        expected_resolution_sha256=args.resolution_result_sha256,
                        source_history_path=args.source_history_path,
                        baseline_path=args.baseline,baseline=baseline_reference,**kw)
                result=r.run(controller,session_factory=factory,**kwargs)
            elif args.resolved_resume_run:
                from resolved_handoff import restore
                def retained_run(path,expected_trace):
                    old=Path(path)
                    trace=safe_read(old/'session/trace.jsonl',32*1024*1024,True)
                    if hashlib.sha256(trace).hexdigest()!=expected_trace:raise ValueError('resolved predecessor trace pin changed')
                    result_raw=safe_read(old/'session/RESULT.json',128*1024,True)
                    if result_raw!=safe_read(old/'DRIVER-TERMINAL.json',128*1024,True):raise ValueError('original immutable terminal evidence differs')
                    if spec_raw!=safe_read(old/'SESSION-SPEC.json',4096,True):raise ValueError('resolved handoff retains original Session spec')
                    return old,trace,result_raw
                old4,trace4,result4=retained_run(args.predecessor_resume_run,args.predecessor_trace_sha256)
                old5,trace5,result5=retained_run(args.resolved_resume_run,args.resolved_trace_sha256)
                resolution_raw=safe_read(args.resolution_result,65536,True)
                if hashlib.sha256(resolution_raw).hexdigest()!=args.resolution_result_sha256:raise ValueError('explicit resolution result pin changed')
                def factory(c,**kw):
                    return restore(c,r4_trace=trace4,r4_result=result4,
                        r4_trace_path=old4/'session/trace.jsonl',r4_result_path=old4/'session/RESULT.json',
                        expected_r4_trace_sha256=args.predecessor_trace_sha256,
                        expected_r4_result_sha256=hashlib.sha256(result4).hexdigest(),
                        r5_trace=trace5,r5_result=result5,
                        r5_trace_path=old5/'session/trace.jsonl',r5_result_path=old5/'session/RESULT.json',
                        expected_r5_trace_sha256=args.resolved_trace_sha256,
                        expected_r5_result_sha256=hashlib.sha256(result5).hexdigest(),
                        baseline_path=args.baseline,baseline=baseline_reference,resolution_raw=resolution_raw,
                        resolution_path=args.resolution_result,
                        expected_resolution_sha256=args.resolution_result_sha256,**kw)
                result=r.run(controller,session_factory=factory,**kwargs)
            elif args.known_closed_resume_run:
                from trace_handoff import restore
                old=Path(args.known_closed_resume_run)
                old_trace=safe_read(old/'session/trace.jsonl',32*1024*1024,True)
                if hashlib.sha256(old_trace).hexdigest()!=args.known_closed_trace_sha256:raise ValueError('retained known CLOSED trace changed')
                old_result=safe_read(old/'session/RESULT.json',128*1024,True)
                if old_result!=safe_read(old/'DRIVER-TERMINAL.json',128*1024,True):raise ValueError('stopped terminal evidence differs')
                if spec_raw!=safe_read(old/'SESSION-SPEC.json',4096,True):raise ValueError('same Session must retain original spec')
                # Original trace did not capture boot_id: do not invent it. The
                # restorer keeps the original deadline and explicitly rolls over.
                def factory(c,**kw):
                    return restore(c,old_trace=old_trace,old_result=old_result,
                        old_trace_path=old/'session/trace.jsonl',expected_trace_sha256=args.known_closed_trace_sha256,**kw)
                result=r.run(controller,session_factory=factory,**kwargs)
            elif args.maintenance_resume_run:
                if not args.maintenance_trace_sha256:raise ValueError('explicit retained maintenance trace SHA required')
                from zero_attempt_handoff import resume
                old=Path(args.maintenance_resume_run)
                old_trace=safe_read(old/'session/trace.jsonl',2*1024*1024,True)
                if hashlib.sha256(old_trace).hexdigest()!=args.maintenance_trace_sha256:raise ValueError('retained maintenance trace changed')
                old_result=safe_read(old/'session/RESULT.json',8192,True)
                if old_result!=safe_read(old/'DRIVER-TERMINAL.json',8192,True):raise ValueError('maintenance terminal evidence differs')
                if spec_raw!=safe_read(old/'SESSION-SPEC.json',4096,True):raise ValueError('maintenance must retain original spec')
                result=resume(controller,old_trace=old_trace,old_result=old_result,**kwargs)
            else:
                if args.maintenance_trace_sha256:raise ValueError('maintenance source directory required')
                result=r.run(controller,**kwargs)
        write_new(out/'DRIVER-TERMINAL.json',encode(result))
        return 0
    except BaseException as e:
        # No retry, second launch or window-close side effect on failure.
        write_new(out/'DRIVER-FAILURE.json',encode(dict(type=type(e).__name__,reason=str(e)[:180],game_close_performed=False)))
        raise

if __name__=='__main__':raise SystemExit(cli())

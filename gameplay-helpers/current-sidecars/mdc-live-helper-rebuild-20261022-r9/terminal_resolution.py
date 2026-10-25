"""Recognize the exact original action's proven terminal, never repeat its input.

An explicitly authorized sidecar successor to C8's sticky public UNKNOWN.
Transport timeouts are evidence uncertainty, not an eternal prohibition on reading
that original action's outcome. Native deadlines, counters and release rules stay.
"""
import argparse,base64,copy,hashlib,os,sys,time
from pathlib import Path
from reconcile_original import (ResolutionRefused,require,sha,status_path,private_read,write_new)
KIND='explicit_original_terminal_resolution_v2'

def terminal(controller,raw,request):
    from survival6_controller.legacy import strict_json
    require(raw.complete is True and raw.status==200 and len(raw.body)<=65536,
            'complete_original_status_required')
    term=strict_json(raw.body);controller._validate_receipt(term,request)
    require(term['state']=='SETTLED' and term['protocol_state']=='SETTLED'
            and all(term[k] is True for k in ('protocol_terminal','settled','input_invalidated','release_proven'))
            and term['unknown_lock'] is False and term['release_state'] in ('not_needed','proven'),
            'known_released_original_terminal_required')
    return term

def proposal(controller,action_id,reply,observation,*,before_sha256,independent_raw=None):
    from survival6_controller.legacy import encode,strict_json,PROFILE
    from maintenance5_controller.transport import RawReply
    data=controller.ledger.data;rec=data['actions'].get(action_id)
    require(isinstance(rec,dict) and rec.get('state')=='UNKNOWN' and rec.get('terminal_native') is None
            and data['unknown_lock'] is True and rec.get('unknown_reasons')
            and 'resolution' not in rec,'original_unresolved_unknown_required')
    require(all(k==action_id or r['state']=='CLOSED' for k,r in data['actions'].items()),
            'sole_unresolved_original_required')
    req=rec['request'];controller.validate_request(req)
    require(req['id']==action_id and req['owner_id']==controller.owner_id and req['profile']==PROFILE,
            'original_retained_owner_profile_required')
    term=terminal(controller,reply,req)
    if independent_raw is not None:
        require(terminal(controller,RawReply(200,independent_raw,True),req)==term,
                'independent_original_terminal_conflict')
    # Incomplete/bad receipts remain evidence, not truth. Every *valid* retained
    # native receipt must agree on identity and not regress counts; a retained
    # known terminal must match exactly. No native UNKNOWN is silently cleared.
    retained=[rec.get('latest_native')]
    for e in rec['evidence']:
        if e['complete'] is True and e['http_status']==200:
            try:
                old=strict_json(base64.b64decode(e['raw_base64'],validate=True))
                controller._validate_receipt(old,req)
            except Exception:continue
            retained.append(old)
    for old in retained:
        if old is None:continue
        controller._validate_receipt(old,req)
        require(old['applied_calls']<=term['applied_calls']
                and old['cancellation_generation']<=term['cancellation_generation'],
                'original_native_counts_must_not_regress')
        require(old['state']!='UNKNOWN' and old['unknown_lock'] is False,
                'native_unknown_not_resolved_by_sidecar')
        if old['state']=='SETTLED':require(old==term,'retained_terminal_conflict')
    require(isinstance(observation,dict) and observation.get('profile')==req['profile']
            and observation.get('bound_owner_id')==req['owner_id']
            and all(observation.get(k)==req[k] for k in ('session','world_generation','player_uuid'))
            and observation.get('active_id') is None and observation.get('unknown_lock') is False
            and observation.get('owner_generation')==len(data['actions'])+1,
            'fresh_idle_same_native_context_required')
    require(len(rec['evidence'])<controller.MAX_EVIDENCE,'original_evidence_capacity_required')
    proof=dict(schema_version=1,kind=KIND,original_id=action_id,original_public_state='UNKNOWN',
        original_record_sha256=sha(encode(rec)),original_ledger_sha256=before_sha256,
        source_sha256=sha(Path(__file__).read_bytes()),fresh_status_sha256=sha(reply.body),
        fresh_observation_sha256=sha(encode(observation)),
        independent_status_sha256=None if independent_raw is None else sha(independent_raw),
        original_unknown_reasons=copy.deepcopy(rec['unknown_reasons']),resolved=True,no_effect_retried=True,
        applied_calls=term['applied_calls'],requested_calls=term['requested_calls'],
        context={k:req[k] for k in ('session','world_generation','player_uuid','owner_id')},
        stage_id=req['stage_id'],retained_stage_uses=sum(r['request'].get('stage_id')==req['stage_id']
          and all(r['request'].get(k)==req[k] for k in ('session','world_generation','player_uuid'))
          for r in data['actions'].values()))
    new=copy.deepcopy(rec);new['evidence'].append(dict(kind='status',complete=True,http_status=200,
        raw_base64=base64.b64encode(reply.body).decode('ascii')))
    new.update(state='CLOSED',latest_native=copy.deepcopy(term),terminal_native=copy.deepcopy(term),resolution=proof)
    proposed=dict(data,actions=dict(data['actions']),unknown_lock=False);proposed['actions'][action_id]=new
    return proposed,proof

def resolve(controller,action_id,outdir,*,expected_before_sha256=None,independent_raw=None,
            read_attempts=3,sleep=time.sleep):
    """GET-only reads; one durable commit. Failure never retries a gameplay POST."""
    from survival6_controller.legacy import encode,Refused
    out=Path(outdir)
    require(not out.exists() and not any(p.is_symlink() for p in (out,*out.parents)),
            'new_original_resolution_evidence_dir_required')
    rec=controller.ledger.data['actions'].get(action_id)
    require(isinstance(rec,dict) and rec['state']=='UNKNOWN','unresolved_original_required')
    before=private_read(controller.ledger.path);before_sha=sha(before)
    require(expected_before_sha256 is None or before_sha==expected_before_sha256,'before_history_pin_changed')
    require(encode(controller.ledger.data)==before,'locked_complete_history_changed')
    req=rec['request'];last=None
    for attempt in range(read_attempts):
        try:
            reply=controller.transport.request('GET',status_path(controller,req))
            terminal(controller,reply,req)
            obs=controller.observe()
            proposed,proof=proposal(controller,action_id,reply,obs,before_sha256=before_sha,
                                    independent_raw=independent_raw)
            break
        except (ResolutionRefused,Refused) as e:
            last=e
            # GET only; each missing/nonterminal read may be revisited, never input.
            if attempt+1==read_attempts:raise
            sleep(.25)
    else:raise last
    out.mkdir(parents=True,mode=0o700)
    write_new(out/'ORIGINAL-ACTION.json',encode(rec));write_new(out/'FRESH-STATUS.json',reply.body)
    write_new(out/'FRESH-OBSERVATION.json',encode(obs));write_new(out/'INTENT.json',encode(proof))
    if independent_raw is not None:write_new(out/'INDEPENDENT-STATUS.json',independent_raw)
    for directory in (out,out.parent):
        fd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
    controller.ledger.data=proposed
    try:controller.ledger.save()
    except BaseException:
        write_new(out/'COMMIT-UNCERTAIN.json',encode(dict(kind=KIND,state='inspect_original_file_no_retry')))
        raise
    after=private_read(controller.ledger.path)
    require(after==encode(proposed),'complete_commit_verification_failed_no_retry')
    result=dict(proof,state='CLOSED',unknown_lock=False,final_count=len(proposed['actions']),
        after_ledger_sha256=sha(after),after_record_sha256=sha(encode(proposed['actions'][action_id])),
        evidence_dir=str(out),original_request_unchanged=True,unrelated_records_unchanged=True)
    write_new(out/'RESULT.json',encode(result))
    return controller.report(action_id)

def install(controller,evidence_root):
    """Wrap original finish once; new successor resolves by original-ID reads only."""
    original=controller.finish_one_step
    def finish(action_id,**kwargs):
        rec=original(action_id,**kwargs)
        if rec.get('state')!='UNKNOWN':return rec
        try:return resolve(controller,action_id,Path(evidence_root)/action_id,sleep=kwargs.get('sleep',time.sleep))
        except ResolutionRefused:return controller.report(action_id)
        # Malformed native schema, persistence errors etc remain maintenance; no
        # exception path issues another start/finish or erases the old evidence.
    controller.finish_one_step=finish
    return controller

def cli(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('source-root','recovery-root','original-id','before-ledger-sha256','independent-status','independent-status-sha256','evidence-dir','endpoint'):
        ap.add_argument('--'+name,required=True)
    a=ap.parse_args(argv);source=Path(a.source_root).resolve();root=Path(a.recovery_root).resolve()
    sys.path.insert(0,str(source/'survival6-controller'))
    from survival6_controller import Controller
    from survival6_controller.legacy import encode,ROOT
    from maintenance5_controller.transport import HttpTransport
    raw=private_read(a.independent_status,65536)
    require(sha(raw)==a.independent_status_sha256,'independent_status_pin_changed')
    token=private_read(root/'polymc-data/instances/MDC-RECOVERY-F1220-20261022/minecraft/config/mineclient-bridge.token',512).decode('ascii').strip()
    class ReadOnlyTransport(HttpTransport):
        allowed_status=None
        def request(self,method,path,body=None):
            require(method=='GET' and body is None and path in (ROOT+'observe',self.allowed_status),'resolution_get_only')
            return super().request(method,path,body)
    t=ReadOnlyTransport(a.endpoint,token,5.)
    with Controller(root/'controller-state',t) as c:
        rec=c.ledger.data['actions'].get(a.original_id);require(isinstance(rec,dict),'retained_original_required')
        t.allowed_status=status_path(c,rec['request'])
        resolve(c,a.original_id,a.evidence_dir,expected_before_sha256=a.before_ledger_sha256,independent_raw=raw)
        print((Path(a.evidence_dir)/'RESULT.json').read_text())
    return 0
if __name__=='__main__':raise SystemExit(cli())

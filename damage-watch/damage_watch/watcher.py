"""Bounded GET-only capture. Operator independently watches stop-trigger.json to close UI."""
from dataclasses import dataclass
from datetime import datetime,timezone
import hashlib
import math
import os
from pathlib import Path
import tempfile
import time
from .strict import Invalid,strict_json,encode,number,integer
from .schema import PATH,MAX_RESPONSE,validate,uuid,pos


@dataclass(frozen=True)
class Reply:
    status:int|None
    body:bytes
    complete:bool
    error:str|None=None # Only connection_unavailable grants preworld retry; never exception text.


def atomic(path,raw):
    fd,name=tempfile.mkstemp(prefix='.capture-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
        d=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(d)
        finally:os.close(d)
    finally:
        if os.path.exists(name):os.unlink(name)


def danger(snapshot,expected_pose,expected_owner,expected_player,expected_next_generation,expected_entry_count):
    if any(event['player_uuid']!=expected_player for event in snapshot['damage_events']):return 'player_identity_changed'
    if snapshot['damage_total'] or snapshot['damage_events']:return 'damage_detected'
    if snapshot['damage_dropped']:return 'damage_capture_overflow'
    if snapshot['client_nonzero_count'] or snapshot['first_nonzero_tick'] is not None:return 'nonzero_input_detected'
    if snapshot['capture_errors']:return 'native_capture_error'
    samples=[snapshot[k] for k in ('server_first','client_first','client_latest') if snapshot[k] is not None]+snapshot['client_samples']
    for sample in samples:
        if sample['player_uuid']!=expected_player:return 'player_identity_changed'
        if sample['health']<20:return 'health_below20'
        if any(abs(sample['position'][k]-expected_pose[k])>.05 for k in ('x','y','z')):return 'pose_deviation'
        if 'input' in sample:
            if sample['input']['forward']!=0 or sample['input']['strafe']!=0 or sample['input']['jump']:return 'nonzero_input_detected'
            n=sample['native']
            if not n['enabled'] or n['owner_id']!=expected_owner or n['next_generation']!=expected_next_generation or n['entry_count']!=expected_entry_count or n['unknown_lock']:return 'native_identity_or_generation_changed'
            if any(n[k] is not None for k in ('active_id','profile','state')) or n['applied_count']!=0:return 'native_action_detected'
    return None


def watch(transport,outdir,*,expected_pose,expected_owner,expected_player,expected_next_generation,expected_entry_count,
          startup_s=60.,world_s=12.,interval_s=.2,clock=time.monotonic,sleep=time.sleep,
          utc=lambda:datetime.now(timezone.utc).isoformat()):
    """transport.get(exact_path, timeout_s=...) must enforce absolute timeout, raw bound, no retries.

    No credentials are read here. Only explicit preworld connection_unavailable may retry.
    Output must be a NEW directory. This writes evidence/trigger, never closes game or posts.
    """
    pos(expected_pose);uuid(expected_owner);uuid(expected_player);integer(expected_next_generation,1);integer(expected_entry_count,1,256)
    for v,low,high in ((startup_s,.1,60),(world_s,.1,12),(interval_s,.2,1)):number(v,low,high)
    root=Path(outdir)
    if any(p.is_symlink() for p in (root.absolute(),*root.absolute().parents)):raise Invalid('capture symlink path forbidden')
    root.mkdir(mode=0o700) # Never overwrite or adopt an existing run.
    started=clock();startup_deadline=started+startup_s;world_deadline=None
    boot=None;previous=None;world_seen=False;polls=0;incomplete=0;latest=None
    def finish(reason):
        result=dict(schema_version=1,close_required=True,reason=reason,polls=polls,world_seen=world_seen,
                    damage_reproduced=reason in ('damage_detected','health_below20'),
                    elapsed_seconds=max(0,clock()-started),finished_utc=utc(),incomplete_transport_responses=incomplete,
                    boot_id=boot,native_window_closed=latest['window_closed'] if latest else False,
                    native_capture_errors=latest['capture_errors'] if latest else None,damage_dropped=latest['damage_dropped'] if latest else None,client_dropped=latest['client_dropped'] if latest else None,
                    diagnostic_window_complete=bool(latest and latest['window_closed'] and not latest['capture_errors'] and not latest['damage_dropped'] and not incomplete),
                    client_ring_is_continuous=False,game_control_performed=False,effect_posts=0)
        # Trigger is durable/atomic and independent of the conversational/model path.
        atomic(root/'stop-trigger.json',encode(result));atomic(root/'report.json',encode(result));return result
    while True:
        now=clock();deadline=world_deadline if world_deadline is not None else startup_deadline
        if now>=deadline:return finish('window_not_reproduced' if world_seen else 'startup_not_in_world')
        if polls>=400:return finish('poll_bound_exhausted')
        index=polls;polls+=1;begin=clock();stamp=utc()
        try:reply=transport.get(PATH,timeout_s=min(.75,max(.001,deadline-begin)))
        except Exception:reply=Reply(None,b'',False,'transport_exception')
        valid_reply=isinstance(reply,Reply) and (reply.status is None or type(reply.status) is int and 100<=reply.status<=599) and type(reply.body) is bytes and type(reply.complete) is bool
        if not valid_reply:reply=Reply(None,reply.body if isinstance(reply,Reply) and type(reply.body) is bytes else b'',False,'invalid_transport_contract')
        overflow=len(reply.body)>MAX_RESPONSE
        raw=reply.body[:MAX_RESPONSE+1]
        complete=reply.complete and not overflow
        error=reply.error if reply.error in (None,'connection_unavailable','transport_exception','invalid_transport_contract','timeout','response_too_large','secret_quarantined') else 'transport_error'
        meta=dict(index=index,method='GET',path=PATH,started_utc=stamp,finished_utc=utc(),started_monotonic=begin,finished_monotonic=clock(),http_status=reply.status,complete=complete,raw_bytes=len(raw),raw_sha256=hashlib.sha256(raw).hexdigest(),raw_is_prefix=overflow,error=error)
        atomic(root/f'{index:04d}.raw',raw);atomic(root/f'{index:04d}.json',encode(meta))
        if not complete or reply.status!=200:
            incomplete+=1
            if not world_seen and error=='connection_unavailable' and reply.status is None and not raw:
                sleep(max(0,min(interval_s,startup_deadline-clock())));continue
            return finish('transport_incomplete')
        try:snapshot=validate(strict_json(raw))
        except (Invalid,TypeError,KeyError):return finish('invalid_diagnostic_response')
        latest=snapshot
        if not snapshot['enabled']:return finish('diagnostic_disabled')
        if boot is None:boot=snapshot['boot_id']
        elif snapshot['boot_id']!=boot:return finish('boot_identity_changed')
        if previous is not None:
            if any(snapshot[k]<previous[k] for k in ('query_nanos','client_total','client_nonzero_count','damage_total','capture_errors')) or (previous['window_started'] and snapshot['window_start_nanos']!=previous['window_start_nanos']):return finish('diagnostic_evidence_regressed')
        previous=snapshot
        if snapshot['window_started']:
            elapsed=(snapshot['query_nanos']-snapshot['window_start_nanos'])/1e9
            candidate=begin+max(0,world_s-elapsed) # Conservative request-start anchor; network latency never extends the window.
            world_deadline=candidate if world_deadline is None else min(world_deadline,candidate)
            world_seen=True
        reason=danger(snapshot,expected_pose,expected_owner,expected_player,expected_next_generation,expected_entry_count)
        if reason:return finish(reason)
        if snapshot['window_closed']:return finish('native_window_closed_not_reproduced')
        if clock()>=(world_deadline if world_seen else startup_deadline):return finish('window_not_reproduced' if world_seen else 'startup_not_in_world')
        sleep(max(0,min(interval_s,(world_deadline if world_seen else startup_deadline)-clock())))

"""One append-only transition between fully closed test sessions in one fixed ledger.

No game mutations, transport construction, old-record rewrite, or unresolved-action
reconciliation. Native state has no persistent save ID: same-save continuity is
an explicit, independently verified operator evidence reference.
"""
from copy import deepcopy
from pathlib import Path
import re
from types import SimpleNamespace

from post_trial_safety import (_load, _write, _sha, _json, _ref, _require, _finite,
                               _identity, NO_SUCCESS, PostTrialSafety, SafetyHalt)
from receipt_binding import _uncertain

KEYS = ('resident_session', 'action_session', 'world_generation', 'player_uuid')


def identity(value):
    import uuid
    _require(type(value) is dict and set(value) == set(KEYS), 'rollover_identity_invalid')
    try:
        for key in KEYS:
            _require(isinstance(value[key], str), 'rollover_identity_invalid')
            uuid.UUID(value[key])
    except (ValueError, AttributeError, TypeError) as exc:
        raise SafetyHalt('rollover_identity_invalid') from exc
    return deepcopy(value)


def verifier(safety, value):
    value=identity(value)
    o=SimpleNamespace(**vars(safety.o))
    o.resident=value['resident_session'];o.session=value['action_session']
    o.world=value['world_generation'];o.player=value['player_uuid']
    return PostTrialSafety(o, safety.root)


def case_identity(safety, case):
    registration=_load(case/'registration.json')
    return identity(registration.get('session_identity', _load(safety.root/'context.json')))


def closed_case(safety, case):
    """Re-run existing original/closeout proofs under their historical identity."""
    for path in case.glob('*.json*'):
        _require(re.fullmatch(r'.+\.json(?:\.sha256)?',path.name) is not None,
                 'rollover_case_partial_or_unknown_record')
        _load(Path(str(path).removesuffix('.sha256')))
    for path in case.glob('*.intent.json'):
        if _load(path).get('read_only') is not True:
            _require(path.with_name(path.name.replace('.intent.json','.effect.json')).exists(),
                     'rollover_unresolved_mutation_intent')
    old=verifier(safety,case_identity(safety,case));registration=_load(case/'registration.json')
    if registration.get('active_ai_supported') is True:
        binding,record,closeout=old._verified_operator_closeout(case)
        verify_active_auxiliaries(case,binding,record)
        closed={'kind':'operator_closeout','sha256':_sha((case/'operator-closeout.json').read_bytes())}
    else:
        _require(registration.get('active_ai_supported') is False,'rollover_old_case_mode_unknown')
        binding,record=old._eligible(case)
        effects=['cleanup-'+e['uuid'] for e in registration['entities']]+['pause']
        for name in effects:old._verified_effect(case,name,binding,record)
        closed={'kind':'noai_exact_cleanup_and_pause','effects':{
            name:_sha((case/(name+'.effect.json')).read_bytes()) for name in effects}}
    for path in case.glob('*.intent.json'):
        if _load(path).get('read_only') is not True:
            name=path.name.removesuffix('.intent.json')
            _require(name=='pause' or name in {'cleanup-'+e['uuid'] for e in registration['entities']},
                     'rollover_unrecognized_mutation_intent')
            old._verified_effect(case,name,binding,record)
    _require(record['resolved_outcome']['kind'] in ('bound_terminal','admission_rejected')
             and record['resolved_outcome']['needs_reconciliation'] is False
             and record['release_observed'] is True,'rollover_old_trial_unresolved')
    return {'case_directory':case.name,'registration_sha256':_sha((case/'registration.json').read_bytes()),
            'resolution_sha256':_sha((case/'trial-resolution.json').read_bytes()),'closed':closed}


def verify_active_auxiliaries(case,binding,record):
    """Bind only the existing one resume and one pause path to their saved claims."""
    import uuid
    report=record['original_report'];resume=report.get('resume',{});response=resume.get('response')
    reserved=_load(case/'active-resume-reservation.json');dispatch=_load(case/'active-resume-dispatch.json')
    rid=uuid.uuid5(uuid.UUID(binding.resident_session),binding.request_id+':resume').hex
    command={'op':'direct','endpoint':'raw-key','body':{'key':'key.keyboard.escape','action':'click'}}
    _require(resume.get('request_id')==reserved.get('request_id')==dispatch.get('request_id')==rid
        and resume.get('command')==reserved.get('command')==dispatch.get('command')==command
        and reserved.get('only_from_verified_native_pause') is True
        and _ref(reserved.get('authorization_ref')) and dispatch.get('automatic_retry') is False,
        'rollover_old_resume_binding_mismatch')
    _require(type(response) is dict and response.get('request_id')==rid
        and response.get('session_id')==binding.resident_session and response.get('status')=='succeeded'
        and not _uncertain(response) and response.get('reason')=='direct_input_dispatched'
        and response.get('result',{}).get('ok') is True
        and response['result'].get('key')=='key.keyboard.escape'
        and response['result'].get('action')=='click' and response['result'].get('down') is False,
        'rollover_old_resume_unknown_or_unbound')
    pause=report.get('pause',{});reserved=_load(case/'active-pause-reservation.json')
    pid=uuid.uuid5(uuid.UUID(binding.resident_session),binding.request_id+':pause').hex
    body={'pause_schema_version':1,'expected_action_session':binding.action_session,
          'expected_world_generation':binding.world_generation,'expected_player_uuid':binding.player_uuid,
          'expected_action_id':binding.expected_action_id}
    command={'op':'encounter_pause','expected_resident_session':binding.resident_session,'body':body}
    _require(pause.get('request_id')==reserved.get('request_id')==pid
        and pause.get('command')==reserved.get('command')==command
        and reserved.get('owner_request_id')==binding.request_id and _ref(reserved.get('authorization_ref'))
        and pause.get('native_pause_observed') is True and pause.get('native_release_observed') is True
        and not pause.get('error') and not pause.get('effect_error'), 'rollover_old_pause_unknown_or_unbound')
    native=record['resolved_outcome']['native_action']
    if pause.get('source')=='native_terminal_hook':
        _require(pause.get('native_hook',{}).get('outcome')=='screen_installed'
            and pause.get('native_hook')==native['result'].get('encounter_terminal_pause')
            and pause.get('fallback_skipped_prior_native_attempt') is True
            and not (case/'active-pause-dispatch.json').exists(),'rollover_old_native_pause_mismatch')
    else:
        dispatch=_load(case/'active-pause-dispatch.json');response=pause.get('response')
        _require(dispatch.get('request_id')==pid and dispatch.get('command')==command
            and dispatch.get('automatic_retry') is False and type(response) is dict
            and response.get('request_id')==pid and response.get('session_id')==binding.resident_session
            and response.get('status')=='succeeded' and not _uncertain(response),'rollover_old_pause_unknown_or_unbound')
        from resident_controller.pause_contract import validate_pause_receipt
        from receipt_binding import terminal_signature
        value=validate_pause_receipt(response.get('result'),body,binding.encounter_request)
        _require(value.get('expected_action_present') is True
            and terminal_signature(value['client_action'])==terminal_signature(native),
            'rollover_old_pause_original_terminal_mismatch')


def _session_valid(value,new):
    _require(type(value) is dict and value.get('session_id')==new['resident_session']
        and value.get('bridge_identity',{}).get('action_session')==new['action_session']
        and value.get('state')=='ready' and 'reason' in value and value['reason'] is None
        and value.get('active_request_id') is None and 'active_request_id' in value
        and value.get('active_action_id') is None and 'active_action_id' in value
        and type(value.get('pending')) is int and value['pending']==0
        and value.get('pending_request_ids',[])==[], 'rollover_current_session_not_idle')
    PostTrialSafety._automation_idle(value)


def _validate_observed(safety,new,observation,previous_observation,cases):
    current=verifier(safety,new);current._validate_observation(observation)
    _require(current._paused(observation),'rollover_requires_actual_native_pause')
    _require(_finite(observation['state']['player'].get('health'))
        and observation['state']['player']['health']>0,'rollover_current_player_not_living')
    old_dimension=previous_observation.get('state',{}).get('world',{}).get('dimension')
    _require(isinstance(old_dimension,str) and old_dimension
        and observation['state']['world'].get('dimension')==old_dimension,'rollover_dimension_changed')
    old_uuids={e['uuid'] for case in cases for e in _load(case/'registration.json')['entities']}
    for e in observation['state']['nearby']['entities']:
        _require(e['uuid'] not in old_uuids or current._operator_dead(e),'rollover_old_target_still_living')
        _require(e['type']!='minecraft:zombie' or current._operator_dead(e),'rollover_unregistered_living_zombie')


def read_chain(safety):
    """Read under the ledger lock for authority; never cache the mutable head."""
    initial=identity(_load(safety.root/'context.json'));cases=safety._cases()
    records=sorted(safety.root.glob('session-*.rollover.json'))
    entries=list(safety.root.glob('session-*.rollover*'))
    anchors=sorted(safety.root.parent.glob(safety.root.name+'.session-*.anchor.json'))
    anchor_entries=list(safety.root.parent.glob(safety.root.name+'.session-*.anchor*'))
    _require(len(entries)==2*len(records) and len(anchor_entries)==2*len(anchors)
        and len(records)==len(anchors),'rollover_record_or_sibling_anchor_missing')
    current=initial;head=None;previous_count=0;seen={tuple(initial[k] for k in KEYS)}
    boundaries=[]
    for index,(path,anchor_path) in enumerate(zip(records,anchors),1):
        _require(path.name=='session-%06d.rollover.json'%index
            and anchor_path.name==safety.root.name+'.session-%06d.anchor.json'%index,'rollover_sequence_gap')
        value=_load(path);anchor=_load(anchor_path);count=value.get('through_case_ordinal');new=identity(value.get('to_identity'))
        _require(value.get('schema_version')==1 and value.get('ordinal')==index
            and value.get('ledger_directory')==str(safety.root)
            and value.get('root_context_sha256')==_sha((safety.root/'context.json').read_bytes())
            and value.get('from_identity')==current and value.get('previous_rollover_sha256')==head
            and type(count) is int and previous_count<=count<=len(cases) and count>0,
            'rollover_chain_or_boundary_invalid')
        _require(new['player_uuid']==initial['player_uuid'] and tuple(new[k] for k in KEYS) not in seen,
                 'rollover_identity_reused_or_player_changed')
        _require(_ref(value.get('authorization_ref')) and _ref(value.get('same_save_evidence_ref'))
            and value.get('same_save_proof_source')=='independent_operator_evidence_not_native_save_id'
            and value.get('ordinary_mutation_permission') is False and value.get('new_case_authorized') is False
            and value.get('automatic_retry') is False and all(value.get(k) is False for k in NO_SUCCESS),'rollover_claim_invalid')
        tail=safety.root/('ledger-case-%06d.anchor.json'%count)
        _require(value.get('last_case_anchor_sha256')==_sha(tail.read_bytes()),'rollover_old_tail_changed')
        _require(value.get('closed_cases')==[closed_case(safety,c) for c in cases[:count]],
                 'rollover_closed_prefix_changed')
        for c in cases[previous_count:count]:
            reg=_load(c/'registration.json')
            _require(case_identity(safety,c)==current and reg.get('session_rollover_sha256')==head,
                     'rollover_case_session_mismatch')
        before=value.get('session_before');after=value.get('session_after')
        _session_valid(before,new);_session_valid(after,new)
        empty={'queue_directory':str(safety.root.parent),'inbox':[],'working':[]}
        _require(value.get('queue_before')==empty and value.get('queue_after')==empty,'rollover_saved_queue_not_empty')
        verify_saved_queue_audit(safety,value.get('durable_queue_before'));verify_saved_queue_audit(safety,value.get('durable_queue_after'))
        _validate_observed(safety,new,value.get('observation'),
            _load(cases[count-1]/'trial-resolution.json')['original_report']['after'],cases[:count])
        digest=_sha(path.read_bytes())
        _require(anchor=={'schema_version':1,'ordinal':index,'ledger_directory':str(safety.root),
            'rollover_sha256':digest,'previous_rollover_sha256':head},'rollover_sibling_anchor_mismatch')
        boundaries.append((count,digest,new));current=new;head=digest;previous_count=count
        seen.add(tuple(new[k] for k in KEYS))
    for c in cases[previous_count:]:
        reg=_load(c/'registration.json')
        _require(case_identity(safety,c)==current and reg.get('session_rollover_sha256')==head,
                 'rollover_case_session_mismatch')
    return {'identity':current,'sha256':head,'ordinal':len(records),'through_case_ordinal':previous_count,
            'records':[_load(p) for p in records]}


def authorization_refs(safety):
    refs=set()
    for case in safety._cases():
        registration=_load(case/'registration.json')
        refs.update(registration.get(k) for k in ('authorization_ref','previous_case_authorization_ref','pause_authorization_ref'))
        p=case/'operator-closeout.json'
        if p.exists():refs.add(_load(p).get('authorization_ref'))
    for path in safety.root.glob('session-*.rollover.json'):refs.add(_load(path).get('authorization_ref'))
    return refs


def request_consumed(safety,request_id):
    def found(value):
        if type(value) is dict:
            return value.get('request_id')==request_id or any(found(v) for v in value.values())
        return type(value) is list and any(found(v) for v in value)
    if any(found(_load(p)) for c in safety._cases() for p in c.glob('*.json')):
        return True
    if any(found(_load(p)) for p in safety.root.glob('session-*.rollover.json')):
        return True
    # Only this named, schema-validated store is added; never search arbitrary paths.
    guard=safety.root.parent/'boat-entry-guard'
    if guard.exists() or guard.is_symlink():
        from boat_entry_guard import validate_store
        stored=validate_store(safety.root.parent)
        if request_id in stored['consumed_request_ids']:
            return True
    # A retained result or non-expiring G1 claim is also a consumed request ID.
    names={request_id+'.json',request_id+'.intent.json',request_id+'.result.json'}
    return any(p.name in names for name in ('results','gate-off-probes','gate-off-case-evidence')
               for p in (safety.root.parent/name).glob('*.json'))


def rollover(safety,*,authorization_ref,same_save_evidence_ref):
    _require(_ref(authorization_ref) and _ref(same_save_evidence_ref),'rollover_authorization_or_same_save_evidence_missing')
    with safety._locked(rollover=True):
        chain=read_chain(safety);cases=safety._cases();new=identity(safety.identity)
        _require(cases and chain['identity']!=new,'rollover_requires_changed_closed_session')
        prior_identities=[_load(safety.root/'context.json')]+[r['to_identity'] for r in chain['records']]
        _require(new not in prior_identities,'rollover_identity_reused_or_player_changed')
        _require(new['player_uuid']==chain['identity']['player_uuid'],'rollover_player_changed')
        _require(authorization_ref not in authorization_refs(safety),'rollover_requires_new_authorization')
        closed=[closed_case(safety,c) for c in cases]
        empty_before=queue_empty(safety)
        durable_before=durable_queue_audit(safety)
        before=safety._session();_session_valid(before,new)
        observation=safety._observe(safety.root,'session-rollover-check')
        after=safety._session();_session_valid(after,new)
        empty_after=queue_empty(safety)
        durable_after=durable_queue_audit(safety)
        _validate_observed(safety,new,observation,
            _load(cases[-1]/'trial-resolution.json')['original_report']['after'],cases)
        ordinal=chain['ordinal']+1;path=safety.root/('session-%06d.rollover.json'%ordinal)
        anchor=safety.root.with_name(safety.root.name+'.session-%06d.anchor.json'%ordinal)
        record={'schema_version':1,'ordinal':ordinal,'ledger_directory':str(safety.root),
            'root_context_sha256':_sha((safety.root/'context.json').read_bytes()),
            'from_identity':chain['identity'],'to_identity':new,'previous_rollover_sha256':chain['sha256'],
            'through_case_ordinal':len(cases),'last_case_anchor_sha256':_sha((safety.root/('ledger-case-%06d.anchor.json'%len(cases))).read_bytes()),
            'closed_cases':closed,'authorization_ref':authorization_ref,'same_save_evidence_ref':same_save_evidence_ref,
            'same_save_proof_source':'independent_operator_evidence_not_native_save_id',
            'session_before':before,'session_after':after,'observation':observation,
            'queue_before':empty_before,'queue_after':empty_after,
            'durable_queue_before':durable_before,'durable_queue_after':durable_after,
            'ordinary_mutation_permission':False,'new_case_authorized':False,'automatic_retry':False,**NO_SUCCESS}
        # Anchor first: any interruption leaves a detectable partial transition,
        # never permission to reset or reuse an old session.
        raw=(_json(record)+'\n').encode();digest=_sha(raw)
        _write(anchor,{'schema_version':1,'ordinal':ordinal,'ledger_directory':str(safety.root),
            'rollover_sha256':digest,'previous_rollover_sha256':chain['sha256']})
        _write(path,record)
        _require(read_chain(safety)['identity']==new,'rollover_final_verification_failed')
        return deepcopy(record)


def queue_empty(safety):
    directory=getattr(safety.o.c,'root',None)
    _require(directory is not None,'rollover_fixed_queue_path_required')
    directory=Path(directory)
    _require(directory.is_dir() and directory.resolve()==directory.absolute()
        and directory.resolve()==safety.root.parent,'rollover_wrong_or_aliased_queue')
    for name in ('inbox','working'):
        folder=directory/name
        _require(folder.is_dir() and not folder.is_symlink() and not list(folder.iterdir()),
                 'rollover_mailbox_not_empty')
    return {'queue_directory':str(directory.resolve()),'inbox':[],'working':[]}


def authorize_successor(safety,previous,authorization_ref,next_entities,*,active_ai):
    chain=read_chain(safety)
    _require(chain['identity']==safety.identity and chain['sha256'] is not None
        and int(previous.name.removeprefix('case-'))<=chain['through_case_ordinal'],
        'rollover_previous_case_not_in_closed_prefix')
    _require(_ref(authorization_ref) and authorization_ref not in authorization_refs(safety),
             'next_case_requires_new_explicit_authorization')
    closed=closed_case(safety,previous)
    observation=safety._observe(safety.root,'next-session-case-check')
    _require(safety._paused(observation),'next_case_requires_fresh_previous_pause')
    old_uuids={e['uuid'] for c in safety._cases() for e in _load(c/'registration.json')['entities']}
    for entity in observation['state']['nearby']['entities']:
        _require(entity['uuid'] not in old_uuids or safety._operator_dead(entity),'previous_case_has_residual_entity')
        _require(entity['type']!='minecraft:zombie' or safety._operator_dead(entity)
            or _identity(entity) in [_identity(e) for e in next_entities],
            'unregistered_living_zombie_blocks_next_case')
    # Separate from old case records. This observation is bound to the new session.
    import uuid
    _write(safety.root/('next-session-case-authorization-'+uuid.uuid4().hex+'.json'),
        {'authorization_ref':authorization_ref,'session_rollover_sha256':chain['sha256'],
         'previous_closed_case':closed,'fresh_observation':observation,
         'scope':'one_new_independent_registered_active_case' if active_ai else 'one_new_independent_registered_noai_case',
         'ordinary_mutation_permission':False,**NO_SUCCESS})


def durable_queue_audit(safety):
    """Check retained queue outcomes and the two existing durable G1 claim stores.

    This is not a reconstruction of expired arbitrary mailbox history. Registered
    cases remain covered by their complete ledger; G1 claims do not expire.
    """
    import json
    directory=safety.root.parent
    def read(path):
        _require(path.is_file() and not path.is_symlink() and path.stat().st_size<=2*1024*1024,
                 'rollover_queue_record_invalid')
        try:value=json.loads(path.read_bytes(),parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except (ValueError,UnicodeError) as exc:raise SafetyHalt('rollover_queue_record_invalid') from exc
        _require(type(value) is dict,'rollover_queue_record_invalid')
        return value
    results=directory/'results'
    _require(results.is_dir() and not results.is_symlink(),'rollover_results_directory_missing')
    summaries=[]
    for path in sorted(results.iterdir()):
        _require(re.fullmatch(r'[A-Za-z0-9_-]{1,80}\.json',path.name) is not None,
                 'rollover_partial_queue_result')
        value=read(path)
        _require(value.get('request_id')==path.stem and isinstance(value.get('session_id'),str)
            and value.get('status') in ('succeeded','failed','cancelled') and not _uncertain(value),
            'rollover_durable_queue_outcome_unknown')
        summaries.append({'file':path.name,'sha256':_sha(path.read_bytes()),
            'request_id':value['request_id'],'session_id':value['session_id'],'status':value['status'],
            'reason':value.get('reason'),'uncertain':False})
    stores={};gate_files={}
    for name in ('gate-off-probes','gate-off-case-evidence'):
        folder=directory/name;entries={}
        if folder.exists():
            _require(folder.is_dir() and not folder.is_symlink(),'rollover_gate_claim_directory_invalid')
            for path in sorted(folder.iterdir()):
                match=re.fullmatch(r'([A-Za-z0-9_-]{1,80})\.(intent|result)\.json',path.name)
                _require(match is not None,'rollover_gate_claim_partial')
                entries.setdefault(match[1],{})[match[2]]=read(path)
                gate_files[name+'/'+path.name]=_sha(path.read_bytes())
        _require(all(set(pair)=={'intent','result'} for pair in entries.values()),'rollover_gate_claim_unfinished')
        stores[name]=entries
    from gate_probe_contract import ownership, probe_body
    from encounter_contract import MODE, validate_encounter_request
    probes=stores['gate-off-probes'];outer=stores['gate-off-case-evidence']
    _require(set(outer)<=set(probes),'rollover_gate_native_claim_missing')
    for rid,pair in probes.items():
        intent,result=pair['intent'],pair['result']
        _require(intent.get('request_id')==result.get('request_id')==rid
            and all(result.get(k)==v for k,v in intent.items())
            and result.get('post_attempted') is True and result.get('probe_passed') is True
            and result.get('expected_rejection') is True and result.get('http_status')==409
            and result.get('native_error')=='encounter_stage1_disabled'
            and result.get('transport_uncertain') is False
            and result.get('automatic_retry') is False
            and result.get('ownership_and_inputs_unchanged') is True
            and result.get('stop_reason')=='gate_probe_expected_rejection',
            'rollover_gate_probe_unknown_or_not_passed')
        try:
            valid=(validate_encounter_request(result.get('body')) is not None
                and result['body']['encounter_mode']==MODE
                and ownership(result.get('before'))==ownership(result.get('after')))
        except (ValueError,KeyError,TypeError) as exc:
            raise SafetyHalt('rollover_gate_probe_binding_invalid') from exc
        _require(valid,'rollover_gate_probe_binding_invalid')
        if rid in outer:
            original,completed=outer[rid]['intent'],outer[rid]['result']
            stable=('request_id','command','authorization_ref','targets_are_unspawned_test_identifiers','fixture_registration','automatic_retry')
            receipt=completed.get('result');command=original.get('command',{})
            _require(type(command) is dict,'rollover_gate_outer_claim_unknown_or_unbound')
            _require(original.get('request_id')==rid and all(completed.get(k)==original.get(k) for k in stable)
                and _ref(original.get('authorization_ref')) and completed.get('submitted') is True
                and completed.get('probe_passed') is True and type(receipt) is dict
                and receipt.get('request_id')==rid and receipt.get('session_id')==command.get('expected_resident_session')
                and receipt.get('status')=='succeeded' and not _uncertain(receipt) and receipt.get('result')==result,
                'rollover_gate_outer_claim_unknown_or_unbound')
            try:expected=probe_body(dict(command,request_id=rid),command['expected_resident_session'])
            except (ValueError,KeyError,TypeError) as exc:
                raise SafetyHalt('rollover_gate_expected_body_mismatch') from exc
            _require(expected==result['body'],'rollover_gate_expected_body_mismatch')
    # The guard author owns the one pure validator used by both entry and rollover.
    # A completed guard is only pre-action evidence, never a boat-action terminal.
    guard=directory/'boat-entry-guard'
    if guard.exists() or guard.is_symlink():
        from boat_entry_guard import validate_store
        gate_files.update(validate_store(directory)['files'])
    return {'scope':'retained_queue_results_and_existing_durable_gate_claims',
            'known_results':summaries,'durable_gate_files':gate_files,'unresolved':False}


def verify_saved_queue_audit(safety,audit):
    _require(type(audit) is dict and audit.get('scope')=='retained_queue_results_and_existing_durable_gate_claims'
        and audit.get('unresolved') is False and type(audit.get('known_results')) is list
        and type(audit.get('durable_gate_files')) is dict,'rollover_saved_queue_audit_invalid')
    for value in audit['known_results']:
        _require(type(value) is dict and value.get('status') in ('succeeded','failed','cancelled')
            and not _uncertain(value) and value.get('uncertain') is False,'rollover_saved_queue_audit_unknown')
    # Ordinary results can expire normally. G1 and boat-entry claims remain exact.
    for relative,digest in audit['durable_gate_files'].items():
        _require(isinstance(relative,str) and re.fullmatch(r'(?:(gate-off-probes|gate-off-case-evidence)/[A-Za-z0-9_-]{1,80}\.(intent|result)\.json|boat-entry-guard/[A-Za-z0-9_-]{1,80}\.(reservation|result)\.json(?:\.sha256)?)',relative),
                 'rollover_saved_gate_path_invalid')
        path=safety.root.parent/relative
        _require(path.is_file() and not path.is_symlink() and not path.parent.is_symlink() and _sha(path.read_bytes())==digest,
                 'rollover_saved_gate_claim_changed_or_missing')

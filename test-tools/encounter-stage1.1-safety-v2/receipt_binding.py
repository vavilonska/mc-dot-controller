"""Pure, fail-closed single-step resident receipt attribution. No I/O or queue calls."""
from dataclasses import dataclass
from copy import deepcopy
import uuid
import json

TERMINAL = frozenset(('succeeded', 'failed', 'cancelled'))
CONTRACT = 'resident_uuid5_single_step_v1'

@dataclass(frozen=True)
class Binding:
    request_id: str
    resident_session: str
    action_session: str
    world_generation: str
    player_uuid: str
    action_kind: str
    contract: str = CONTRACT

    def __post_init__(self):
        if self.contract != CONTRACT or not isinstance(self.request_id, str) or not self.request_id:
            raise ValueError('unsupported_or_invalid_action_id_contract')
        for value in (self.resident_session, self.action_session, self.world_generation, self.player_uuid):
            uuid.UUID(value)
        if self.action_kind not in ('combat_entity','boat_drive','follow_path','break_block','place_block','click_slot'):
            raise ValueError('unsupported_action_kind')

    @property
    def expected_action_id(self):
        # This is a planned ID, NOT proof of admission. Only op:action step 1 is supported.
        return uuid.uuid5(uuid.UUID(self.resident_session), self.request_id + ':1').hex

    def wire(self):
        return {**vars(self), 'expected_action_id': self.expected_action_id}

    def observation_context_problem(self, observation):
        if not isinstance(observation, dict):
            return 'observation_missing'
        state = observation.get('state')
        if not isinstance(state, dict):
            return 'observation_state_missing'
        if state.get('world',{}).get('world_generation') != self.world_generation:
            return 'observation_world_mismatch'
        if state.get('player',{}).get('uuid') != self.player_uuid:
            return 'observation_player_mismatch'
        if state.get('client_action',{}).get('action_session') != self.action_session:
            return 'observation_action_session_mismatch'
        for name in ('action',):
            obj = observation.get(name)
            if isinstance(obj,dict) and obj.get('action_session') != self.action_session:
                return 'observation_action_session_mismatch'
        return None

    def native_problem(self, action):
        if not isinstance(action,dict): return 'native_action_missing'
        if type(action.get('action_schema_version')) is not int or action.get('action_schema_version') != 1: return 'native_schema_mismatch'
        if action.get('action_id') != self.expected_action_id: return 'native_action_id_mismatch'
        if action.get('action_session') != self.action_session: return 'native_action_session_mismatch'
        if action.get('action') != self.action_kind: return 'native_action_kind_mismatch'
        payload = action.get('result')
        if not isinstance(payload,dict) or payload.get('world_generation') != self.world_generation:
            return 'native_world_mismatch'
        if action.get('status') not in TERMINAL | {'running'}: return 'native_status_invalid'
        ticks = action.get('ticks')
        if type(ticks) is not int or ticks < 0: return 'native_ticks_invalid'
        return None

    def classify_observation(self, observation):
        problem = self.observation_context_problem(observation)
        if problem: return {'relation':'context_mismatch','reason':problem,'action':None}
        action = observation.get('action')
        if not isinstance(action,dict) or action.get('action_id') != self.expected_action_id:
            return {'relation':'unrelated_retained_action','reason':'not_the_requested_native_action','action':None}
        problem = self.native_problem(action)
        if problem: return {'relation':'identity_mismatch','reason':problem,'action':None}
        return {'relation':'bound','reason':None,'action':deepcopy(action)}


def terminal_signature(action):
    # Native terminal payloads are immutable. Query transport decorations and global input_owner
    # may differ, but every identity/status/tick/result field must agree exactly.
    core={k:action.get(k) for k in ('action_schema_version','action_id','action_session','action','status','reason','ticks','result')}
    return json.dumps(core,sort_keys=True,separators=(',',':'),allow_nan=False)


def _out(kind, reason, receipt, *, action=None, source=None, admission=None, abort=False):
    return {'kind':kind, 'reason':reason, 'request_status':receipt.get('status') if isinstance(receipt,dict) else None,
            'native_admission_confirmed':admission, 'native_action':deepcopy(action),
            'native_action_source':source, 'needs_reconciliation':abort,
            'task_success':bool(kind == 'bound_terminal' and receipt.get('status') == 'succeeded'
                                and action and action.get('status') == 'succeeded')}


def _uncertain(receipt):
    if receipt.get('status') == 'uncertain': return True
    if any(receipt.get(k) is True for k in ('uncertain','post_uncertain','unknown_outcome')): return True
    reason = str(receipt.get('reason','')).lower()
    return any(t in reason for t in ('unknown_post','unknown_outcome','uncertain_post','post_timeout','transport_timeout'))


def receipt_envelope_problem(binding, receipt):
    if not isinstance(receipt,dict): return 'receipt_missing_or_malformed'
    if receipt.get('request_id') != binding.request_id: return 'receipt_request_id_mismatch'
    # QueueClient's local pending timeout object has no session field; it is not a server receipt.
    if (receipt.get('status') != 'pending' or 'session_id' in receipt) and receipt.get('session_id') != binding.resident_session:
        return 'receipt_resident_session_mismatch'
    if receipt.get('status') not in ('succeeded','failed','cancelled','uncertain','pending'):
        return 'receipt_status_invalid'
    return None


def resolve(binding, receipt, *, before=None, after=None, running_evidence=(), interrupt_proof=None):
    """Attribute exactly one op:action. Unknown outcomes never borrow a terminal observation."""
    problem = receipt_envelope_problem(binding,receipt)
    if problem: return _out('identity_mismatch',problem,receipt,abort=True)
    if receipt['status'] == 'pending':
        return _out('observer_wait_timeout','wait_timeout_is_not_action_failure_or_completion',receipt,abort=True)
    if _uncertain(receipt):
        return _out('unknown_post_outcome',receipt.get('reason','uncertain_receipt'),receipt,abort=True)
    if before is not None:
        problem = binding.observation_context_problem(before)
        if problem: return _out('identity_mismatch',problem,receipt,abort=True)
        if before.get('action',{}).get('action_id') == binding.expected_action_id:
            return _out('identity_mismatch','preexisting_expected_action_id_no_replay',receipt,abort=True)
    if after is not None:
        problem = binding.observation_context_problem(after)
        if problem: return _out('identity_mismatch',problem,receipt,abort=True)
    # Native identity supplied by the resident must agree; null is not a new native ID.
    explicit_id = receipt.get('action_id')
    if explicit_id is not None and explicit_id != binding.expected_action_id:
        return _out('identity_mismatch','receipt_native_action_id_mismatch',receipt,abort=True)
    candidates=[]
    nested=receipt.get('result')
    if isinstance(nested,dict) and nested.get('action') is not None:
        candidates.append(('result.action',nested['action']))
    for key in ('action','resolved_action'):
        if receipt.get(key) is not None: candidates.append((key,receipt[key]))
    cancel=receipt.get('cancellation')
    if isinstance(cancel,dict) and ('action_id' in cancel or 'action_schema_version' in cancel):
        candidates.append(('cancellation',cancel))
    for source, action in candidates:
        problem=binding.native_problem(action)
        if problem: return _out('identity_mismatch',source+':'+problem,receipt,abort=True)
    if 'action_id' in receipt and explicit_id is None and candidates:
        return _out('receipt_conflict','explicit_null_action_id_conflicts_with_native_evidence',receipt,abort=True)
    # A complete failed pre/admission response expressly contains no action.
    if receipt['status']=='failed' and 'action_id' in receipt and explicit_id is None and not candidates:
        if any(isinstance(a,dict) and a.get('action_id')==binding.expected_action_id for a in running_evidence):
            return _out('receipt_conflict','null_rejection_conflicts_with_prior_same_id_running_evidence',receipt,abort=True)
        if (receipt.get('task_completed') is False and receipt.get('action_step')==1
            and receipt.get('postcondition_observed') is False and receipt.get('reason')
            and receipt.get('original_error')==receipt.get('reason')
            and receipt.get('action') is None and receipt.get('resolved_action') is None
            and receipt.get('cancellation') is None):
            relation=binding.classify_observation(after) if after is not None else None
            if relation and relation['relation'] in ('bound','identity_mismatch'):
                return _out('receipt_conflict','rejection_conflicts_with_same_request_native_action',receipt,abort=True)
            return _out('admission_rejected',receipt['reason'],receipt,admission=False)
        return _out('unattributed_request_failure','incomplete_null_action_rejection_receipt',receipt,abort=True)
    terminal=[(s,a) for s,a in candidates if a['status'] in TERMINAL]
    if terminal:
        try: signatures={terminal_signature(a) for _,a in terminal}
        except (TypeError,ValueError): return _out('receipt_conflict','invalid_native_terminal_payload',receipt,abort=True)
        if len(signatures)>1:
            return _out('receipt_conflict','conflicting_same_id_terminal_records',receipt,abort=True)
        source, action=terminal[-1]
        if after is None:
            return _out('postcondition_unverified','no_final_observation',receipt,action=action,source=source,admission=True,abort=True)
        relation=binding.classify_observation(after)
        if relation['relation']!='bound':
            return _out('identity_mismatch','final_observation_not_bound_to_request',receipt,abort=True)
        last=relation['action']
        try: consistent=last['status'] in TERMINAL and terminal_signature(last)==terminal_signature(action)
        except (TypeError,ValueError): consistent=False
        if not consistent:
            return _out('receipt_conflict','final_observation_contradicts_terminal_receipt',receipt,abort=True)
        if receipt['status']!=action['status']:
            return _out('request_native_status_conflict','task_status_differs_from_native_terminal',receipt,
                        action=action,source=source,admission=True,abort=True)
        return _out('bound_terminal',action.get('reason'),receipt,action=action,source=source,admission=True)
    # Explicit cancel/direct takeover can finish the resident request before native status is returned.
    if receipt['status']=='cancelled' and receipt.get('reason') in ('cancel_requested','direct_takeover'):
        relation=binding.classify_observation(after) if after is not None else None
        running = any(binding.native_problem(a) is None and a['status']=='running' for a in running_evidence)
        proof = interrupt_proof if isinstance(interrupt_proof,dict) else {}
        proof_response = proof.get('response') if isinstance(proof.get('response'),dict) else {}
        desired_kind = 'cancel' if receipt.get('reason')=='cancel_requested' else 'direct'
        proof_ok = (proof.get('kind')==desired_kind and proof.get('request_id')
                    and proof['request_id']!=binding.request_id
                    and proof_response.get('request_id')==proof['request_id']
                    and proof_response.get('session_id')==binding.resident_session
                    and proof_response.get('status')=='succeeded')
        if proof_ok:
            proof_ok = (proof_response.get('result',{}).get('released') is True if desired_kind=='cancel'
                        else proof_response.get('reason')=='direct_input_dispatched'
                             and proof_response.get('result',{}).get('ok') is True)
        if running and proof_ok and relation and relation['relation']=='bound' and relation['action']['status']=='cancelled':
            action=relation['action']
            required={'cancel_requested':{'inputs_released','cancel_requested'},'direct_takeover':{'direct_takeover'}}
            if action.get('reason') in required[receipt['reason']]:
                return _out('bound_terminal',action['reason'],receipt,action=action,
                            source='same_request_final_observation_after_explicit_interrupt',admission=True)
        return _out('unattributed_interrupt','cancelled_request_without_bound_native_cancellation',receipt,abort=True)
    if candidates:
        return _out('nonterminal_receipt','request_ended_without_native_terminal',receipt,abort=True)
    if receipt['status']=='failed' and receipt.get('reason') in ('action_world_changed','action_session_changed'):
        relation=binding.classify_observation(after) if after is not None else None
        prior=any(isinstance(a,dict) and a.get('action_id')==binding.expected_action_id for a in running_evidence)
        if prior or relation and relation['relation'] in ('bound','identity_mismatch'):
            return _out('receipt_conflict','binding_rejection_conflicts_with_same_request_native_evidence',receipt,abort=True)
        return _out('pre_admission_binding_rejected',receipt['reason'],receipt,admission=False)
    return _out('unattributed_request_failure','no_bound_native_terminal_in_receipt',receipt,abort=True)


def release_observed(binding, observation):
    if binding.observation_context_problem(observation): return False
    status=observation.get('status',{});player=observation['state']['player'];action=observation.get('action',{})
    return (status.get('held_mappings')==[] and action.get('status') in TERMINAL | {'idle'}
            and player.get('using_item') is False and player.get('sprinting') is False
            and status.get('mouse',{}).get('held_world_buttons')==[])


def summarize(binding, outcome, after=None):
    """Counters are absent unless the terminal is bound and request outcome is definite."""
    action=outcome.get('native_action') if outcome['kind']=='bound_terminal' else None
    combat=(action or {}).get('result',{}).get('combat',{})
    released = release_observed(binding,after) if after is not None else None
    return {'binding':binding.wire(),'outcome_kind':outcome['kind'],'request_status':outcome['request_status'],
            'reason':outcome['reason'],'action_id':action.get('action_id') if action else None,
            'native_admission_confirmed':outcome['native_admission_confirmed'],
            'native_status':action.get('status') if action else None,'ticks':action.get('ticks') if action else None,
            'attack_dispatches':combat.get('attack_dispatches') if action else None,
            'target_dead_observed':combat.get('target_dead_observed') if action else None,
            'native_health_lost_observed':combat.get('player_health_lost_observed') if action else None,
            'release_observed':released,
            'request_reported_task_success':outcome['task_success'],
            'task_success':outcome['task_success'] and released is True,
            'needs_reconciliation':outcome['needs_reconciliation'] or released is not True,
            'read_timing':'Outer state/action reads are separate, never assumed same tick.'}

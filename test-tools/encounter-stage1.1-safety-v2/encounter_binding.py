"""Strict opt-in layer over unchanged legacy attribution; no I/O or live calls."""
from copy import deepcopy
from dataclasses import dataclass, field
import json
from encounter_contract import validate_encounter_request, validate_encounter_receipt, OUTCOME_SCOPE
from receipt_binding import Binding, CONTRACT, resolve as legacy_resolve, summarize as legacy_summarize, _out, _uncertain


@dataclass(frozen=True, init=False)
class EncounterBinding(Binding):
    _request_json: str = field(init=False, repr=False)

    def __init__(self, request_id, resident_session, action_session, world_generation,
                 player_uuid, action_kind, contract=CONTRACT, *, encounter_request):
        super().__init__(request_id, resident_session, action_session, world_generation,
                         player_uuid, action_kind, contract)
        request = validate_encounter_request(encounter_request or {})
        if request is None:
            raise ValueError('encounter_request_required')
        if (request['action'] != self.action_kind
                or request['expected_action_session'] != self.action_session
                or request['expected_world_generation'] != self.world_generation
                or request['expected_player_uuid'] != self.player_uuid):
            raise ValueError('encounter_request_binding_mismatch')
        object.__setattr__(self, '_request_json', json.dumps(request, sort_keys=True, allow_nan=False))

    @property
    def encounter_request(self):
        # Return a copy on every read: even direct nested-property mutation cannot
        # rebind the original scope after admission or change later validation.
        return json.loads(self._request_json)

    def wire(self):
        result = super().wire()
        result.pop('_request_json', None)
        result['encounter_request'] = self.encounter_request
        return deepcopy(result)

    def native_problem(self, action):
        problem = super().native_problem(action)
        if problem:
            return problem
        try:
            validate_encounter_receipt(action, self.encounter_request)
        except (ValueError, KeyError, TypeError) as exc:
            return 'encounter_contract:' + str(exc)
        return None


def build_binding(request_id, resident_session, action_session, world_generation,
                  player_uuid, body, timeout):
    request = validate_encounter_request(dict(body, timeout_ms=timeout,
                  expected_action_session=action_session, expected_world_generation=world_generation,
                  expected_player_uuid=player_uuid))
    args = (request_id, resident_session, action_session, world_generation, player_uuid, body.get('action'))
    return Binding(*args) if request is None else EncounterBinding(*args, encounter_request=request)


def bind_command(binding, command):
    if not isinstance(binding, EncounterBinding):
        return binding
    if command.get('op') != 'action':
        raise ValueError('encounter_requires_action_operation')
    request = {k: deepcopy(v) for k, v in command.items() if k != 'op'}
    navigation = {'expected_navigation_epoch', 'expected_origin'}
    if ({k:v for k,v in request.items() if k not in navigation}
            != {k:v for k,v in binding.encounter_request.items() if k not in navigation}):
        raise ValueError('encounter_command_rebinding_forbidden')
    return EncounterBinding(binding.request_id, binding.resident_session, binding.action_session,
        binding.world_generation, binding.player_uuid, binding.action_kind, binding.contract,
        encounter_request=request)


def resolve(binding, receipt, *, before=None, after=None, running_evidence=(), interrupt_proof=None):
    if not isinstance(binding, EncounterBinding):
        return legacy_resolve(binding, receipt, before=before, after=after,
                              running_evidence=running_evidence, interrupt_proof=interrupt_proof)
    running_evidence = tuple(running_evidence)
    # Examine every supplied native path even for unknown receipts, but preserve
    # unknown/pending classification and never use this diagnostic as admission.
    checks = []
    def inspect(path, action, running=False):
        problem = binding.native_problem(action)
        if not problem and running and action.get('status') != 'running':
            problem = 'encounter_running_evidence_not_running'
        checks.append({'path': path, 'valid': problem is None, 'problem': problem})
    if isinstance(receipt, dict):
        nested = receipt.get('result')
        if isinstance(nested, dict) and nested.get('action') is not None:
            inspect('result.action', nested['action'])
        for key in ('action', 'resolved_action', 'cancellation'):
            if receipt.get(key) is not None:
                inspect(key, receipt[key])
    for index, action in enumerate(running_evidence):
        inspect('running_evidence[' + str(index) + ']', action, running=True)
    for label, observation in (('before', before), ('after', after)):
        action = observation.get('action') if isinstance(observation, dict) else None
        if isinstance(action, dict) and action.get('action_id') == binding.expected_action_id:
            inspect(label + '.action', action)
    known = isinstance(receipt, dict) and receipt.get('status') != 'pending' and not _uncertain(receipt)
    if known and (receipt.get('risk_remaining') is not True
            or receipt.get('requires_handoff') is not True or receipt.get('safety_assured') is not False):
        outcome = _out('identity_mismatch', 'encounter_resident_risk_contract_invalid', receipt, abort=True)
    elif known and any(not x['valid'] for x in checks):
        first = next(x for x in checks if not x['valid'])
        outcome = _out('identity_mismatch', first['path'] + ':' + first['problem'], receipt, abort=True)
    else:
        outcome = legacy_resolve(binding, receipt, before=before, after=after,
                                 running_evidence=running_evidence, interrupt_proof=interrupt_proof)
    outcome['encounter_native_path_validation'] = checks
    outcome['diagnostic_validation_is_not_admission'] = True
    outcome['intervention_present'] = interrupt_proof is not None
    outcome['operator_rescue_guard'] = (isinstance(interrupt_proof, dict)
                                       and interrupt_proof.get('operator_rescue_guard') is True)
    return outcome


def summarize(binding, outcome, after=None):
    summary = legacy_summarize(binding, outcome, after)
    if not isinstance(binding, EncounterBinding):
        return summary
    action = outcome.get('native_action') if outcome['kind'] == 'bound_terminal' else None
    encounter = (action or {}).get('result', {}).get('combat', {}).get('encounter')
    limited = bool(summary['task_success'] and action and action['status'] == 'succeeded'
                   and action.get('reason') == 'encounter_clearance_observed')
    intervention = outcome.get('intervention_present') is True
    rescue = outcome.get('operator_rescue_guard') is True
    summary.update(encounter_mode=binding.encounter_request['encounter_mode'],
        encounter_scope=deepcopy(binding.encounter_request['encounter_scope']),
        bound_encounter=deepcopy(encounter), native_bounded_clearance_reported=limited,
        bounded_clearance_observed=limited and not intervention,
        bounded_outcome_scope=OUTCOME_SCOPE if limited and not intervention else None,
        intervention_present=intervention, operator_rescue_guard=rescue,
        controlled_trial_accepted=False,
        controlled_trial_acceptance='STOPPED-SAFETY' if rescue else 'INTERRUPTED' if intervention else 'NOT_EVALUATED',
        task_success=False, combat_success=False, survival_proven=False,
        risk_remaining=True, requires_handoff=True, safety_assured=False,
        offense_disabled_verified=action is not None,
        native_claim_is_not_live_acceptance=True,
        risk_statement_source='harness_conservative_policy_even_when_native_outcome_unknown')
    return summary

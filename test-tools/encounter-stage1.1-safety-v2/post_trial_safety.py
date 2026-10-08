"""Append-only two-zombie trial ledger and narrow NoAI post-trial capabilities.

No transport is imported or constructed here. All I/O uses the explicitly supplied
operator. Production must choose one queue-scoped ledger, never an output-scoped
ledger. Explicit active cases require paused registration and the separate
pause-first entry; they never inherit NoAI cleanup permission. No live acceptance
or actual case authorization is established by this module.

Native command submission is not evidence of an entity kill. Escape is a toggle,
so an already-paused game is never toggled again. Unknown effects require operator
reconciliation/CUA rescue; they are never retried, unpaused, or promoted to success.
"""
from contextlib import contextmanager
from copy import deepcopy
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
import uuid as uuid_module

from encounter_binding import EncounterBinding, bind_command, resolve
from encounter_contract import UUID
from receipt_binding import Binding, _uncertain, release_observed, terminal_signature

PAUSE_SCREEN = 'net.minecraft.client.gui.screens.PauseScreen'
MAX_OBSERVE_SECONDS = 3.0
NO_SUCCESS = {'controlled_trial_accepted': False, 'live_acceptance_proven': False,
              'combat_success': False, 'task_success': False, 'safety_assured': False}


class SafetyHalt(RuntimeError):
    pass


def _require(condition, reason):
    if not condition:
        raise SafetyHalt(reason)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _ref(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 2048


def _point(value):
    return {key: value[key] for key in ('x', 'y', 'z')}


def _identity(entity):
    return {key: entity[key] for key in ('entity_id', 'uuid', 'type')}


def _write(path, value):
    """Exclusive, fsynced creation; an existing/partial record is never replaced."""
    raw = (_json(value) + '\n').encode()
    with Path(path).open('xb') as handle:
        os.chmod(path, 0o600)
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    with Path(str(path) + '.sha256').open('x') as digest:
        os.chmod(digest.name, 0o600)
        digest.write(_sha(raw) + '\n')
        digest.flush()
        os.fsync(digest.fileno())
    fd = os.open(str(Path(path).parent), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _load(path):
    try:
        path = Path(path)
        _require(path.is_file() and not path.is_symlink(), 'ledger_file_invalid')
        raw = path.read_bytes()
        digest = Path(str(path) + '.sha256')
        _require(digest.is_file() and not digest.is_symlink()
            and digest.read_text().strip() == _sha(raw), 'ledger_record_digest_mismatch')
        return json.loads(raw)
    except SafetyHalt:
        raise
    except Exception as exc:
        raise SafetyHalt('ledger_record_unreadable_no_reset') from exc


def _binding(wire):
    result = EncounterBinding(*(wire[key] for key in ('request_id', 'resident_session',
        'action_session', 'world_generation', 'player_uuid', 'action_kind')),
        contract=wire['contract'], encounter_request=wire['encounter_request'])
    _require(result.wire() == wire, 'ledger_binding_noncanonical')
    return result


class PostTrialSafety:
    def __init__(self, operator, ledger_directory):
        self.o = operator
        # Keep the requested absolute identity. Resolving here would silently
        # redirect both the ledger and its sibling budget anchor through aliases.
        self.root = Path(os.path.abspath(os.fspath(ledger_directory)))
        self.ever_used = self.root.with_name(self.root.name + '.ever-used.json')
        self.identity = {'resident_session': operator.resident, 'action_session': operator.session,
                         'world_generation': operator.world, 'player_uuid': operator.player}

    @contextmanager
    def _locked(self, *, create=False):
        self._verify_ever_used_anchor()
        if not self.root.exists() and not create:
            yield
            return
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / '.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                pin = self.root / 'context.json'
                if not pin.exists():
                    _require(not list(self.root.glob('case-*'))
                        and not list(self.root.glob('ledger-case-*'))
                        and not (self.root / 'CASE-LEDGER-USED.json').exists()
                        and not (self.root / 'CASE-LEDGER-USED.json.sha256').exists(), 'ledger_context_missing')
                    _write(pin, self.identity)
                _require(_load(pin) == self.identity, 'ledger_context_changed_no_reset')
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _verify_ever_used_anchor(self):
        try:
            canonical = self.root.resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise SafetyHalt('ledger_root_alias_or_symlink_forbidden') from exc
        _require(canonical == self.root and not self.root.is_symlink(),
                 'ledger_root_alias_or_symlink_forbidden')
        marker = self.root / 'CASE-LEDGER-USED.json'
        if self.ever_used.exists() or Path(str(self.ever_used) + '.sha256').exists():
            anchor = _load(self.ever_used)
            _require(anchor.get('ledger_directory') == str(self.root)
                and anchor.get('identity') == self.identity, 'ledger_sibling_anchor_identity_mismatch')
            _require(self.root.is_dir() and not self.root.is_symlink() and marker.is_file()
                and _sha(marker.read_bytes()) == anchor.get('root_commitment_sha256'),
                'previously_used_ledger_missing_or_changed_no_reset')
        else:
            _require(not marker.exists() and not Path(str(marker) + '.sha256').exists(),
                     'ledger_sibling_ever_used_anchor_missing')

    def _cases(self):
        """Validate root anchors before allowing an apparently empty ledger.

        Anchors precede directory creation. A crash, lost case, rename, orphan
        sidecar, or missing index therefore blocks rather than resetting budget.
        The root marker is a fixed, hashed first-anchor commitment, not a flag
        that can be switched off to make old cases disappear.
        """
        if not self.root.exists():
            return []
        candidates = list(self.root.glob('case-*'))
        _require(all(re.fullmatch(r'case-[0-9]{6}', p.name) is not None
            and p.is_dir() and not p.is_symlink() for p in candidates), 'ledger_case_name_or_type_invalid')
        cases = sorted(candidates)
        anchor_entries = list(self.root.glob('ledger-case-*'))
        _require(all(re.fullmatch(r'ledger-case-[0-9]{6}\.anchor\.json(?:\.sha256)?', p.name) is not None
            and p.is_file() and not p.is_symlink() for p in anchor_entries), 'ledger_anchor_name_or_type_invalid')
        anchors = sorted(self.root.glob('ledger-case-*.anchor.json'))
        marker = self.root / 'CASE-LEDGER-USED.json'
        used = marker.exists() or Path(str(marker) + '.sha256').exists()
        if not used:
            _require(not cases and not anchor_entries, 'ledger_used_marker_missing')
            return []
        commitment = _load(marker)
        _require(commitment.get('schema_version') == 1 and commitment.get('first_ordinal') == 1
            and commitment.get('context_sha256') == _sha((self.root / 'context.json').read_bytes()),
            'ledger_used_commitment_invalid')
        _require(bool(anchors) and len(anchor_entries) == 2 * len(anchors)
            and len(cases) == len(anchors), 'ledger_case_or_anchor_missing_no_reset')
        previous_sha = None
        for index, (case, anchor) in enumerate(zip(cases, anchors), 1):
            _require(case.name == 'case-%06d' % index
                and anchor.name == 'ledger-case-%06d.anchor.json' % index, 'ledger_case_or_anchor_gap')
            value = _load(anchor)
            _require(value.get('ordinal') == index and value.get('case_directory') == case.name
                and value.get('previous_anchor_sha256') == previous_sha
                and value.get('context_sha256') == commitment['context_sha256'], 'ledger_anchor_chain_mismatch')
            current_sha = _sha(anchor.read_bytes())
            if index == 1:
                _require(current_sha == commitment.get('first_anchor_sha256'), 'ledger_first_anchor_changed')
            registration = case / 'registration.json'
            registered = _load(registration)
            _require(value.get('registration_sha256') == _sha(registration.read_bytes())
                and value.get('case_id') == registered.get('case_id'), 'ledger_registration_anchor_mismatch')
            previous_sha = current_sha
        return cases

    def _current(self):
        cases = self._cases()
        _require(bool(cases), 'no_registered_noai_case')
        return cases[-1]

    def _stop(self, case, reason, **details):
        path = case / 'SAFETY-STOP.json'
        if not path.exists():
            _write(path, {'reason': reason, 'details': details, **NO_SUCCESS,
                          'automatic_retry': False, 'operator_cua_escape_required': True})
        raise SafetyHalt(reason)

    def _session(self, owner=None, *, evidence_path=None):
        session = self.o.c.session()
        if evidence_path is not None:
            _write(evidence_path, {'session': session, 'read_only': True})
        _require(isinstance(session, dict) and session.get('session_id') == self.o.resident
            and session.get('bridge_identity', {}).get('action_session') == self.o.session,
            'fresh_resident_identity_mismatch')
        _require(session.get('state') in ('ready', 'paused', 'busy'), 'resident_unavailable')
        _require('active_request_id' in session and session['active_request_id'] in (None, owner)
            and 'active_action_id' in session
            and (session['active_action_id'] is None or owner is not None
                and session['active_action_id'] == uuid_module.uuid5(uuid_module.UUID(self.o.resident), owner + ':1').hex)
            and type(session.get('pending')) is int
            and (session['pending'] == 0 and session.get('pending_request_ids', []) == [] or owner is not None
                and session['pending'] == 1 and session.get('pending_request_ids') == [owner]
                and session['active_request_id'] is None and session['active_action_id'] is None),
            'active_pending_or_unknown_resident_work')
        self._automation_idle(session)
        return session

    @staticmethod
    def _automation_idle(value):
        _require(value.get('aim_lock', {}).get('active') is False
            and value.get('combat', {}).get('active') is False
            and value.get('combat', {}).get('held_mappings') == [],
            'automatic_input_owner_active_or_unknown')

    def _validate_observation(self, observation, binding=None, *, released=True):
        probe = binding or Binding('identity_probe', self.o.resident, self.o.session,
            self.o.world, self.o.player, 'combat_entity')
        _require(probe.observation_context_problem(observation) is None, 'observation_identity_mismatch')
        self._automation_idle(observation)
        if released:
            _require(release_observed(probe, observation), 'native_input_release_unverified')
        state = observation['state']
        _require(all(_finite(state['player'].get(k)) for k in ('x', 'y', 'z')),
                 'player_position_invalid')
        nearby = state.get('nearby')
        _require(type(nearby) is dict and type(nearby.get('entities')) is list
            and nearby.get('truncated') is False and type(nearby.get('total')) is int
            and type(nearby.get('returned')) is int
            and nearby['total'] == nearby['returned'] == len(nearby['entities'])
            and _finite(nearby.get('radius')) and 0 < nearby['radius'] <= 32,
            'nearby_not_complete')
        uuids, ids = set(), set()
        for entity in nearby['entities']:
            _require(type(entity) is dict and isinstance(entity.get('uuid'), str)
                and UUID.fullmatch(entity['uuid']) is not None
                and type(entity.get('entity_id')) is int and entity['entity_id'] >= 0
                and isinstance(entity.get('type'), str) and entity['type']
                and all(_finite(entity.get(k)) for k in ('x', 'y', 'z'))
                and type(entity.get('alive')) is bool, 'nearby_entity_invalid')
            _require(entity['uuid'] not in uuids and entity['entity_id'] not in ids,
                     'nearby_duplicate_identity')
            uuids.add(entity['uuid']); ids.add(entity['entity_id'])
            _require(self._distance(entity, state['player']) <= nearby['radius'] + 1e-9,
                     'nearby_entity_outside_coverage')
        return observation

    @staticmethod
    def _distance(a, b):
        return math.sqrt(sum((a[k] - b[k]) ** 2 for k in ('x', 'y', 'z')))

    def _observe(self, folder, label, binding=None, *, owner=None, released=True):
        rid = uuid_module.uuid4().hex
        prefix = folder / (label + '-' + rid)
        self._session(owner, evidence_path=str(prefix) + '.session-before.json')
        body = {'op': 'observe', 'frame': False}
        _write(str(prefix) + '.intent.json', {'request_id': rid, 'body': body,
            'read_only': True, 'owner_request_id': owner, 'automatic_retry': False})
        started = time.monotonic()
        returned = self.o.c.submit(deepcopy(body), request_id=rid)
        _require(returned == rid, 'observation_submit_id_mismatch')
        receipt = self.o.c.wait(rid, 20)
        _write(str(prefix) + '.receipt.json', receipt)
        _require(type(receipt) is dict and receipt.get('request_id') == rid
            and receipt.get('session_id') == self.o.resident
            and receipt.get('status') == 'succeeded' and not _uncertain(receipt),
            'fresh_observation_receipt_unknown_or_failed')
        _require(time.monotonic() - started <= MAX_OBSERVE_SECONDS, 'fresh_observation_too_slow')
        observation = receipt.get('result')
        self._validate_observation(observation, binding, released=released)
        self._session(owner, evidence_path=str(prefix) + '.session-after.json')
        if binding is not None and (folder / 'trial-resolution.json').exists():
            self._record_post_health(folder, observation, label)
        _write(str(prefix) + '.effect.json', {'read_validated': True,
            'observation_sha256': _sha(_json(observation).encode()), **NO_SUCCESS})
        return deepcopy(observation)

    def _record_post_health(self, case, observation, label):
        previous = _load(case / 'trial-resolution.json')['original_report']['after']['state']['player'].get('health')
        existing = sorted(case.glob('post-health-[0-9]*.json'))
        if existing:
            previous = _load(existing[-1]).get('health')
        current = observation['state']['player'].get('health')
        stopped = not _finite(current) or not _finite(previous) or current < previous
        _write(case / ('post-health-%06d.json' % (len(existing) + 1)),
            {'health': current, 'previous_health': previous, 'source': label,
             'stopped_safety': stopped, 'original_trial_never_upgraded': True, **NO_SUCCESS})
        if stopped and not (case / 'POST-HEALTH-STOPPED-SAFETY.json').exists():
            _write(case / 'POST-HEALTH-STOPPED-SAFETY.json',
                {'reason': 'post_trial_health_decrease_or_unknown', 'health': current,
                 'previous_health': previous, 'native_safety_capability_not_combat_permission': True, **NO_SUCCESS})

    def _registered_entities(self, case):
        return _load(case / 'registration.json')['entities']

    def _find(self, observation, entity):
        entries = observation['state']['nearby']['entities']
        matches = [actual for actual in entries if actual['uuid'] == entity['uuid']
                   or actual['entity_id'] == entity['entity_id']]
        _require(not matches or len(matches) == 1 and _identity(matches[0]) == _identity(entity),
                 'registered_entity_identity_changed')
        return matches[0] if matches else None

    @staticmethod
    def _dead(entity):
        return entity.get('alive') is False or _finite(entity.get('health')) and entity['health'] == 0

    def _coverage_same(self, before, after):
        _require(_point(before['state']['player']) == _point(after['state']['player'])
            and before['state']['nearby']['radius'] == after['state']['nearby']['radius'],
            'observation_coverage_changed')

    def register_noai_case(self, case_id, entities, observation, *, evidence_ref,
                          noai_proof, authorization_ref, previous_case_authorization_ref=None):
        return self._register_case(case_id, entities, observation, evidence_ref=evidence_ref,
            noai_proof=noai_proof, authorization_ref=authorization_ref,
            previous_case_authorization_ref=previous_case_authorization_ref)

    def register_active_case(self, case_id, entities, observation, *, evidence_ref,
                             active_ai_proof, authorization_ref, pause_authorization_ref,
                             previous_case_authorization_ref=None):
        """Exactly two adult enabled-AI zombies, registered while natively paused.

        This is a distinct explicit case, not a NoAI proof override. It permits
        only the separate pause-first entry; cleanup remains a later operator step.
        """
        _require(_ref(pause_authorization_ref), 'active_pause_authorization_required')
        return self._register_case(case_id, entities, observation, evidence_ref=evidence_ref,
            noai_proof=active_ai_proof, authorization_ref=authorization_ref,
            previous_case_authorization_ref=previous_case_authorization_ref,
            active_ai=True, pause_authorization_ref=pause_authorization_ref)

    def _register_case(self, case_id, entities, observation, *, evidence_ref,
                       noai_proof, authorization_ref, previous_case_authorization_ref=None,
                       active_ai=False, pause_authorization_ref=None):
        _require(isinstance(case_id, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,80}', case_id), 'case_id_invalid')
        _require(_ref(evidence_ref) and _ref(authorization_ref), 'registration_authorization_or_evidence_missing')
        _require(type(entities) is list and len(entities) == 2, 'registration_requires_exactly_two_zombies')
        for entity in entities:
            _require(type(entity) is dict and set(entity) == {'uuid', 'entity_id', 'type', 'x', 'y', 'z'}
                and isinstance(entity['uuid'], str) and UUID.fullmatch(entity['uuid']) is not None
                and type(entity['entity_id']) is int and entity['entity_id'] >= 0
                and entity['type'] == 'minecraft:zombie'
                and all(_finite(entity[k]) for k in ('x', 'y', 'z')), 'registration_identity_invalid')
        _require(len({e['uuid'] for e in entities}) == len({e['entity_id'] for e in entities}) == 2,
                 'registration_duplicate_entity')
        proofs = noai_proof.get('entities') if type(noai_proof) is dict else None
        _require(type(proofs) is list and len(proofs) == 2
            and all(type(p) is dict and p.get('no_ai') is (False if active_ai else True)
                and (not active_ai or p.get('is_baby') is False)
                and _ref(p.get('evidence_ref')) for p in proofs)
            and {p.get('uuid') for p in proofs} == {e['uuid'] for e in entities},
            'exact_adult_active_ai_proof_required' if active_ai else 'exact_noai_proof_required_active_ai_unsupported')
        with self._locked(create=True):
            cases = self._cases()
            _require(all(_load(c / 'registration.json')['case_id'] != case_id for c in cases), 'case_already_registered')
            self._validate_observation(observation)
            if active_ai:
                _require(self._paused(observation), 'active_registration_requires_native_pause')
            _require(_finite(observation['state']['player'].get('health'))
                and observation['state']['player']['health'] == 20, 'noai_registration_requires_full_health_20')
            if cases:
                self._authorize_next_case(cases[-1], previous_case_authorization_ref, entities, active_ai=active_ai)
            fresh = self._observe(self.root, 'register')
            if active_ai:
                _require(self._paused(fresh), 'fresh_active_registration_requires_native_pause')
            _require(_finite(fresh['state']['player'].get('health'))
                and fresh['state']['player']['health'] == 20, 'fresh_noai_registration_requires_full_health_20')
            self._coverage_same(observation, fresh)
            for entity in entities:
                for sample in (observation, fresh):
                    actual = self._find(sample, entity)
                    _require(actual is not None and actual['alive'] is True
                        and _finite(actual.get('health')) and actual['health'] > 0
                        and _point(actual) == _point(entity), 'registration_current_noai_entity_unverified')
            ordinal = len(cases) + 1
            _require(ordinal <= 999999, 'ledger_case_limit_reached')
            case = self.root / ('case-%06d' % ordinal)
            record = {'context_sha256': _sha((self.root / 'context.json').read_bytes()), 'case_id': case_id, 'entities': deepcopy(entities), 'observation': deepcopy(observation),
                'fresh_observation': fresh, 'evidence_ref': evidence_ref,
                **({'active_ai_proof': deepcopy(noai_proof), 'pause_authorization_ref': pause_authorization_ref}
                   if active_ai else {'noai_proof': deepcopy(noai_proof)}),
                'authorization_ref': authorization_ref, 'previous_case_authorization_ref': previous_case_authorization_ref,
                'output_directory': str(Path(self.o.out).resolve()), 'ordinary_mutation_permission': False,
                'active_ai_supported': active_ai, **NO_SUCCESS}
            anchor = {'ordinal': ordinal, 'case_directory': case.name, 'case_id': case_id,
                'context_sha256': record['context_sha256'],
                'registration_sha256': _sha((_json(record) + '\n').encode()),
                'previous_anchor_sha256': (_sha((self.root / ('ledger-case-%06d.anchor.json' % (ordinal - 1))).read_bytes())
                    if cases else None)}
            if not cases:
                commitment = {'schema_version': 1, 'first_ordinal': 1,
                    'context_sha256': record['context_sha256'],
                    'first_anchor_sha256': _sha((_json(anchor) + '\n').encode())}
                _write(self.ever_used, {'ledger_directory': str(self.root), 'identity': self.identity,
                    'root_commitment_sha256': _sha((_json(commitment) + '\n').encode())})
                _write(self.root / 'CASE-LEDGER-USED.json', commitment)
            # Commit the case budget before creating its directory. Partial commits
            # are deliberately unrecoverable by an automatic new registration.
            _write(self.root / ('ledger-case-%06d.anchor.json' % ordinal), anchor)
            case.mkdir()
            _write(case / 'registration.json', record)
            return deepcopy(record)

    def current_authorization_ref(self):
        with self._locked():
            return _load(self._current() / 'registration.json')['authorization_ref']

    def require_noai_case(self):
        with self._locked():
            _require(_load(self._current() / 'registration.json').get('active_ai_supported') is False,
                     'active_case_requires_pause_first_entry')

    def reserve_trial(self, binding, command, trial_name):
        _require(isinstance(binding, EncounterBinding), 'noai_encounter_binding_required')
        _require(re.fullmatch(r'[A-Za-z0-9_-]{1,80}', trial_name or '') is not None, 'trial_name_invalid')
        with self._locked():
            case = self._current()
            _require(not (case / 'trial-reservation.json').exists(), 'case_trial_already_reserved')
            _require(not (case / 'SAFETY-STOP.json').exists(), 'case_safety_stopped')
            _require({k: getattr(binding, k) for k in self.identity} == self.identity, 'trial_context_mismatch')
            _require(bind_command(binding, command).wire() == binding.wire(), 'trial_command_binding_mismatch')
            _require(binding.encounter_request['encounter_scope'] == [_identity(e) for e in self._registered_entities(case)],
                     'trial_scope_not_registered')
            active_ai = _load(case / 'registration.json').get('active_ai_supported') is True
            _require(binding.encounter_request.get('encounter_pause_on_terminal') is True if active_ai
                     else binding.encounter_request.get('encounter_pause_on_terminal') is not True,
                     'active_case_requires_native_terminal_pause' if active_ai else 'noai_case_requires_original_terminal_flow')
            _require(str(Path(self.o.out).resolve()) == _load(case / 'registration.json')['output_directory'],
                     'registered_case_output_changed')
            _write(case / 'trial-reservation.json', {'registration_sha256': _sha((case / 'registration.json').read_bytes()),
                'binding': binding.wire(), 'command': deepcopy(command),
                'trial_name': trial_name, 'request_id': binding.request_id,
                'original_report_path': str(Path(self.o.out).resolve() / (trial_name + '.json')), **NO_SUCCESS})
            return binding.request_id

    def assert_mutation_allowed(self, *, request_id=None, body=None, owned_request=None, intent_request_id=None):
        with self._locked():
            cases = self._cases()
            if not cases:
                return  # Integration also refuses unregistered encounter admission.
            case = cases[-1]
            _require(not (case / 'trial-resolution.json').exists() and not (case / 'SAFETY-STOP.json').exists(),
                     'encounter_handoff_blocks_ordinary_mutation')
            _require((case / 'trial-reservation.json').exists(), 'registered_case_blocks_ordinary_mutation')
            reservation = _load(case / 'trial-reservation.json')
            rid = request_id or intent_request_id
            if rid == reservation['request_id'] and (body is None or body == reservation['command']):
                _require(not (case / 'trial-dispatch.json').exists() or body is None,
                         'trial_dispatch_already_consumed')
                return
            cancel = case / 'running-cancel-authorization.json'
            if cancel.exists():
                permit = _load(cancel)
                if rid == permit['request_id'] and owned_request == reservation['request_id']:
                    _require(not (case / 'running-cancel-rejected.json').exists(), 'running_cancel_pre_dispatch_rejected_no_replay')
                    _require(body is None or body == {'op': 'cancel'}, 'only_exact_owner_cancel_permitted')
                    _require(not (case / 'running-cancel-dispatch.json').exists() or body is None,
                             'running_cancel_already_consumed')
                    return
            # Owned reads/checks during an action can pass no body; never a submit.
            if body is None and rid is None and owned_request == reservation['request_id']:
                return
            raise SafetyHalt('encounter_handoff_blocks_ordinary_mutation')

    def claim_trial_dispatch(self, request_id, body, *, owned_request=None):
        with self._locked():
            cases = self._cases()
            if not cases:
                _require('encounter_mode' not in body and 'encounter_scope' not in body,
                         'encounter_requires_registered_noai_case')
                return
            case = cases[-1]
            _require(not (case / 'trial-resolution.json').exists() and not (case / 'SAFETY-STOP.json').exists(),
                     'encounter_handoff_blocks_ordinary_mutation')
            reservation = _load(case / 'trial-reservation.json')
            if request_id == reservation['request_id'] and body == reservation['command']:
                target = case / 'trial-dispatch.json'
            else:
                permit = _load(case / 'running-cancel-authorization.json')
                _require(request_id == permit['request_id'] and owned_request == reservation['request_id']
                    and body == {'op': 'cancel'}, 'only_exact_owner_cancel_permitted')
                target = case / 'running-cancel-dispatch.json'
                _require(not target.exists(), 'dispatch_already_consumed_no_replay')
                _require(not (case / 'running-cancel-rejected.json').exists(), 'running_cancel_pre_dispatch_rejected_no_replay')
                binding = _binding(reservation['binding'])
                main = self.o.c.result(binding.request_id)
                if main is not None:
                    self._reject_running_cancel(case, 'main_receipt_already_present_no_cancel', main_receipt=main)
                try:
                    current = self._session(binding.request_id)
                except Exception as exc:
                    self._reject_running_cancel(case, 'cancel_dispatch_bound_owner_unavailable', error=str(exc))
                if (current.get('active_request_id') != binding.request_id
                        or current.get('active_action_id') != binding.expected_action_id):
                    self._reject_running_cancel(case, 'cancel_dispatch_bound_owner_unavailable', session=current)
                main = self.o.c.result(binding.request_id)
                if main is not None:
                    self._reject_running_cancel(case, 'main_receipt_already_present_no_cancel', main_receipt=main)

            _require(not target.exists(), 'dispatch_already_consumed_no_replay')
            _write(target, {'request_id': request_id, 'body': deepcopy(body),
                           'owned_request': owned_request, 'reserved_before_submit': True,
                           'reservation_sha256': _sha((case / 'trial-reservation.json').read_bytes()),
                           'checks_and_native_dispatch_are_not_atomic': True, **NO_SUCCESS})

    def _reject_running_cancel(self, case, reason, **proof):
        path = case / 'running-cancel-rejected.json'
        if not path.exists():
            _write(path, {'reason': reason, 'proof': proof, 'dispatched': False,
                'authorization_sha256': _sha((case / 'running-cancel-authorization.json').read_bytes()),
                'ordinary_mutation_permission': False, 'automatic_retry': False, **NO_SUCCESS})
        raise SafetyHalt(reason)

    def authorize_running_cancel(self, observation, *, reason, authorization_ref, request_id=None):
        self.require_noai_case()
        _require(_ref(reason) and _ref(authorization_ref), 'running_cancel_authorization_missing')
        rid = request_id or uuid_module.uuid4().hex
        _require(isinstance(rid, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,100}', rid) is not None, 'cancel_request_id_invalid')
        with self._locked():
            case = self._current()
            _require((case / 'trial-dispatch.json').exists() and not (case / 'trial-resolution.json').exists()
                and not (case / 'SAFETY-STOP.json').exists()
                and not (case / 'running-cancel-authorization.json').exists(), 'running_cancel_unavailable')
            reservation = _load(case / 'trial-reservation.json'); binding = _binding(reservation['binding'])
            _require(rid != binding.request_id, 'cancel_request_must_be_distinct')
            relation = binding.classify_observation(observation)
            _require(relation['relation'] == 'bound' and relation['action']['status'] == 'running',
                     'strict_bound_running_observation_required')
            _require(self.o.c.result(binding.request_id) is None, 'main_receipt_already_present_no_cancel')
            fresh = self._observe(case, 'running-cancel-check', binding, owner=binding.request_id, released=False)
            relation = binding.classify_observation(fresh)
            _require(relation['relation'] == 'bound' and relation['action']['status'] == 'running',
                     'fresh_bound_running_observation_required')
            _require(self.o.c.result(binding.request_id) is None, 'main_receipt_already_present_no_cancel')
            _write(case / 'running-cancel-authorization.json', {'request_id': rid, 'owner_request_id': binding.request_id,
                'observation': deepcopy(observation), 'fresh_observation': fresh,
                'reason': reason, 'authorization_ref': authorization_ref, 'body': {'op': 'cancel'}, **NO_SUCCESS})
            return rid

    @staticmethod
    def _resolve_trial(binding, report):
        """Recheck all samples, including terminal evidence between polls.

        A terminal sample proves admission just as a running sample does. It
        must not disappear when resolving a later null rejection or a different
        terminal receipt. Use the same checks when reopening a persisted ledger.
        """
        _require(type(report.get('samples')) is list, 'complete_report_samples_missing')
        running, terminals = [], []
        for sample in report['samples']:
            _require(type(sample) is dict and type(sample.get('observation')) is dict, 'trial_sample_malformed')
            relation = binding.classify_observation(sample['observation'])
            _require(relation['relation'] not in ('context_mismatch', 'identity_mismatch'), 'trial_sample_identity_mismatch')
            action = sample['observation'].get('action', {})
            _require(action.get('status') != 'running' or relation['relation'] == 'bound', 'foreign_running_trial_sample')
            if relation['relation'] == 'bound':
                (running if action['status'] == 'running' else terminals).append(action)
        _require(type(report.get('before')) is dict and type(report.get('after')) is dict,
                 'complete_report_observations_missing')
        outcome = resolve(binding, report.get('response'), before=report['before'], after=report['after'],
                          running_evidence=running, interrupt_proof=report.get('interrupt_proof'))
        conflict = None
        if terminals and outcome['kind'] == 'admission_rejected':
            conflict = 'null_rejection_conflicts_with_prior_same_id_terminal_evidence'
        elif terminals and outcome['kind'] == 'bound_terminal':
            expected = terminal_signature(outcome['native_action'])
            if any(terminal_signature(action) != expected for action in terminals):
                conflict = 'trial_terminal_sample_contradicts_terminal_receipt'
        if conflict:
            outcome.update(kind='receipt_conflict', reason=conflict,
                native_admission_confirmed=None, native_action=None, native_action_source=None,
                needs_reconciliation=True, task_success=False)
        return outcome

    def record_trial(self, report):
        with self._locked():
            case = self._current()
            _require(not (case / 'trial-resolution.json').exists(), 'trial_already_recorded')
            reservation = _load(case / 'trial-reservation.json'); binding = _binding(reservation['binding'])
            _require((case / 'trial-dispatch.json').exists(), 'trial_dispatch_not_recorded')
            path = Path(reservation['original_report_path'])
            _require(path.is_file() and not path.is_symlink(), 'original_trial_artifact_missing')
            raw = path.read_bytes()
            _require(_json(json.loads(raw)) == _json(report), 'original_trial_artifact_mismatch')
            _require(report.get('binding') == binding.wire() and report.get('request_id') == binding.request_id
                and report.get('command') == reservation['command'] and report.get('name') == reservation['trial_name'],
                'report_reservation_mismatch')
            outcome = self._resolve_trial(binding, report)
            known = outcome['kind'] in ('bound_terminal', 'admission_rejected') and not outcome['needs_reconciliation']
            released = release_observed(binding, report['after'])
            record = {'registration_sha256': _sha((case / 'registration.json').read_bytes()),
                'reservation_sha256': _sha((case / 'trial-reservation.json').read_bytes()),
                'original_report_path': str(path), 'original_report_sha256': _sha(raw),
                'original_report': deepcopy(report), 'resolved_outcome': outcome, 'release_observed': released,
                'narrow_safety_eligible': known and released, 'ordinary_mutation_permission': False, **NO_SUCCESS}
            _write(case / 'trial-resolution.json', record)
            if not record['narrow_safety_eligible']:
                self._stop(case, 'main_trial_unknown_or_release_unverified')
            return deepcopy(record)

    def _eligible(self, case):
        _require(not (case / 'SAFETY-STOP.json').exists(), 'safety_stopped_operator_cua_required')
        for intent in case.glob('*.intent.json'):
            if _load(intent).get('read_only') is not True:
                _require(intent.with_name(intent.name.replace('.intent.json', '.effect.json')).exists(),
                         'unresolved_safety_intent_operator_cua_required')
        binding, record = self._verified_original_trial(case)
        # Every completed narrow mutation remains part of the authority chain.
        # Existence alone cannot turn a damaged prior effect into proof or permit
        # another UUID cleanup/pause. This verifier never calls _eligible again.
        verified_record = dict(record, narrow_safety_eligible=True)
        effects = [effect for effect in case.glob('cleanup-*.effect.json')
                   if UUID.fullmatch(effect.name.removeprefix('cleanup-').removesuffix('.effect.json')) is not None]
        if (case / 'pause.effect.json').exists():
            effects.append(case / 'pause.effect.json')
        for effect in effects:
            self._verified_effect(case, effect.name.removesuffix('.effect.json'), binding, verified_record)
        # Computed authority wins over a saved boolean or summary.
        return binding, verified_record

    def _verified_original_trial(self, case):
        """Recompute original authority/outcome without granting any mutation."""
        registration = _load(case / 'registration.json')
        reservation = _load(case / 'trial-reservation.json')
        dispatch = _load(case / 'trial-dispatch.json')
        record = _load(case / 'trial-resolution.json')
        _require(registration['context_sha256'] == _sha((self.root / 'context.json').read_bytes())
            and reservation['registration_sha256'] == record['registration_sha256']
                == _sha((case / 'registration.json').read_bytes())
            and dispatch['reservation_sha256'] == record['reservation_sha256']
                == _sha((case / 'trial-reservation.json').read_bytes()), 'ledger_authority_chain_mismatch')
        path = Path(record['original_report_path'])
        _require(path.is_file() and not path.is_symlink() and _sha(path.read_bytes()) == record['original_report_sha256']
            and str(path) == reservation['original_report_path'], 'original_trial_artifact_changed')
        report = json.loads(path.read_bytes())
        binding = _binding(reservation['binding'])
        _require({k: getattr(binding, k) for k in self.identity} == self.identity
            and [_identity(e) for e in registration['entities']] == binding.encounter_request['encounter_scope']
            and report['binding'] == binding.wire()
            and report['command'] == reservation['command'] == dispatch['body']
            and bind_command(binding, report['command']).wire() == binding.wire()
            and report['request_id'] == dispatch['request_id'] == reservation['request_id'] == binding.request_id
            and report['name'] == reservation['trial_name'] and report == record['original_report'],
            'ledger_original_scope_or_request_changed')
        recomputed = self._resolve_trial(binding, report)
        _require(recomputed == record['resolved_outcome']
            and recomputed['kind'] in ('bound_terminal', 'admission_rejected')
            and not recomputed['needs_reconciliation'] and release_observed(binding, report.get('after')),
            'main_trial_not_safe_for_native_cleanup')
        return binding, record

    def _current_terminal(self, case, binding, record, observation):
        outcome = record['resolved_outcome']
        relation = binding.classify_observation(observation)
        if outcome['kind'] == 'bound_terminal':
            _require(relation['relation'] == 'bound'
                and terminal_signature(relation['action']) == terminal_signature(outcome['native_action']),
                'current_native_terminal_changed')
        else:
            _require(relation['relation'] == 'unrelated_retained_action', 'null_admission_current_action_conflict')

    def _execute(self, case, name, body, authorization_ref, before, binding, record, verify):
        prefix = case / name
        _require(not Path(str(prefix) + '.intent.json').exists(), 'safety_action_already_reserved_no_replay')
        rid = uuid_module.uuid4().hex
        _write(str(prefix) + '.intent.json', {'request_id': rid, 'body': body, 'authorization_ref': authorization_ref,
            'before': before, 'original_report_sha256': record['original_report_sha256'],
            'ordinary_mutation_permission': False, 'automatic_retry': False, **NO_SUCCESS})
        try:
            self._session()
            returned = self.o.c.submit(deepcopy(body), request_id=rid)
            _require(returned == rid, 'safety_submit_id_mismatch')
            receipt = self.o.c.wait(rid, 20)
            _write(str(prefix) + '.receipt.json', receipt)
            _require(type(receipt) is dict and receipt.get('request_id') == rid
                and receipt.get('session_id') == self.o.resident and receipt.get('status') == 'succeeded'
                and not _uncertain(receipt) and receipt.get('reason') == 'direct_input_dispatched'
                and receipt.get('result', {}).get('ok') is True, 'safety_receipt_unknown_or_failed')
            if body['endpoint'] == 'command':
                _require(receipt['result'].get('submitted') is True, 'command_send_unconfirmed')
            else:
                _require(receipt['result'].get('key') == 'key.keyboard.escape'
                    and receipt['result'].get('action') == 'click' and receipt['result'].get('down') is False,
                    'native_escape_receipt_invalid')
            after = self._observe(case, name + '-after', binding)
            self._current_terminal(case, binding, record, after)
            effect = verify(after)
            result = {'request_id': rid, 'effect_confirmed': True, 'effect': effect,
                'after': after, 'native_command_dispatch_is_not_combat_success': True,
                'ordinary_mutation_permission': False,
                'intent_sha256': _sha(Path(str(prefix) + '.intent.json').read_bytes()),
                'receipt_sha256': _sha(Path(str(prefix) + '.receipt.json').read_bytes()),
                'resolution_sha256': _sha((case / 'trial-resolution.json').read_bytes()), **NO_SUCCESS}
            _write(str(prefix) + '.effect.json', result)
            return result
        except Exception as exc:
            self._stop(case, 'safety_effect_unknown_no_retry_operator_cua_required', error_type=type(exc).__name__, error=str(exc))

    def cleanup_uuid(self, uuid, authorization_ref):
        self.require_noai_case()
        _require(isinstance(uuid, str) and UUID.fullmatch(uuid) is not None, 'canonical_uuid_required_no_selector')
        _require(_ref(authorization_ref), 'cleanup_authorization_missing')
        with self._locked():
            case = self._current(); binding, record = self._eligible(case)
            entries = [e for e in self._registered_entities(case) if e['uuid'] == uuid]
            _require(len(entries) == 1, 'uuid_not_registered_in_current_case')
            entity = entries[0]; name = 'cleanup-' + uuid
            _require(not (case / (name + '.intent.json')).exists(), 'cleanup_already_reserved_no_replay')
            try:
                before = self._observe(case, name + '-before', binding)
                self._current_terminal(case, binding, record, before)
                actual = self._find(before, entity)
                _require(actual is not None and not self._dead(actual)
                    and _finite(actual.get('health')) and actual['health'] > 0,
                    'cleanup_target_not_currently_living_and_in_range')
                _require(self._distance(actual, before['state']['player']) < before['state']['nearby']['radius'],
                         'cleanup_target_on_coverage_boundary')
                def verify(after):
                    self._coverage_same(before, after)
                    remaining = self._find(after, entity)
                    _require(remaining is None or self._dead(remaining), 'exact_uuid_death_or_absence_unverified')
                    return 'exact_uuid_absent_in_same_complete_coverage' if remaining is None else 'exact_uuid_dead_observed'
                return self._execute(case, name, {'op': 'direct', 'endpoint': 'command',
                    'body': {'command': 'kill ' + uuid}}, authorization_ref, before, binding, record, verify)
            except Exception as exc:
                self._stop(case, 'cleanup_precondition_or_effect_failed', error=str(exc))

    def pause_once(self, authorization_ref):
        self.require_noai_case()
        _require(_ref(authorization_ref), 'pause_authorization_missing')
        with self._locked():
            case = self._current(); binding, record = self._eligible(case)
            _require(not (case / 'pause.intent.json').exists() and not (case / 'pause.effect.json').exists(), 'pause_already_checked_or_attempted')
            try:
                before = self._observe(case, 'pause-before', binding)
                self._current_terminal(case, binding, record, before)
                if self._paused(before):
                    record = {'effect_confirmed': True, 'effect': 'already_paused_no_toggle',
                        'authorization_ref': authorization_ref, 'after': before, 'dispatched': False, **NO_SUCCESS}
                    _write(case / 'pause.effect.json', record)
                    return record
                _require(before['state'].get('paused') is False and before['state'].get('screen_open') is False
                    and before.get('screen', {}).get('open') is False,
                    'escape_toggle_requires_active_game_no_screen')
                def verify(after):
                    _require(self._paused(after), 'native_pause_effect_unverified')
                    return 'native_escape_pause_observed'
                return self._execute(case, 'pause', {'op': 'direct', 'endpoint': 'raw-key',
                    'body': {'key': 'key.keyboard.escape', 'action': 'click'}}, authorization_ref, before, binding, record, verify)
            except Exception as exc:
                self._stop(case, 'pause_precondition_or_effect_failed', error=str(exc))

    @staticmethod
    def _paused(observation):
        screen = observation.get('screen', {})
        return (observation['state'].get('paused') is True and observation['state'].get('screen_open') is True
                and screen.get('open') is True and screen.get('class') == PAUSE_SCREEN)

    def record_external_escape(self, evidence):
        _require(type(evidence) is dict and evidence.get('operator_executed') is True
            and evidence.get('method') == 'cua_escape' and _ref(evidence.get('evidence_ref'))
            and _ref(evidence.get('authorization_ref')), 'explicit_operator_cua_evidence_required')
        with self._locked():
            case = self._current()
            result = {'evidence': deepcopy(evidence), 'native_release_proven': False,
                'native_outcome_proven': False, 'ordinary_mutation_permission': False,
                'dispatched_by_module': False, **NO_SUCCESS}
            _write(case / ('external-escape-' + uuid_module.uuid4().hex + '.json'), result)
            return result

    @staticmethod
    def _operator_dead(entity):
        # Active closeout requires a positively observed death, not absence or
        # contradictory alive/health fields. The corpse may remain while paused.
        return (entity is not None and entity.get('alive') is False
                and _finite(entity.get('health')) and entity['health'] == 0)

    def _operator_closeout_base(self, case):
        registration = _load(case / 'registration.json')
        _require(registration.get('active_ai_supported') is True, 'operator_closeout_requires_active_case')
        stop = _load(case / 'SAFETY-STOP.json')
        _require(stop.get('reason') == 'active_case_requires_separate_operator_closeout',
                 'operator_closeout_cannot_clear_unknown_or_other_stop')
        binding, record = self._verified_original_trial(case)
        _require(record['resolved_outcome']['kind'] == 'bound_terminal'
            and record['resolved_outcome']['native_action']['result'].get('input_release_confirmed') is True,
            'operator_closeout_requires_original_known_released_terminal')
        return binding, record

    def _operator_evidence(self, evidence, binding, seen, prior_end, *, expected_body=None):
        _require(type(evidence) is dict and set(evidence) == {'intent', 'receipt'}, 'operator_evidence_shape_invalid')
        intent, wrapped = evidence['intent'], evidence['receipt']
        _require(type(intent) is dict and type(wrapped) is dict, 'operator_evidence_missing')
        rid = intent.get('request_id')
        _require(isinstance(rid, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,80}', rid)
            and rid not in seen, 'operator_evidence_request_reused_or_invalid')
        seen.add(rid)
        start, end = wrapped.get('started_monotonic'), wrapped.get('finished_monotonic')
        _require(_finite(start) and _finite(end) and 0 <= start <= end
            and start >= prior_end and _finite(intent.get('started_monotonic'))
            and intent.get('started_monotonic') == start,
            'operator_evidence_time_invalid_or_reordered')
        receipt = wrapped.get('receipt')
        _require(type(receipt) is dict and receipt.get('request_id') == rid
            and receipt.get('session_id') == binding.resident_session
            and receipt.get('status') == 'succeeded' and not _uncertain(receipt),
            'operator_evidence_receipt_unknown_or_foreign')
        if expected_body is None:
            _require(intent.get('body') in ({'op': 'observe'}, {'op': 'observe', 'frame': False})
                and end - start <= MAX_OBSERVE_SECONDS, 'operator_effect_requires_bounded_observe')
            return receipt.get('result'), end
        _require(intent.get('body') == expected_body and receipt.get('reason') == 'direct_input_dispatched'
            and type(receipt.get('result')) is dict
            and receipt.get('result', {}).get('ok') is True
            and receipt['result'].get('submitted') is True, 'operator_cleanup_dispatch_unverified')
        return receipt, end

    def _operator_observation(self, observation, binding, record):
        self._validate_observation(observation, binding)
        self._current_terminal(None, binding, record, observation)
        _require(self._paused(observation), 'operator_closeout_requires_actual_pause')
        _require(_finite(observation['state']['player'].get('health'))
            and observation['state']['player']['health'] > 0, 'operator_closeout_player_health_unknown_or_dead')

    def _verify_operator_proof(self, case, binding, record, proof):
        _require(type(proof) is dict and set(proof) == {'native_terminal', 'before', 'cleanups', 'final_observation'},
                 'operator_closeout_proof_missing')
        terminal = proof['native_terminal']
        _require(binding.native_problem(terminal) is None
            and terminal_signature(terminal) == terminal_signature(record['resolved_outcome']['native_action']),
            'operator_closeout_original_terminal_mismatch')
        seen = {binding.request_id}
        ends = [sample.get('finished_monotonic') for sample in record['original_report'].get('samples', [])]
        _require(ends and all(_finite(end) and end >= 0 for end in ends), 'operator_original_observation_timing_missing')
        before, end = self._operator_evidence(proof['before'], binding, seen, max(ends))
        self._operator_observation(before, binding, record)
        entities = self._registered_entities(case)
        cleanups = proof['cleanups']
        _require(type(cleanups) is list and len(cleanups) == 2, 'operator_closeout_requires_exact_two_cleanups')
        current = before
        for index, (entity, cleanup) in enumerate(zip(entities, cleanups)):
            _require(type(cleanup) is dict and set(cleanup) == {'uuid', 'dispatch', 'effect'}
                and cleanup['uuid'] == entity['uuid'], 'operator_cleanup_uuid_or_order_mismatch')
            actual = self._find(current, entity)
            _require(actual is not None and actual['alive'] is True
                and _finite(actual.get('health')) and actual['health'] > 0
                and self._distance(actual, current['state']['player']) < current['state']['nearby']['radius'],
                'operator_cleanup_target_not_living_inside_coverage')
            body = {'op': 'direct', 'endpoint': 'command', 'body': {'command': 'kill ' + entity['uuid']}}
            _, end = self._operator_evidence(cleanup['dispatch'], binding, seen, end, expected_body=body)
            after, end = self._operator_evidence(cleanup['effect'], binding, seen, end)
            self._operator_observation(after, binding, record)
            self._coverage_same(current, after)
            dead = self._find(after, entity)
            _require(self._operator_dead(dead) and _point(dead) == _point(actual),
                     'operator_exact_death_not_observed')
            for previous in entities[:index]:
                _require(self._operator_dead(self._find(after, previous)), 'operator_prior_death_contradicted')
            current = after
        _require(proof['final_observation'] == current, 'operator_final_observation_not_last_effect')
        _require(end <= time.monotonic(), 'operator_evidence_not_yet_completed')
        return current

    def _operator_current(self, observation, binding, record, final):
        self._operator_observation(observation, binding, record)
        self._coverage_same(final, observation)
        for entity in binding.encounter_request['encounter_scope']:
            actual = self._find(observation, entity)
            # Absence now cannot supply death proof; both deaths were already
            # positively established by separate complete effect observations.
            _require(actual is None or self._operator_dead(actual), 'operator_closeout_current_living_or_conflicting_target')

    def record_operator_closeout(self, case_id, *, native_terminal, before, cleanups,
                                 final_observation, authorization_ref, evidence_ref):
        """Append verified completed operator work; performs reads, never cleanup.

        Original report/STOP/anchors remain immutable. This records no gameplay
        success and grants no ordinary mutation or automatic next-case permit.
        """
        _require(_ref(authorization_ref) and _ref(evidence_ref), 'operator_closeout_authorization_or_evidence_missing')
        with self._locked():
            case = self._current()
            registration = _load(case / 'registration.json')
            _require(case_id == registration['case_id'], 'operator_closeout_case_mismatch')
            target = case / 'operator-closeout.json'
            _require(not target.exists() and not Path(str(target) + '.sha256').exists(), 'operator_closeout_already_recorded')
            binding, record = self._operator_closeout_base(case)
            proof = deepcopy({'native_terminal': native_terminal, 'before': before,
                'cleanups': cleanups, 'final_observation': final_observation})
            final = self._verify_operator_proof(case, binding, record, proof)
            fresh = self._observe(case, 'operator-closeout-current', binding)
            self._operator_current(fresh, binding, record, final)
            result = {'schema_version': 1, 'case_id': case_id, 'identity': self.identity,
                'authorization_ref': authorization_ref, 'evidence_ref': evidence_ref,
                'registration_sha256': _sha((case / 'registration.json').read_bytes()),
                'resolution_sha256': _sha((case / 'trial-resolution.json').read_bytes()),
                'original_report_sha256': record['original_report_sha256'],
                'stop_sha256': _sha((case / 'SAFETY-STOP.json').read_bytes()),
                'proof': proof, 'proof_sha256': _sha(_json(proof).encode()),
                'fresh_observation': fresh, 'operator_closeout_verified': True,
                'ordinary_mutation_permission': False, 'automatic_retry': False,
                'original_trial_never_upgraded': True, **NO_SUCCESS}
            _write(target, result)
            return deepcopy(result)

    def _verified_operator_closeout(self, case):
        binding, record = self._operator_closeout_base(case)
        closeout = _load(case / 'operator-closeout.json')
        _require(closeout.get('schema_version') == 1 and closeout.get('case_id') == _load(case / 'registration.json')['case_id']
            and closeout.get('identity') == self.identity and _ref(closeout.get('authorization_ref'))
            and _ref(closeout.get('evidence_ref')) and closeout.get('operator_closeout_verified') is True
            and closeout.get('ordinary_mutation_permission') is False
            and closeout.get('automatic_retry') is False and closeout.get('original_trial_never_upgraded') is True
            and all(closeout.get(key) is False for key in NO_SUCCESS), 'saved_operator_closeout_invalid')
        _require(closeout.get('registration_sha256') == _sha((case / 'registration.json').read_bytes())
            and closeout.get('resolution_sha256') == _sha((case / 'trial-resolution.json').read_bytes())
            and closeout.get('stop_sha256') == _sha((case / 'SAFETY-STOP.json').read_bytes())
            and closeout.get('original_report_sha256') == record['original_report_sha256']
            and closeout.get('proof_sha256') == _sha(_json(closeout.get('proof')).encode()),
            'saved_operator_closeout_authority_changed')
        final = self._verify_operator_proof(case, binding, record, closeout['proof'])
        self._operator_current(closeout.get('fresh_observation'), binding, record, final)
        return binding, record, closeout

    def _verified_effect(self, case, name, binding, record):
        effect = _load(case / (name + '.effect.json'))
        _require(effect.get('effect_confirmed') is True and effect.get('ordinary_mutation_permission', False) is False,
                 'saved_safety_effect_invalid')
        after = effect['after']
        self._validate_observation(after, binding)
        self._current_terminal(case, binding, record, after)
        if name == 'pause' and effect.get('dispatched') is False:
            _require(effect.get('effect') == 'already_paused_no_toggle' and self._paused(after),
                     'saved_noop_pause_unverified')
            return effect
        intent_path = case / (name + '.intent.json')
        receipt_path = case / (name + '.receipt.json')
        intent = _load(intent_path); response = _load(receipt_path)
        _require(effect.get('intent_sha256') == _sha(intent_path.read_bytes())
            and effect.get('receipt_sha256') == _sha(receipt_path.read_bytes())
            and effect.get('resolution_sha256') == _sha((case / 'trial-resolution.json').read_bytes())
            and intent.get('original_report_sha256') == record['original_report_sha256'],
            'saved_effect_authority_chain_mismatch')
        _require(response.get('request_id') == intent.get('request_id') == effect.get('request_id')
            and response.get('session_id') == self.o.resident and response.get('status') == 'succeeded'
            and response.get('reason') == 'direct_input_dispatched' and not _uncertain(response)
            and response.get('result', {}).get('ok') is True, 'saved_safety_receipt_invalid')
        if name == 'pause':
            expected = {'op': 'direct', 'endpoint': 'raw-key', 'body': {'key': 'key.keyboard.escape', 'action': 'click'}}
            _require(intent['body'] == expected and self._paused(after)
                and response['result'].get('key') == 'key.keyboard.escape'
                and response['result'].get('action') == 'click' and response['result'].get('down') is False,
                'saved_native_pause_unverified')
        else:
            target = name.removeprefix('cleanup-')
            scope = [e for e in self._registered_entities(case) if e['uuid'] == target]
            _require(len(scope) == 1 and intent['body'] == {'op': 'direct', 'endpoint': 'command', 'body': {'command': 'kill ' + target}}
                and response['result'].get('submitted') is True, 'saved_cleanup_scope_unverified')
            before = intent['before']; self._validate_observation(before, binding)
            actual = self._find(before, scope[0]); remaining = self._find(after, scope[0])
            self._coverage_same(before, after)
            _require(actual is not None and not self._dead(actual)
                and self._distance(actual, before['state']['player']) < before['state']['nearby']['radius']
                and (remaining is None or self._dead(remaining)), 'saved_exact_cleanup_effect_unverified')
        return effect

    def _authorize_next_case(self, previous, authorization_ref, next_entities, *, active_ai=False):
        _require(_ref(authorization_ref), 'explicit_next_independent_case_authorization_required')
        prior = _load(previous / 'registration.json')
        _require(authorization_ref not in (prior['authorization_ref'], prior.get('previous_case_authorization_ref')),
                 'next_case_requires_new_explicit_authorization')
        if prior.get('active_ai_supported') is True:
            binding, record, closeout = self._verified_operator_closeout(previous)
            _require(authorization_ref != closeout['authorization_ref'], 'next_case_requires_new_explicit_authorization')
            observation = self._observe(previous, 'next-active-case-check', binding)
            self._operator_current(observation, binding, record, closeout['fresh_observation'])
            for entity in observation['state']['nearby']['entities']:
                _require(entity['type'] != 'minecraft:zombie' or self._operator_dead(entity)
                    or _identity(entity) in [_identity(e) for e in next_entities],
                    'unregistered_living_zombie_blocks_next_case')
            _write(previous / ('next-case-authorization-' + uuid_module.uuid4().hex + '.json'),
                {'authorization_ref': authorization_ref, 'fresh_observation': observation,
                 'operator_closeout_sha256': _sha((previous / 'operator-closeout.json').read_bytes()),
                 'scope': 'one_new_independent_registered_active_case' if active_ai else 'one_new_independent_registered_noai_case',
                 'ordinary_mutation_permission': False, **NO_SUCCESS})
            return
        _require(prior.get('active_ai_supported') is False, 'prior_case_mode_unknown')
        binding, record = self._eligible(previous)
        effects = [previous / ('cleanup-' + e['uuid'] + '.effect.json') for e in self._registered_entities(previous)]
        _require((previous / 'pause.effect.json').exists() and all(p.exists() for p in effects),
                 'previous_case_pause_and_exact_cleanup_effect_required')
        self._verified_effect(previous, 'pause', binding, record)
        verified = [self._verified_effect(previous, 'cleanup-' + e['uuid'], binding, record)
                    for e in self._registered_entities(previous)]
        observation = self._observe(previous, 'next-case-check', binding)
        self._current_terminal(previous, binding, record, observation)
        _require(self._paused(observation), 'next_case_requires_fresh_previous_pause')
        for effect in verified:
            self._coverage_same(effect['after'], observation)
        for entity in self._registered_entities(previous):
            remaining = self._find(observation, entity)
            _require(remaining is None or self._dead(remaining), 'previous_case_has_residual_entity')
        for entity in observation['state']['nearby']['entities']:
            _require(entity['type'] != 'minecraft:zombie' or self._dead(entity)
                or _identity(entity) in [_identity(e) for e in next_entities],
                'unregistered_living_zombie_blocks_next_case')
        _write(previous / ('next-case-authorization-' + uuid_module.uuid4().hex + '.json'),
            {'authorization_ref': authorization_ref, 'fresh_observation': observation,
            'scope': 'one_new_independent_registered_active_case' if active_ai else 'one_new_independent_registered_noai_case',
            'ordinary_mutation_permission': False, **NO_SUCCESS})

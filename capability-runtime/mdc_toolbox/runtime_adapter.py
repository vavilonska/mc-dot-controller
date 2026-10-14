"""Injected long-lived facade over the existing Runtime → IntentClient owner chain.

Construction, describe, cancel acknowledgement and reconciliation never launch work.
No direct native HTTP client, credentials, or alternative input owner lives here.
"""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import threading
import time
import uuid
from mdc_skills.core import Runtime, SkillError, Outcome
from .control import JobControl
from .budgets import SharedBudget
from .supervisor import LocalSupervisor
from .serialization import serialize_outcome


def _ref(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _public_context(context):
    return {k: deepcopy(v) for k, v in context.items() if k not in ('cancel_event', 'emit')}


class OwnerRuntimeBackend:
    INITIAL_CAPABILITIES = frozenset({'select_hotbar','ensure_hotbar','equip','consume','close_menu',
        'container_move','container_split','container_merge','container_withdraw','container_deposit','craft','smelt','interact','navigate_local','mine_local','collect_local','place_local','engage'})
    REQUIRED_ACTIONS = {
        'mine_local': {'break_block'},
        'place_local': {'place_block'},
        'collect_local': {'follow_path'},
        'engage': {'combat_entity'},
        'navigate_local': {'follow_path'},
        'select_hotbar': {'select_hotbar'}, 'ensure_hotbar': {'select_hotbar','click_slot'},
        'equip': {'select_hotbar','click_slot'}, 'consume': {'select_hotbar','click_slot','use_item'},
        'interact': {'interact_block'}, 'close_menu': {'close_menu'}, 'craft': {'click_slot'}, 'smelt': {'click_slot'},
        **{name: {'click_slot'} for name in ('container_move','container_split','container_merge','container_withdraw','container_deposit')}}

    def __init__(self, runtime, bindings=None):
        self.runtime = runtime
        self._bindings = bindings
        self._lock = threading.Lock()
        self._active = None
        self._completed = {}
        self._quarantined = False

    def _plugins(self):
        if self._bindings is None:
            from .catalog import CapabilityCatalog
            catalog = CapabilityCatalog()
            return {name: catalog.plugin(name) for name in catalog._plugins}
        return dict(self._bindings)

    def describe(self):
        try:
            session = self.runtime.client.session()  # Read only, no lease acquisition.
        except Exception as exc:
            return {'available': False, 'private_singleplayer': False, 'reason': 'gateway_unavailable:' + type(exc).__name__,
                    'supported_capabilities': [], 'native_features': [], 'supported_budget_metrics': list(SharedBudget.METRICS),
                    'cancellation_supported': False}
        scoped = session.get('scoped_native_preflight')
        features = []
        if (isinstance(scoped, dict) and scoped.get('version') == 'scoped-native-preflight/1'
                and scoped.get('same_callback_capture_validate_admit') is True
                and scoped.get('private_singleplayer_only') is True):
            features.append('scoped-native-preflight/1')
            if scoped.get('capability_guard_schema_version') == 1:
                features.append('capability_guard/1')
            features.extend('profile:' + name for name in scoped.get('profiles', {}))
            features.extend('action:' + name for name in scoped.get('guarded_actions', []))
        negotiated_actions = set(self._profile_actions({'scoped_profiles': scoped.get('profiles', {}) if isinstance(scoped, dict) else {}}))
        supported = sorted(name for name in self._plugins() if name in self.INITIAL_CAPABILITIES
                           and ((name == 'collect_local' and isinstance(scoped,dict) and scoped.get('profiles',{}).get('collect-local-observed-v1') == ['follow_path'])
                                or (name != 'collect_local' and self.REQUIRED_ACTIONS[name] <= negotiated_actions))
                           and (name != 'place_local' or session.get('execution_policy') == 'request_only')
                           and 'scoped-native-preflight/1' in features)
        known = isinstance(session.get('capability_context'), dict) and all(
            isinstance(session['capability_context'].get(k), str) for k in ('world_generation','dimension','player_uuid','action_session'))
        available = (not self._quarantined and session.get('state') in ('ready', 'busy') and known
                     and session.get('capability_lease_schema_version') == 1
                     and not self.runtime.has_unresolved_execution)
        return {'available': available, 'private_singleplayer': session.get('private_singleplayer') is True,
                'session_ref': _ref(session.get('session_id')), 'context_ref': _ref(session.get('capability_context')),
                'supported_capabilities': supported, 'native_features': sorted(features),
                'supported_budget_metrics': list(SharedBudget.METRICS),
                'supported_policies': {'version': 1, 'execution_mode': ['noncombat','guarded','request_only'], 'reactions': ['stop']},
                'execution_policy': session.get('execution_policy'),
                'cancellation_supported': session.get('capability_cancel_schema_version') == 1,
                'scoped_profiles': deepcopy(scoped.get('profiles', {})) if isinstance(scoped, dict) else {},
                'validation': {'live': 'not_run', 'scope': 'negotiated_features_not_live_acceptance'}}

    def _profile_actions(self, description):
        profiles = description.get('scoped_profiles', {})
        output = {}
        for profile in ('state-menu-v1', 'state-use-v1', 'block-menu-v1', 'movement-flat-observed-v2'):
            actions = profiles.get(profile, [])
            if isinstance(actions, list):
                for action in actions:
                    if action in {'state-menu-v1': {'click_slot','close_menu','select_hotbar'},
                                  'state-use-v1': {'use_item'}, 'block-menu-v1': {'interact_block'},
                                  'movement-flat-observed-v2': {'follow_path'}}[profile]:
                        output[action] = profile
        if profiles.get('placement-local-observed-v1') == ['place_block']:
            output['place_block'] = 'placement-local-observed-v1'
        if profiles.get('mining-local-observed-v2') == ['break_block']:
            output['break_block'] = 'mining-local-observed-v2'
        if profiles.get('combat-local-observed-v1') == ['combat_entity']:
            output['combat_entity'] = 'combat-local-observed-v1'
        return output

    def _effect(self):
        # A small per-job certainty latch survives hot-journal compaction.
        return self.runtime._job_effect_certainty

    def execute(self, capability, arguments, context):
        if not self._lock.acquire(blocking=False):
            return self._blocked('runtime_owner_busy', context)
        begun = False
        outcome = None
        try:
            description = self.describe()
            plugin = self._plugins().get(capability)
            if capability not in description.get('supported_capabilities', []) or plugin is None or not description.get('available') or not description.get('private_singleplayer'):
                return self._blocked('runtime_or_binding_unavailable', context)
            if context.get('expected_context') not in (None, description.get('context_ref')):
                return self._blocked('expected_context_changed', context)
            policy = context.get('policy', {})
            if (not isinstance(policy, dict) or set(policy) - {'version','execution_mode','reactions'}
                    or policy.get('version') != 1 or policy.get('execution_mode') not in ('noncombat','guarded','request_only')
                    or policy.get('reactions', 'stop') != 'stop'):
                return self._blocked('unsupported_execution_or_reaction_policy', context)
            expected_policy = {'noncombat': 'noncombat', 'guarded': 'standard', 'request_only': 'request_only'}[policy['execution_mode']]
            if description.get('execution_policy') != expected_policy:
                return self._blocked('requested_gateway_execution_policy_not_active', context)
            if context.get('budget', {}).get('cleanup_reserve_actions', 1) < 1:
                return self._blocked('exact_cancel_cleanup_reserve_required', context)
            control = JobControl(context)
            self.runtime.required_execution_policy = expected_policy
            self._active = {'context': _public_context(context), 'control': control}
            profiles = self._profile_actions(description)
            if capability == 'collect_local':
                profiles['follow_path'] = 'collect-local-observed-v1'
            self.runtime.begin_job(control, scoped_profiles=profiles)
            begun = True
            self._active['owner_context'] = self.runtime.owner_context()
            supervisor = LocalSupervisor(control, policy)
            with supervisor.ordinary():
                control.checkpoint()
                outcome = plugin.invoke(capability, self.runtime, deepcopy(arguments), control)
        except SkillError as exc:
            outcome = Outcome(exc.status, exc.reason, (exc.request_id,) if exc.request_id else ())
        except Exception as exc:
            outcome = Outcome('unknown' if self.runtime.has_unresolved_execution else 'blocked',
                              'runtime_adapter_error:' + type(exc).__name__)
        finally:
            if begun:
                effect = self._effect()
                control = self._active['control']
                release = self.runtime.finish_job()
                owner_context = self.runtime.owner_context()
                budget = control.budget.snapshot()
                cleanup = 'confirmed' if release.ok else 'unknown'
                value = serialize_outcome(outcome or Outcome('unknown', 'missing_domain_result'))
                state = value.get('status', value.get('state', 'blocked'))
                if state not in ('succeeded','blocked','failed','cancelled','interrupted','unknown'):
                    state = 'blocked'
                # Semantic results survive unconfirmed ownership cleanup unchanged.
                if cleanup == 'unknown' or effect == 'unknown':
                    state = 'unknown'
                result = {'state': state, 'reason': value.get('reason', 'domain_result'),
                          'effect_certainty': effect, 'cleanup_certainty': cleanup, 'result': value,
                          'request_ids': list(self.runtime._job_request_ids),
                          'context': {**_public_context(context), 'owner_context': owner_context},
                          'evidence': {'budget': budget, 'owner_release': serialize_outcome(release),
                                       'owner_context': owner_context, 'server_confirmed': False}}
                self._completed[context['job_id']] = deepcopy(result)
                # Freeze the entire backend if its owner cannot be released.
                if cleanup == 'confirmed':
                    self._active = None
                else:
                    self._quarantined = True
            if not begun and self.runtime._job_control is None:
                self._active = None
            self._lock.release()
        return result if begun else self._blocked(getattr(outcome, 'reason', 'runtime_not_started'), context)

    @staticmethod
    def _blocked(reason, context):
        return {'state': 'blocked', 'reason': reason, 'effect_certainty': 'none_proven',
                'cleanup_certainty': 'not_needed', 'result': None, 'evidence': {},
                'context': _public_context(context), 'request_ids': []}

    def cancel_exact(self, job_context, cancel_request_id):
        active = self._active
        if active is None:
            known = self._completed.get(job_context.get('job_id'))
            return deepcopy(known) if known is not None else {**self._blocked('original_owner_not_active', job_context),
                                                            'state': 'unknown', 'effect_certainty': 'unknown'}
        original = active['context']
        claimed = job_context.get('owner_context', job_context)
        current = self.runtime.owner_context()
        if (job_context.get('job_id') != original['job_id'] or job_context.get('request_id') != original['request_id']
                or claimed.get('owner_id') != current['owner_id']
                or claimed.get('owner_generation', current['owner_generation']) != current['owner_generation']):
            return {**self._blocked('exact_cancel_job_or_owner_mismatch', job_context), 'state': 'unknown',
                    'effect_certainty': 'unknown', 'cleanup_certainty': 'unknown'}
        if self.runtime.has_unresolved_execution:
            rid = self.runtime.pending_request_id
            if rid and self.runtime._journal['records'][rid].get('status') == 'unknown':
                return {**self._blocked('unknown_original_must_reconcile', job_context), 'state': 'unknown',
                        'effect_certainty': 'unknown', 'cleanup_certainty': 'unknown'}
        if not active['control'].request_cancel(cancel_request_id):
            return {'state': 'stopping', 'reason': 'original_cancel_already_requested', 'effect_certainty': 'unknown',
                    'cleanup_certainty': 'pending', 'request_ids': current['original_request_ids'],
                    'context': {**original, 'owner_context': current}, 'evidence': {}}
        return {'state': 'stopping', 'reason': 'exact_cancel_requested', 'effect_certainty': 'unknown',
                'cleanup_certainty': 'pending', 'request_ids': current['original_request_ids'],
                'context': {**original, 'owner_context': current}, 'evidence': {}}

    def reconcile_original(self, job_context):
        """Exact reads only. Does not release, resume, replay or start a new lease."""
        known = self._completed.get(job_context.get('job_id'))
        if known is not None and known['cleanup_certainty'] == 'confirmed':
            return deepcopy(known)
        owner = job_context.get('owner_context', job_context)
        ids = owner.get('original_request_ids', [])
        if not isinstance(ids, list) or not ids:
            return {**self._blocked('original_request_identity_missing', job_context), 'state': 'unknown',
                    'effect_certainty': 'unknown', 'cleanup_certainty': 'unknown'}
        evidence = []
        try:
            records = {rid: self.runtime._journal['records'][rid] for rid in ids if rid in self.runtime._journal['records']}
            missing = set(ids) - set(records)
            for ref in reversed(self.runtime._journal.get('segments', [])):
                if not missing:
                    break
                archived = self.runtime._read_evidence(ref, 'segment')['records']
                for rid in missing.intersection(archived):
                    records[rid] = archived[rid]
                missing.difference_update(records)
            for rid in ids:
                record = records.get(rid)
                if record is None or record.get('job_id') != job_context.get('job_id'):
                    raise SkillError('original_job_record_mismatch')
                receipt = self.runtime.client.result(rid)
                if receipt is not None and (receipt.get('request_id') != rid or receipt.get('session_id') != record['gateway_session']):
                    raise SkillError('reconciliation_identity_changed')
                evidence.append({'request_id': rid, 'receipt': deepcopy(receipt)})
        except Exception as exc:
            return {'state': 'unknown', 'reason': 'exact_reconciliation_unconfirmed:' + type(exc).__name__,
                    'effect_certainty': 'unknown', 'cleanup_certainty': 'unknown', 'result': known and known.get('result'),
                    'request_ids': list(ids), 'context': _public_context(job_context), 'evidence': {'original_reads': evidence}}
        return {'state': 'unknown', 'reason': 'original_receipts_read_no_auto_resume_or_release',
                'effect_certainty': known.get('effect_certainty','unknown') if known else 'unknown',
                'cleanup_certainty': 'unknown', 'result': known and known.get('result'),
                'request_ids': list(ids), 'context': _public_context(job_context), 'evidence': {'original_reads': evidence}}

    def observe(self, profile, selectors, bounds):
        if profile == 'memory':
            from .bindings.memory import read
            try:
                context = self.runtime.client.session().get('capability_context')
            except Exception:
                context = None
            return read(self.runtime, selectors, bounds, trusted_context=context)
        if profile not in ('player','inventory','menu','entities','local_terrain','survey'):
            raise SkillError('observation_profile_unavailable')
        if selectors:
            raise SkillError('observation_selectors_unavailable')
        if set(bounds) - {'radius','vertical','entity_radius','max_age_ms'}:
            raise SkillError('observation_bounds_unavailable')
        if not self._lock.acquire(blocking=False):
            raise SkillError('observation_owner_busy')
        begun = False
        try:
            description = self.describe()
            if not description.get('available') or not description.get('private_singleplayer'):
                raise SkillError('observation_runtime_unavailable')
            context = {'job_id': uuid.uuid4().hex, 'request_id': uuid.uuid4().hex,
                       'deadline_at': time.time() + 30, 'budget': {'max_actions': 1, 'max_observations': 3},
                       'policy': {'version': 1, 'execution_mode': 'noncombat', 'reactions': 'stop'}}
            self.runtime.begin_job(JobControl(context)); begun = True
            options = {k: bounds[k] for k in ('radius','vertical','entity_radius') if k in bounds}
            observation = (self.runtime.survey(allow_menu=True, **options) if profile == 'survey' else
                           self.runtime.observe(terrain=profile == 'local_terrain', allow_menu=True, **options))
            result = {'profile': profile, 'state': deepcopy(observation.state), 'terrain': deepcopy(observation.terrain),
                      'request_id': observation.request_id, 'context_ref': _ref(dict(zip(
                          ('world_generation','dimension','player_uuid','action_session'), observation.context))),
                      'age_ms': max(0, (self.runtime.clock() - observation.captured_at) * 1000),
                      'execution_authority': False, 'historical': profile == 'survey',
                      'source_clock': {'domain': 'native-system-nanotime',
                          'source_tick': observation.state.get('capability_guard', {}).get('source_tick'),
                          'source_nano': observation.state.get('capability_guard', {}).get('source_nano')},
                      'source_times': {'runtime_capture_monotonic': observation.captured_at,
                          'age_at_response_ms': max(0, (self.runtime.clock() - observation.captured_at) * 1000)},
                      'provenance': {'original_request_id': observation.request_id,
                          'world_context': list(observation.context), 'historical_pages':
                          deepcopy((observation.terrain or {}).get('source_pages', [])),
                          'grants_dispatch_authority': False},
                      'coverage': {'profile': profile,
                          'terrain_complete': (observation.terrain or {}).get('complete') if observation.terrain is not None else None,
                          'entities_truncated': observation.state.get('nearby', {}).get('truncated'),
                          'inventory_truncated': observation.player.get('inventory_truncated'),
                          'menu_slots_truncated': observation.state.get('menu', {}).get('slots_truncated')},
                      'server_confirmed': False}
            wire = observation.raw.get('native_capability_wire')
            if wire is not None:
                # Raw bytes stay once in the archived receipt/data, not duplicated into public output.
                result['provenance'].update(state_representation='decoded-semantic-native-siblings',
                    native_wire_encoding=wire['encoding'], native_wire_bytes=wire['bytes'],
                    native_wire_sha256=wire['sha256'])
        finally:
            if begun:
                release = self.runtime.finish_job()
                if not release.ok:
                    self._lock.release()
                    raise SkillError('observation_owner_release_unconfirmed', status='unknown')
            self._lock.release()
        return result


def create_backend(control_directory, runtime_journal_directory):
    """Operator-only fixed factory. No action, rearm, login or game launch."""
    import sys
    source = Path(__file__).resolve().parents[2]
    watchdog = source / 'defense-watchdog'
    if str(watchdog) not in sys.path:
        sys.path.insert(0, str(watchdog))
    from intent_client import IntentClient
    return OwnerRuntimeBackend(Runtime(IntentClient(control_directory), runtime_journal_directory))

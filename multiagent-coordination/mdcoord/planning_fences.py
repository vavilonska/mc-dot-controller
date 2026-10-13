"""Owner-local issuance registry for immutable planning source/deadline fences.

This is freshness lineage, not worker identity or a security sandbox. Once an
owner captures a planning source, all subsequent submissions require a receipt
that THIS owner issued. Caller-provided role/origin/deadline text is insufficient.
"""
import hashlib
import json
import uuid

from .schema import Proposal, canonical, integer, number, require


_SAMPLE_FIELDS = ('sample_id', 'content_revision', 'continuity_revision',
                  'capture_started_mono', 'capture_finished_mono', 'expires_mono')


class PlanningFenceStore:
    def __init__(self):
        self.required = False
        self.sources = {}
        self.bindings = {}

    def reset_task(self):
        # The gate stays enabled. New task identity cannot resurrect old receipts.
        self.sources.clear()
        self.bindings.clear()

    def capture(self, snapshot, lease, now):
        require(type(lease) is dict, 'planning_lease_required')
        require(snapshot['context'] is not None and snapshot['clock_epoch'] == lease['clock_epoch'],
                'planning_source_context')
        require(now < min(lease['expires_mono'], lease['task_deadline_mono']), 'planning_lease_expired')
        require(len(self.sources) < 128, 'planning_source_capacity')
        frozen = json.loads(canonical({'snapshot': snapshot, 'lease': lease}))
        sid = uuid.uuid4().hex
        self.sources[sid] = {**frozen, 'issued_mono': now}
        self.required = True
        return {**json.loads(canonical(frozen)), 'source_id': sid, 'issued_mono': now}

    def _source_check(self, source, proposal, snapshot, lease, now, deadline, *, renewal=False):
        require(type(lease) is dict, 'planning_lease_required')
        require(now < deadline, 'planning_absolute_deadline_expired')
        original = source['snapshot']
        require(snapshot['clock_epoch'] == original['clock_epoch'] == lease['clock_epoch'] and
                snapshot['context'] == original['context'] == proposal['context'], 'planning_source_session_fence')
        for key in ('task_id', 'epoch'):
            require(lease[key] == source['lease'][key] == proposal['task_id' if key == 'task_id' else 'epoch'],
                    'planning_source_task_fence')
        if not renewal:
            require(lease['revision'] == source['lease']['revision'] == proposal['lease_revision'],
                    'planning_source_lease_revision')
        required = {'player', 'entities'} | set(proposal['based_on'])
        if proposal['intent']['kind'] == 'follow_path':
            required.add('terrain')
        limit = min(source['lease']['expires_mono'], source['lease']['task_deadline_mono'])
        for name in required:
            old = original['sections'].get(name)
            current = snapshot['sections'].get(name)
            require(old is not None and old['freshness'] == 'fresh' and old['expires_mono'] is not None,
                    'planning_original_source_not_fresh')
            require(current is not None and current['freshness'] == 'fresh' and
                    all(current[key] == old[key] for key in _SAMPLE_FIELDS),
                    'planning_source_sample_changed')
            limit = min(limit, old['expires_mono'])
        require(deadline <= limit, 'planning_deadline_extension')
        require(now < deadline, 'planning_absolute_deadline_expired')
        require(now < min(lease['expires_mono'], lease['task_deadline_mono']), 'planning_lease_expired')

    def seal(self, proposal, source_id, deadline, snapshot, lease, now):
        require(type(proposal) is dict and 'planning_fence' not in proposal, 'planning_receipt_already_present')
        number(deadline, 0, 1e15)
        require(source_id in self.sources, 'planning_source_receipt_unknown')
        require(proposal.get('proposal_id') not in self.bindings, 'planning_candidate_already_sealed')
        require(len(self.bindings) < 512, 'planning_candidate_capacity')
        fence = {'source_id': source_id, 'deadline_mono': deadline, 'clock_epoch': snapshot['clock_epoch']}
        data = Proposal.parse({**proposal, 'planning_fence': fence}).wire()
        self._source_check(self.sources[source_id], data, snapshot, lease, now, deadline)
        self.bindings[data['proposal_id']] = {'fence': fence,
            'digest': hashlib.sha256(canonical(data)).hexdigest()}
        return json.loads(canonical(data))

    def verify(self, proposal, snapshot, lease, now, *, renewal=False):
        fence = proposal.get('planning_fence')
        binding = self.bindings.get(proposal['proposal_id'])
        if fence is None:
            require(not self.required and binding is None, 'planning_source_receipt_required')
            return None
        require(binding is not None and fence == binding['fence'], 'planning_receipt_unknown_or_changed')
        require(not binding.get('revoked', False), 'planning_candidate_revoked')
        require(hashlib.sha256(canonical(proposal)).hexdigest() == binding['digest'],
                'planning_sealed_candidate_changed')
        source = self.sources.get(fence['source_id'])
        require(source is not None, 'planning_source_receipt_unknown')
        self._source_check(source, proposal, snapshot, lease, now, fence['deadline_mono'], renewal=renewal)
        return fence['deadline_mono']

    def finish_source(self, source_id, submitted_ids):
        for proposal_id, binding in self.bindings.items():
            if binding['fence']['source_id'] == source_id and proposal_id not in submitted_ids:
                binding['revoked'] = True

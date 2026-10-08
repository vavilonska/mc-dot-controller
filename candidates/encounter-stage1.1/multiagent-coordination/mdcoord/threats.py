"""Explicit offline-owner threat assessments; never synthesized from entity revisions.

The observation schema has no entity position, reach, or threat radius. A fresh or
empty entity list is therefore NOT a navigation clearance. This separate owner API
accepts a bounded, independently assessed synthetic/offline assertion only. It is
not exposed on PlannerPort and is not an authentication or live-game safety layer.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from threading import RLock

from .schema import Context, Rejected, canonical, identifier, integer, number, require
from .snapshots import Acquisition


def _position(value):
    require(type(value) is tuple and len(value) == 3, 'threat_invalid_position')
    for axis, coordinate in enumerate(value):
        number(coordinate, -2048 if axis == 1 else -30_000_000,
               2048 if axis == 1 else 30_000_000)


@dataclass(frozen=True)
class ThreatClearance:
    """Immutable owner input. Neither a planner assertion nor resident evidence.

    Supply exactly one coverage form: a finite axis-aligned bounds tuple, or an
    exact centered start and ordered waypoint tuple. Assessment validity applies
    to the covered swept corridor, including threats capable of reaching into it;
    it does not merely mean that entity centers were absent from those points.
    """
    proof_id: str
    context: Context
    entities_sample_id: int
    entities_content_revision: int
    acquisition: Acquisition
    ttl_ms: int
    complete: bool
    no_threats: bool
    valid: bool
    bounds: tuple | None = None
    start: tuple | None = None
    waypoints: tuple | None = None

    def __post_init__(self):
        identifier(self.proof_id)
        require(type(self.context) is Context, 'threat_invalid_context')
        integer(self.entities_sample_id, 1, 2**63 - 1)
        integer(self.entities_content_revision, 1, 2**63 - 1)
        require(type(self.acquisition) is Acquisition, 'threat_invalid_acquisition')
        identifier(self.acquisition.clock_epoch)
        # Only offline evidence is supported. No live adapter currently produces
        # the positional, coverage, completeness and provenance evidence needed.
        require(self.acquisition.source_clock == 'fixture_wall', 'threat_offline_assessment_only')
        number(self.acquisition.start_mono, 0, 1e15)
        number(self.acquisition.end_mono, self.acquisition.start_mono, 1e15)
        if self.acquisition.source_time_ms is not None:
            number(self.acquisition.source_time_ms, 0, 1e15)
        if self.acquisition.source_tick is not None:
            integer(self.acquisition.source_tick, 0, 2**63 - 1)
        integer(self.ttl_ms, 50, 3000)
        require(all(type(value) is bool for value in (self.complete, self.no_threats, self.valid)),
                'threat_boolean_required')
        if self.bounds is not None:
            require(self.start is None and self.waypoints is None, 'threat_coverage_ambiguous')
            require(type(self.bounds) is tuple and len(self.bounds) == 6, 'threat_invalid_bounds')
            _position(self.bounds[:3]); _position(self.bounds[3:])
            # Local proof, not an unbounded world-wide assertion. Routes are at
            # most 16 unit steps; a 64-block box leaves bounded surrounding space.
            require(all(0 <= self.bounds[i + 3] - self.bounds[i] <= 64 for i in range(3)),
                    'threat_bounds_too_large')
        else:
            _position(self.start)
            require(type(self.waypoints) is tuple and 1 <= len(self.waypoints) <= 16,
                    'threat_waypoint_bound')
            previous = self.start
            for current in (self.start,) + self.waypoints:
                _position(current)
                require(current[0] % 1 == .5 and current[2] % 1 == .5 and current[1] % 1 == 0,
                        'threat_flat_centered_route_required')
            for current in self.waypoints:
                require(current[1] == previous[1] and
                        abs(current[0] - previous[0]) + abs(current[2] - previous[2]) == 1,
                        'threat_nonadjacent_or_vertical_route')
                previous = current

    def wire(self):
        return {'proof_id': self.proof_id, 'context': self.context.wire(),
                'entities_sample_id': self.entities_sample_id,
                'entities_content_revision': self.entities_content_revision,
                'acquisition': dict(vars(self.acquisition)), 'ttl_ms': self.ttl_ms,
                'complete': self.complete, 'no_threats': self.no_threats, 'valid': self.valid,
                'bounds': self.bounds, 'start': self.start, 'waypoints': self.waypoints,
                'origin': 'offline_owner_assessment'}


class ThreatStore:
    """Bounded, in-memory owner store; a restart never recovers proof freshness.

    Receipt-time proof IDs can be pinned by the coordinator. Replacing or renewing
    an assessment cannot revive a queued plan whose original proof has expired,
    been revoked, or ceased to match the latest entity sample.
    """
    def __init__(self, clock, *, epoch):
        identifier(epoch)
        self.clock, self.epoch = clock, epoch
        self._lock = RLock()
        self._proofs = {}
        self._acquisition_expiry = {}
        self._capture_origins = {}
        self._interval_expiry = {}
        self._watermarks = {}
        self._unsafe_watermarks = {}
        self._revoked = set()
        self._revoked_captures = set()
        self._revoked_intervals = set()
        self._blocked = False

    def publish(self, proof):
        require(type(proof) is ThreatClearance, 'owner_threat_clearance_required')
        # Revalidate even a mutated/forged dataclass before copying owned bytes.
        ThreatClearance(**vars(proof))
        data = proof.wire()
        require(proof.acquisition.clock_epoch == self.epoch, 'threat_foreign_monotonic_clock')
        now = self.clock()
        number(proof.acquisition.start_mono, 0, now)
        number(proof.acquisition.end_mono, proof.acquisition.start_mono, now)
        content = {key: value for key, value in data.items() if key not in ('ttl_ms', 'proof_id')}
        digest = hashlib.sha256(canonical(content)).hexdigest()
        acquisition = data['acquisition']
        context_key = canonical(data['context'])
        source = {'context': data['context'], 'clock_epoch': acquisition['clock_epoch'],
                  'source_clock': acquisition['source_clock'], 'source_tick': acquisition['source_tick'],
                  'source_time_ms': acquisition['source_time_ms']}
        if acquisition['source_tick'] is None and acquisition['source_time_ms'] is None:
            # No external capture identity: one origin per entities sample is
            # conservative. Merely relabeling a read as a new interval cannot
            # establish an independently acquired threat assessment.
            source['entities_sample_id'] = proof.entities_sample_id
        capture = hashlib.sha256(canonical(source)).hexdigest()
        # TTL always begins at original acquisition START. A longer finish
        # interval plus a changed source stamp cannot create a renewed capture.
        interval = hashlib.sha256(canonical({'context': data['context'],
            'clock_epoch': acquisition['clock_epoch'],
            'start_mono': acquisition['start_mono']})).hexdigest()
        with self._lock:
            prior = self._proofs.get(proof.proof_id)
            if prior is not None:
                require(prior['digest'] == digest, 'threat_proof_id_payload_conflict')
                return self.read(proof.proof_id)
            if len(self._proofs) >= 256:
                # An unrecordable assessment could be negative. Do not leave an
                # older positive usable when the bounded owner store is full.
                self._blocked = True
                raise Rejected('threat_proof_capacity')
            clear = proof.complete and proof.no_threats and proof.valid
            origin = (proof.acquisition.start_mono, proof.acquisition.end_mono)
            recorded_origin = self._capture_origins.get(capture)
            marks = self._watermarks.get(context_key)
            unsafe = self._unsafe_watermarks.get(context_key)
            if clear:
                require(recorded_origin is None or recorded_origin == origin, 'threat_capture_retimestamped')
                if marks is not None:
                    require(origin[0] >= marks['start_mono'] and origin[1] >= marks['end_mono'],
                            'threat_observation_time_reversed')
                    for field in ('source_tick', 'source_time_ms'):
                        if marks[field] is not None:
                            require(acquisition[field] is not None and acquisition[field] >= marks[field],
                                    'threat_source_time_reversed_or_unknown')
                if unsafe is not None:
                    require(origin[0] > unsafe['start_mono'] and
                            any(acquisition[field] is not None and unsafe[field] is not None and
                                acquisition[field] > unsafe[field]
                                for field in ('source_tick', 'source_time_ms')),
                            'threat_clearance_not_newer_than_hazard')
            # Negative evidence always invalidates old positives, even if the
            # submitted negative capture is old or has incomplete provenance.
            # Only a genuinely newer positive assessment can clear that latch.
            expiry = (recorded_origin or origin)[0] + proof.ttl_ms / 1000
            # New IDs/import/read time cannot extend an already-known capture.
            expiry = min(expiry, self._acquisition_expiry.get(capture, expiry),
                         self._interval_expiry.get(interval, expiry))
            self._acquisition_expiry[capture] = expiry
            self._interval_expiry[interval] = expiry
            self._capture_origins.setdefault(capture, origin)
            merged = dict(acquisition)
            if marks is not None:
                for field in ('start_mono', 'end_mono', 'source_tick', 'source_time_ms'):
                    if marks[field] is not None:
                        merged[field] = max(merged[field], marks[field]) if merged[field] is not None else marks[field]
            self._watermarks[context_key] = merged
            if not clear:
                self._unsafe_watermarks[context_key] = merged
                # Conservatively revoke every older proof for this context.
                # A later positive assertion cannot resurrect those pinned IDs.
                for pid, entry in self._proofs.items():
                    if json.loads(entry['encoded'])['context'] == data['context']:
                        self._revoke_evidence(pid)
            self._proofs[proof.proof_id] = {'encoded': canonical(data), 'digest': digest,
                                           'expires_mono': expiry, 'capture': capture, 'interval': interval}
            return self.read(proof.proof_id)

    def _revoke_evidence(self, proof_id):
        # Revoke the captured evidence, not merely one caller-chosen label.
        # These sets are bounded by the store's 256 stored proof entries.
        entry = self._proofs[proof_id]
        self._revoked.add(proof_id)
        self._revoked_captures.add(entry['capture'])
        self._revoked_intervals.add(entry['interval'])

    def revoke(self, proof_id):
        """Owner-only invalidation; never an extension of freshness."""
        identifier(proof_id)
        with self._lock:
            require(proof_id in self._proofs, 'threat_proof_missing')
            self._revoke_evidence(proof_id)

    def read(self, proof_id):
        identifier(proof_id)
        with self._lock:
            require(proof_id in self._proofs, 'threat_proof_missing')
            entry = self._proofs[proof_id]
            return {**json.loads(entry['encoded']),
                    'expires_mono': min(entry['expires_mono'], self._acquisition_expiry[entry['capture']],
                                        self._interval_expiry[entry['interval']]),
                    'revoked': (proof_id in self._revoked or
                                entry['capture'] in self._revoked_captures or
                                entry['interval'] in self._revoked_intervals)}

    @staticmethod
    def _covers(proof, start, waypoints):
        route = [[p[key] for key in ('x', 'y', 'z')] for p in [start, *waypoints]]
        if proof['bounds'] is not None:
            bounds = proof['bounds']
            return all(all(bounds[axis] <= p[axis] <= bounds[axis + 3] for axis in range(3))
                       for p in route)
        return proof['start'] == route[0] and proof['waypoints'] == route[1:]

    def require_clearance(self, snapshot, start, waypoints, *, proof_id=None):
        """Validate latest entities and a complete, bounded, unexpired assessment.

        No selection fallback exists when an explicit (receipt-time) ID is given.
        Returns the ID to pin at proposal receipt and recheck at dispatch.
        """
        entities = snapshot['sections'].get('entities')
        require(entities is not None, 'entities_missing')
        require(entities.get('freshness') == 'fresh', 'entities_not_fresh')
        require(entities['data'].get('truncated') is False, 'entities_incomplete')
        require(snapshot.get('clock_epoch') == self.epoch and entities.get('clock_epoch') == self.epoch,
                'threat_foreign_monotonic_clock')
        require(type(entities.get('sample_id')) is int, 'entities_sample_unknown')
        require(type(entities.get('content_revision')) is int, 'entities_revision_unknown')
        with self._lock:
            require(not self._blocked, 'threat_store_blocked')
            if proof_id is None:
                # Newest relevant assertion wins; never fall back to an older
                # positive proof because a newer one is invalid or has expired.
                matching = [pid for pid in self._proofs
                            if (self.read(pid)['context'] == snapshot['context'] and
                                self._covers(self.read(pid), start, waypoints))]
                require(bool(matching), 'threat_proof_missing')
                proof_id = matching[-1]
            proof = self.read(proof_id)
            require(proof['context'] == snapshot['context'] == entities['context'], 'threat_context_changed')
            require(proof['entities_sample_id'] == entities['sample_id'], 'threat_entities_sample_changed')
            require(proof['entities_content_revision'] == entities['content_revision'],
                    'threat_entities_content_changed')
            capture_finished = entities.get('capture_finished_mono')
            require(type(capture_finished) in (int, float) and
                    proof['acquisition']['end_mono'] >= capture_finished,
                    'threat_assessment_predates_entities')
            require(self._covers(proof, start, waypoints), 'threat_coverage_mismatch')
            require(not proof['revoked'], 'threat_proof_revoked')
            require(proof['valid'] is True and proof['complete'] is True and proof['no_threats'] is True,
                    'threat_not_cleared')
            now = self.clock()
            require(proof['acquisition']['start_mono'] <= proof['acquisition']['end_mono'] <= now,
                    'threat_capture_in_future')
            require(now < proof['expires_mono'], 'threat_proof_expired')
            expiry = entities.get('expires_mono')
            require(type(expiry) in (int, float) and now < expiry, 'entities_not_fresh')
            return proof_id

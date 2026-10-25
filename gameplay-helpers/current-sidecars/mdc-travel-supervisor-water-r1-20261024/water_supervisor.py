"""Water-first sibling of frozen travel supervisor r1.1. Import is side-effect free."""
import copy
import math
import uuid
from travel_supervisor import Supervisor, KnownStop, context, neutral, unknown


class WaterFirstSupervisor(Supervisor):
    """Own only flotation (no guessed shore route); original UNKNOWN remains read-only."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._recover_bodies = {}
        self._previous_air = None
        self._air_falling = False

    def request(self, method, path, payload=None):
        reply = super().request(method, path, payload)
        if method == 'GET' and path.split('?', 1)[0] == '/control/state' and reply[0] == 200:
            p = reply[1].get('player', {})
            air, maximum = p.get('air'), p.get('max_air')
            if all(type(v) in (int, float) and math.isfinite(v) for v in (air, maximum)):
                if self._previous_air is not None and air < self._previous_air and air < maximum:
                    self._air_falling = True
                if air >= maximum:
                    self._air_falling = False
                self._previous_air = air
        return reply

    def water_risk(self, s):
        p = s.get('player', {})
        return p.get('in_water') is True or p.get('eye_in_water') is True or self._air_falling

    def _reconcile(self, s):
        super()._reconcile(s)
        p = self.pending
        if not p or p.get('pre') or p.get('exists_after_pre'):
            return
        b, st = p['body'], p.get('status')
        if b != self._recover_bodies.get(b.get('action_id')) or not isinstance(st, dict):
            return
        r = st.get('result')
        # Recovery is legacy in the current JAR: do not fabricate a native release.
        # Only these normal terminal paths are covered, not arbitrary callback failure.
        allowed = {('succeeded', 'environment_dry_observed'),
                   ('failed', 'deadline_exceeded'), ('cancelled', 'cancel_requested')}
        if ((st.get('status'), st.get('reason')) not in allowed
                or st.get('action_id') != b['action_id']
                or st.get('action') != 'recover_environment'
                or st.get('action_session') != b['expected_action_session']
                or not isinstance(r, dict) or 'input_release_confirmed' in r
                or 'input_release_diagnostics' in r or unknown(st)):
            return
        a = s.get('client_action', {})
        if (not self.available(s) or not neutral(s) or not self._owned_inputs(s)
                or context(s) != self.ctx or a.get('action_id') != b['action_id']
                or a.get('action') != 'recover_environment'
                or a.get('action_session') != b['expected_action_session']
                or a.get('status') != st['status'] or a.get('reason') != st['reason']
                or 'input_release_diagnostics' in (a.get('result') or {}) or unknown(a)):
            return
        self.last_resolution = {'action_id': b['action_id'], 'known': True,
            'status': st['status'], 'terminal': copy.deepcopy(st),
            'release_basis': 'own_legacy_recovery_then_fresh_same_id_direct_neutral'}
        self.note('supervisor_original_resolved', **self.last_resolution)
        self.pending = None

    def action_once(self, body):
        # A known travel endpoint in water must not proceed to the next mission action.
        # Original pending/raw UNKNOWN is always resolved by the inherited owner loop.
        if not self.pending and not self.raw_pending:
            s = self.state(0)
            if self.water_risk(s):
                raise KnownStop('water_priority_return_to_owner_loop')
        result = super().action_once(body)
        if self.water_risk(self.state(0)):
            raise KnownStop('water_at_known_endpoint_return_to_owner_loop')
        return result

    def defend_step(self):
        if self.pending or self.raw_pending:
            self.resolve_step(self.handoff_requested())
            return
        s = self.state(0)
        if not self.available(s) or not self._owned_inputs(s):
            raise KnownStop('water_defense_owner_or_context_changed')
        if not self.water_risk(s):
            return super().defend_step()
        # This only releases a known key.use owned by this instance. Uncertain down
        # or up remains raw_pending; neither a recover nor a second up may follow it.
        self.shield(False, s)
        s = self.state(0)
        if not self.available(s) or not neutral(s) or not self._owned_inputs(s):
            raise KnownStop('water_recovery_requires_fresh_neutral')
        if not self.water_risk(s):
            return
        b = {'action_id': str(uuid.uuid4()), 'action': 'recover_environment',
             'timeout_ms': 15000, 'waypoints': [],
             'expected_world_generation': self.ctx[0], 'expected_player_uuid': self.ctx[2],
             'expected_action_session': self.ctx[4]}
        self._recover_bodies[b['action_id']] = copy.deepcopy(b)
        self.mode = 'WATER_NATIVE_RECOVERY'
        self.reason = 'fresh_water_or_falling_air_no_guessed_shore'
        # One POST only. The inherited loop reads this ID to terminal. A later
        # known 15s deadline + fresh water starts another NEW bounded segment.
        self.request('POST', '/control/action', b)

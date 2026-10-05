"""Health-drop awareness and sticky hostile selection. No game I/O or hit attribution."""
from __future__ import annotations
import math

DAMAGE_WINDOW = 2.0
MISSING_GRACE = .8
UNREACHABLE_GRACE = 3.0
MIN_TARGET_HOLD = 2.0
RESELECT_COOLDOWN = 2.0
EXCLUDE_OLD_FOR = 4.0
WAITING_PHASES = {'waiting_in_range', 'waiting_target_crosshair', 'refreshing_approach', 'approaching'}


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


class TargetPolicy:
    def __init__(self, hostile_types):
        self.hostile_types = hostile_types
        self.identity, self.last_health = None, None
        self.last_damage = None
        self.damage_until = -math.inf
        self.locked_uuid = None
        self.acquired_at = self.last_started_at = -math.inf
        self.last_selected_uuid = None
        self.last_switch_at = -math.inf
        self.switches = 0
        self.missing_since = self.unreachable_since = None
        self.last_dispatches = 0
        self.preferred_uuid = None
        self.excluded = {}
        self.reason = 'no_target'

    def observe_health(self, state, now):
        p = state.get('player', {})
        identity = (state.get('world', {}).get('world_generation'), p.get('uuid'))
        health = p.get('health')
        if identity != self.identity:
            self.identity, self.last_health = identity, None
            self.damage_until, self.last_damage = -math.inf, None
        damaged = finite(health) and finite(self.last_health) and health < self.last_health - 1e-6
        if damaged:
            self.last_damage = {'health_before': self.last_health, 'health_after': health,
                                'observed_at_monotonic': now, 'source': 'unknown', 'attacker_uuid': None}
            self.damage_until = now + DAMAGE_WINDOW
        self.last_health = health if finite(health) else None
        return damaged

    def recent_damage(self, now):
        return now <= self.damage_until

    def enemies(self, state, radius=8):
        return [e for e in state.get('nearby', {}).get('entities', [])
                if e.get('type') in self.hostile_types and e.get('alive') is True
                and isinstance(e.get('uuid'), str) and finite(e.get('distance'))
                and 0 <= e['distance'] <= radius
                and (e.get('health') is None or (finite(e['health']) and e['health'] > 0))]

    def choose(self, state, now, *, exclude=()):
        self.excluded = {k: until for k, until in self.excluded.items() if until > now}
        choices = [e for e in self.enemies(state, 8 if self.recent_damage(now) else 6)
                   if e['uuid'] not in self.excluded and e['uuid'] not in exclude]
        preferred = next((e for e in self.enemies(state, 8) if e['uuid'] == self.preferred_uuid
                          and e['uuid'] not in self.excluded and e['uuid'] not in exclude), None)
        return preferred or min(choices, key=lambda e: (e['distance'], e['uuid']), default=None)

    def lock(self, target_uuid, now):
        if target_uuid != self.locked_uuid:
            if self.last_selected_uuid is not None and target_uuid != self.last_selected_uuid:
                self.last_switch_at = now
                self.switches += 1
            self.last_selected_uuid = target_uuid
            self.locked_uuid, self.acquired_at = target_uuid, now
            self.missing_since = self.unreachable_since = None
            self.last_dispatches = 0
        self.last_started_at = now
        self.preferred_uuid, self.reason = None, 'keeping_selected_uuid'

    def release(self, now, reason, *, avoid=False):
        if avoid and self.locked_uuid:
            self.excluded[self.locked_uuid] = now + EXCLUDE_OLD_FOR
        self.locked_uuid = None
        self.missing_since = self.unreachable_since = None
        self.reason = reason

    def prepare_retarget(self, candidate, now):
        self.release(now, 'persistent_unreachable_select_alternative', avoid=True)
        self.preferred_uuid = candidate['uuid']
        return 'retarget', candidate

    def assess(self, state, combat, now):
        """Return keep/wait/released/reacquire/retarget/error, with detail.

        New damage is deliberately not a switching signal. It affects admission
        only when no viable target is already owned.
        """
        active = combat.get('active') is True
        actual = combat.get('target_uuid')
        if active and actual and actual != self.locked_uuid:
            self.lock(actual, now)
        if not self.locked_uuid:
            return 'released', None
        target = next((e for e in self.enemies(state) if e['uuid'] == self.locked_uuid), None)
        if active:
            if target is None:
                if self.missing_since is None: self.missing_since = now
                self.reason = 'waiting_for_resident_target_loss'
                return 'keep', None  # The resident owns immediate life/UUID checks.
            self.missing_since = None
            dispatches = combat.get('attack_dispatches', 0)
            progressed = type(dispatches) is int and dispatches > self.last_dispatches
            if type(dispatches) is int: self.last_dispatches = dispatches
            waiting = combat.get('phase') in WAITING_PHASES
            if not waiting or progressed:
                self.unreachable_since = None
                self.reason = 'keeping_attackable_target'
                return 'keep', target
            if self.unreachable_since is None: self.unreachable_since = now
        else:
            reason = str(combat.get('reason', 'missing_combat_status'))
            if any(word in reason for word in ('target_dead', 'target_no_longer_alive')):
                self.release(now, 'target_dead_select_next', avoid=True)
                return 'released', None
            if any(word in reason for word in ('target_missing', 'target_lost')):
                if self.missing_since is None: self.missing_since = now
                if target and now - self.last_started_at >= MISSING_GRACE:
                    previous = self.locked_uuid
                    self.release(now, 'reacquire_same_uuid_after_brief_loss')
                    self.preferred_uuid = previous
                    return 'reacquire', target
                if now - self.missing_since < MISSING_GRACE:
                    self.reason = 'target_loss_hysteresis'
                    return 'wait', None
                self.release(now, 'target_missing_after_grace', avoid=True)
                return 'released', None
            if 'flat_approach_blocked' in reason:
                if target is None:
                    raw = next((e for e in state.get('nearby', {}).get('entities', [])
                                if e.get('uuid') == self.locked_uuid), None)
                    dead = raw is not None and (raw.get('alive') is False
                                               or (finite(raw.get('health')) and raw['health'] <= 0))
                    if self.missing_since is None: self.missing_since = now
                    if dead or now - self.missing_since >= MISSING_GRACE:
                        self.release(now, 'stopped_target_dead_or_missing', avoid=True)
                        return 'released', None
                    self.reason = 'stopped_target_loss_hysteresis'
                    return 'wait', None
                self.missing_since = None
                crosshair = state.get('crosshair', {})
                reach = crosshair.get('distance_euclidean')
                if (crosshair.get('type') == 'entity' and crosshair.get('uuid') == self.locked_uuid
                        and finite(reach) and 0 <= reach <= 3
                        and now - self.last_started_at >= MISSING_GRACE):
                    previous = self.locked_uuid
                    self.release(now, 'blocked_target_now_reachable_keep_uuid')
                    self.preferred_uuid = previous
                    return 'reacquire', target
                if self.unreachable_since is None: self.unreachable_since = now
            else:
                return 'error', reason
        if (now - self.unreachable_since >= UNREACHABLE_GRACE
                and now - self.acquired_at >= MIN_TARGET_HOLD
                and now - self.last_switch_at >= RESELECT_COOLDOWN):
            alternative = self.choose(state, now, exclude=(self.locked_uuid,))
            if alternative:
                return self.prepare_retarget(alternative, now)
            if not active:
                self.release(now, 'stopped_unreachable_without_alternative', avoid=True)
                return 'released', None
        self.reason = 'keeping_target_until_unreachable_grace'
        return ('keep' if active else 'wait'), target

    def status(self, now):
        return {'target_uuid': self.locked_uuid, 'reason': self.reason,
                'last_health_drop': self.last_damage,
                'damage_source_available': False, 'recent_health_drop': self.recent_damage(now),
                'switches': self.switches, 'missing_grace_seconds': MISSING_GRACE,
                'unreachable_grace_seconds': UNREACHABLE_GRACE,
                'minimum_target_hold_seconds': MIN_TARGET_HOLD,
                'reselect_cooldown_seconds': RESELECT_COOLDOWN}

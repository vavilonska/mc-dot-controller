"""Pure native position binding. No I/O, retries, queue discovery or clock authority.

Identical copies accompany the two standalone helpers; contract tests verify bytes.
Capability knowledge is sticky for its caller's observation/owner lifetime.
"""
from copy import deepcopy
import math

NAVIGATION_REJECTIONS = frozenset(('navigation_rebind_required', 'navigation_epoch_changed',
                                   'navigation_not_settled', 'navigation_origin_changed'))


class NavigationNotReady(ValueError):
    pass


class NativeBindingContext:
    def __init__(self, saved=None):
        if saved is not None and (not isinstance(saved, dict) or type(saved.get('seen')) is not bool):
            raise ValueError('navigation_binding_checkpoint_invalid')
        self.seen = saved['seen'] if saved is not None else False

    def dump(self):
        return {'seen': self.seen}

    def observe(self, state):
        world = state.get('world', {}) if isinstance(state, dict) else {}
        if not isinstance(world, dict):
            raise ValueError('navigation_guard_invalid_world')
        if 'navigation_guard' not in world:
            if self.seen:
                raise ValueError('navigation_guard_missing_after_seen')
            return {}
        self.seen = True  # Presence, including invalid/null, cannot downgrade later.
        g = world['navigation_guard']
        if not isinstance(g, dict) or type(g.get('schema_version')) is not int or g['schema_version'] != 1:
            raise ValueError('navigation_guard_invalid_schema')
        if type(g.get('epoch')) is not int or not 0 <= g['epoch'] <= 2**53 - 1:
            raise ValueError('navigation_guard_invalid_epoch')
        if type(g.get('rebind_ready')) is not bool or type(g.get('fresh_binding_required')) is not bool:
            raise ValueError('navigation_guard_invalid_readiness')
        if (type(g.get('stable_ticks')) is not int or not 0 <= g['stable_ticks'] <= 3
                or g['rebind_ready'] != (g['stable_ticks'] == 3)):
            raise ValueError('navigation_guard_invalid_stable_ticks')
        p, a = state.get('player'), state.get('client_action')
        if not isinstance(p, dict) or not isinstance(a, dict):
            raise ValueError('navigation_guard_invalid_context')
        identity = (world.get('world_generation'), world.get('dimension'), p.get('uuid'), a.get('action_session'))
        if not all(isinstance(v, str) and v for v in identity):
            raise ValueError('navigation_guard_invalid_context')
        if 'dimension' in p and p['dimension'] != identity[1]:
            raise ValueError('navigation_guard_invalid_context')
        origin = {k: p.get(k) for k in ('x', 'y', 'z')}
        if not all(type(v) in (int, float) and math.isfinite(v) for v in origin.values()):
            raise ValueError('navigation_guard_invalid_origin')
        return {'expected_navigation_epoch': g['epoch'], 'expected_origin': origin,
                'expected_world_generation': identity[0], 'expected_player_uuid': identity[2],
                'expected_action_session': identity[3]}

    def bind(self, body, state):
        if isinstance(state,dict) and 'observation_clock' in state:
            raise ValueError('read_only_observation_navigation_forbidden')
        pair = self.observe(state)
        fields = ('expected_navigation_epoch', 'expected_origin', 'expected_world_generation',
                  'expected_player_uuid', 'expected_action_session')
        if 'expected_origin' in body:
            origin = body['expected_origin']
            if (not isinstance(origin, dict) or set(origin) != {'x', 'y', 'z'}
                    or not all(type(v) in (int, float) and math.isfinite(v) for v in origin.values())):
                raise ValueError('navigation_binding_conflict')
        if any(k in body for k in fields):
            if (('expected_navigation_epoch' in body) != ('expected_origin' in body)
                    or not pair or any(k in body and (type(body[k]) is not type(pair[k]) or body[k] != pair[k]) for k in fields)):
                raise ValueError('navigation_binding_conflict')
        if state.get('client_action', {}).get('status') == 'running':
            raise NavigationNotReady('navigation_action_running')
        if pair and state['world']['navigation_guard']['rebind_ready'] is not True:
            raise NavigationNotReady('navigation_not_settled')
        return {**deepcopy(pair), **deepcopy(body)}


def no_effect_navigation_rejection(response):
    """Resident's actual first-step HTTP rejection, never a terminal reason alone."""
    if not isinstance(response, dict) or response.get('status') != 'failed':
        return False
    e = response.get('action_admission')
    return (isinstance(e, dict) and type(e.get('schema_version')) is int and e['schema_version'] == 1
            and type(e.get('http_status')) is int and e['http_status'] == 409
            and e.get('admitted') is False and e.get('uncertain') is False
            and all(response.get(k, False) is False for k in ('post_uncertain', 'uncertain', 'unknown_outcome'))
            and isinstance(e.get('reason'), str) and e['reason'] in NAVIGATION_REJECTIONS and e['reason'] == response.get('reason')
            and response.get('action') is None and response.get('action_id') is None
            and response.get('cancellation') is None)


def discontinuity_release_confirmed(receipt):
    """This new cancellation has no missing-field legacy variant."""
    if not isinstance(receipt, dict):
        return False
    result = receipt.get('result')
    return (type(receipt.get('action_schema_version')) is int and receipt['action_schema_version'] == 1
            and receipt.get('status') == 'cancelled'
            and receipt.get('reason') == 'position_discontinuity_rebind_required'
            and all(isinstance(receipt.get(k), str) and receipt[k] for k in ('action_id', 'action_session'))
            and isinstance(result, dict) and result.get('input_release_confirmed') is True)


def planning_context(state, previous=None):
    world, player, action = state.get('world', {}), state.get('player', {}), state.get('client_action', {})
    current = (world.get('world_generation'), world.get('dimension'), player.get('uuid'), action.get('action_session'))
    if previous is not None:
        if any(old is not None and old != new for old, new in zip(previous, current)):
            raise ValueError('navigation_context_changed_stop_no_replay')
        current = tuple(new if old is None else old for old, new in zip(previous, current))
    return current


def native_handoff_required(receipt):
    if not isinstance(receipt, dict):
        return False
    result = receipt.get('result')
    combat = result.get('combat') if isinstance(result, dict) else None
    # Only the newly introduced encounter receipt has this member. An invalid
    # value cannot silently regain old automatic-defense semantics.
    return isinstance(combat, dict) and 'encounter' in combat


def task_handoff_required(response):
    if not isinstance(response, dict) or response.get('status') not in ('succeeded', 'failed', 'cancelled', 'uncertain'):
        return False
    if 'requires_handoff' in response and response['requires_handoff'] is not False:
        return True
    if response['status'] == 'succeeded':
        return False  # Successful observe may contain a historical native receipt.
    nested = response.get('result')
    return (native_handoff_required(response.get('action'))
            or isinstance(nested, dict) and native_handoff_required(nested.get('action')))

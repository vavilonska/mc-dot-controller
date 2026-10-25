"""One owner-bound stationary strike or crystal shot; never retarget or replay."""
from __future__ import annotations
import math
from . import threats, dimensions
from .core import Outcome, require

PROFILE = 'target-action-stationary-v1'
ACTIONS = ('attack_entity', 'shoot_entity')
AXES = frozenset('minecraft:'+material+'_axe' for material in ('wooden','stone','iron','golden','diamond','netherite'))


def require_profile(runtime, action):
    require(getattr(runtime, 'required_execution_policy', None) == 'request_only',
            'target_action_request_only_required')
    require(getattr(runtime, '_job_scoped_profiles', {}).get(action) == PROFILE,
            'target_action_scoped_profile_not_negotiated')


def _proof(after, command):
    native = after.state.get('client_action', {})
    result = native.get('result', {})
    p = result.get('target_scope', {})
    ranged = command['action'] == 'shoot_entity'
    shield = command.get('blaze_safety_mode') == 'shield_window'
    return (native.get('status') == 'succeeded' and native.get('action') == command['action']
        and result.get('input_release_confirmed') is True and p.get('profile') == PROFILE
        and all(type(p.get(k)) is type(command[k]) and p[k] == command[k]
                for k in ('target_entity_id', 'target_uuid', 'target_type'))
        and all(type(p.get(k)) is int and p[k] == expected for k, expected in
                (('offense_effects', 1), ('offense_packets', 1),
                 ('draw_effects', int(ranged)), ('draw_packets', int(ranged)),
                 ('shield_use_effects', 2 if shield else 0), ('shield_use_packets', 2 if shield else 0),
                 ('shield_release_effects', 2 if shield else 0), ('shield_release_packets', 2 if shield else 0)))
        and p.get('input_neutral') is True and p.get('unknown_outcome') is False
        and p.get('automatic_replay_allowed') is False and p.get('server_confirmed') is False)


class _OneTargetRuntime:
    """Verifier composition only. The original Runtime retains all ownership and writes."""
    def __init__(self, runtime):
        self.runtime = runtime
        self.called = False
    def observe(self, **kwargs):
        return self.runtime.observe(**kwargs)
    def execute(self, name, command, verified, **kwargs):
        require(not self.called and name == 'threats.strike'
                and command.get('action') in ACTIONS, 'single_target_one_dispatch_only')
        self.called = True
        return self.runtime.execute(name, command,
            lambda old, new: _proof(new, command) and verified(old, new), **kwargs)


def strike(runtime, target_uuid, *, ranged=False, min_health=10,
           timeout_ms=threats._DEFAULT_TIMEOUT, expected_dragon_phase=None, blaze_safety_mode=None):
    require(type(ranged) is bool, 'ranged_boolean_required')
    require_profile(runtime, 'shoot_entity' if ranged else 'attack_entity')
    before = runtime.observe(entity_radius=48)
    selected=before.player.get('selected_slot')
    rows=before.player.get('inventory', [])
    require(type(selected) is int and 0 <= selected <= 8
            and before.player.get('inventory_truncated') is False
            and len([row for row in rows if row.get('slot') == selected and row.get('count') == 1
                     and row.get('id') in ({'minecraft:bow'} if ranged else AXES)]) == 1,
            'target_action_already_selected_bow_required' if ranged else 'target_action_already_selected_nonsweeping_axe_required')
    result = threats.strike(_OneTargetRuntime(runtime), target_uuid, ranged=ranged, before=before,
        min_health=min_health, timeout_ms=timeout_ms, expected_dragon_phase=expected_dragon_phase,
        blaze_safety_mode=blaze_safety_mode)
    return Outcome(result.status, result.reason, result.request_ids,
        {**result.evidence, 'profile': PROFILE, 'stationary': True,
         'automatic_replay_allowed': False, 'server_confirmed': False}, result.last_observation)


def remove_crystal(runtime, target_uuid, *, min_health=12):
    """One selected-bow release. Equipment setup is a separate explicit capability."""
    require_profile(runtime, 'shoot_entity')
    require(threats._number(min_health) and 12 <= min_health <= 20, 'crystal_health_reserve_12_to_20')
    before = runtime.observe(entity_radius=48)
    require(dimensions._dimension(before) == dimensions.END, 'crystal_goal_requires_end')
    threats._health(before, min_health)
    target = threats.entity(before, target_uuid)
    require(target.get('type') == 'minecraft:end_crystal' and target.get('alive') is True,
            'live_end_crystal_required')
    distance = math.dist(threats.position(before.player), threats.position(target))
    require(12 <= distance <= 32, 'crystal_observation_station_12_to_32_blocks')
    cell = {k: math.floor(target[k]) for k in ('x', 'y', 'z')}
    dimensions._chunk_loaded(before, cell)
    selected = before.player.get('selected_slot')
    rows = before.player.get('inventory', [])
    require(type(selected) is int and 0 <= selected <= 8
            and before.player.get('inventory_truncated') is False
            and len([s for s in rows if s.get('slot') == selected and s.get('id') == 'minecraft:bow'
                     and s.get('count') == 1]) == 1, 'crystal_already_selected_bow_required')
    command = threats._command(before, 'shoot_entity', target, 5000)
    command.update(draw_ticks=20, min_health=min_health)
    def verified(_, after):
        if not _proof(after, command):
            return False
        require(math.dist(threats.position(before.player), threats.position(after.player)) <= .5,
                'crystal_observer_moved')
        dimensions._chunk_loaded(after, cell)
        return threats._same_target(target, after) is None
    result = runtime.execute('dimensions.remove_crystal', command, verified, before=before,
                             max_samples=80, stable_samples=3)
    return Outcome(result.status,
        'crystal_removed_from_loaded_observed_area' if result.ok else result.reason,
        result.request_ids, {**result.evidence, 'profile': PROFILE, 'target_uuid': target_uuid,
            'outcome': 'local_removal_observed' if result.ok else 'not_verified',
            'destruction_attributed_to_action': False, 'all_world_crystals_absent': False,
            'automatic_replay_allowed': False, 'server_confirmed': False}, result.last_observation)

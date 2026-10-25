"""Ordinary flat walking inside the unchanged C8 input/sample bounds.

This is a sidecar policy, not a native speed or tick-rate change. Jumps/drops
retain the previous policy; every request is fresh-gated against actual geometry.
"""
import math
from navigation4_controller.geometry import box_values,observation_geometry
from grounded_contact import partial
from live_session_runner import redirected as original_redirected, arrived as original_arrived


def flat(stage):
    b=stage['source_bounds']
    return not stage['jump_first'] and b['max_y']-b['min_y']<=.100001


def stride(distance):
    if distance>=1.5:return 1.,8
    if distance>=.9:return 1.,6
    if distance>.5:return 1.,4
    if distance>.35:return .5,4
    return .5,2


def redirected(observation,stage):
    result,samples=original_redirected(observation,stage)
    if not flat(stage):return result,samples
    p,t=observation['pose'],stage['target']
    dx,dz=t['x']-p['x'],t['z']-p['z']
    magnitude,samples=stride(max(abs(dx),abs(dz)))
    if partial(box_values(observation['player_bbox']),observation_geometry(observation)[1]):
        magnitude,samples=.5,min(samples,4)
    # Original redirected chooses the dominant cardinal axis, preserving actual
    # yaw and the original logical target, ID and cumulative move budget.
    result['forward']*=magnitude/.5
    result['strafe']*=magnitude/.5
    return result,min(samples,stage['max_samples'])


def arrived(observation,stage):
    if not flat(stage):return original_arrived(observation,stage)
    p,t=observation['pose'],stage['target']
    # This records actual occupancy of the target cell, not exact center
    # convergence. The caller still independently establishes grounded stability.
    return (abs(p['y']-t['y'])<=.05
            and math.hypot(p['x']-t['x'],p['z']-t['z'])<=.25
            and all(math.floor(p[k])==math.floor(t[k]) for k in ('x','z')))

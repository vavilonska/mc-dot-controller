"""One short straight native-admitted segment; no remote terrain grants authority."""
import math
from . import reach
from .core import Outcome, require

PROFILE = 'movement-flat-observed-v2'


def _points(player, goal):
    goal = reach.coordinate(goal)
    x, y, z = (player[k] for k in ('x', 'y', 'z'))
    require(all(type(v) in (int, float) and math.isfinite(v) for v in (x,y,z)), 'scoped_movement_pose_missing')
    sx, sy, sz = math.floor(x), round(y), math.floor(z)
    require(abs(x-sx-.5) <= .1 and abs(z-sz-.5) <= .1 and abs(y-sy) <= 1e-7,
            'scoped_movement_centered_integer_origin_required')
    dx, dz = goal['x']-sx, goal['z']-sz
    require(goal['y'] == sy, 'scoped_movement_flat_required')
    require((dx == 0) != (dz == 0), 'scoped_movement_cardinal_nonzero_goal_required')
    steps = abs(dx)+abs(dz)
    require(steps == 1, 'scoped_movement_exactly_one_step')
    dx, dz = (dx > 0)-(dx < 0), (dz > 0)-(dz < 0)
    return [dict(x=sx+.5+dx*i,y=sy,z=sz+.5+dz*i,jump=False) for i in range(1,steps+1)]


def _settled_goal(observation, goal):
    p = observation.player
    velocity = p.get('velocity', {})
    return (reach._arrived(p, goal) and abs(p['y']-goal['y']) <= 1e-6 and p.get('on_ground') is True
            and all(type(velocity.get(k)) in (int,float) and math.isfinite(velocity[k]) for k in ('x','y','z'))
            and math.hypot(velocity['x'],velocity['z']) <= .003 and -.09 <= velocity['y'] <= 0
            and observation.state.get('client_action', {}).get('result', {}).get('input_release_confirmed') is True)


def navigate_local(runtime, goal, *, min_health=12, control=None):
    """Single goal segment. A refusal, failure, cancellation or UNKNOWN is never retried."""
    require(getattr(runtime, '_job_scoped_profiles', {}).get('follow_path') == PROFILE,
            'scoped_movement_profile_not_negotiated')
    require(type(min_health) in (int,float) and math.isfinite(min_health) and 8 <= min_health <= 20,
            'mobility_min_health_8_to20')
    if control is not None: control.checkpoint()
    before = runtime.observe(terrain=False, entity_radius=8)
    require(before.context[1] == 'minecraft:overworld', 'scoped_movement_overworld_required')
    points = _points(before.player, goal)
    command = {'op':'action','action':'follow_path','waypoints':points,'capability_route':True,
               'timeout_ms':8000,'min_health':min_health}
    target = {k:points[-1][k] for k in ('x','y','z')}
    if control is not None:
        control.checkpoint()
        control.emit('local_segment_planned', {'goal':target,'steps':len(points),'profile':PROFILE,
                     'geometry_authority':'native_admission_required'})
    result = runtime.execute('mobility.navigate_local', command, lambda old,new:_settled_goal(new,target),
                             before=before, max_samples=16, stable_samples=2)
    return Outcome(result.status,result.reason,result.request_ids,{**result.evidence,
                   'profile':PROFILE,'goal':target,'planned_steps':len(points),
                   'scope':'one_cardinal_flat_block','general_pathfinding':False,
                   'entity_guard_guarantee':'same-callback-current-facts-only','future_dynamics_certified':False,
                   'physical_distance_accounting':'native_callback_sampled_only'}, result.last_observation)

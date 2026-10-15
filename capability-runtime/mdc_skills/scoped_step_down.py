"""One native-admitted dry cardinal descent; never a route or replay controller."""
import math
from . import reach
from .core import Outcome, require

PROFILE = 'movement-step-down-observed-v1'


def _point(player, goal):
    goal = reach.coordinate(goal)
    values = [player.get(k) for k in ('x','y','z')]
    require(all(type(v) in (int,float) and math.isfinite(v) for v in values), 'step_down_pose_missing')
    x,y,z = values
    sx,sy,sz = math.floor(x),round(y),math.floor(z)
    require(abs(x-sx-.5)<=.10 and abs(z-sz-.5)<=.10 and abs(y-sy)<=1e-7,
            'step_down_centered_integer_origin_required')
    require(goal['y']==sy-1 and abs(goal['x']-sx)+abs(goal['z']-sz)==1,
            'step_down_exact_cardinal_descent_required')
    return {'x':goal['x']+.5,'y':goal['y'],'z':goal['z']+.5,'jump':False}


def _settled_goal(observation, target):
    p = observation.player
    velocity = p.get('velocity',{})
    action = observation.state.get('client_action',{})
    result = action.get('result',{})
    terminal = result.get('step_down',{})
    meter = observation.state.get('movement_budget',{})
    return (reach._arrived(p,target) and p.get('on_ground') is True and abs(p['y']-target['y'])<=1e-6
        and all(type(velocity.get(k)) in (int,float) and math.isfinite(velocity[k]) for k in ('x','y','z'))
        and math.hypot(velocity['x'],velocity['z'])<=.003 and -.09<=velocity['y']<=0
        and action.get('action')=='follow_path' and action.get('status')=='succeeded'
        and result.get('input_release_confirmed') is True
        and terminal.get('profile')==PROFILE and terminal.get('phase')=='landed' and terminal.get('landed') is True
        and terminal.get('input_neutral') is True
        and type(meter.get('schema_version')) is int and meter['schema_version']==1
        and meter.get('status')=='unarmed')


def _protected(before, after):
    old,new = before.player,after.player
    return (type(old.get('health')) in (int,float) and type(new.get('health')) in (int,float)
        and math.isfinite(old['health']) and math.isfinite(new['health']) and new['health']>=old['health']
        and old.get('inventory_truncated') is False and new.get('inventory_truncated') is False
        and type(old.get('inventory_total')) is int and old['inventory_total']==new.get('inventory_total')
        and type(old.get('inventory')) is list and old['inventory']==new.get('inventory')
        and all(old.get(k)==new.get(k) for k in ('selected_slot','offhand','armor')))


def navigate_step_down(runtime, goal, *, min_health=12, control=None):
    require(runtime.scoped_profile('follow_path')==PROFILE, 'step_down_profile_not_negotiated')
    require(getattr(runtime,'required_execution_policy',None)=='request_only', 'step_down_request_only_required')
    require(type(min_health) in (int,float) and math.isfinite(min_health) and 8<=min_health<=20,
            'mobility_min_health_8_to20')
    if control is not None: control.checkpoint()
    before = runtime.observe(terrain=False,entity_radius=8)
    require(before.context[1]=='minecraft:overworld','step_down_overworld_required')
    meter = before.state.get('movement_budget',{})
    require(type(meter) is dict and type(meter.get('schema_version')) is int
            and meter['schema_version']==1 and meter.get('status')=='unarmed','step_down_movement_budget_must_be_unarmed')
    p = before.player
    require(type(p.get('health')) in (int,float) and math.isfinite(p['health']) and p['health']>min_health,
            'mobility_health_guard')
    point = _point(p,goal)
    command = {'op':'action','action':'follow_path','waypoints':[point], 'capability_route':True,
               'timeout_ms':8000,'min_health':min_health}
    target = {k:point[k] for k in ('x','y','z')}
    if control is not None:
        control.checkpoint()
        control.emit('step_down_planned',{'goal':target,'steps':1,'profile':PROFILE,
                     'geometry_authority':'native_admission_required'})
    result = runtime.execute('mobility.navigate_step_down',command,lambda old,new:_settled_goal(new,target) and _protected(old,new),
                             before=before,max_samples=16,stable_samples=2)
    return Outcome(result.status,result.reason,result.request_ids,{**result.evidence,
        'profile':PROFILE,'goal':target,'planned_steps':1,'scope':'one_cardinal_block_down',
        'general_pathfinding':False,'composable_route':False,'automatic_replay_allowed':False,
        'future_dynamics_certified':False,'physical_distance_accounting':'native_callback_sampled_only'},result.last_observation)

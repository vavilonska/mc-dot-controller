"""Local risk policy, NOT a global safety/causal proof or zero-damage promise."""
import math
from .storage import Refused


def number(v):
    return type(v) in (int, float) and math.isfinite(v)


def local_gate(obs, req, owner_id):
    if obs.get('ready') is not True or obs.get('unknown_lock') is not False or obs.get('active_id') is not None:
        raise Refused('native context not ready')
    if obs.get('bound_owner_id') not in (None, owner_id): raise Refused('native owner mismatch')
    for key in ('session', 'world_generation', 'player_uuid', 'owner_generation'):
        if obs.get(key) != req[key] or type(obs.get(key)) is not type(req[key]): raise Refused('fresh observation binding mismatch')
    if obs.get('alive') is not True or obs.get('paused') is not False or obs.get('screen_open') is not False or obs.get('on_ground') is not True:
        raise Refused('flat grounded first-step context required')
    pose, velocity = obs.get('pose'), obs.get('velocity')
    if not isinstance(pose, dict) or not isinstance(velocity, dict) or any(not number(pose.get(k)) for k in ('x','y','z','yaw','pitch')) or any(not number(velocity.get(k)) for k in ('x','y','z')):
        raise Refused('finite local pose required')
    # Prototype first-step qualification intentionally excludes jump, falling/sliding.
    if req['jump_first']: raise Refused('jump policy is not yet qualified')
    if abs(velocity['x']) > .1 or abs(velocity['z']) > .1 or abs(velocity['y']) > .1:
        raise Refused('first-step velocity exceeds local qualification')
    blocks = obs.get('local_blocks')
    if not isinstance(blocks, list) or len(blocks) != 125: raise Refused('bounded local terrain missing')
    cells = {}
    for b in blocks:
        if not isinstance(b, dict) or set(b) != {'dx','dy','dz','loaded','collision','fluid','id'}: raise Refused('invalid local cell')
        key = (b['dx'], b['dy'], b['dz'])
        if any(type(x) is not int or x not in (-2,-1,0,1,2) for x in key) or key in cells: raise Refused('invalid local coordinates')
        if type(b['loaded']) is not bool: raise Refused('invalid loaded flag')
        if b['loaded'] and (type(b['collision']) is not bool or not isinstance(b['fluid'],str) or not isinstance(b['id'],str)): raise Refused('invalid local flags')
        if not b['loaded'] and any(b[k] is not None for k in ('collision','fluid','id')): raise Refused('unloaded cell must be explicit null')
        cells[key] = b
    yaw = math.radians(pose['yaw'])
    dx = req['strafe'] * math.cos(yaw) - req['forward'] * math.sin(yaw)
    dz = req['forward'] * math.cos(yaw) + req['strafe'] * math.sin(yaw)
    sx, sz = (0 if abs(dx)<1e-6 else (1 if dx>0 else -1)), (0 if abs(dz)<1e-6 else (1 if dz>0 else -1))
    # Immediate support and one-cell projection only. Unknown drop is refused;
    # collision in body cells remains an ordinary blocked-gameplay possibility.
    for x,z in {(0,0), (sx,sz)}:
        for y in (-1,0,1):
            b = cells[(x,y,z)]
            if not b['loaded'] or b['fluid'] != 'minecraft:empty': raise Refused('local route unloaded or fluid risk')
        if not cells[(x,-1,z)]['collision']:
            below=cells[(x,-2,z)]
            if not below['loaded'] or not below['collision'] or below['fluid'] != 'minecraft:empty': raise Refused('local drop exceeds one block or is unknown')
    living = obs.get('nearby_living')
    if not isinstance(living, list) or len(living)>32: raise Refused('bounded nearby flags unavailable')
    warnings = []
    for entity in living:
        if not isinstance(entity,dict) or any(not number(entity.get(k)) for k in ('x','y','z')) or type(entity.get('alive')) is not bool: raise Refused('invalid nearby flag')
        if not entity['alive']: continue
        ex,ey,ez = entity['x']-pose['x'], entity['y']-pose['y'], entity['z']-pose['z']
        # Only immediate body / short projected overlap refuses; radius presence isn't a veto.
        if min(abs(ex),abs(ex-dx*.4)) < .6 and min(abs(ez),abs(ez-dz*.4)) < .6 and abs(ey)<1.8:
            raise Refused('immediate nearby entity overlap')
        warnings.append({'type':entity.get('type','unspecified'), 'distance':round(math.sqrt(ex*ex+ey*ey+ez*ez),2)})
    return {'nearby_risk_flags':warnings, 'nearby_truncated':obs.get('nearby_truncated'), 'gameplay_risk':'ordinary_damage_and_death_accepted', 'scope':'local_flat_first_step_only_not_full_trajectory_proof'}

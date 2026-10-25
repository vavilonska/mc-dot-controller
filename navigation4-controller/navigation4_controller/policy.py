"""Explicit finite stage admission, not a route planner or collision-free guarantee."""
import math
from .legacy import Refused,PROFILE
from .schema import finite
from interaction_controller.policy import context
from .geometry import box_values,observation_geometry,clear_body,translated,required,support


def gate(obs,req,owner,history,plan):
    if obs.get('sprinting') is not False:raise Refused('navigation admission requires current not-sprinting')
    pose=context(obs,req,owner);plan.bind(obs);stage=plan.stage(req['stage_id'])
    used=[r for r in history.values() if r['request'].get('profile')==PROFILE and r['request'].get('plan_sha256')==plan.sha256 and r['request'].get('stage_id')==req['stage_id'] and r['request'].get('kind')==req['kind']]
    if len(used)>=(stage['max_moves'] if req['kind']=='move' else stage['max_looks']):raise Refused('stage intent budget consumed, including knownzero')
    bbox=box_values(obs.get('player_bbox'));bounds=stage['source_bounds']
    if abs(bbox[1]-pose['y'])>1e-5 or abs((bbox[0]+bbox[3])/2-pose['x'])>1e-5 or abs((bbox[2]+bbox[5])/2-pose['z'])>1e-5 or any(bbox[i+3]-bbox[i]>4 for i in range(3)):raise Refused('bbox must describe actual player pose')
    if not (bounds['min_x']<=bbox[0]<bbox[3]<=bounds['max_x'] and bounds['min_z']<=bbox[2]<bbox[5]<=bounds['max_z'] and bounds['min_y']<=pose['y']<=bounds['max_y']):raise Refused('whole current footprint outside reviewed source corridor')
    if obs.get('on_ground') is not True or any(abs(v)>.1 for v in obs['velocity'].values()):raise Refused('grounded low-velocity fresh source required')
    cells,boxes=observation_geometry(obs)
    if obs['collision_boxes_complete'] is not True:raise Refused('complete actual local geometry required')
    required(cells,[bbox[0],bbox[1]-1,bbox[2],bbox[3],bbox[4],bbox[5]]);clear_body(bbox,boxes);support(bbox,boxes,bbox[1]-1,bbox[1],contact=True)
    nearby=obs.get('nearby_living')
    if not isinstance(nearby,list) or len(nearby)>32 or obs.get('nearby_truncated') is not False:raise Refused('bounded nearby evidence required')
    for entity in nearby:
        if not isinstance(entity,dict) or set(entity)!={'id','type','x','y','z','alive'} or type(entity['alive']) is not bool or not isinstance(entity['type'],str) or any(not finite(entity[k],-3e7,3e7) for k in 'xyz'):raise Refused('bounded nearby entity record required')
        if entity.get('alive') is True and abs(entity['x']-pose['x'])<.8 and abs(entity['z']-pose['z'])<.8 and abs(entity['y']-pose['y'])<2:raise Refused('immediate nearby living overlap risk')
    risk={'plan_sha256':plan.sha256,'stage_id':stage['id'],'gameplay_risk':'ordinary_damage_collision_and_target_not_reached','physical_settlement':'not_observed','arrival':'not_assessed','nearby_living_count':len(nearby)}
    if req['kind']=='look':
        if req['yaw']!=stage['yaw'] or req['pitch']!=stage['pitch'] or abs((req['yaw']-pose['yaw']+180)%360-180)>90 or abs(req['pitch']-pose['pitch'])>90:raise Refused('exact reviewed bounded stage look required')
        return risk
    if any(req[k]!=stage[k] for k in ('forward','strafe','jump_first')) or req['samples']>stage['max_samples'] or abs((pose['yaw']-stage['yaw']+180)%360-180)>.1 or abs(pose['pitch']-stage['pitch'])>.1:raise Refused('reviewed stage input/heading bounds required')
    target=stage['target'];dy=target['y']-pose['y'];distance=math.hypot(target['x']-pose['x'],target['z']-pose['z'])
    if abs(dy)>1 or not .01<distance<=3:raise Refused('local target displacement/drop bound exceeded')
    if not req['jump_first'] and dy>min(obs['step_height'],.6)+1e-6:raise Refused('target above actual native step height')
    angle=math.radians(pose['yaw']);dx=req['strafe']*math.cos(angle)-req['forward']*math.sin(angle);dz=req['forward']*math.cos(angle)+req['strafe']*math.sin(angle)
    if dx*(target['x']-pose['x'])+dz*(target['z']-pose['z'])<=0 or abs(dx*(target['z']-pose['z'])-dz*(target['x']-pose['x']))/math.hypot(dx,dz)>.1:raise Refused('stage input must align toward actual target')
    landing=translated(bbox,pose,target);required(cells,[landing[0],landing[1]-1,landing[2],landing[3],landing[4],landing[5]]);clear_body(landing,boxes);support(landing,boxes,landing[1],landing[1])
    # Finite local projected footprint/drop checks, not an ideal jump arc or future guarantee.
    for i in range(1,math.ceil(distance/.25)+1):
        f=i/math.ceil(distance/.25);mid={k:pose[k]+f*(target[k]-pose[k]) for k in 'xyz'};foot=translated(bbox,pose,mid)
        required(cells,[foot[0],min(pose['y'],target['y'])-1,foot[2],foot[3],max(pose['y'],target['y'])+.01,foot[5]])
        support(foot,boxes,min(pose['y'],target['y'])-1,max(pose['y'],target['y']))
    return risk

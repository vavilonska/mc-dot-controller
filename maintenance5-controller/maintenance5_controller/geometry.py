"""Bounded actual collision-box reader and local geometric predicates, no material shapes."""
import math
from .legacy import Refused
from .schema import finite,integer

EPS=1e-7
BOX_KEYS={'min_x','min_y','min_z','max_x','max_y','max_z'}
CELL_KEYS={'dx','dy','dz','loaded','id','collision','fluid','collision_boxes'}


def box_values(value):
    if not isinstance(value,dict) or set(value)!=BOX_KEYS:raise Refused('closed actual bbox required')
    b=[value[k] for k in ('min_x','min_y','min_z','max_x','max_y','max_z')]
    if any(not finite(v,-3e7,3e7) for v in b) or any(b[k]>=b[k+3] for k in range(3)):raise Refused('ordered actual bbox required')
    return b


def observation_geometry(obs):
    complete=obs.get('collision_boxes_complete');step=obs.get('step_height')
    if type(complete) is not bool:raise Refused('geometry completeness must be explicit')
    if obs['world_generation'] is None:
        if complete or step is not None or obs.get('sprinting') is not None or obs['local_blocks']!=[] or obs['ready'] is not False:raise Refused('no-world geometry mismatch')
        return {},[]
    if obs.get('sprinting') is not None and type(obs['sprinting']) is not bool:raise Refused('explicit current sprint state required')
    if step is not None and not finite(step,0,16):raise Refused('finite actual step height required')
    cells=obs.get('local_blocks');pose=obs.get('pose')
    if not isinstance(cells,list) or len(cells)!=150 or not isinstance(pose,dict) or any(not finite(pose.get(k),-3e7,3e7) for k in 'xyz'):raise Refused('bounded local geometry and pose required')
    origin=[math.floor(pose[k]) for k in 'xyz'];out={};boxes=[];all_known=step is not None and obs.get('sprinting') is not None
    for c in cells:
        if not isinstance(c,dict) or set(c)!=CELL_KEYS or type(c['loaded']) is not bool or not integer(c['dx'],-2,2) or not integer(c['dz'],-2,2) or not integer(c['dy'],-2,3):raise Refused('closed local collision cell required')
        key=tuple(origin[i]+c[k] for i,k in enumerate(('dx','dy','dz')))
        if key in out:raise Refused('duplicate cell geometry')
        out[key]=c;raw=c['collision_boxes']
        if not c['loaded']:
            if any(c[k] is not None for k in ('id','collision','fluid','collision_boxes')):raise Refused('unloaded cell must be null')
            all_known=False;continue
        if not isinstance(c['id'],str) or not isinstance(c['fluid'],str):raise Refused('loaded identity/fluid required')
        if raw is None:
            if c['collision'] is not None:raise Refused('unknown shape must not claim collision')
            all_known=False;continue
        if not isinstance(raw,list) or len(raw)>16 or type(c['collision']) is not bool or c['collision']!=bool(raw):raise Refused('collision/box mismatch')
        for b in raw:
            if not isinstance(b,list) or len(b)!=6 or any(not finite(v,-16,16) for v in b) or any(b[i]>=b[i+3] for i in range(3)):raise Refused('bounded finite shape box required')
            boxes.append(([b[i]+key[i%3] for i in range(6)],key))
    if len(boxes)>512 or complete!=all_known or not complete and obs['ready'] is not False:raise Refused('geometry bound/completeness mismatch')
    return out,boxes


def intersects(a,b):return all(min(a[i+3],b[i+3])-max(a[i],b[i])>EPS for i in range(3))


def clear_body(box,boxes):
    if any(intersects(box,b) for b,_ in boxes):raise Refused('actual body intersects sampled solid')


def translated(box,pose,target):
    delta=[target[k]-pose[k] for k in 'xyz'];return [v+delta[i%3] for i,v in enumerate(box)]


def required(cells,box):
    for x in range(math.floor(box[0]+EPS),math.floor(box[3]-EPS)+1):
        for y in range(math.floor(box[1]+EPS),math.floor(box[4]-EPS)+1):
            for z in range(math.floor(box[2]+EPS),math.floor(box[5]-EPS)+1):
                c=cells.get((x,y,z))
                if not c or not c['loaded'] or c['collision_boxes'] is None or c['fluid']!='minecraft:empty' or c['id']=='minecraft:tnt':raise Refused('required local cell missing/fluid/TNT')


def covered(rect,rects):
    x0,z0,x1,z1=rect;clipped=[]
    for a,b,c,d in rects:
        a,b,c,d=max(a,x0),max(b,z0),min(c,x1),min(d,z1)
        if c-a>EPS and d-b>EPS:clipped.append((a,b,c,d))
    cuts=sorted({x0,x1}|{v for a,_,c,_ in clipped for v in (a,c)})
    for left,right in zip(cuts,cuts[1:]):
        if right-left<=EPS:continue
        mid=(left+right)/2;intervals=sorted((b,d) for a,b,c,d in clipped if a-EPS<=mid<=c+EPS);end=z0
        for start,stop in intervals:
            if start>end+EPS:return False
            end=max(end,stop)
        if end<z1-EPS:return False
    return bool(clipped)


def support(box,boxes,low,high,contact=False):
    rect=(box[0],box[2],box[3],box[5]);surfaces=[(b[0],b[2],b[3],b[5]) for b,_ in boxes if low-EPS<=b[4]<=high+EPS]
    if not covered(rect,surfaces):raise Refused('whole footprint lacks bounded local support')
    if contact and not any(abs(b[4]-box[1])<=1e-5 and min(b[3],box[3])-max(b[0],box[0])>EPS and min(b[5],box[5])-max(b[2],box[2])>EPS for b,_ in boxes):raise Refused('no actual current support contact')

WITNESS_KEYS={'x','y','z','id','fluid','loaded','complete','unstable','neighbor_signal','adjacent_fire_or_lava'}
TNT_FACTS=('unstable','neighbor_signal','adjacent_fire_or_lava')
def witness_valid(obs):
    w=obs.get('ray_target_witness');ray=obs.get('ray')
    if ray is not None:
        if not isinstance(ray,dict) or set(ray)!={'kind','x','y','z','face','point','block_id'} or ray['kind'] not in ('block','miss','entity'):raise Refused('closed current ray required')
        if ray['kind']=='block':
            if any(not integer(ray[k],-2048 if k=='y' else -30000000,2048 if k=='y' else 30000000) for k in 'xyz') or ray['face'] not in ('UP','DOWN','NORTH','SOUTH','EAST','WEST') or not isinstance(ray['block_id'],str) or not isinstance(ray['point'],dict) or set(ray['point'])!={'x','y','z'} or any(not finite(ray['point'][k],-3e7,3e7) for k in 'xyz'):raise Refused('closed block ray target required')
        elif any(ray[k] is not None for k in ('x','y','z','face','point','block_id')):raise Refused('non-block ray target fields must be null')
    if obs['world_generation'] is None or not isinstance(ray,dict) or ray.get('kind')!='block':
        if w is not None:raise Refused('non-block ray cannot claim target witness')
        return
    if not isinstance(w,dict) or set(w)!=WITNESS_KEYS or any(not integer(w[k],-2048 if k=='y' else -30000000,2048 if k=='y' else 30000000) for k in 'xyz') or any(type(w[k]) is not bool for k in ('loaded','complete')) or any(w[k]!=ray.get(k) for k in 'xyz'):raise Refused('closed actual-ray target witness required')
    if any(w[k] is not None and type(w[k]) is not bool for k in TNT_FACTS):raise Refused('explicit current TNT fact required')
    if not w['loaded']:
        if w['complete'] or any(w[k] is not None for k in ('id','fluid',*TNT_FACTS)):raise Refused('unloaded witness nulls required')
    else:
        if any(w[k] is not None and not isinstance(w[k],str) for k in ('id','fluid')):raise Refused('nullable partial witness state invalid')
        if w['complete']:
            if not isinstance(w['id'],str) or not isinstance(w['fluid'],str) or w['id']!=ray.get('block_id'):raise Refused('complete ray/witness state mismatch')
            if w['id']=='minecraft:tnt':
                if not all(type(w[k]) is bool for k in TNT_FACTS):raise Refused('complete TNT witness facts missing')
            elif any(w[k] is not None for k in TNT_FACTS):raise Refused('complete non-TNT witness must not invent TNT facts')
    if not w['complete'] and obs['ready'] is not False:raise Refused('incomplete witness cannot be ready')


def primed_valid(obs):
    v=obs.get('local_primed_tnt')
    if not isinstance(v,dict) or set(v)!={'count','complete','overflow'} or not integer(v['count'],0,32) or type(v['complete']) is not bool or type(v['overflow']) is not bool or v['overflow'] and v['complete']:raise Refused('closed bounded local primed-TNT evidence required')
    if obs['world_generation'] is None and v!={'count':0,'complete':False,'overflow':False}:raise Refused('no-world local primed evidence mismatch')
    return v


LATEST_KEYS={'action_id','x','y','z','id','fluid','loaded','complete'}
def latest_valid(obs):
    w=obs.get('latest_target_witness')
    if w is None:return
    if obs['world_generation'] is None or not isinstance(w,dict) or set(w)!=LATEST_KEYS or any(not integer(w[k],-2048 if k=='y' else -30000000,2048 if k=='y' else 30000000) for k in 'xyz') or any(type(w[k]) is not bool for k in ('loaded','complete')):raise Refused('closed current original-target witness required')
    from .legacy import legacy
    legacy.uuid(w['action_id'])
    if w['loaded']:
        if any(w[k] is not None and not isinstance(w[k],str) for k in ('id','fluid')) or w['complete'] and any(not isinstance(w[k],str) for k in ('id','fluid')):raise Refused('complete or nullable partial latest target state required')
    elif w['complete'] or w['id'] is not None or w['fluid'] is not None:raise Refused('unloaded latest target nulls required')


def eye_valid(obs):
    eye=obs.get('eye_position')
    if obs['world_generation'] is None:
        if eye is not None:raise Refused('no-world eye must be null')
    elif eye is None:
        if obs['ready'] is not False:raise Refused('unavailable eye cannot be ready')
    elif not isinstance(eye,dict) or set(eye)!={'x','y','z'} or any(not finite(eye[k],-3e7,3e7) for k in 'xyz'):raise Refused('finite actual native eye position required')

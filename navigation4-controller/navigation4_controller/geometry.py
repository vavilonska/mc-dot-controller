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

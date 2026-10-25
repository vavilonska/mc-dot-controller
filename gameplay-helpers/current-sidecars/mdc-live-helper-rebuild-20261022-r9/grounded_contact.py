"""Shared actual-ground contact and short inward geometry; no IO or authority."""
import math
from navigation4_controller.geometry import EPS,required,clear_body,support,translated
from navigation4_controller.legacy import Refused
SUPPORT_REFUSAL='whole footprint lacks bounded local support'

def area(box,boxes):
    """Actual contact union area, not a fabricated full-floor rectangle."""
    rects=[]
    for b,_ in boxes:
        if abs(b[4]-box[1])>1e-5:continue
        x0,z0,x1,z1=max(box[0],b[0]),max(box[2],b[2]),min(box[3],b[3]),min(box[5],b[5])
        if x1-x0>EPS and z1-z0>EPS:rects.append((x0,z0,x1,z1))
    cuts=sorted({x for a,_,c,_ in rects for x in (a,c)});total=0.
    for lo,hi in zip(cuts,cuts[1:]):
        mid=(lo+hi)/2;segments=sorted((b,d) for a,b,c,d in rects if a<=mid<=c);length=0.;end=None
        for a,b in segments:
            if end is None or a>end:length+=b-a;end=b
            elif b>end:length+=b-end;end=b
        total+=(hi-lo)*length
    return total

def partial(box, boxes):
    try:
        support(box,boxes,box[1]-1,box[1],contact=True)
        return False
    except Refused as e:
        if str(e)!=SUPPORT_REFUSAL:raise
        if area(box,boxes)<=EPS:raise Refused('no actual current support contact')
        return True


def current_support(box, boxes):
    # Callers already require actual on_ground, current bbox and clear body.
    partial(box,boxes)


def inward_project(p,b,cells,boxes,target):
    distance=math.hypot(target['x']-p['x'],target['z']-p['z'])
    if abs(target['y']-p['y'])>1e-5 or not .01<distance<=.75:
        raise Refused('edge recovery requires short same-height inward step')
    landing=translated(b,p,target)
    required(cells,[landing[0],landing[1]-1,landing[2],landing[3],landing[4],landing[5]])
    clear_body(landing,boxes);support(landing,boxes,landing[1],landing[1])
    count=max(1,math.ceil(distance/.1));previous=area(b,boxes)
    if previous<=EPS:raise Refused('no actual current support contact')
    for i in range(1,count+1):
        t={k:p[k]+(target[k]-p[k])*i/count for k in 'xyz'};foot=translated(b,p,t)
        required(cells,[foot[0],foot[1]-1,foot[2],foot[3],foot[4],foot[5]]);clear_body(foot,boxes)
        current=area(foot,boxes)
        if current+EPS<previous or current<=EPS:raise Refused('edge recovery must increase real support')
        previous=current
    return landing

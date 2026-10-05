"""Small gameplay helpers; configure a caller-owned client before queue use.

Importing does not create a queue client, read observations, or send actions.
The path and inventory helpers also work directly on supplied observations.
"""
import math,collections,json

q=None

def configure(client):
 """Use the caller's existing QueueClient; this does not send a request."""
 global q
 q=client

def run(c,wait=30):
 if q is None:raise RuntimeError('configure_a_queue_client_before_use')
 i=q.submit(c);print('request',i,c.get('op'),c.get('action',c.get('endpoint','')),flush=True);r=q.wait(i,wait)
 if r.get('status')!='succeeded':raise RuntimeError(json.dumps({'id':i,'status':r.get('status'),'reason':r.get('reason')}))
 return r.get('result',{})
def obs(radius=None,vertical=4):
 c={'op':'observe'}
 if radius:c.update(terrain=True,radius=radius,vertical=vertical)
 return run(c)
def path(o,target):
 cells={(c['x'],c['y'],c['z']):c for c in o['terrain']['cells']};p=o['state']['player'];start=tuple(math.floor(p[k]) for k in ['x','y','z']);target=tuple(target)
 def clear(a):
  c=cells.get(a,{});return c.get('collision_empty') and c.get('fluid')=='minecraft:empty' and not c.get('hazards')
 def stand(a):
  x,y,z=a;c=cells.get((x,y-1,z),{});return clear(a) and clear((x,y+1,z)) and c.get('full_top_support') and not c.get('hazards')
 prev={start:None};todo=collections.deque([start])
 while todo:
  a=todo.popleft();x,y,z=a
  if a==target:break
  for dx,dz in [(1,0),(-1,0),(0,1),(0,-1)]:
   for dy in [0,1,-1]:
    b=x+dx,y+dy,z+dz
    if b not in prev and stand(b) and (dy!=1 or clear((x,y+2,z))) and (dy!=-1 or clear((b[0],b[1]+2,b[2]))):prev[b]=a;todo.append(b)
 if target not in prev:raise ValueError('target_not_reachable_in_observed_terrain')
 nodes=[];a=target
 while prev[a] is not None:nodes.append(a);a=prev[a]
 nodes.reverse();way=[];a=start
 for b in nodes:way.append({'x':b[0]+.5,'y':b[1],'z':b[2]+.5,'jump':b[1]>a[1]});a=b
 return way
 def_unused=None
def go(target,radius=8):
 o=obs(radius);way=path(o,target)
 if way:return run({'op':'action','action':'follow_path','waypoints':way,'timeout_ms':30000},35)
 return {'state':o['state']}
def inventory(o):return [(v['slot'],v['id'],v['count']) for v in o['state']['player']['inventory'] if not v['empty']]
def look_at(x,y,z):
 p=obs()['state']['player'];dx=x-p['x'];dy=y-p['y']-1.62;dz=z-p['z'];return run({'op':'direct','endpoint':'look','body':{'yaw':math.degrees(math.atan2(-dx,dz)),'pitch':-math.degrees(math.atan2(dy,math.hypot(dx,dz))),'relative':False}})
def travel(target):
 target=tuple(target)
 while True:
  o=obs(8);p=o['state']['player'];cur=tuple(math.floor(p[k]) for k in ['x','y','z'])
  if cur==target:return o
  cs={(c['x'],c['y'],c['z']):c for c in o['terrain']['cells']}
  heuristic=lambda a:abs(a[0]-target[0])+abs(a[2]-target[2])+abs(a[1]-target[1])*1.5
  choices=[]
  for a,c in cs.items():
   x,y,z=a
   if c.get('collision_empty') and cs.get((x,y+1,z),{}).get('collision_empty') and cs.get((x,y-1,z),{}).get('full_top_support') and heuristic(a)<heuristic(cur):choices.append(a)
  for dest in sorted(choices,key=lambda a:(heuristic(a),abs(a[0]-cur[0])+abs(a[2]-cur[2]))):
   try:way=path(o,dest)
   except ValueError:continue
   if not way:continue
   print('travel_leg',cur,'to',dest,'goal',target,flush=True)
   run({'op':'action','action':'follow_path','waypoints':way,'timeout_ms':30000},35)
   break
  else:raise ValueError('need_new_route_no_local_progress')

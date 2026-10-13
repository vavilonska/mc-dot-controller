"""Regenerate complete synthetic geometry; never starts or controls Minecraft."""
import gzip, json
from pathlib import Path

def cell(x,y,z,kind):
    solid=kind not in ('minecraft:air','minecraft:iron_bars')
    bar=kind=='minecraft:iron_bars'
    return dict(x=x,y=y,z=z,id=kind,status='loaded',known=True,id_truncated=False,
        properties_truncated=False,properties={'north':'true','east':'true','south':'true','west':'true','waterlogged':'false'} if bar else {},
        collision_known=True,collision_empty=not (solid or bar),full_top_support=solid,
        collision_bounds=[0,0,0,1,1,1] if solid else ([.4375,0,0,.5625,1,1] if bar else []),
        fluid='minecraft:empty',fluid_source=False,fluid_truncated=False,hazards=[],hazards_exhaustive=False,air=not (solid or bar))
worlds=[]
for radius,height,cage in ((2,72,False),(3,78,True),(4,84,True)):
    cells=[]
    for x in range(-17,18):
      for y in range(62,height+7):
       for z in range(-9,10):
        kind='minecraft:air'
        if y<=63:kind='minecraft:end_stone'
        if y<height and x*x+z*z<=radius*radius+1:kind='minecraft:obsidian'
        if x==z==0 and y==height:kind='minecraft:bedrock'
        if cage and -2<=x<=2 and -2<=z<=2 and height<=y<=height+3 and (abs(x)==2 or abs(z)==2 or y==height+3):kind='minecraft:iron_bars'
        cells.append(cell(x,y,z,kind))
    crystal=dict(uuid='crystal-'+str(radius),entity_id=radius,type='minecraft:end_crystal',alive=True,
        x=.5,y=height+1,z=.5,bounding_box={'min':{'x':-.5,'y':height+1,'z':-.5},'max':{'x':1.5,'y':height+3,'z':1.5}})
    worlds.append(dict(name=f'radius-{radius}-height-{height}-caged-{cage}',radius=radius,tower_top=height,
        cage=cage,crystal=crystal,complete_bounds={'min':[-17,62,-9],'max':[17,height+6,9]},cells=cells))
p=Path(__file__).with_name('crystal-tower-worlds.json.gz')
with p.open('wb') as raw:
 with gzip.GzipFile(fileobj=raw,mode='wb',mtime=0) as out:
  out.write(json.dumps({'schema_version':1,'scope':'offline synthetic vanilla-shaped cylinders and cages, not a game export',
    'worlds':worlds},separators=(',',':')).encode())
print(p, p.stat().st_size)

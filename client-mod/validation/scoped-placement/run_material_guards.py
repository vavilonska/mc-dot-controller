#!/usr/bin/env python3
"""Exact production material/furnace/settlement method slices with explicit synthetic readers.
No Minecraft initialization, physics, block effect, packet, world or deployment proof.
"""
from pathlib import Path
import hashlib, json, os, subprocess, sys
HERE=Path(__file__).resolve().parent
SOURCE=HERE.parents[2]/'client-mod/src/main/java/io/github/campione01/mineclientbridge/ScopedPlacement.java'
OUT=Path(sys.argv[1]).resolve()
if OUT.exists():raise SystemExit('Existing attempt forbidden')
OUT.mkdir(parents=True)
text=SOURCE.read_text()
def sha(value):return hashlib.sha256(value).hexdigest()
def extract(signature):
    start=text.index(signature);end=text.index('{',start)+1;depth=1
    while depth:
        depth+=(text[end]=='{')-(text[end]=='}');end+=1
    body=text[start:end]
    return body,{'signature':signature,'start':start,'end':end,'sha256':sha(body.encode())}
methods=[];bindings=[]
for sig in ('    private static boolean exactPlacedClass(', '    private boolean blockEntityPermitted(',
            '    boolean settled()', '    static boolean exactDecrement('):
    body,binding=extract(sig);methods.append(body);bindings.append(binding)
preamble='''import java.util.*;
/** Test-only exact-source receiver. Every block/world/entity/item reader is synthetic. */
public final class PlacementMaterialSlice {
 static class Block {} static class CraftingTableBlock extends Block {} static class FurnaceBlock extends Block {}
 static class CustomFurnaceBlock extends FurnaceBlock {}
 static final class Blocks {static final Block COBBLESTONE=new Block(),CRAFTING_TABLE=new CraftingTableBlock(),FURNACE=new FurnaceBlock();}
 static class BlockState {final Block b;BlockState(Block b){this.b=b;}Block getBlock(){return b;}}
 record BlockPos(int x,int y,int z){}
 static final class BlockEntityType {static final Object FURNACE=new Object();}
 static class BlockEntity {}
 static class FurnaceBlockEntity extends BlockEntity {
  Object type=BlockEntityType.FURNACE;boolean removed;Level level;BlockPos pos;BlockState state;
  int size=3;List<ItemStack> slots=new ArrayList<>(List.of(new ItemStack(0,""),new ItemStack(0,""),new ItemStack(0,"")));
  Object getType(){return type;}boolean isRemoved(){return removed;}Level getLevel(){return level;}
  BlockPos getBlockPos(){return pos;}BlockState getBlockState(){return state;}int getContainerSize(){return size;}
  ItemStack getItem(int i){return slots.get(i);}
 }
 static class CustomFurnaceEntity extends FurnaceBlockEntity {}
 static class OtherEntity extends BlockEntity {}
 static class Level {BlockEntity entity;boolean loaded=true;BlockState state;
  BlockEntity getBlockEntity(BlockPos p){return entity;}boolean hasChunkAt(BlockPos p){return loaded;}BlockState getBlockState(BlockPos p){return state;}}
 static class ItemStack {int count;String identity;ItemStack(int n,String s){count=n;identity=s;}
  boolean isEmpty(){return count==0;}int getCount(){return count;}
  static boolean isSameItemSameComponents(ItemStack a,ItemStack b){return a.identity.equals(b.identity);}}
 static class Player {ItemStack held;ItemStack getMainHandItem(){return held;}}
 Level level=new Level();BlockPos target=new BlockPos(1,64,2);BlockState placedState=new BlockState(Blocks.FURNACE);
 int effectCount=1,selected=0;Player player=new Player();List<ItemStack> inventory=List.of(new ItemStack(5,"plain:furnace"));
 PlacementMaterialSlice(){level.state=placedState;player.held=new ItemStack(4,"plain:furnace");var f=new FurnaceBlockEntity();f.level=level;f.pos=target;f.state=placedState;level.entity=f;}
 static int checks;
 static void check(boolean condition,String why){checks++;if(!condition)throw new AssertionError(why);}
 static void rejects(java.util.function.Consumer<PlacementMaterialSlice> mutation,String why){var f=new PlacementMaterialSlice();mutation.accept(f);check(!f.settled(),why);}
'''
tests='''
 public static void main(String[] args){
  var f=new PlacementMaterialSlice();check(f.settled(),"exact fresh empty furnace and exact decrement");
  for(Block block:List.of(Blocks.COBBLESTONE,Blocks.CRAFTING_TABLE,Blocks.FURNACE))check(exactPlacedClass(new BlockState(block)),"exact vanilla target class");
  check(!exactPlacedClass(new BlockState(new Block())),"unregistered block refused");
  check(!exactPlacedClass(new BlockState(new CustomFurnaceBlock())),"subclass refused");
  rejects(a->a.level.loaded=false,"unloaded target");
  rejects(a->a.level.state=new BlockState(Blocks.FURNACE),"different facing/state singleton");
  rejects(a->a.level.entity=null,"missing furnace entity");
  rejects(a->a.level.entity=new OtherEntity(),"wrong entity class");
  rejects(a->a.level.entity=new CustomFurnaceEntity(),"subclass entity rejected");
  rejects(a->((FurnaceBlockEntity)a.level.entity).type=new Object(),"wrong entity type");
  rejects(a->((FurnaceBlockEntity)a.level.entity).removed=true,"removed entity");
  rejects(a->((FurnaceBlockEntity)a.level.entity).level=new Level(),"other level");
  rejects(a->((FurnaceBlockEntity)a.level.entity).pos=new BlockPos(0,64,2),"other target position");
  rejects(a->((FurnaceBlockEntity)a.level.entity).state=new BlockState(Blocks.FURNACE),"entity state changed");
  for(int size:new int[]{0,2,4})rejects(a->((FurnaceBlockEntity)a.level.entity).size=size,"nonordinary inventory size");
  for(int i=0;i<3;i++){final int slot=i;rejects(a->((FurnaceBlockEntity)a.level.entity).slots.set(slot,new ItemStack(1,"inserted")),"nonempty furnace slot "+i);}
  rejects(a->a.player.held.count=5,"no decrement");rejects(a->a.player.held.count=3,"double decrement");
  rejects(a->a.player.held.identity="renamed:furnace","components changed");
  for(int effects:new int[]{0,2})rejects(a->a.effectCount=effects,"furnace entity cannot precede or exceed effect latch");
  check(!f.blockEntityPermitted(new BlockPos(0,64,2),f.placedState),"furnace entity cannot occupy another cell");
  for(Block block:List.of(Blocks.COBBLESTONE,Blocks.CRAFTING_TABLE)){
   var plain=new PlacementMaterialSlice();plain.placedState=new BlockState(block);plain.level.state=plain.placedState;
   plain.level.entity=null;check(plain.settled(),"plain target without entity");plain.level.entity=new FurnaceBlockEntity();check(!plain.settled(),"plain target cannot carry entity");
  }
  var one=new PlacementMaterialSlice();one.inventory=List.of(new ItemStack(1,"plain:furnace"));one.player.held=new ItemStack(0,"");check(one.settled(),"last item exact empty decrement");
  System.out.println("PASS exact-source material/target-only entity/decrement guards: "+checks);
 }
}
'''
source=preamble+'\n'.join(methods)+tests
java=OUT/'PlacementMaterialSlice.java';java.write_text(source)
(OUT/'EXTRACTION.json').write_text(json.dumps({'production_source':str(SOURCE),
    'production_sha256':sha(SOURCE.read_bytes()),'methods':bindings,'receiver_sha256':sha(source.encode()),
    'scope':'Exact unchanged source method bodies, entirely synthetic block/entity/world/item readers. No engine or live effect proof.'},indent=2)+'\n')
jdk=Path(os.environ['JAVA_HOME']);receipts=[]
for label,command in [('compile',[str(jdk/'bin/javac'),'-proc:none','--release','21','-d',str(OUT),str(java)]),
        ('execute',[str(jdk/'bin/java'),'-cp',str(OUT),'PlacementMaterialSlice'])]:
    with (OUT/(label+'.stdout')).open('w') as out,(OUT/(label+'.stderr')).open('w') as err:
        result=subprocess.run(command,stdin=subprocess.DEVNULL,stdout=out,stderr=err,timeout=60)
    receipts.append({'label':label,'exit_code':result.returncode})
    if result.returncode:raise SystemExit(label+' failed; terminal inspected, no automatic retry')
assert SOURCE.read_text()==text
(OUT/'RESULT.json').write_text(json.dumps({'status':'passed','runs':receipts,'source_unchanged':True,
    'game_started':False,'world_effect_proven':False},indent=2)+'\n')
print((OUT/'execute.stdout').read_text().strip())

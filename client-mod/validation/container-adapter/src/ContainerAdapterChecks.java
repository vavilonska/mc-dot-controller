package io.github.campione01.mineclientbridge;
import com.google.gson.*;
import java.lang.reflect.*;
import java.util.*;
import net.minecraft.core.component.DataComponents;
import net.minecraft.world.item.*;
import net.minecraft.world.item.component.ItemContainerContents;
import net.minecraft.world.level.block.ShulkerBoxBlock;
public final class ContainerAdapterChecks {
 static int checks;
 static final Item STONE=new Item("minecraft:stone");
 static final BlockItem BOX=new BlockItem("minecraft:shulker_box",new ShulkerBoxBlock());
 static final Method ADAPTER;
 static {try {ADAPTER=BridgeServer.class.getDeclaredMethod("itemSnapshot",ItemStack.class);ADAPTER.setAccessible(true);}catch(Exception e){throw new ExceptionInInitializerError(e);}}
 static void eq(Object want,Object got){checks++;if(!Objects.equals(want,got))throw new AssertionError("expected "+want+" got "+got);}
 static JsonObject snapshot(ItemStack item)throws Exception{return (JsonObject)ADAPTER.invoke(null,item);}
 static ItemStack stone(){return new ItemStack(STONE,3,0);}
 static ItemStack box(List<ItemStack> contents){return new ItemStack(BOX,1,0).set(DataComponents.CONTAINER,new ItemContainerContents(contents));}
 static boolean bool(JsonObject o,String k){return o.get(k).getAsBoolean();}
 static int number(JsonObject o,String k){return o.get(k).getAsInt();}
 static JsonObject cargo(JsonObject o){return o.getAsJsonObject("container");}
 public static void main(String[] args)throws Exception {
  for(ItemStack s:new ItemStack[]{null,ItemStack.EMPTY}){
   JsonObject v=snapshot(s);eq(Set.of("empty","id","count","damage","max_damage"),v.keySet());
   eq(true,bool(v,"empty"));eq("",v.get("id").getAsString());eq(0,number(v,"count"));eq(0,number(v,"damage"));eq(0,number(v,"max_damage"));
  }
  JsonObject ordinary=snapshot(stone());eq(false,bool(ordinary,"empty"));eq("minecraft:stone",ordinary.get("id").getAsString());eq(3,number(ordinary,"count"));eq(0,number(ordinary,"damage"));eq(0,number(ordinary,"max_damage"));eq(true,bool(ordinary,"identity_complete"));eq(0,number(ordinary,"unrepresented_component_changes"));eq(false,ordinary.has("container"));
  for(int n:new int[]{127,128,129,1024}){
   JsonObject v=snapshot(stone().set(DataComponents.CUSTOM_NAME,new DataComponents.Text("x".repeat(n))));
   eq(Math.min(n,128),v.get("custom_name").getAsString().length());eq(n>128,bool(v,"custom_name_truncated"));eq(false,bool(v,"identity_complete"));eq(0,number(v,"unrepresented_component_changes"));
  }
  JsonObject damaged=snapshot(new ItemStack(new Item("minecraft:iron_sword"),1,250).set(DataComponents.DAMAGE,2));
  eq(2,number(damaged,"damage"));eq(250,number(damaged,"max_damage"));eq(true,bool(damaged,"identity_complete"));
  for(ItemStack s:List.of(stone().remove(DataComponents.DAMAGE),stone().set(DataComponents.OTHER,"opaque"),stone().set(DataComponents.CONTAINER,ItemContainerContents.EMPTY))){JsonObject v=snapshot(s);eq(1,number(v,"unrepresented_component_changes"));eq(false,bool(v,"identity_complete"));}
  BoundedContainerSnapshot.beginSnapshot();
  ItemStack named=stone().set(DataComponents.CUSTOM_NAME,new DataComponents.Text("cargo"));
  JsonObject nested=snapshot(box(List.of(stone(),ItemStack.EMPTY,named,box(List.of(stone())))));
  JsonObject c=cargo(nested);eq(1,number(c,"schema_version"));eq(27,number(c,"capacity"));eq(false,bool(c,"nested_containers_supported"));eq(4,number(c,"slot_extent"));eq(false,bool(c,"slots_truncated"));eq(false,bool(nested,"identity_complete"));
  JsonArray rows=c.getAsJsonArray("items");eq(3,rows.size());
  for(int i=0;i<3;i++){JsonObject row=rows.get(i).getAsJsonObject();eq(Set.of("slot","id","count","damage","identity_complete"),row.keySet());eq(new int[]{0,2,3}[i],number(row,"slot"));eq(i==0,bool(row,"identity_complete"));eq(false,row.has("container"));}
  BoundedContainerSnapshot.beginSnapshot();
  for(int i=0;i<5;i++){JsonObject v=snapshot(box(List.of(stone())));eq(i==4,bool(cargo(v),"slots_truncated"));eq(i<4,bool(v,"identity_complete"));eq(i<4?1:0,cargo(v).getAsJsonArray("items").size());}
  BoundedContainerSnapshot.beginSnapshot();JsonObject fresh=snapshot(box(List.of(stone())));eq(false,bool(cargo(fresh),"slots_truncated"));eq(true,bool(fresh,"identity_complete"));
  BoundedContainerSnapshot.beginSnapshot();
  List<ItemStack> many=new ArrayList<>();for(int i=0;i<28;i++)many.add(stone());
  JsonObject large=snapshot(box(many));eq(28,number(cargo(large),"slot_extent"));eq(27,cargo(large).getAsJsonArray("items").size());eq(26,number(cargo(large).getAsJsonArray("items").get(26).getAsJsonObject(),"slot"));eq(true,bool(cargo(large),"slots_truncated"));eq(false,bool(large,"identity_complete"));
  System.out.println("ContainerAdapterChecks PASS assertions="+checks+" (configured types; real adapter/helper; no MC loader)");
 }
}

package io.github.campione01.mineclientbridge;

import com.google.gson.*;
import java.nio.file.*;
import java.util.*;
import net.minecraft.world.phys.shapes.*;

/** Cold block IDs/properties plus explicitly synthetic metadata/shape model through the actual DTO/JSON codec.
 * This is NOT native world capture. Shapes.box/or are real shape implementations, not a running Minecraft world. */
public final class RecoveryNavigationV4ObservationWire {
 static final String V4=RecoveryShortInputLedger.NAVIGATION_V4_PROFILE;
 static JsonObject xyz(double x,double y,double z){var j=new JsonObject();j.addProperty("x",x);j.addProperty("y",y);j.addProperty("z",z);return j;}
 static JsonObject base(double x,double y,double z){
  var out=NativeRecoveryShortInput.describeNoWorld(false,false,V4);out.addProperty("ready",true);out.addProperty("reason","ready");out.addProperty("client_tick",100);out.addProperty("world_generation",RecoveryShortInputChecks.WORLD);out.addProperty("player_uuid",RecoveryShortInputChecks.PLAYER);out.addProperty("alive",true);out.addProperty("on_ground",true);out.addProperty("health",20);out.add("velocity",xyz(0,0,0));
  var pose=xyz(x,y,z);pose.addProperty("yaw",0);pose.addProperty("pitch",0);out.add("pose",pose);var bbox=new JsonObject();bbox.addProperty("min_x",x-.3);bbox.addProperty("min_y",y);bbox.addProperty("min_z",z-.3);bbox.addProperty("max_x",x+.3);bbox.addProperty("max_y",y+1.8);bbox.addProperty("max_z",z+.3);out.add("player_bbox",bbox);out.addProperty("selected_slot",0);
  var hotbar=new JsonArray();for(int i=0;i<9;i++)hotbar.add(RecoveryInteraction.describeHotbarStack(i,"minecraft:air",0,0,0,"a".repeat(64),true));out.add("hotbar",hotbar);var ray=new JsonObject();ray.addProperty("kind","miss");for(String k:List.of("x","y","z","face","point","block_id"))ray.add(k,JsonNull.INSTANCE);out.add("ray",ray);return out;
 }
 static VoxelShape modeledShape(JsonObject cold){
  String id=cold.get("Name").getAsString();return switch(id){
   case "minecraft:air","minecraft:water","minecraft:wheat","minecraft:torch","minecraft:wall_torch","minecraft:nether_portal"->Shapes.empty();
   case "minecraft:white_bed"->{var p=cold.getAsJsonObject("Properties");if(!p.get("facing").getAsString().equals("west"))throw new IllegalArgumentException("fixture bed orientation");boolean west=p.get("part").getAsString().equals("head");double x0=west?0:13.0/16,x1=west?3.0/16:1;yield Shapes.or(Shapes.box(0,3.0/16,0,1,9.0/16,1),Shapes.box(x0,0,0,x1,3.0/16,3.0/16),Shapes.box(x0,0,13.0/16,x1,3.0/16,1));}
   case "minecraft:chest"->{if(!cold.getAsJsonObject("Properties").get("type").getAsString().equals("single"))throw new IllegalArgumentException("fixture chest type");yield Shapes.box(1.0/16,0,1.0/16,15.0/16,14.0/16,15.0/16);}
   case "minecraft:farmland"->Shapes.box(0,0,0,1,15.0/16,1);
   case "minecraft:stone","minecraft:sandstone","minecraft:cut_sandstone","minecraft:clay","minecraft:gravel","minecraft:chiseled_sandstone","minecraft:obsidian","minecraft:tnt","minecraft:orange_terracotta","minecraft:dirt","minecraft:crafting_table","minecraft:furnace","minecraft:blue_terracotta"->Shapes.block();
   default->throw new IllegalArgumentException("unmodeled synthetic cold ID");
  };
 }
 static JsonObject window(Map<String,JsonObject> cold,double x,double y,double z){
  var out=base(x,y,z);var g=new RecoveryNavigationV4.Geometry(.6F);var rows=new JsonArray();boolean loaded=true;
  for(int dy=-2;dy<=3;dy++)for(int dz=-2;dz<=2;dz++)for(int dx=-2;dx<=2;dx++){
   var cell=new JsonObject();cell.addProperty("dx",dx);cell.addProperty("dy",dy);cell.addProperty("dz",dz);var data=cold.get(((int)Math.floor(x)+dx)+","+((int)Math.floor(y)+dy)+","+((int)Math.floor(z)+dz));cell.addProperty("loaded",data!=null);
   if(data==null){loaded=false;for(String key:List.of("id","fluid","collision"))cell.add(key,JsonNull.INSTANCE);g.unloaded(cell);}else{String id=data.get("Name").getAsString();cell.addProperty("id",id);cell.addProperty("fluid",id.equals("minecraft:water")?"minecraft:water":"minecraft:empty");g.shape(cell,modeledShape(data));}rows.add(cell);
  }
  out.add("local_blocks",rows);out.addProperty("terrain_complete",loaded);g.describe(out,loaded&&rows.size()==150);if(!out.get("collision_boxes_complete").getAsBoolean()){out.addProperty("ready",false);out.addProperty("reason","navigation_geometry_incomplete");}return out;
 }
 public static void main(String[] args)throws Exception{
  Path coldFile=Path.of(args[0]),out=Path.of(args[1]);Files.createDirectories(out);Map<String,JsonObject> cold=new HashMap<>();var source=JsonParser.parseString(Files.readString(coldFile)).getAsJsonObject();for(var row:source.getAsJsonArray("blocks")){var j=row.getAsJsonObject();cold.put(j.get("x")+","+j.get("y")+","+j.get("z"),j);}
  var l=new RecoveryShortInputLedger(new RecoveryShortInputChecks.Memory(),()->100);RecoveryInteractionChecks.setLedger(l);var e=l.submit(RecoveryNavigationV4Checks.request(l,UUID.randomUUID().toString(),"look",false));l.rejectQueued(e,"offline_fixture_bind");
  double[][] points={{-166.5,55,10.5},{-166.5,55.5625,9.5},{-165.5,55.5625,9.5},{-165.5,56,10.5},{-164.5,55,9.5},{-164.5,55,10.5},{-163.5,55.875,10.5},{-162.5,56,10.5},{-160.5,56,13.5}};String[] names={"source","bed-head","bed-foot","table","floor-north","floor-west","chest","cut-sandstone","door"};var cases=new JsonArray();
  for(int i=0;i<points.length;i++){var p=points[i];save(out,names[i]+".json",window(cold,p[0],p[1],p[2]),cases,true);}
  var failed=window(cold,-166.5,55,10.5);var cell=failed.getAsJsonArray("local_blocks").get(0).getAsJsonObject();cell.add("collision",JsonNull.INSTANCE);cell.add("collision_boxes",JsonNull.INSTANCE);failed.addProperty("collision_boxes_complete",false);failed.addProperty("ready",false);failed.addProperty("reason","navigation_geometry_incomplete");save(out,"shape-failed.json",failed,cases,true);
  var unloaded=window(cold,-166.5,55,10.5);cell=unloaded.getAsJsonArray("local_blocks").get(0).getAsJsonObject();cell.addProperty("loaded",false);for(String key:List.of("collision","collision_boxes","id","fluid"))cell.add(key,JsonNull.INSTANCE);unloaded.addProperty("terrain_complete",false);unloaded.addProperty("collision_boxes_complete",false);unloaded.addProperty("ready",false);unloaded.addProperty("reason","navigation_geometry_incomplete");save(out,"unloaded.json",unloaded,cases,true);
  save(out,"no-world.json",NativeRecoveryShortInput.describeNoWorld(false,true,V4),cases,true);
  for(boolean large:new boolean[]{false,true}){var maximum=window(cold,-166.5,55,10.5);var g=new RecoveryNavigationV4.Geometry(.6F);int index=0;for(var row:maximum.getAsJsonArray("local_blocks")){var c=row.getAsJsonObject();double[] b=large?new double[]{-.1234567890123456,-.2345678901234567,-.3456789012345678,.4567890123456789,.5678901234567891,.6789012345678912}:new double[]{0,0,0,1,1,1};g.shape(c,new RecoveryNavigationV4Checks.FakeShape(index++<32?16:0,b,false));}g.describe(maximum,true);save(out,large?"max-512-long-decimals.json":"max-512-short-decimals.json",maximum,cases,!large);}
  var manifest=new JsonObject();manifest.addProperty("scope","Synthetic shape models derived from already-exported cold block metadata; actual production Geometry and JSON codec; NOT native live geometry/gameplay");manifest.addProperty("cold_source",coldFile.toString());manifest.addProperty("cold_blocks",cold.size());manifest.addProperty("max_response_bytes",65536);manifest.add("cases",cases);Files.write(out.resolve("manifest.json"),RecoveryShortInputCodec.encode(manifest));System.out.println(manifest);
 }
 static void save(Path out,String name,JsonObject data,JsonArray cases,boolean expectedPass)throws Exception{
  byte[] bytes=RecoveryShortInputCodec.encode(data);boolean pass=true;try{RecoveryNavigationV4.checkResponseBudget(bytes);}catch(IllegalArgumentException tooLarge){pass=false;}
  if(pass!=expectedPass)throw new AssertionError("unexpected byte budget "+name+" "+bytes.length);Files.write(out.resolve(name),bytes);var row=new JsonObject();row.addProperty("file",name);row.addProperty("bytes",bytes.length);row.addProperty("budget_accepted",pass);row.addProperty("ready",data.get("ready").getAsBoolean());row.addProperty("collision_boxes_complete",data.get("collision_boxes_complete").getAsBoolean());cases.add(row);
 }
}

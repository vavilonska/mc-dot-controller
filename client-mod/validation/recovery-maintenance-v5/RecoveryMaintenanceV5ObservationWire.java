package io.github.campione01.mineclientbridge;
import com.google.gson.*;
import java.nio.file.*;
import java.util.*;
/** Cold/synthetic bounded data through actual Geometry and production JSON codec. Never live capture. */
public final class RecoveryMaintenanceV5ObservationWire {
 static final String V5=RecoveryShortInputLedger.MAINTENANCE_V5_PROFILE;
 static JsonObject converted(JsonObject j){j.addProperty("profile",V5);j.add("eye_position",j.get("pose").isJsonNull()?JsonNull.INSTANCE:RecoveryMaintenanceV5.eyeJson(new net.minecraft.world.phys.Vec3(j.getAsJsonObject("pose").get("x").getAsDouble(),j.getAsJsonObject("pose").get("y").getAsDouble()+1.62,j.getAsJsonObject("pose").get("z").getAsDouble())));j.add("ray_target_witness",JsonNull.INSTANCE);j.add("latest_target_witness",JsonNull.INSTANCE);j.add("local_primed_tnt",new RecoveryMaintenanceV5.PrimedFacts(0,j.get("alive").getAsBoolean(),false).json());return j;}
 static JsonObject cell(int x,int y,int z,String id){var j=new JsonObject();j.addProperty("x",x);j.addProperty("y",y);j.addProperty("z",z);j.addProperty("id",id);j.addProperty("fluid","minecraft:empty");j.addProperty("loaded",true);j.addProperty("complete",true);return j;}
 public static void main(String[] args)throws Exception{
  Path cold=Path.of(args[0]),out=Path.of(args[1]);Files.createDirectories(out);Path base=out.resolve("v4-source-models");RecoveryNavigationV4ObservationWire.main(new String[]{cold.toString(),base.toString()});JsonArray cases=new JsonArray();
  try(var paths=Files.list(base)){for(Path p:paths.filter(x->x.toString().endsWith(".json")&&!x.getFileName().toString().equals("manifest.json")).sorted().toList()){
   var j=converted(JsonParser.parseString(Files.readString(p)).getAsJsonObject());RecoveryNavigationV4ObservationWire.save(out,p.getFileName().toString(),j,cases,!p.getFileName().toString().equals("max-512-long-decimals.json"));
  }}
  var source=converted(JsonParser.parseString(Files.readString(base.resolve("source.json"))).getAsJsonObject());var ray=new JsonObject();ray.addProperty("kind","block");ray.addProperty("x",-166);ray.addProperty("y",53);ray.addProperty("z",11);ray.addProperty("face","UP");ray.add("point",RecoveryNavigationV4ObservationWire.xyz(-165.5,54,11.5));ray.addProperty("block_id","minecraft:tnt");source.add("ray",ray);var witness=cell(-166,53,11,"minecraft:tnt");witness.addProperty("unstable",false);witness.addProperty("neighbor_signal",false);witness.addProperty("adjacent_fire_or_lava",false);source.add("ray_target_witness",witness);source.addProperty("selected_slot",2);
  var hb=source.getAsJsonArray("hotbar");hb.set(2,RecoveryInteraction.describeHotbarStack(2,"minecraft:stone_pickaxe",1,107,131,"a".repeat(64),true));hb.set(3,RecoveryInteraction.describeHotbarStack(3,"minecraft:andesite",27,0,0,"b".repeat(64),true));
  RecoveryNavigationV4ObservationWire.save(out,"tnt-current-synthetic.json",source,cases,true);
  var latest=cell(-166,53,11,"minecraft:air");latest.addProperty("action_id",new UUID(0,999).toString());var post=source.deepCopy();post.add("latest_target_witness",latest);post.addProperty("client_tick",101);RecoveryNavigationV4ObservationWire.save(out,"latest-target-air-synthetic.json",post,cases,true);
  for(String id:List.of("minecraft:andesite","minecraft:tnt")){var x=post.deepCopy();x.getAsJsonObject("latest_target_witness").addProperty("id",id);RecoveryNavigationV4ObservationWire.save(out,"latest-target-"+id.substring(10)+"-synthetic.json",x,cases,true);}
  for(int mode=0;mode<3;mode++){var x=post.deepCopy();x.add("local_primed_tnt",new RecoveryMaintenanceV5.PrimedFacts(mode==0?1:mode==1?32:0,mode==0,mode==1).json());RecoveryNavigationV4ObservationWire.save(out,"primed-"+mode+"-synthetic.json",x,cases,true);}
  var unloaded=post.deepCopy();var u=unloaded.getAsJsonObject("latest_target_witness");u.addProperty("loaded",false);u.addProperty("complete",false);u.add("id",JsonNull.INSTANCE);u.add("fluid",JsonNull.INSTANCE);RecoveryNavigationV4ObservationWire.save(out,"latest-unloaded-ready-synthetic.json",unloaded,cases,true);
  var max=converted(JsonParser.parseString(Files.readString(base.resolve("max-512-short-decimals.json"))).getAsJsonObject());max.add("ray",ray);max.add("ray_target_witness",witness);max.add("latest_target_witness",latest);RecoveryNavigationV4ObservationWire.save(out,"max-512-with-witnesses.json",max,cases,true);
  for(int mode=0;mode<4;mode++){
   var x=post.deepCopy();JsonObject f=mode==3?x.getAsJsonObject("latest_target_witness"):x.getAsJsonObject("ray_target_witness");f.addProperty("complete",false);
   if(mode==0||mode==3){f.add("id",JsonNull.INSTANCE);f.add("fluid",JsonNull.INSTANCE);if(mode==0)for(String k:List.of("unstable","neighbor_signal","adjacent_fire_or_lava"))f.add(k,JsonNull.INSTANCE);}
   if(mode==2){f.addProperty("id","minecraft:cut_sandstone");x.getAsJsonObject("ray").addProperty("block_id","minecraft:cut_sandstone");for(String k:List.of("unstable","neighbor_signal","adjacent_fire_or_lava"))f.add(k,JsonNull.INSTANCE);}
   if(mode!=3){x.addProperty("ready",false);x.addProperty("reason","maintenance_ray_facts_incomplete");}
   RecoveryNavigationV4ObservationWire.save(out,"incomplete-"+mode+"-synthetic.json",x,cases,true);
  }
  var badEye=post.deepCopy();badEye.add("eye_position",JsonNull.INSTANCE);badEye.addProperty("ready",false);badEye.addProperty("reason","maintenance_eye_unavailable");RecoveryNavigationV4ObservationWire.save(out,"eye-unavailable-synthetic.json",badEye,cases,true);
  if(args.length==4)stations(Path.of(args[2]),Path.of(args[3]),out,cases);
  var manifest=new JsonObject();manifest.addProperty("scope","Explicit synthetic witness, eye=feet+1.62 fixture ONLY (not live/native eye), and calm/primed facts; cold shape model through actual Geometry and production codec; no game/native geometry or entity capture");manifest.addProperty("max_response_bytes",65536);manifest.add("cases",cases);Files.write(out.resolve("manifest.json"),RecoveryShortInputCodec.encode(manifest));System.out.println(manifest);
 }
 static void stations(Path factsFile,Path planFile,Path out,JsonArray cases)throws Exception{
  var facts=JsonParser.parseString(Files.readString(factsFile)).getAsJsonObject();var plan=JsonParser.parseString(Files.readString(planFile)).getAsJsonObject();Map<String,JsonObject> model=new HashMap<>();
  for(var v:facts.getAsJsonArray("blocks")){var row=v.getAsJsonObject();model.put(row.get("x")+","+row.get("y")+","+row.get("z"),row.deepCopy());}
  for(String name:List.of("R","S","A","B","C")){
   String cleared=name.equals("A")?"S":name.equals("B")?"A":name.equals("C")?"B":null;
   if(cleared!=null)for(var v:plan.getAsJsonArray("service_breaks")){var b=v.getAsJsonObject();if(b.getAsJsonObject("ray").get("station").getAsString().equals(cleared)){var p=b.getAsJsonArray("target");var row=new JsonObject();row.addProperty("Name","minecraft:air");model.put(p.get(0)+","+p.get(1)+","+p.get(2),row);}}
   var point=plan.getAsJsonObject("stations").getAsJsonArray(name);var dto=converted(RecoveryNavigationV4ObservationWire.window(model,point.get(0).getAsDouble(),point.get(1).getAsDouble(),point.get(2).getAsDouble()));
   if(!dto.get("ready").getAsBoolean())throw new AssertionError("cold task station window incomplete "+name);
   RecoveryNavigationV4ObservationWire.save(out,"task-station-"+name+"-synthetic-phase.json",dto,cases,true);
  }
  var audit=new JsonObject();audit.addProperty("scope","Original exported 1573 cold cells plus EXPLICIT hypothetical earlier service removals: A after S-column, B after S+A columns, C after S+A+B columns. NOT actual operations or native/live capture. Geometry uses production shape DTO and JSON codec.");audit.addProperty("facts_source",factsFile.toString());audit.addProperty("plan_source",planFile.toString());Files.write(out.resolve("task-station-model-scope.json"),RecoveryShortInputCodec.encode(audit));
 }
}

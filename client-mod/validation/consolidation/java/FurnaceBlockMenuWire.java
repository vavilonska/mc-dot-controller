package io.github.campione01.mineclientbridge;
import com.google.gson.*;
import java.nio.file.*;
import java.util.*;
import static io.github.campione01.mineclientbridge.SyntheticBlockMenuFixture.*;
/** Synthetic furnace/readers/terminal. Actual production witness factory, digest, Entry and HTTP serialization. */
public final class FurnaceBlockMenuWire {
 static JsonObject pos(int x,int y,int z){var j=new JsonObject();j.addProperty("x",x);j.addProperty("y",y);j.addProperty("z",z);return j;}
 static JsonObject properties(){var j=new JsonObject();j.addProperty("facing","west");j.addProperty("lit","false");return j;}
 static JsonArray box(double... values){var a=new JsonArray();for(double d:values)a.add(d);return a;}
 static JsonObject cell(int x,int y,int z){var c=pos(x,y,z);boolean furnace=x==2&&y==0&&z==0,solid=y==-1||furnace;c.addProperty("id",furnace?"minecraft:furnace":solid?"minecraft:stone":"minecraft:air");c.add("properties",furnace?properties():new JsonObject());c.addProperty("loaded",true);c.addProperty("fluid","minecraft:empty");var boxes=new JsonArray();if(solid)boxes.add(box(0,0,0,1,1,1));c.add("collision",boxes);c.add("outline",boxes.deepCopy());return c;}
 static JsonObject geometry(){
  var b=new JsonObject();b.addProperty("version","block-menu-v1");b.addProperty("topology","vanilla-single-cell/1");b.add("target",cell(2,0,0));b.addProperty("block_entity_class","net.minecraft.world.level.block.entity.FurnaceBlockEntity");b.addProperty("expected_open_menu_class","net.minecraft.world.inventory.FurnaceMenu");
  var footprint=new JsonArray();footprint.add(cell(2,0,0));b.add("menu_footprint",footprint);
  var ray=new JsonArray();for(int x=0;x<=2;x++)for(int y=0;y<=1;y++)ray.add(cell(x,y,0));b.add("ray_cells",ray);
  var body=new JsonArray();for(int y=-1;y<=1;y++)body.add(cell(0,y,0));b.add("body_cells",body);
  b.add("support",pos(0,-1,0));b.add("eye",point(.5,0+(double)1.62F,.5));b.add("expected_hit",point(2,.5,.5));b.addProperty("face","west");b.addProperty("reach",4.5);
  for(String k:List.of("line_of_sight_clear","on_ground","stationary","not_riding_or_flying","empty_hands","support_and_body_safe"))b.addProperty(k,true);
  b.add("velocity",point(0,-.0784000015258789,0));double width=(double).6F/2;b.add("body_bounds",box(.5-width,0,.5-width,.5+width,0+(double)1.8F,.5+width));return b;
 }
 static JsonObject blockIntent(){var j=intent();for(String k:List.of("waypoints","capability_route","jump","sneak","sprint","expected_navigation_epoch","expected_origin"))j.remove(k);
  j.addProperty("action_id","synthetic-furnace-block-menu-01");j.addProperty("action","interact_block");j.addProperty("timeout_ms",2000);j.add("target",pos(2,0,0));j.addProperty("face","west");j.addProperty("expected_block_id","minecraft:furnace");j.add("expected_block_properties",properties());j.addProperty("expected_open_menu_class","net.minecraft.world.inventory.FurnaceMenu");j.addProperty("expected_hotbar_slot",8);j.add("expected_held_item",emptyStack());BlockMenuPreflight.validateIntent(j);return j;
 }
 static void write(Path out,String name,JsonObject j)throws Exception{Files.writeString(out.resolve(name),BridgeJson.toJson(j),StandardOpenOption.CREATE_NEW);}
 public static void main(String[] args)throws Exception{
  Path out=Path.of(args[0]);JsonObject overrides=args.length>1?JsonParser.parseString(Files.readString(Path.of(args[1]))).getAsJsonObject():new JsonObject();
  var intent=overrides.has("intent")?overrides.getAsJsonObject("intent").deepCopy():blockIntent();BlockMenuPreflight.validateIntent(intent);
  long tick=overrides.has("source_tick")?overrides.get("source_tick").getAsLong():TICK,nano=overrides.has("source_nano")?overrides.get("source_nano").getAsLong():NANO;
  long admitted=overrides.has("admitted_nano")?overrides.get("admitted_nano").getAsLong():nano+100000,owner=overrides.has("owner_revision")?overrides.get("owner_revision").getAsLong():7;
  var compiled=intent.deepCopy();compiled.add("capability_guard",guard(tick,nano));var scope=request();scope.addProperty("profile","block-menu-v1");scope.addProperty("job_id","synthetic_furnace_block_menu");if(overrides.has("scope"))scope=overrides.getAsJsonObject("scope").deepCopy();
  var facts=facts();facts.remove("movement");facts.addProperty("selected_slot",8);facts.add("block_menu",geometry());if(overrides.has("facts"))facts=overrides.getAsJsonObject("facts").deepCopy();
  var context=facts.getAsJsonObject("context");String session=context.get("action_session").getAsString(),server=context.get("integrated_server_instance").getAsString();
  var w=ScopedNativePreflight.serializeWitness(scope,intent.get("action_id").getAsString(),session,owner,server,ScopedNativePreflight.digest(intent),ScopedNativePreflight.digest(compiled),tick,nano,admitted,facts,intent.getAsJsonObject("capability_guard"));
  // Same supplemental fields as Capture.witness; final ray is explicit synthetic post-hook observation.
  var eye=new net.minecraft.world.phys.Vec3(.5,0+(double)1.62F,.5);var center=new net.minecraft.world.phys.Vec3(2,.5,.5);var angles=BlockMenuPreflight.intendedAim(eye,center);
  var view=(net.minecraft.world.phys.Vec3)QuantizedRayChecks.viewMethod().invoke(null,null,angles[1],angles[0]);var hit=net.minecraft.world.phys.shapes.Shapes.block().clip(eye,eye.add(view.scale(4.5)),new net.minecraft.core.BlockPos(2,0,0));
  var ray=new JsonObject();ray.add("target",pos(2,0,0));ray.addProperty("face","west");ray.add("hit",BlockMenuPreflight.vector(hit.getLocation()));ray.add("eye",BlockMenuPreflight.vector(eye));ray.addProperty("reach",4.5);ray.addProperty("yaw",(double)angles[0]);ray.addProperty("pitch",(double)angles[1]);ray.addProperty("line_of_sight_clear",true);

  w.addProperty("dispatch_fence_confirmed",true);w.add("final_ray",ray);w.addProperty("effect_callback","native-post-use-hooks-packet/1");
  var request=new ClientActionRequest(intent.get("action_id").getAsString(),"interact_block",2000,List.of(),new ClientActionRequest.Cell(2,0,0),null,"west",-1,false,false,-1,-1,0,null,compiled);
  var e=new ActionRegistry.Entry(request);e.status="succeeded";e.reason="interaction_dispatched";e.ticks=1;e.result.add("scoped_native_preflight",w);e.result.addProperty("world_generation",context.get("world_generation").getAsString());for(String k:List.of("dispatched","local_use_started","input_release_confirmed"))e.result.addProperty(k,true);
  var a=e.json(false);a.addProperty("action_session",session);var budget=new JsonObject();budget.addProperty("active",false);budget.add("reason",JsonNull.INSTANCE);a.add("movement_budget",budget);var endpoint=actionEndpoint(a,false);
  write(out,"block-menu-coherent.json",capability(a));
  write(out,"block-menu-standalone.json",endpoint);write(out,"block-menu-intent.json",intent);write(out,"block-menu-request.json",scope);write(out,"block-menu-geometry.json",geometry());
  var emitted=JsonParser.parseString(BridgeJson.toJson(endpoint)).getAsJsonObject().getAsJsonObject("result").getAsJsonObject("scoped_native_preflight");Files.writeString(out.resolve("block-menu-witness.json"),emitted.toString(),StandardOpenOption.CREATE_NEW);
  System.out.println("Synthetic furnace fixture; actual production factory/digests/Entry/HTTP codec; no game or menu opening executed.");
 }
}

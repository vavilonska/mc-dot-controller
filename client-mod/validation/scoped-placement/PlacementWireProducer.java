package io.github.campione01.mineclientbridge;

import com.google.gson.*;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.util.List;
import static io.github.campione01.mineclientbridge.WireV1Fixture.*;
import static io.github.campione01.mineclientbridge.ScopedEntityPolicy.*;

/** Synthetic captured inputs/readback; actual production witness, Entry, projection and HTTP codec. */
public final class PlacementWireProducer {
    static int checks;
    static String material="minecraft:cobblestone";
    static JsonObject materialProperties(){JsonObject p=new JsonObject();if(material.equals("minecraft:furnace")){p.addProperty("facing","south");p.addProperty("lit","false");}return p;}
    static void check(boolean ok,String message){checks++;if(!ok)throw new AssertionError(message);}
    static JsonObject cell(int x,int y,int z){JsonObject p=new JsonObject();p.addProperty("x",x);p.addProperty("y",y);p.addProperty("z",z);return p;}
    static JsonObject stack(int count){JsonObject s=emptyStack();s.addProperty("id",material);s.addProperty("count",count);s.addProperty("empty",false);
        s.addProperty("item_fingerprint",count==8?"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa":"bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb");s.addProperty("component_fingerprint","cccccccc-cccc-cccc-cccc-cccccccccccc");return s;}
    static JsonObject ordinary(int count){JsonObject p=point(12.5,64,25.5);p.addProperty("selected_slot",0);p.addProperty("inventory_total",36);p.addProperty("inventory_truncated",false);
        JsonArray a=new JsonArray();for(int i=0;i<36;i++){JsonObject row=i==0?stack(count):emptyStack();row.addProperty("slot",i);a.add(row);}p.add("inventory",a);return p;}
    static JsonObject placementFacts(){
        var frame=new Frame(TICK,NANO+50_000,160,1,new Box(11,62,23,14,67,27),List.of(WireV1Facts.far(10,"minecraft:sheep"),WireV1Facts.removed(30)));
        JsonObject f=facts(frame);f.remove("movement");JsonObject held=stack(8);
        f.getAsJsonArray("inventory").get(0).getAsJsonObject().add("item",held.deepCopy());f.getAsJsonObject("equipment").add("mainhand",held.deepCopy());
        f.getAsJsonObject("menu").getAsJsonArray("slots").get(36).getAsJsonObject().add("item",held.deepCopy());
        JsonObject p=new JsonObject();p.addProperty("profile",ScopedPlacement.PROFILE);p.addProperty("source","native-client-loaded-level");
        p.add("support",cell(12,63,24));p.add("target",cell(12,64,24));p.add("standing_support",cell(12,63,25));p.addProperty("face","up");
        p.addProperty("support_id","minecraft:stone");p.add("support_properties",new JsonObject());p.addProperty("block_id",material);p.add("block_properties",materialProperties());
        p.addProperty("selected_slot",0);p.addProperty("initial_count",8);p.addProperty("min_x",11);p.addProperty("max_x",13);p.addProperty("min_y",62);p.addProperty("max_y",66);p.addProperty("min_z",23);p.addProperty("max_z",26);
        JsonArray cells=new JsonArray();for(int x=11;x<=13;x++)for(int y=62;y<=66;y++)for(int z=23;z<=26;z++){
            boolean solid=y<=63;JsonObject c=cell(x,y,z);c.addProperty("id",solid?"minecraft:stone":"minecraft:air");c.addProperty("state",solid?"Block{minecraft:stone}":"Block{minecraft:air}");
            c.addProperty("loaded",true);c.addProperty("fluid","minecraft:empty");c.addProperty("air",!solid);c.addProperty("static_full_cube",solid);c.addProperty("block_class","net.minecraft.world.level.block."+(solid?"Block":"AirBlock"));c.add("properties",new JsonObject());cells.add(c);
        }
        p.addProperty("expected_cells",cells.size());p.add("cells",cells);for(String key:List.of("all_loaded","complete","callbacks_installed"))p.addProperty(key,true);
        p.addProperty("maximum_action_ticks",40);p.addProperty("maximum_timeout_ms",2000);p.addProperty("deadline_nano",Long.toString(NANO+2_000_000_000L));p.add("entity_guard",frame.json());f.add("placement",p);return f;
    }
    static JsonObject placementIntent(){JsonObject j=intent();for(String k:List.of("waypoints","capability_route","jump","sneak","sprint"))j.remove(k);
        j.addProperty("action","place_block");j.addProperty("timeout_ms",2000);j.add("support",cell(12,63,24));j.addProperty("face","up");
        j.addProperty("expected_support_id","minecraft:stone");j.addProperty("expected_target_id","minecraft:air");j.addProperty("expected_block_id",material);
        for(String k:List.of("expected_support_properties","expected_target_properties","expected_block_properties"))j.add(k,k.equals("expected_block_properties")?materialProperties():new JsonObject());
        j.add("placement_hit",point(12.5,64,24.5));JsonObject c=new JsonObject();c.add("position",cell(12,64,24));c.addProperty("expected_id","minecraft:air");c.add("expected_properties",new JsonObject());c.addProperty("block_id",material);c.add("properties",materialProperties());JsonArray cells=new JsonArray();cells.add(c);j.add("placement_footprint",cells);
        j.addProperty("expected_hotbar_slot",0);j.add("expected_held_item",stack(8));ScopedPlacementIntent.validate(j);return j;
    }
    static JsonObject action(ActionRegistry.Entry e,boolean running){JsonObject a=e.json(running);a.addProperty("action_session",SESSION);JsonObject budget=new JsonObject();budget.addProperty("active",false);budget.add("reason",JsonNull.INSTANCE);a.add("movement_budget",budget);return a;}
    static JsonObject coherent(JsonObject action,JsonObject facts,int count){
        JsonObject template=capability(action),status=template.getAsJsonObject("status"),state=template.getAsJsonObject("state"),screen=template.getAsJsonObject("screen");
        status.add("client_action",action.deepCopy());state.add("client_action",action.deepCopy());
        JsonObject player=ordinary(count);for(String key:player.keySet()){state.getAsJsonObject("player").add(key,player.get(key).deepCopy());status.getAsJsonObject("player").add(key,player.get(key).deepCopy());}
        JsonObject menu=facts.getAsJsonObject("menu").deepCopy();menu.getAsJsonArray("slots").get(36).getAsJsonObject().add("item",stack(count));state.add("menu",menu.deepCopy());screen.add("menu",menu.deepCopy());
        Object level=new Object(),who=new Object(),mode=new Object(),inventory=new Object();var context=new CapabilitySnapshot.Context(level,who,mode,null,inventory,WORLD,PLAYER,"minecraft:overworld",SESSION,TICK);
        return CapabilitySnapshot.assemble(context,context,status,action,state,screen,action);
    }
    static void write(Path out,String name,JsonObject value)throws Exception{Files.writeString(out.resolve(name),BridgeJson.toJson(value),StandardCharsets.UTF_8,StandardOpenOption.CREATE_NEW);}
    static void checkEnvelope(JsonObject standalone,JsonObject coherent){
        JsonObject a=JsonParser.parseString(unchecked(standalone)).getAsJsonObject(),c=JsonParser.parseString(unchecked(coherent)).getAsJsonObject();
        check(c.get(ScopedMovementWire.MARKER).getAsString().equals(ScopedMovementWire.ENCODING),"actual placement compact marker");
        JsonObject witness=a.getAsJsonObject("result").getAsJsonObject(ScopedMovementWire.WITNESS);
        check(witness.equals(c.getAsJsonObject("action").getAsJsonObject("result").getAsJsonObject(ScopedMovementWire.WITNESS)),"actual standalone/coherent witness equality");
        for(String name:List.of("status","state")){var result=c.getAsJsonObject(name).getAsJsonObject("client_action").getAsJsonObject("result");check(result.has(ScopedMovementWire.REFERENCE)&&!result.has(ScopedMovementWire.WITNESS),"actual reference-only "+name);}
        var rows=witness.getAsJsonObject("facts").getAsJsonObject("placement").getAsJsonObject("entity_guard").getAsJsonArray("rows");
        check(rows.size()==2&&rows.get(0).getAsJsonObject().getAsJsonObject("flags").has("mob_target_uuid")&&rows.get(0).getAsJsonObject().getAsJsonObject("flags").get("mob_target_uuid").isJsonNull(),"actual nullable target retained");
        check(rows.get(1).getAsJsonObject().get("removed").getAsBoolean(),"removed row retained");
    }
    static String unchecked(JsonObject v){try{return BridgeJson.toJson(v);}catch(Exception e){throw new AssertionError(e);}}
    public static void main(String[] args)throws Exception{
        Path out=Path.of(args[0]);if(args.length>1)material=args[1];JsonObject scope=request();scope.addProperty("profile",ScopedPlacement.PROFILE);JsonObject intent=placementIntent(),facts=placementFacts(),compiled=intent.deepCopy();compiled.add("capability_guard",guard(TICK,NANO));
        JsonObject witness=ScopedNativePreflight.serializeWitness(scope,ACTION,SESSION,7,SERVER,ScopedNativePreflight.digest(intent),ScopedNativePreflight.digest(compiled),TICK,NANO,ADMITTED,facts,intent.getAsJsonObject("capability_guard"));
        ClientActionRequest request=new ClientActionRequest(ACTION,"place_block",2000,List.of(),null,new ClientActionRequest.Cell(12,63,24),"up",-1,false,false,-1,-1,0,null,compiled);
        ActionRegistry.Entry e=new ActionRegistry.Entry(request);e.result.add("scoped_native_preflight",witness);e.result.addProperty("world_generation",WORLD);
        JsonObject a=action(e,true),standalone=actionEndpoint(a,true),coherent=coherent(a,facts,8);checkEnvelope(standalone,coherent);
        write(out,"placement-standalone.json",standalone);write(out,"placement-coherent.json",coherent);write(out,"placement-request.json",scope);write(out,"placement-intent.json",intent);
        JsonObject emittedWitness=JsonParser.parseString(BridgeJson.toJson(standalone)).getAsJsonObject().getAsJsonObject("result").getAsJsonObject(ScopedMovementWire.WITNESS);
        Files.writeString(out.resolve("placement-witness.json"),emittedWitness.toString(),StandardCharsets.UTF_8,StandardOpenOption.CREATE_NEW);
        write(out,"placement-inventory-before.json",ordinary(8));write(out,"placement-inventory-after.json",ordinary(7));
        // Exact production terminal method body, isolated synthetic count/settled readers; no Minecraft object.
        var receiver=new ScopedPlacementTerminalSlice(request,8,7,0,NANO+2_000_000_000L);
        JsonObject terminal=receiver.terminal(true,true);check(terminal.get("block_placed").getAsBoolean()&&terminal.get("final_count").getAsInt()==7,"production terminal body success fields");
        e.status="succeeded";e.reason="block_placed_observed";e.ticks=6;e.result.add("placement",terminal);e.result.addProperty("input_release_confirmed",true);
        e.result.addProperty("observed_block",material);e.result.addProperty("client_stable_ticks",5);e.result.addProperty("material_consumption_observed",true);e.result.addProperty("confirmation","client_observed_stable");
        a=action(e,false);standalone=actionEndpoint(a,false);coherent=coherent(a,facts,7);checkEnvelope(standalone,coherent);
        write(out,"placement-terminal.json",terminal);write(out,"placement-terminal-standalone.json",standalone);write(out,"placement-terminal-coherent.json",coherent);
        // Same exact terminal body also demonstrates unknown-after-attempt fields without an engine.
        receiver.unknown=true;JsonObject unknown=receiver.terminal(true,false);check(unknown.get("unknown_outcome").getAsBoolean()&&!unknown.get("block_placed").getAsBoolean(),"production unknown terminal");write(out,"placement-unknown-terminal.json",unknown);
        JsonObject report=new JsonObject();report.addProperty("checks",checks);report.addProperty("captured_facts","synthetic");report.addProperty("terminal_readers","synthetic exact-source body extraction");report.addProperty("live_settlement_proven",false);write(out,"JAVA-PLACEMENT-WIRE-RESULT.json",report);
        System.out.println("PASS actual placement witness/Entry/compact/HTTP bytes and extracted terminal body: "+checks);
    }
}
